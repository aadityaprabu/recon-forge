import os
import json

from google.adk.agents import LlmAgent
from google.genai import types

from app.model import gemini_model
from app.prompts import DIAGNOSIS, EVOLUTION, ANALYSIS
from app.evolution_patches.policies.policy_skill import load_policy_skill


def generation_config():
    if os.getenv("MODEL_PROVIDER", "gemini").lower() == "nicrron":
        # Reasoning tokens share the completion budget on GPT-5 models.
        # Gemini thinking_config is not forwarded by the LiteLLM adapter.
        return types.GenerateContentConfig(max_output_tokens=4096)
    return types.GenerateContentConfig(
        max_output_tokens=512,
        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
    )


def literal_instruction(text):
    # Skill/rule braces are literal documentation, not ADK state placeholders.
    # Instruction providers explicitly bypass ADK session-state interpolation.
    def provide(_context):
        return text
    return provide


def create_agents(model_name, policy_skill=None):
    skill = policy_skill or load_policy_skill()
    rules = json.dumps(skill["rules"], sort_keys=True)
    analysis_prompt = ANALYSIS + "\nRead-only policy rules for analysis:\n" + rules
    evolution_prompt = EVOLUTION + "\n\n" + skill["instructions"] + "\nPolicy rules:\n" + rules
    return {
        key: LlmAgent(name=name, model=gemini_model(model_name), instruction=literal_instruction(prompt),
                      # Gemini's response_schema serializer emits an unsupported
                      # additional_properties field for these Pydantic schemas.
                      # Prompts request JSON; the workflow validates every result
                      # against the strict Pydantic model before using it.
                      generate_content_config=generation_config(),
                      include_contents="none", mode="single_turn")
        for key, name, prompt in [
            ("diagnosis", "diagnosis_agent", DIAGNOSIS),
            ("analysis", "analysis_agent", analysis_prompt),
            ("evolution", "evolution_agent", evolution_prompt),
        ]
    }
