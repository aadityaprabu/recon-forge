"""Load and fingerprint policy instructions; reject schema/rule drift."""
import hashlib
import json
from pathlib import Path
from typing import get_args

from app.schemas import PATCH_PATHS, PolicyPatch, Processor

ROOT = Path(__file__).parent


def load_policy_skill():
    instructions = (ROOT / "SKILL.md").read_text()
    rules = json.loads((ROOT / "rules.json").read_text())
    if set(rules["parameters"]) != set(PATCH_PATHS) or set(rules["processor_ids"]) != set(get_args(Processor)):
        raise ValueError("Policy skill rules differ from the runtime schema")
    schema = PolicyPatch.model_json_schema()["properties"]
    for name, (group, field) in PATCH_PATHS.items():
        rule = rules["parameters"][name]
        bounds = next(part for part in schema[name]["anyOf"] if part.get("type") == "integer")
        if (rule["path"] != f"processor_overrides.{{processor}}.{group}.{field}" or
                any(rule[key] != bounds[key] for key in ("minimum", "maximum"))):
            raise ValueError(f"Policy skill path or limits differ from the runtime schema: {name}")
    if rules["max_changed_policy_leaves"] != 1 or not rules["human_approval_required"]:
        raise ValueError("Policy skill cannot bypass single-field edits or approval")
    serialized = json.dumps(rules, sort_keys=True)
    sha256 = hashlib.sha256((instructions + "\n" + serialized).encode()).hexdigest()
    return {"id": rules["id"], "version": rules["version"], "sha256": sha256,
            "instructions": instructions, "rules": rules}


def skill_metadata(skill):
    return {key: skill[key] for key in ("id", "version", "sha256")}
