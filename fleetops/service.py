"""FastAPI control-plane surface (Stage 2 will wrap this with gateway,
identity and guardrails):

    POST /incidents        -> 202, runs the agent flow in the background
    GET  /incidents/{id}   -> session doc (status, plan, findings, actions)
    GET  /agents           -> agent cards
    GET  /traces           -> trace spans (?incident_id= to filter)
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .runner import FleetOpsRunner


class IncidentCreate(BaseModel):
    description: str
    service: str = "app"


def create_app(runner: FleetOpsRunner | None = None) -> FastAPI:
    runner = runner or FleetOpsRunner()
    pool = ThreadPoolExecutor(max_workers=4)
    app = FastAPI(title="FleetOps Control Plane", version="0.1.0")

    @app.post("/incidents", status_code=202)
    def post_incident(body: IncidentCreate) -> dict:
        incident_id = runner.create_incident(body.description, body.service)
        pool.submit(runner.run_incident_sync, incident_id)
        return {"id": incident_id, "status": "accepted"}

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> dict:
        doc = runner.db.collection("sessions").document(incident_id).get().to_dict()
        if doc is None:
            raise HTTPException(status_code=404, detail="incident not found")
        return doc

    @app.get("/agents")
    def get_agents() -> list[dict]:
        return runner.agent_cards()

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
