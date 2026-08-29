"""FastAPI control-plane surface — Stage 2b puts the gateway in front:

    Authorization: Bearer <principal token> is required on mutating routes:
    POST /incidents needs the `dispatch` scope, POST /agents the `publish`
    scope. Unknown principals get 401, out-of-scope ones 403 — every decision
    (allow and deny) lands in the trace store as a gateway span.

    POST /incidents             -> 202; persists state + publishes job events,
                                   NO agent work on the request path — a
                                   background worker drains the pub/sub queue
    GET  /incidents/{id}        -> session doc (status, plan, findings, actions)
    GET  /agents                -> APPROVED agent cards only (Firestore registry)
    POST /agents                -> publish/register an agent card (publish scope)
    GET  /capabilities/{cap}    -> discovery: approved agent serving the
                                   capability, or 404 with a clear reason
    GET  /traces                -> trace spans (?incident_id= to filter)
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from .gateway import Principal, PolicyViolation
from .gcp import make_backends
from .runner import FleetOpsRunner, SimulatedCrash
from .store import AgentCard


class IncidentCreate(BaseModel):
    description: str
    service: str = "app"


class AgentPublish(BaseModel):
    name: str
    role: str = "specialist"
    description: str = ""
    model: str = ""
    tools: list[str] = []
    skills: list[str] = []
    version: str = "1.0.0"
    capabilities: list[str] = []
    owner_dept: str = ""
    # publish = submit for approval; pass "approved" explicitly to fast-track
    approval_status: str = "pending"


def create_app(runner: FleetOpsRunner | None = None) -> FastAPI:
    if runner is None:
        # Backends follow FLEETOPS_BACKEND: fakes locally, real GCP on Cloud Run.
        db, pubsub = make_backends()
        runner = FleetOpsRunner(db=db, pubsub=pubsub)
    app = FastAPI(title="FleetOps Control Plane", version="0.3.0")

    def _gate(action: str):
        """Gateway dependency: authenticate + scope-check the principal."""

        def dep(authorization: str = Header(default="")) -> Principal:
            try:
                return runner.gateway.check(authorization, action, capability=None, incident_id="-")
            except PolicyViolation as e:
                raise HTTPException(status_code=e.status, detail=e.reason)

        return dep

    # One background worker drains the pub/sub queue (the off-request runtime).
    stop = threading.Event()

    def _workloop() -> None:
        while not stop.is_set():
            msg = runner.topic.pop(timeout=1.0)  # blocks until a job is published
            if msg is None:
                continue
            try:
                asyncio.run(runner.handle_msg(msg))
            except SimulatedCrash as e:  # demo hook: surface, don't kill the app
                print(f"[worker] {e}")
            except Exception as e:  # one bad job must not stop the fleet
                import sys

                print(f"[worker] job failed: {e!r}", file=sys.stderr)
        return None

    worker_thread = threading.Thread(target=_workloop, name="fleetops-worker", daemon=True)
    worker_thread.start()
    app.state.worker_stop = stop        # for tests/teardown
    app.state.worker_thread = worker_thread

    @app.post("/incidents", status_code=202)
    def post_incident(body: IncidentCreate, principal: Principal = Depends(_gate("dispatch"))) -> dict:
        incident_id = runner.create_incident(body.description, body.service, principal_token=principal.token)
        return {"id": incident_id, "status": "accepted", "routed_to": "planner", "principal": principal.name}

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict:
        doc = runner.db.collection("sessions").document(incident_id).get().to_dict()
        if doc is None:
            raise HTTPException(status_code=404, detail="incident not found")
        return doc

    @app.get("/agents")
    def get_agents() -> list[dict]:
        # Registry-backed, approved-only (Stage 2a requirement)
        return runner.approved_agents()

    @app.post("/agents", status_code=201)
    def post_agent(body: AgentPublish, principal: Principal = Depends(_gate("publish"))) -> dict:
        card = AgentCard(**body.model_dump())
        ref_id = runner.registry.publish(card)
        return {"name": ref_id, "approval_status": card.approval_status, "published_by": principal.name}

    @app.get("/capabilities/{capability}")
    def get_capability(capability: str) -> dict[str, Any]:
        # Discovery / gateway preflight: who serves this capability?
        card = runner.registry.resolve(capability)
        if card is None:
            raise HTTPException(status_code=404, detail=runner.rejection_reason(capability))
        return {"capability": capability, "agent": card.__dict__}

    @app.get("/traces")
    def get_traces(incident_id: str | None = None) -> list[dict]:
        return runner.get_traces(incident_id)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8080)
