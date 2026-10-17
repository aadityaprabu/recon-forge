"""Local baseline configuration and non-destructive MongoDB initialization."""
import time

from app.evolution_patches import BASELINE_PATH
from app.schemas import Policy


def load_baseline():
    return Policy.model_validate_json(BASELINE_PATH.read_text())


async def seed_policy(db, policy):
    payload = policy.model_dump()
    existing = await db.harness_policies.find_one({"version": policy.version})
    if existing and Policy.model_validate(existing["policy"]) != policy:
        raise ValueError("Policy version already exists with different content; use the approval workflow")
    await db.harness_policies.update_one({"version": policy.version}, {"$setOnInsert": {
        "version": policy.version, "status": "ACTIVE", "patch_name": "Zero-tolerance baseline" if policy.version == "v1" else "Multi-rule policy baseline",
        "policy": payload, "created_at": time.time()}}, upsert=True)
    await db.control.update_one({"_id": "active_policy"}, {"$setOnInsert": {
        "policy": payload, "operations": []}}, upsert=True)
