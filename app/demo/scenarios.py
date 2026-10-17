"""Idempotent seed and independent ingestion cursor."""
import time
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
    # _id upserts make interrupted imports repeatable without clearing existing data.
    for split in ("historical", "live"):
        internal, settlements = dataset.business(split)
        if split == "live":
            await db.evaluation_corpora.update_one({"_id": "live"}, {"$setOnInsert": {
                "internal": internal, "settlements": settlements}}, upsert=True)
        for name, records, id_field in [("internal_ledger", internal, "internal_record_id"),
                                         ("processor_settlement", settlements, "processor_record_id")]:
            # Live business data is added exclusively by the separate stream.
            if split == "live":
                continue
            existing = {r[id_field] async for r in db[name].find({}, {id_field: 1})}
            pending = [{**r, "dataset_split": split} for r in records if r[id_field] not in existing]
            if pending:
                await db[name].insert_many(pending, ordered=False)
        # Evaluation truth is stored separately and never exposed through agent tools.
        records = dataset.load(f"{split}_ground_truth")
        existing = {r["label_group_id"] async for r in db.ground_truth.find({}, {"label_group_id": 1})}
        pending = [r for r in records if r["label_group_id"] not in existing]
        if pending:
            await db.ground_truth.insert_many(pending, ordered=False)
    base = dataset.baseline()
    await seed_policy(db, base)
    internal, settlements = dataset.business("historical")
    benchmark = score(match(internal, settlements, base.matching), dataset.load("historical_ground_truth"), internal)
    await db.harness_policies.update_one({"version": base.version, "benchmark": {"$exists": False}},
        {"$set": {"benchmark": {key: benchmark[key] for key in
            ("accuracy", "auto_resolution_rate", "sample_size", "false_match_rate")}}})
    await seed_patch_versions(db)
    await db.control.update_one({"_id": "stream"}, {"$setOnInsert": {
        "position": 0, "total": dataset.live_total,
        "dataset_id": dataset.manifest.get("dataset_id", "seed-6643"),
        "phase_size": dataset.manifest.get("phase_size"),
        "phase_count": dataset.manifest.get("phase_count"),
        "pause_between_phases": dataset.manifest.get("pause_between_phases", False)}}, upsert=True)
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
        phase_size = claimed.get("phase_size")
        if claimed.get("pause_between_phases") and phase_size:
            phase = start // phase_size
            if start and start % phase_size == 0 and start < claimed["total"]:
                completed = await db.workflow_runs.find_one({
                    "dataset_id": claimed["dataset_id"], "phase_index": phase - 1,
                    "status": "COMPLETED"})
                if not completed:
                    await db.control.update_one({"_id": "stream", "lease_owner": owner},
                        {"$set": {"waiting_for_phase_approval": True}})
                    return {"status": "WAITING_FOR_PHASE_APPROVAL", "position": start,
                            "total": claimed["total"], "phase_index": phase - 1}
            end = min(end, (phase + 1) * phase_size)
        if end == start:
            return {"position": start, "total": claimed["total"], "status": "STREAM_COMPLETE"}
        internal, settlements = dataset.business("live")
        for name, records, id_field in [("internal_ledger", internal, "internal_record_id"),
                                         ("processor_settlement", settlements, "processor_record_id")]:
            for i in range(start, end):
                record = {**records[i], "dataset_split": "live", "stream_index": i}
                await db[name].update_one({id_field: record[id_field]}, {"$setOnInsert": record}, upsert=True)
        # Data is committed before the cursor becomes visible to the reconciler.
        await db.control.update_one({"_id": "stream", "lease_owner": owner},
            {"$set": {"position": end, "updated_at": time.time(), "waiting_for_phase_approval": False}})
        event_id = f"data:{start}:{end}"
        await db.doorbell_events.update_one({"event_id": event_id}, {"$setOnInsert": {
            "event_id": event_id, "kind": "DATA", "position": end, "consumed": False, "timestamp": time.time()}}, upsert=True)
        await Repository(db).audit("stream", "batch_arrived", {"start": start, "end": end}, suffix=event_id)
        return {"start": start, "position": end, "total": claimed["total"]}
    finally:
        await db.control.update_one({"_id": "stream", "lease_owner": owner},
            {"$unset": {"lease_owner": "", "lease_until": ""}})
