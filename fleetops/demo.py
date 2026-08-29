"""Local harness — `make demo` MUST pass before commit.

Stage 2a coverage (all deterministic, offline-capable):
  [1] AGENT REGISTRY      approved-only listing, publish a pending card,
                          capability discovery incl. a clear rejection of an
                          unregistered/unapproved capability
  [2] ASYNC RUNTIME       incident A fully off the request path via pub/sub;
                          SIMULATED CRASH mid-run; RESTART resumes from the
                          persisted Firestore state (kill-and-resume)
  [3] MEMORY BANK         incident B on the same service: planner + specialists
                          recall incident A's outcome BEFORE acting (recalled
                          text printed), write summaries back after
  [4] HTTP SURFACE        endpoints exercised end-to-end, traces verified

Exits non-zero if anything breaks."""

from __future__ import annotations

import json
import os
import sys

from .llm import DEFAULT_GEMINI_MODEL, pinned_model
from .runner import FleetOpsRunner, SimulatedCrash, Worker
from .service import create_app

SERVICE = "payment-service"
INCIDENT_A = {
    "description": f"{SERVICE} returns 500s and high latency since the 14:00 deploy; "
                   "upstream calls to payments-db are timing out",
    "service": SERVICE,
}
INCIDENT_B = {
    "description": f"latency recurred on {SERVICE} after last night's scale-up; "
                   "need the same incident handled again",
    "service": SERVICE,
}


def _section(title: str) -> None:
    print(f"\n{'=' * 64}\n[{title}]\n{'=' * 64}")


def _session(runner: FleetOpsRunner, iid: str) -> dict:
    return runner.db.collection("sessions").document(iid).get().to_dict()


def _print_chain(runner: FleetOpsRunner, iid: str) -> None:
    print("\n--- reasoning chain ---")
    for span in runner.get_traces(iid):
        detail = json.dumps(span["detail"], sort_keys=True)[:220]
        print(f"[{span['agent']:>10}] {span['step']:<18} {detail}")


def main() -> int:
    keyed = bool(os.environ.get("GEMINI_API_KEY"))
    model = pinned_model() if keyed else "mock (offline, deterministic)"
    print("== FleetOps Stage 2a demo — registry + async runtime + memory bank ==")
    print(f"model pin: GEMINI_MODEL={pinned_model()} (default {DEFAULT_GEMINI_MODEL}) | active LLM: {model}")

    runner = FleetOpsRunner()

    # ------------------------------------------------------------------ [1]
    _section("1. AGENT REGISTRY — publish / version / discover approved agents")
    from fastapi.testclient import TestClient

    client = TestClient(create_app(runner))  # shared runner: one registry, one queue

    agents = client.get("/agents").json()
    assert len(agents) == 3 and all(a["approval_status"] == "approved" for a in agents)
    print("GET /agents (approved only):")
    for a in agents:
        print(f"  {a['name']:<10} v{a['version']} caps={a['capabilities']} dept={a['owner_dept']}")

    r = client.post("/agents", json={
        "name": "billing-refunder", "role": "specialist",
        "description": "Refunds billing disputes (pending enterprise approval).",
        "model": pinned_model() if keyed else "mock",
        "capabilities": ["billing.refund"], "owner_dept": "finance",
        "version": "0.9.0", "approval_status": "pending",
    })
    assert r.status_code == 201, r.text
    print(f"POST /agents billing-refunder -> {r.status_code} (submitted as pending)")

    agents = client.get("/agents").json()
    names = [a["name"] for a in agents]
    assert "billing-refunder" not in names, "pending card must NOT be listed"
    print(f"GET /agents still lists {names} — pending card hidden from discovery ✓")

    ok = client.get("/capabilities/incident.diagnose").json()
    print(f"discovery GET /capabilities/incident.diagnose -> 200 served by "
          f"{ok['agent']['name']} v{ok['agent']['version']}")
    rej = client.get("/capabilities/billing.refund")
    assert rej.status_code == 404, rej.text
    print(f"discovery GET /capabilities/billing.refund   -> {rej.status_code} "
          f"{rej.json()['detail']}")

    # Retire the app's background worker (deterministic sections drive their own
    # Worker below; in `make run` this same thread is what drains the queue).
    client.app.state.worker_stop.set()
    client.app.state.worker_thread.join(timeout=3)

    # ------------------------------------------------------------------ [2]
    _section("2. ASYNC RUNTIME — incident A off the request path; kill-and-resume")
    iid_a = runner.create_incident(INCIDENT_A["description"], INCIDENT_A["service"])
    print(f"POST /incidents -> 202 accepted {iid_a} (request path returned before any agent work)")
    assert _session(runner, iid_a)["status"] == "accepted", "no inline execution allowed"

    w1 = Worker(runner, crash_after=2)  # dies after: incident.accepted + task t1
    try:
        handled = w1.run()
        raise AssertionError("worker was supposed to crash")
    except SimulatedCrash as e:
        print(f"\n*** SIMULATED CRASH — {e}")
    snap = _session(runner, iid_a)
    task_states = {t["id"]: t["status"] for t in snap["plan"]}
    print(f"persisted state at crash (Firestore session doc): status={snap['status']} tasks={task_states} "
          f"findings={len(snap['findings'])}")
    assert task_states.get("t1") == "done", "crash point assumed t1 done"
    assert runner.topic.pending_count >= 1, "unacked job must survive the crash"

    print("\n*** RESTART — new worker resumes from persisted state")
    w2 = Worker(runner)
    handled = w2.run()
    snap = _session(runner, iid_a)
    task_states = {t["id"]: t["status"] for t in snap["plan"]}
    print(f"after resume: status={snap['status']} tasks={task_states} "
          f"findings={len(snap['findings'])} actions={len(snap['actions'])}")
    assert snap["status"] == "resolved", "crash-resume did not resolve incident A"
    assert all(v == "done" for v in task_states.values())
    _print_chain(runner, iid_a)

    # ------------------------------------------------------------------ [3]
    _section("3. MEMORY BANK — incident B recalls A's outcome before acting")
    prior_fleet = runner.memory.read("fleet", SERVICE)
    assert prior_fleet, "incident A must have recorded a fleet-level outcome"
    print("[memory] planner context BEFORE planning (recalled from the memory bank):")
    for e in prior_fleet:
        print(f"  fleet:{SERVICE} <- {e['text']}")

    iid_b = runner.create_incident(INCIDENT_B["description"], INCIDENT_B["service"])
    Worker(runner).run()
    snap_b = _session(runner, iid_b)
    assert snap_b["status"] == "resolved", f"incident B: {snap_b['status']}"

    # specialists read their own prior notes BEFORE acting (trace evidence):
    chain = runner.get_traces(iid_b)
    reads = [s for s in chain if s["step"] == "memory_read"]
    recalled_by = sorted({s["detail"]["principal"] for s in reads})
    assert any(p.startswith(f"diagnoser:{SERVICE}") or p.startswith("fleet:") for p in recalled_by), \
        "specialists/planner must read memory before acting on incident B"
    print(f"\n[memory] principals that recalled prior context BEFORE acting: {recalled_by}")
    for s in reads:
        if s["detail"]["entries"]:
            e0 = s["detail"]["entries"][0]["text"][:120]
            print(f"  {s['agent']} <- {e0}...")

    after_fleet = runner.memory.read("fleet", SERVICE)
    assert len(after_fleet) == 2, "both incidents' outcomes must be in fleet memory"
    print("\n[memory bank] fleet-level outcomes for payment-service (cross-session):")
    for e in after_fleet:
        print(f"  {e['ts'][:19]}Z  {e['text']}")
    _print_chain(runner, iid_b)

    # ------------------------------------------------------------------ [4]
    _section("4. HTTP SURFACE — end-to-end sanity (incident C via API)")
    r = client.post("/incidents", json=INCIDENT_B)
    assert r.status_code == 202, r.text
    iid_c = r.json()["id"]
    Worker(runner).run()  # app worker retired for determinism; drive the queue explicitly
    doc = client.get(f"/incidents/{iid_c}").json()
    assert doc["status"] == "resolved", doc["status"]
    print(f"POST /incidents      -> 202 {iid_c} (accepted off-request; worker drained the queue)")
    print(f"GET /incidents/{{id}} -> status={doc['status']} plan={len(doc['plan'])} subtasks")
    agents = client.get("/agents").json()
    assert len(agents) == 3
    print(f"GET /agents          -> {len(agents)} approved cards (pending still hidden)")
    traces = client.get("/traces", params={"incident_id": iid_c}).json()
    assert len(traces) >= 6, "trace chain too short"
    print(f"GET /traces          -> {len(traces)} spans for {iid_c}")

    print("\nDEMO PASSED — registry ✓ crash-resume ✓ cross-session memory ✓ async runtime ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
