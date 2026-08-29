"""Local harness: runs the full planner -> specialist flow with fakes,
prints the reasoning chain + emitted events, then exercises the HTTP surface.
Exits non-zero if anything breaks. `make demo` MUST pass before commit."""

from __future__ import annotations

import json
import sys
import time

from .runner import FleetOpsRunner
from .service import create_app

INCIDENT = {
    "service": "payment-service",
    "description": "payment-service returns 500s and high latency since the 14:00 deploy; "
    "upstream calls to payments-db are timing out",
}


def _print_flow(runner: FleetOpsRunner, incident_id: str) -> None:
    print("\n--- reasoning chain ---")
    for span in runner.get_traces(incident_id):
        detail = json.dumps(span["detail"], sort_keys=True)[:300]
        print(f"[{span['agent']:>10}] {span['step']:<18} {detail}")

    print("\n--- emitted events ---")
    for msg in runner.topic.log:
        data = dict(msg["data"])
        print(f"{msg['message_id']:<22} {data.pop('type'):<20} {data}")

    session = runner.db.collection("sessions").document(incident_id).get().to_dict()
    print("\n--- memory bank (payment-service) ---")
    mem = runner.db.collection("memory").document("payment-service").get().to_dict()
    print(json.dumps(mem, indent=2)[:500])

    print(f"\nfinal status: {session['status']}")
    assert session["status"] == "resolved", "incident did not resolve"
    assert session["findings"], "no findings recorded"
    assert session["actions"], "no remediation actions recorded"
    assert len(session["plan"]) >= 2, "planner produced fewer than 2 subtasks"


def _print_http(runner: FleetOpsRunner) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(create_app(runner))
    r = client.post("/incidents", json=INCIDENT)
    assert r.status_code == 202, r.text
    incident_id = r.json()["id"]
    print(f"\n--- HTTP surface ---\nPOST /incidents        -> {r.status_code} {r.json()}")

    for _ in range(60):
        doc = client.get(f"/incidents/{incident_id}").json()
        if doc.get("status") == "resolved":
            break
        time.sleep(0.5)
    assert doc["status"] == "resolved", "background flow did not finish"
    print(f"GET  /incidents/{{id}}   -> 200 status={doc['status']} plan={len(doc['plan'])} subtasks")

    agents = client.get("/agents").json()
    assert len(agents) == 3
    print(f"GET  /agents           -> 200 {[a['name'] for a in agents]}")

    traces = client.get("/traces", params={"incident_id": incident_id}).json()
    assert len(traces) >= 6
    print(f"GET  /traces           -> 200 {len(traces)} spans for {incident_id}")


def main() -> int:
    import os

    model_mode = "gemini" if os.environ.get("GEMINI_API_KEY") else "mock-llm (offline)"
    print(f"== FleetOps demo — model: {model_mode} ==")
    print(f"incident: {INCIDENT['description']}")

    runner = FleetOpsRunner()
    incident_id = runner.create_incident(INCIDENT["description"], INCIDENT["service"])
    runner.run_incident_sync(incident_id)

    _print_flow(runner, incident_id)
    _print_http(runner)
    print("\nDEMO PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
