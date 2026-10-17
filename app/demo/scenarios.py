"""Idempotent seed and independent ingestion cursor."""
import time
import hashlib
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.persistence.repositories import Repository
from app.policies import seed_policy
from app.evolution_patches import seed_patch_versions
from app.tools.backtester import score
from app.tools.matcher import match


async def seed(db, dataset):
    existing_stream = await db.control.find_one({"_id": "stream"})
    dataset_id = dataset.manifest.get("dataset_id", "seed-6643")
    if existing_stream and (existing_stream.get("dataset_id", "seed-6643") != dataset_id
                            or existing_stream["total"] != dataset.live_total):
        raise ValueError("Dataset differs from this database; configure a separate MONGODB_DB")
    # Fixture payloads and labels remain local; pin their exact contents for replay.
    fingerprint = hashlib.sha256()
    for path in sorted(dataset.directory.glob("*.json")):
        fingerprint.update(path.name.encode())
        fingerprint.update(path.read_bytes())
    dataset_sha256 = fingerprint.hexdigest()
    if existing_stream and existing_stream.get("dataset_sha256") not in (None, dataset_sha256):
        raise ValueError("Local dataset content changed; use a separate database")
    base = dataset.baseline()
    await seed_policy(db, base)
    archived = await db.harness_policies.find_one({"version": base.version}, {"benchmark": 1})
    if not archived or "benchmark" not in archived:
        internal, settlements = dataset.business("historical")
        benchmark = score(match(internal, settlements, base.matching), dataset.load("historical_ground_truth"), internal)
        await db.harness_policies.update_one({"version": base.version, "benchmark": {"$exists": False}},
            {"$set": {"benchmark": {key: benchmark[key] for key in
                ("accuracy", "auto_resolution_rate", "sample_size", "false_match_rate")}}})
    await seed_patch_versions(db)
    await db.control.update_one({"_id": "stream"}, {"$setOnInsert": {
        "position": 0, "total": dataset.live_total,
        "dataset_sha256": dataset_sha256,
        "dataset_id": dataset.manifest.get("dataset_id", "seed-6643"),
        "phase_size": dataset.manifest.get("phase_size"),
        "phase_count": dataset.manifest.get("phase_count"),
        "expected_evolutions": dataset.manifest.get("expected_evolutions", 10),
        "pause_between_phases": False}}, upsert=True)
    await db.control.update_one({"_id": "engine"}, {"$setOnInsert": {"enabled": False, "interval_seconds": 15}}, upsert=True)
    for memory in dataset.seed_memories():
        await db.incident_memories.update_one({"memory_id": memory["memory_id"]}, {"$setOnInsert": memory}, upsert=True)
    await Repository(db).audit("seed", "dataset_loaded", {"seed": dataset.manifest["seed"]})
    return {"seed": dataset.manifest["seed"], "historical_records": dataset.manifest["historical_base_pairs"],
            "stream_total": dataset.live_total}


async def advance(db, dataset, count):
    cursor = await db.control.find_one({"_id": "stream"})
    if not cursor:
        raise ValueError("Seed the dataset first")
    owner = str(uuid4())
    claimed = await db.control.find_one_and_update({"_id": "stream", "$or": [
        {"lease_until": {"$lt": time.time()}}, {"lease_until": {"$exists": False}}]},
        {"$set": {"lease_until": time.time()+120, "lease_owner": owner}}, return_document=ReturnDocument.AFTER)
    if not claimed:
        raise ValueError("Another stream batch is being ingested")
    try:
        start, end = claimed["position"], min(claimed["total"], claimed["position"] + count)
        if end == start:
            return {"position": start, "total": claimed["total"], "status": "STREAM_COMPLETE"}
        # The cursor exposes the next immutable local fixture prefix to reconciliation.
        await db.control.update_one({"_id": "stream", "lease_owner": owner},
            {"$set": {"position": end, "updated_at": time.time(), "waiting_for_phase_approval": False}})
        return {"start": start, "position": end, "total": claimed["total"]}
    finally:
        await db.control.update_one({"_id": "stream", "lease_owner": owner},
            {"$unset": {"lease_owner": "", "lease_until": ""}})
