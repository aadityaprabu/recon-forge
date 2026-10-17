from pymongo import AsyncMongoClient


def connect(settings):
    if not settings.mongodb_uri:
        raise ValueError("Set MONGODB_URI in .env before starting the backend")
    client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    return client, client[settings.mongodb_db]


async def init_indexes(db):
    for name, keys in {
        "adk_sessions": [("app_name", 1), ("user_id", 1), ("session_id", 1)],
        "adk_events": [("app_name", 1), ("user_id", 1), ("session_id", 1), ("event_id", 1)],
        "reconciliation_cases": [("internal_record_id", 1)],
        "workflow_runs": [("run_id", 1)],
        "harness_policies": [("version", 1)],
        "policy_evaluations": [("run_id", 1)],
        "doorbell_events": [("event_id", 1)],
        "human_approvals": [("run_id", 1)],
        "incident_memories": [("memory_id", 1)],
        "agent_action_logs": [("idempotency_key", 1)],
        "case_events": [("idempotency_key", 1)],
    }.items():
        await db[name].create_index(keys, unique=True)
    await db.adk_events.create_index([("session_id", 1), ("seq", 1)])
    await db.workflow_runs.create_index("status")
    await db.doorbell_events.create_index([("run_id", 1), ("consumed", 1)])
    # Operational telemetry is short-lived; durable decision records have no TTL.
    for name in ("metric_snapshots", "evaluator_decisions", "doorbell_events", "adk_sessions", "adk_events"):
        await db[name].create_index("expires_at", expireAfterSeconds=0)
