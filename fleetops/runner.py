"""Orchestrates the incident flow across an async pub/sub runtime.

Request path (fast, no agent work): `create_incident` persists a session doc
and publishes `incident.accepted`. That is all that runs inline.

Worker path (off-request): a `Worker` drains the topic queue. An
`incident.accepted` event triggers planning — the planner recalls prior fleet
outcomes from the memory bank BEFORE acting and may only dispatch subtasks to
registered+approved agents (registry gate; unresolvable kinds block the
incident with a clear reason). Each subtask becomes a `task.created` job:
resolve capability -> read specialist's memory notes -> run agent -> write the
result back to memory + session doc (persisted before the task is marked done)
-> publish `task.completed`. When every task is done, one consolidated outcome
is written to fleet-level memory (the cross-session recall target), the
session flips to `resolved`, and `incident.completed` is published.

Crash-resume: job state lives in the Firestore session doc + the topic queue,
never only in process memory. A crashed worker's unacked jobs stay on the
topic; a fresh worker resumes from persisted state — done tasks are skipped
(at-least-once), in-flight ones re-run."""

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
from .gateway import DEFAULT_TOKEN, INCIDENT_ID, PRINCIPAL_FOR_AGENT, PolicyViolation
from .gateway import Gateway
from .memory import MemoryBank
from .registry import Registry
from .store import InMemoryFirestore, SessionDoc, TraceSpan

TOPIC = "incidents"

# subtask kind -> capability the serving agent must register + approved for
CAPABILITY_FOR_KIND = {
    "diagnose": "incident.diagnose",
    "remediate": "incident.remediate",
}


class SimulatedCrash(RuntimeError):
    """Worker died mid-run (process kill in production). Unacked jobs remain
    on the topic queue; session state is persisted — a new worker resumes."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _principal_token(agent_name: str) -> str:
    """Demo principal token carrying this agent's hops (synthetic, seeded)."""
    principal = PRINCIPAL_FOR_AGENT[agent_name]
    from .gateway import _SEED_PRINCIPALS
    return _SEED_PRINCIPALS[principal][0]


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
        self.planner, self.diagnoser, self.remediator, self.cards = None, None, None, []
        # Stage 2b pillars: gateway (identity + policy + Model Armor) first —
        # agent tools are built behind its Armor guard.
        self.gateway = Gateway(self.db, self.trace)
        self.planner, self.diagnoser, self.remediator, self.cards = build_agents(gateway=self.gateway)
        # Stage 2a pillars: registry + memory bank (both backed by Firestore docs)
        self.registry = Registry(self.db)
        for card in self.cards:
            self.registry.publish(card)
        self.memory = MemoryBank(self.db)
        self._runners = {
            name: InMemoryRunner(agent=agent, app_name="fleetops")
            for name, agent in (("planner", self.planner), ("diagnoser", self.diagnoser), ("remediator", self.remediator))
        }

    # -- request path -------------------------------------------------------

    def create_incident(self, description: str, service: str,
                        principal_token: str = DEFAULT_TOKEN) -> str:
        """Accept an incident. Persists state + publishes the first job event;
        NO agent work runs here — a Worker picks the job up from the queue.
        The gateway routes the caller's dispatch hop to the planner (traced)."""
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
        self.gateway.check(principal_token, "dispatch", "incident.plan", incident_id)
        self.topic.publish({"type": "incident.accepted", "incident_id": incident_id, "service": service})
        return incident_id

    # -- worker path --------------------------------------------------------

    async def handle_msg(self, msg: dict) -> None:
        data = msg["data"]
        if data.get("type") == "incident.accepted":
            await self._plan(data["incident_id"])
        elif data.get("type") == "task.created":
            await self._execute_task(data["incident_id"], data["task"]["id"])
        # else: completion notifications (task.completed / incident.completed) —
        # downstream signals; no state change here. Redeliveries are harmless.
    def rejection_reason(self, capability: str) -> str:
        """Clear gateway-style reason for a capability no approved agent serves."""
        reason = f"no registered+approved agent serves capability '{capability}'"
        cands = self.registry.candidates_for(capability)
        if cands:
            reason += f" (registered but unapproved: {', '.join(cands)})"
        return reason

    async def _plan(self, incident_id: str) -> None:
        ref = self.db.collection("sessions").document(incident_id)
        doc = ref.get().to_dict()
        incident = INCIDENT_ID.set(incident_id)  # armor attributes tool calls to this incident
        try:
            await self._plan_inner(ref, doc)
        finally:
            INCIDENT_ID.reset(incident)

    async def _plan_inner(self, ref, doc: dict) -> None:
        incident_id = doc["incident_id"]
        self._set_status(ref, "planning")

        # Memory BEFORE acting: recall this service's prior fleet outcomes.
        prior = self.memory.read("fleet", doc["service"])
        context = f"Incident: {doc['description']} (Service: {doc['service']})"
        if prior:
            recalled = "\n".join(e["text"] for e in prior)
            context += f"\nRecalled prior outcome from the fleet memory bank:\n{recalled}"
        self.trace(incident_id, "planner", "memory_read", {"principal": f"fleet:{doc['service']}", "entries": prior})

        plan_text = await self._run_agent("planner", context)
        subtasks = (_extract_json(plan_text) or {}).get("subtasks") or []
        if not subtasks:
            self.trace(incident_id, "planner", "plan_empty", {"raw": plan_text})
            self._set_status(ref, "blocked")
            return

        # Registry gate: planner may only dispatch to registered+approved agents.
        for st in subtasks:
            cap = CAPABILITY_FOR_KIND.get(st.get("kind"))
            if self.registry.resolve(cap) is None:
                reason = (f"capability '{cap}' not served by any registered+approved agent"
                          + (f" (registered but unapproved: {', '.join(self.registry.candidates_for(cap))})"
                             if cap and self.registry.candidates_for(cap) else ""))
                self.trace(incident_id, "planner", "dispatch_rejected", {"kind": st.get("kind"), "capability": cap, "reason": reason})
                self._set_status(ref, "blocked")
                return

        for st in subtasks:
            st["status"] = "pending"
        ref.set({**doc, "plan": subtasks})
        self.trace(incident_id, "planner", "planner_plan", {"plan": subtasks, "raw": plan_text})
        self._set_status(ref, "executing")
        for st in subtasks:  # one job event per subtask — execution is off-request from here
            self.topic.publish({"type": "task.created", "incident_id": incident_id, "task": st})

    async def _execute_task(self, incident_id: str, task_id: str) -> None:
        incident = INCIDENT_ID.set(incident_id)  # armor attributes tool calls to this incident
        try:
            await self._execute_task_inner(incident_id, task_id)
        finally:
            INCIDENT_ID.reset(incident)

    async def _execute_task_inner(self, incident_id: str, task_id: str) -> None:
        ref = self.db.collection("sessions").document(incident_id)
        doc = ref.get().to_dict()
        task = next((t for t in doc["plan"] if t["id"] == task_id), None)
        if task is None:
            self.trace(incident_id, "system", "task_unknown", {"task_id": task_id})
            return
        # Resume idempotency: redelivered jobs whose work already landed are skipped.
        if task.get("status") == "done":
            self.trace(incident_id, "system", "task_skipped_done", {"task_id": task_id})
            return

        kind = task["kind"]
        agent_name = "diagnoser" if kind == "diagnose" else "remediator"
        cap = CAPABILITY_FOR_KIND[kind]
        # Gateway hop: the specialist's own principal executes — identity +
        # policy + capability resolution in one traced decision.
        try:
            self.gateway.check(_principal_token(agent_name), "execute", cap, incident_id)
        except PolicyViolation as e:
            self.trace(incident_id, agent_name, "dispatch_rejected", {"task_id": task_id, "capability": cap, "reason": e.reason})
            self._set_status(ref, "blocked")
            return

        service = task.get("service") or doc["service"]
        # Memory BEFORE acting: the specialist's own prior notes on this service.
        notes = self.memory.read(agent_name, service)
        context = (
            f"Subtask: {task['title']}\nKind: {kind}\nService: {service}\n"
            f"Incident: {doc['description']}"
        )
        if notes:
            context += "\nRecalled prior context from the memory bank:\n" + json.dumps(notes, sort_keys=True)
        self.trace(incident_id, agent_name, "memory_read", {"principal": f"{agent_name}:{service}", "entries": notes})

        # Persist in-flight state BEFORE the (slow) agent run — crash evidence:
        # if we die here, a resumed worker sees status=running and re-runs the job.
        inflight = ref.get().to_dict()
        for t in inflight["plan"]:
            if t["id"] == task_id:
                t["status"] = "running"
        ref.set(inflight)

        result = await self._run_agent(agent_name, context)

        # Write back AFTER: memory bank + session doc, then mark done (atomic order).
        ts = _now()
        self.memory.write(agent_name, service, result, ts)
        fresh = ref.get().to_dict()
        if kind == "diagnose":
            fresh["findings"] = (fresh.get("findings") or []) + [result]
        else:
            fresh["actions"] = (fresh.get("actions") or []) + [result]
        for t in fresh["plan"]:
            if t["id"] == task_id:
                t["status"] = "done"
        ref.set(fresh)
        self.trace(incident_id, agent_name, f"{agent_name}_result", {"result": result})
        self.topic.publish({"type": "task.completed", "incident_id": incident_id, "task_id": task_id, "agent": agent_name})

        # Completion: all tasks done -> resolve + record the cross-session outcome.
        fresh = ref.get().to_dict()
        if fresh["plan"] and all(t.get("status") == "done" for t in fresh["plan"]):
            outcome = (f"Incident {incident_id} on {fresh['service']} resolved: "
                       f"findings={' | '.join(fresh.get('findings') or [])}; "
                       f"actions={' | '.join(fresh.get('actions') or [])}")
            self.memory.write("fleet", fresh["service"], outcome, _now())
            self._set_status(ref, "resolved")
            self.trace(incident_id, "system", "incident_resolved", {"subtasks": len(fresh["plan"])})
            self.topic.publish({"type": "incident.completed", "incident_id": incident_id})

    # -- shared surface -----------------------------------------------------

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

    def approved_agents(self) -> list[dict]:
        return [c.__dict__ for c in self.registry.list_approved()]

    def get_traces(self, incident_id: str | None = None) -> list[dict]:
        spans = [s.to_dict() for s in self.db.collection("traces").stream()]
        if incident_id:
            spans = [s for s in spans if s["incident_id"] == incident_id]
        return sorted(spans, key=lambda s: s["ts"])

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _set_status(ref, status: str) -> None:
        doc = ref.get().to_dict()
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


class Worker:
    """Drains the incident topic until it is idle. `crash_after` simulates a
    process kill after N handled jobs — unacked jobs stay on the topic and a
    new Worker resumes from persisted state (see FleetOpsRunner.handle_msg)."""

    def __init__(self, runner: FleetOpsRunner, crash_after: int | None = None):
        self.runner = runner
        self.crash_after = crash_after

    def run(self) -> int:
        jobs = 0
        while True:
            msg = self.runner.topic.pop(timeout=0.25)
            if msg is None:
                return jobs  # queue idle — nothing left to do
            asyncio.run(self.runner.handle_msg(msg))
            jobs += 1
            if self.crash_after and jobs >= self.crash_after:
                raise SimulatedCrash(
                    f"worker died after {jobs} job(s); unacked on topic: "
                    f"{self.runner.topic.pending_count}"
                )
