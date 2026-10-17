"""Local API. The scheduler is disposable; MongoDB owns all execution state."""
import asyncio
from contextlib import asynccontextmanager, suppress
import hmac
import os
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.error_details import error_details
from pydantic import BaseModel, Field

from app.config import Settings
from app.model import model_configuration
from app.demo.generator import Dataset
from app.demo.scenarios import advance, seed
from app.persistence.mongo import connect, init_indexes
from app.persistence.repositories import Repository, rows
from app.workflow.controller import Controller, BusyError


class StreamRequest(BaseModel):
    count: int = Field(default=50, ge=1, le=5000)


class ApprovalRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT", "MORE_EVIDENCE"]


class EngineRequest(BaseModel):
    enabled: bool


def create_api(settings=None, database=None, reasoners=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(api):
        client = None
        db = database
        if db is None and settings.mongodb_uri:
            client, db = connect(settings)
            await init_indexes(db)
        api.state.db = db
        api.state.controller = Controller(db, settings, reasoners) if db is not None else None
        dataset = Dataset(settings.dataset_dir)

        if db is not None:
            # Make startup hands-off: seed idempotently, then let the service own
            # stream ingestion and evaluator scheduling for the life of the API.
            await seed(db, dataset)
            await db.control.update_one({"_id": "engine"}, {"$set": {
                "enabled": True, "interval_seconds": 1,
                "batch_size": 10, "ingestion_interval_seconds": 5}}, upsert=True)

        async def scheduler(ingest=False):
            while True:
                ingestion = await db.control.find_one({"_id": "engine"}) if ingest and db is not None else {}
                await asyncio.sleep(max(1, (ingestion or {}).get("ingestion_interval_seconds", 5)) if ingest else 1)
                if db is None:
                    continue
                try:
                    stream = await db.control.find_one({"_id": "stream"})
                    if not stream:
                        continue
                    if ingest:
                        if stream["position"] < stream["total"]:
                            await advance(db, dataset, max(1, min(5000, (ingestion or {}).get("batch_size", 10))))
                        continue
                    # Evaluation and ingestion have independent tasks and leases.
                    result = await api.state.controller.tick()
                    if isinstance(result, dict) and result.get("status") in {"WAITING_APPROVAL", "COMPLETED"}:
                        # A recovered workflow clears the transient banner; its
                        # earlier failed runs remain in the historical audit.
                        await db.control.update_one({"_id": "engine"}, {"$unset": {
                            "last_error": "", "last_error_details": "", "last_error_at": ""}})
                except BusyError:
                    pass
                except ValueError as exc:
                    # Concurrent stream/evaluator work can hold a lease briefly.
                    if "Another stream batch" not in str(exc):
                        await db.control.update_one({"_id": "engine"}, {"$set": {
                            "last_error": type(exc).__name__, "last_error_details": error_details(exc),
                            "last_error_at": time.time()}}, upsert=True)
                except Exception as exc:
                    await db.control.update_one({"_id": "engine"}, {"$set": {
                        "last_error": type(exc).__name__, "last_error_details": error_details(exc),
                        "last_error_at": time.time()}}, upsert=True)
        tasks = [asyncio.create_task(scheduler(ingest=True)), asyncio.create_task(scheduler())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if client:
                await client.close()

    async def auth(authorization: str | None = Header(default=None)):
        if settings.api_token and not hmac.compare_digest(authorization or "", f"Bearer {settings.api_token}"):
            raise HTTPException(401, "Invalid API token")

    api = FastAPI(title="ReconForge", version="0.1.0", lifespan=lifespan, dependencies=[Depends(auth)])
    api.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    def database_ready():
        if api.state.db is None:
            raise HTTPException(503, "Set MONGODB_URI in .env and restart the API")
        return api.state.db

    async def call(operation):
        try:
            return await operation
        except BusyError as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
        except Exception as exc:
            raise HTTPException(503, f"Operation failed ({type(exc).__name__}); check service configuration and resume the saved run") from None

    @api.get("/health")
    async def health():
        model = model_configuration(settings.model_name)
        return {"status": "ready" if api.state.db is not None else "configuration_required",
                "mongodb_configured": api.state.db is not None,
                **model, "model_configured": model["model_configured"] or reasoners is not None}

    @api.post("/demo/seed")
    async def seed_demo():
        from app.workflow.controller import engine_lease
        db = database_ready()
        async with engine_lease(db):
            return await call(seed(db, Dataset(settings.dataset_dir)))

    @api.post("/stream/advance")
    async def stream_batch(body: StreamRequest):
        return await call(advance(database_ready(), Dataset(settings.dataset_dir), body.count))

    @api.post("/engine/control")
    async def engine_control(body: EngineRequest):
        db = database_ready()
        await db.control.update_one({"_id": "engine"}, {"$set": {"enabled": body.enabled}}, upsert=True)
        return {"enabled": body.enabled}

    @api.post("/engine/tick")
    async def engine_tick():
        database_ready()
        return await call(api.state.controller.tick())

    @api.post("/runs/start")
    async def start_run():
        database_ready()
        return await call(api.state.controller.start())

    @api.get("/runs/{run_id}")
    async def get_run(run_id: str):
        run = await Repository(database_ready()).run(run_id)
        if not run:
            raise HTTPException(404, "Unknown run")
        return run

    @api.get("/runs/{run_id}/events")
    async def get_events(run_id: str):
        return await database_ready().agent_action_logs.find({"run_id": run_id}, {"_id": 0}).sort("timestamp", 1).to_list(None)

    @api.post("/runs/{run_id}/approval")
    async def approve_run(run_id: str, body: ApprovalRequest):
        database_ready()
        return await call(api.state.controller.approve(run_id, body.decision))

    @api.post("/runs/{run_id}/resume")
    async def resume_run(run_id: str):
        database_ready()
        return await call(api.state.controller.resume(run_id))

    @api.get("/policies")
    async def policies():
        return await rows(database_ready().harness_policies)

    @api.get("/memories/search")
    async def memories(q: str = ""):
        candidates = await rows(database_ready().incident_memories, {"verified": True})
        words = q.lower().split()
        return sorted(candidates, key=lambda m: -sum(w in m["summary"].lower() for w in words))[:5]

    @api.get("/dashboard")
    async def dashboard():
        db = database_ready()
        repo = Repository(db)
        active = await db.control.find_one({"_id": "active_policy"}, {"_id": 0})
        active_policy = active.get("policy") if active else None
        active_patch = await db.harness_policies.find_one(
            {"version": active_policy["version"]}, {"_id": 0, "patch_name": 1}) if active_policy else None
        runs = await db.workflow_runs.find({}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(None)
        evaluations = await db.policy_evaluations.find({}, {"_id": 0}).sort("created_at", 1).to_list(None)
        snapshots = await db.metric_snapshots.find({}, {"_id": 0}).sort("timestamp", -1).limit(200).to_list(None)
        decisions = await db.evaluator_decisions.find({}, {"_id": 0}).sort("timestamp", -1).limit(50).to_list(None)
        current_evaluation = next((item for item in decisions
                                   if active_policy and item.get("policy_version") == active_policy["version"]), None)
        sessions = await db.adk_sessions.find({}, {"_id": 0, "session_id": 1, "last_event_seq": 1, "last_invocation_id": 1}).to_list(None)
        policies = await rows(db.harness_policies)
        policy_history = [{"version": p["version"], "name": p.get("patch_name", p["version"]),
                           **p["benchmark"]} for p in sorted(policies, key=lambda p: p.get("created_at", 0))
                          if p.get("benchmark") and (p["version"] == (active_policy or {}).get("version")
                              or p.get("status") == "ARCHIVED")]
        return {"active_policy": active_policy,
                "policy_accuracy_history": policy_history,
                "agents": [
                    {"name": "Diagnosis", "stage": "diagnose", "role": "Identify the recurring break and likely root cause."},
                    {"name": "Analysis", "stage": "analysis", "role": "Check measured evidence, risks, and verified memories."},
                    {"name": "Evolution", "stage": "upgrade", "role": "Use the Policy Update Skill, diagnosis, and analysis to propose one bounded policy change."}],
                "active_patch_name": (active_patch or {}).get("patch_name", "Zero-tolerance baseline" if active_policy and active_policy["version"] == "v1" else (active_policy or {}).get("version")),
                "stream": await db.control.find_one({"_id": "stream"}, {"_id": 0}) or {"position": 0, "total": dataset.live_total},
                "engine": await db.control.find_one({"_id": "engine"}, {"_id": 0}) or {},
                "runs": runs, "evaluations": evaluations, "domain": await repo.domain_metrics(),
                "snapshots": list(reversed(snapshots)), "sessions": sessions,
                "policies": policies,
                "memories": await rows(db.incident_memories, {"verified": True}),
                "doorbells": await db.doorbell_events.find({}, {"_id": 0}).sort("timestamp", -1).limit(50).to_list(None),
                "checks": snapshots[0].get("check_counts", {}) if snapshots else {},
                "decisions": decisions,
                "current_evaluation": current_evaluation,
                "cases": await db.reconciliation_cases.find({"status": {"$ne": "RESOLVED_AUTO"}}, {"_id": 0}).limit(200).to_list(None)}

    frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if (frontend_dist / "assets").is_dir():
        api.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")

        @api.get("/{frontend_path:path}", include_in_schema=False)
        async def frontend_app(frontend_path: str):
            root = frontend_dist.resolve()
            file_path = (root / frontend_path).resolve()
            if frontend_path and file_path.is_relative_to(root) and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(root / "index.html")

    return api


app = create_api()
