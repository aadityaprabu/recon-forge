"""Configured Gemini or Nicrron model for the Google ADK agents."""
import os


def model_configuration(model_name):
    provider = os.getenv("MODEL_PROVIDER", "gemini").lower()
    if provider == "nicrron":
        return {"provider": provider, "model": os.getenv("NICRRON_MODEL", ""),
                "model_configured": bool(os.getenv("NICRRON_API_KEY") and os.getenv("NICRRON_MODEL"))}
    if provider != "gemini":
        raise ValueError("MODEL_PROVIDER must be gemini or nicrron")
    return {"provider": provider, "model": model_name,
            "model_configured": bool(os.getenv("GOOGLE_API_KEY"))}


def gemini_model(model_name):
    config = model_configuration(model_name)
    if config["provider"] == "nicrron":
        if not config["model_configured"]:
            raise ValueError("Set NICRRON_MODEL and NICRRON_API_KEY in the project .env")
        from google.adk.models.lite_llm import LiteLlm
        return LiteLlm(model=f"openai/{config['model']}",
                       api_base=os.getenv("NICRRON_BASE_URL") or os.getenv("NICRRON_API_BASE", "https://api.nicrron.ai/v1"),
                       reasoning_effort="low",
                       api_key=os.environ["NICRRON_API_KEY"])
    if not os.getenv("GOOGLE_API_KEY"):
        raise ValueError("Set GOOGLE_API_KEY in the project .env to run agent evaluations")
    from google.adk.models import Gemini
    return Gemini(model=model_name)
