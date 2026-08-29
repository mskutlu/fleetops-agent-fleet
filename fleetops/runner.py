"""Orchestrates the incident flow: plan -> execute subtasks with specialists.

Every step is traced to the `traces` collection, prior context is pulled from
the memory bank before specialists act, and task events are published to the
`incidents` topic."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agents import build_agents
from .events import InMemoryPubSub
from .store import InMemoryFirestore, SessionDoc, TraceSpan

TOPIC = "incidents"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


class FleetOpsRunner:
    def __init__(self, db: InMemoryFirestore | None = None, pubsub: InMemoryPubSub | None = None):
        self.db = db or InMemoryFirestore()
        self.pubsub = pubsub or InMemoryPubSub()
        self.topic = self.pubsub.topic(TOPIC)
        self.planner, self.diagnoser, self.remediator, self.cards = build_agents()
        self._runners = {
            name: InMemoryRunner(agent=agent, app_name="fleetops")
            for name, agent in (("planner", self.planner), ("diagnoser", self.diagnoser), ("remediator", self.remediator))
        }

    # -- public API ---------------------------------------------------------

    def create_incident(self, description: str, service: str) -> str:
        incident_id = f"inc-{uuid.uuid4().hex[:8]}"
        doc = SessionDoc(
            incident_id=incident_id,
            status="accepted",
            description=description,
            service=service,
            created_at=_now(),
            updated_at=_now(),
        )
        self.db.collection("sessions").document(incident_id).set(doc.__dict__)
        self.trace(incident_id, "system", "incident_accepted", {"service": service, "description": description})
        self.topic.publish({"type": "incident.accepted", "incident_id": incident_id, "service": service})
        return incident_id

    def run_incident_sync(self, incident_id: str) -> dict:
        return asyncio.run(self.run_incident(incident_id))

    async def run_incident(self, incident_id: str) -> dict:
        ref = self.db.collection("sessions").document(incident_id)
        doc = ref.get().to_dict()

        # 1. Plan
        self._set_status(ref, doc, "planning")
        plan_text = await self._run_agent("planner", f"{doc['description']} (Service: {doc['service']})")
        plan = (_extract_json(plan_text) or {}).get("subtasks") or []
        doc = ref.get().to_dict()
        doc["plan"] = plan
        ref.set(doc)
        self.trace(incident_id, "planner", "planner_plan", {"plan": plan, "raw": plan_text})
        for st in plan:
            self.topic.publish({"type": "task.created", "incident_id": incident_id, "task": st})

        # 2. Execute subtasks
        for st in plan:
            kind, service = st["kind"], st["service"]
            agent_name = "diagnoser" if kind == "diagnose" else "remediator"
            memory = self.db.collection("memory").document(service).get().to_dict()
            self.trace(incident_id, agent_name, "memory_read", {"memory": memory or {}})
            context = (
                f"Subtask: {st['title']}\nKind: {kind}\nService: {service}\n"
                f"Incident: {doc['description']}\n"
                f"Memory context: {json.dumps(memory or {}, sort_keys=True)}"
            )
            result = await self._run_agent(agent_name, context)
            self.trace(incident_id, agent_name, f"{agent_name}_result", {"result": result})
            if kind == "diagnose":
                self._remember(service, result)
                doc = ref.get().to_dict()
                doc["findings"].append(result)
                ref.set(doc)
            else:
                doc = ref.get().to_dict()
                doc["actions"].append(result)
                ref.set(doc)
            self.topic.publish({"type": "task.completed", "incident_id": incident_id, "task_id": st["id"], "agent": agent_name})

        # 3. Done
        self._set_status(ref, ref.get().to_dict(), "resolved")
        self.trace(incident_id, "system", "incident_resolved", {"subtasks": len(plan)})
        self.topic.publish({"type": "incident.completed", "incident_id": incident_id})
        return ref.get().to_dict()

    def trace(self, incident_id: str, agent: str, step: str, detail: dict) -> None:
        span = TraceSpan(
            id=f"span-{uuid.uuid4().hex[:8]}",
            incident_id=incident_id,
            agent=agent,
            step=step,
            detail=detail,
            ts=_now(),
        )
        self.db.collection("traces").add(span.to_doc())

    def agent_cards(self) -> list[dict]:
        return [c.__dict__ for c in self.cards]

    def get_traces(self, incident_id: str | None = None) -> list[dict]:
        spans = [s.to_dict() for s in self.db.collection("traces").stream()]
        if incident_id:
            spans = [s for s in spans if s["incident_id"] == incident_id]
        return sorted(spans, key=lambda s: s["ts"])

    # -- internals ----------------------------------------------------------

    def _remember(self, service: str, findings: str) -> None:
        ref = self.db.collection("memory").document(service)
        existing = ref.get().to_dict() or {"findings": []}
        existing["findings"] = (existing.get("findings") or [])[-4:] + [findings]
        existing["updated_at"] = _now()
        ref.set(existing)

    @staticmethod
    def _set_status(ref, doc: dict, status: str) -> None:
        doc["status"] = status
        doc["updated_at"] = _now()
        ref.set(doc)

    async def _run_agent(self, name: str, message: str) -> str:
        runner = self._runners[name]
        session_id = f"s-{uuid.uuid4().hex[:12]}"
        await runner.session_service.create_session(app_name="fleetops", user_id="fleet", session_id=session_id)
        final = ""
        async for event in runner.run_async(
            user_id="fleet",
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            if event.is_final_response and event.content and event.content.parts:
                final = "".join(p.text or "" for p in event.content.parts if p.text)
        return final
