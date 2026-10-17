"""Versioned local artifacts; executable candidates require separate evaluation."""
import hashlib
import json
from pathlib import Path
import time

ROOT = Path(__file__).parent
BASELINE_PATH = ROOT / "policies" / "policy.json"


def local_versions():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    for entry in manifest:
        path = (ROOT / entry["file"]).resolve()
        if not path.is_relative_to(ROOT.resolve()):
            raise ValueError("Artifact must be inside evolution_patches")
        content = path.read_text()
        if entry["artifact_type"] == "policy":
            json.loads(content)
        yield {**entry, "content": content,
               "sha256": hashlib.sha256(content.encode()).hexdigest()}


async def seed_patch_versions(db):
    collection = db.evolution_patch_versions
    await collection.create_index([("artifact_type", 1), ("name", 1), ("version", 1)], unique=True)
    count = 0
    for artifact in local_versions():
        if artifact["status"] == "DRAFT":
            continue
        key = {field: artifact[field] for field in ("artifact_type", "name", "version")}
        existing = await collection.find_one(key)
        if existing and any(existing.get(field) != artifact[field]
                            for field in ("sha256", "parent")):
            raise ValueError(f"Immutable patch version changed: {artifact['name']} {artifact['version']}; create a new version")
        await collection.update_one(key, {"$setOnInsert": {**artifact, "created_at": time.time()}}, upsert=True)
        count += 1
    return count
