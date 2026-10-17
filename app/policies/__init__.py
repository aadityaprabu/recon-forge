"""Local baseline configuration and non-destructive MongoDB initialization."""
from pathlib import Path
import time

from app.schemas import Policy

BASELINE_PATH = Path(__file__).with_name("baseline.json")


def load_baseline():
    return Policy.model_validate_json(BASELINE_PATH.read_text())


async def seed_policy(db, policy):
    payload = policy.model_dump()
    existing = await db.harness_policies.find_one({"version": policy.version})
    if existing and Policy.model_validate(existing["policy"]) != policy:
        raise ValueError("Policy version already exists with different content; use the approval workflow")
    await db.harness_policies.update_one({"version": policy.version}, {"$setOnInsert": {
        "version": policy.version, "status": "ACTIVE", "patch_name": "Zero-tolerance baseline",
        "policy": payload, "created_at": time.time()}}, upsert=True)
    await db.control.update_one({"_id": "active_policy"}, {"$setOnInsert": {
        "policy": payload, "operations": []}}, upsert=True)
