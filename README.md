# FleetOps — enterprise agent-fleet control plane

FleetOps is an incident-response control plane for a fleet of Google ADK agents
on GCP: a **Planner** decomposes an incident into subtasks, **specialist
agents** (diagnoser, remediator) execute them with tools, and every step is
traced, stored, and streamed as events. Built for the *Fortified Enterprise
Fleet* track — this repo is Stage 1a (local, fully offline-capable); the
gateway / identity / guardrails layers arrive in Stage 2.

## Architecture

The control plane is a FastAPI service backed by three ADK agents and two GCP
service fakes with production-identical contracts.

**Flow.** `POST /incidents` accepts a synthetic incident, persists a session
doc, and publishes an `incident.accepted` event. The runner asks the
**Planner** ADK agent (Gemini) to decompose the incident into 2–4 subtasks,
each tagged `diagnose` or `remediate`, and publishes a `task.created` event per
subtask. Specialists then run one subtask each: before acting they **pull prior
context from the memory bank** (a Firestore-scoped doc keyed by service), call
their tools (`query_logs` / `check_metrics` for the diagnoser, `restart_service`
/ `scale_service` for the remediator), record findings back to the memory bank,
and emit `task.completed`. When all subtasks finish the session doc flips to
`resolved` and `incident.completed` is published. Every step appends a trace
span, so `GET /traces` is a full reasoning chain.

**Agents (Google ADK).** Three `LlmAgent`s registered as agent cards
(`GET /agents`). The model layer resolves to `gemini-2.0-flash` when
`GEMINI_API_KEY` is set; without a key a deterministic `MockLlm` (an ADK
`BaseLlm`) takes over — it drives real ADK tool-calling (emits `function_call`
parts, consumes `function_response`s) with scripted, reproducible output, so
`make demo` runs offline and identically every time.

**GCP contracts, faked locally.** Two modules define the service contracts and
ship in-memory fakes exposing the same read/write API as the GCP clients:

- `fleetops/events.py` — Pub/Sub: `topic(name)`, `publish(data, **attrs) ->
  message_id`, `subscribe(callback)`. Stage 3 swaps in
  `google.cloud.pubsub_v1` with no code change elsewhere.
- `fleetops/store.py` — Firestore: `collection().document().get()/set()`,
  `add()`, `stream()`, plus the doc shapes (`AgentCard`, `SessionDoc`,
  `TraceSpan`, memory-bank docs). Stage 3 swaps in `google.cloud.firestore`.

**Collections:** `agents` (agent cards), `sessions` (incident state), `traces`
(trace spans), `memory` (memory bank keyed by service).

## Run it

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) (or pip).

```bash
git clone https://github.com/mskutlu/fleetops-agent-fleet
cd fleetops-agent-fleet
make demo          # offline; uses the deterministic mock LLM
```

With Gemini (optional):

```bash
export GEMINI_API_KEY=...   # https://aistudio.google.com/apikey
make demo
```

Run the HTTP service directly:

```bash
uv run uvicorn fleetops.service:create_app --factory --port 8080
curl -s localhost:8080/agents
curl -s -X POST localhost:8080/incidents \
  -H 'content-type: application/json' \
  -d '{"description": "payment-service 500s and timeouts since 14:00 deploy", "service": "payment-service"}'
curl -s localhost:8080/incidents/<id> && curl -s localhost:8080/traces
```

## HTTP surface

| Method | Path                | Purpose                                          |
|--------|---------------------|--------------------------------------------------|
| POST   | `/incidents`        | Accept incident, run agent flow async (202)      |
| GET    | `/incidents/{id}`   | Session doc: status, plan, findings, actions     |
| GET    | `/agents`           | Agent cards (planner, diagnoser, remediator)     |
| GET    | `/traces`           | Trace spans, `?incident_id=` to filter           |

## GCP deployment (Stage 3 — details pending)

Target topology: Cloud Run for the control plane, Pub/Sub for job events,
Firestore (Native mode) for agents/sessions/traces/memory. The fakes in
`fleetops/events.py` and `fleetops/store.py` are drop-in shaped for the real
clients; deployment config, IAM, and identities land in Stage 3.

## Project layout

```
fleetops/
  agents.py    ADK LlmAgents (planner, diagnoser, remediator) + agent cards
  runner.py    orchestration: plan -> memory pull -> tool use -> trace -> events
  llm.py       Gemini when keyed, deterministic MockLlm otherwise
  tools.py     diagnoser/remediator tools (synthetic fleet state)
  events.py    Pub/Sub contract + in-memory fake
  store.py     Firestore contract, doc shapes + in-memory fake
  service.py   FastAPI control plane
  demo.py      `make demo` harness — full flow + HTTP surface, fails loudly
```

No secrets are committed; synthetic incident data only.
