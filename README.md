# FleetOps — enterprise agent-fleet control plane

FleetOps is an incident-response control plane for a fleet of Google ADK agents
on GCP: a **Planner** decomposes an incident into subtasks, **specialist
agents** (diagnoser, remediator) execute them with tools, and every step is
traced, stored, and streamed as events. Built for the *Fortified Enterprise
Fleet* track — this repo covers Stage 1a + 2a + 2b + 2c: an **agent registry**
(publish/version/discover approved agents), an **async pub/sub runtime** with
crash-resume, a cross-session **memory bank**, **zero-trust agent identity**, a
policy-enforcing **gateway**, inline **Model Armor guardrails**, and
**OpenTelemetry-compliant traces + a one-page observability dashboard**. All
local and fully offline-capable; deployment lands in Stage 3.

## Architecture

![Architecture diagram](docs/architecture.png)

*Diagram source: [`docs/architecture.svg`](docs/architecture.svg). Demo video: [`docs/demo_video.mp4`](docs/demo_video.mp4) (3:55, captions, real runs). Devpost submission text: [`submission/devpost_submission.md`](submission/devpost_submission.md).*

The control plane is a FastAPI service backed by three ADK agents and two GCP
service fakes with production-identical contracts.

**Flow (async runtime).** `POST /incidents` accepts a synthetic incident,
persists a session doc, and publishes an `incident.accepted` job event — that
is all that runs on the request path. A **worker** drains the pub/sub queue:
on `incident.accepted` it asks the **Planner** ADK agent (Gemini) to decompose
the incident into 2–4 subtasks, each tagged `diagnose` or `remediate`. The
planner may only dispatch to **registered+approved agents** — every kind is
resolved through the registry (`incident.diagnose`, `incident.remediate`) and
an unserved capability blocks the incident with a clear reason. Each subtask
becomes its own `task.created` job: re-resolve the capability, have the
specialist **read prior context from the memory bank BEFORE acting**, run its
tools (`query_logs` / `check_metrics` for the diagnoser, `restart_service`
/ `scale_service` for the remediator), then **write the result back** to the
memory bank and the session doc (persisted before the task is marked done).
When all subtasks finish the session flips to `resolved`, one consolidated
fleet-level outcome lands in memory (the cross-session recall target), and
`incident.completed` is published. Every step appends a trace span, so
`GET /traces` is a full reasoning chain.

**Crash-resume.** Job state lives in the Firestore session doc + the topic
queue, never only in process memory: unacked jobs survive a worker crash on
the topic (at-least-once), done tasks are skipped on redelivery, and a fresh
worker resumes from persisted state. `make demo` shows exactly this
kill-and-resume step.

**Memory bank.** Firestore `memory` docs keyed by **principal+topic**
(doc id `"principal:topic"`, e.g. `diagnoser:payment-service`): each
specialist's own notes plus one fleet-level outcome per resolved incident,
so the next session on that service recalls what happened before.

**Agent identity + gateway (Stage 2b).** Every caller — external client or
agent-to-agent hop — carries a principal token (`Authorization: Bearer …` on
HTTP). Principals live in the Firestore `principals` collection (token →
name/role/scopes; synthetic demo credentials only — traces log a masked
prefix, never the token). `Gateway.check()` is the single entrypoint:
authenticate, enforce the scope policy (**planner may `dispatch`; specialists
may `execute` but not `publish`**), resolve the capability to a
registered+approved agent — and record the route+decision as a trace span for
EVERY hop (`gateway_route` allow / `gateway_rejected` deny, with reason).
Unknown principal → 401; out-of-scope action → 403; both visible in the
response and the trace store.

**Model Armor — inline guardrails (Stage 2b).** Deterministic, cheap
pre-tool-call inspection of tool arguments (`fleetops/gateway.py`): a call
whose arguments carry prompt-injection markers (instruction override,
system-prompt probing, exfiltration, tool poisoning), PII patterns (email,
card-like numbers), or credential shapes (access keys, private keys) never
reaches the tool — the wrapper traces `guardrail_blocked` with the matched
reasons and returns a structured blocked result to the calling agent.
`make demo` section 6 blocks a live injection+PII payload.

**Observability — OTel traces + dashboard (Stage 2c).** Every agent hop is
emitted as an **OpenTelemetry span** via the opentelemetry SDK trace API:
planner decisions, gateway route+policy (allow and deny), tool calls including
blocked guardrail events, and memory reads/writes. Span attributes carry the
contract: `incident_id`, `agent` (+ `agent.version`), task id where applicable,
principal (masked token only), `model` = **active model id on every hop**
(so the traces themselves prove the Gemini 3.x mandatory-stack pin), and the
full detail payload; rejections/blocks end their span with ERROR status +
reason. A `SpanExporter` (`fleetops/otel.py`) persists each ended span as ONE
doc in the existing Firestore `traces` collection — **same query surface as
GET /traces**, now deterministically ordered by a monotonic emission `seq`
(the chain reads top-to-bottom). The dashboard is one server-rendered HTML page
on the same FastAPI app (`GET /trace/{incident_id}`, no JS): timeline of hops
with timestamps, which agent did what, memory recall events, and red-
highlighted rejected/blocked spans with reasons. `make demo` ends by serving
it (see below); it works against local fakes and unchanged after GCP deploy.
New deps added: `opentelemetry-api` + `opentelemetry-sdk` only.

**Agents (Google ADK).** Three `LlmAgent`s registered as agent cards in the
Firestore registry (`GET /agents`, approved-only).

**Model pin (mandatory stack).** Every agent is created with an explicit
3-series Gemini id — never a silent ADK default. `GEMINI_MODEL` overrides the
default, which is pinned at `gemini-3.6-flash` (the exact `gemini-3-flash` id
is retired for new API keys; 2.5 ids are deprecated for new users); if your
key serves a different
3-series id, pin THAT via `GEMINI_MODEL` and note it here/in the writeup so a
judge can verify compliance at deploy time (an empty override raises rather
than falling back). Without an API key a deterministic `MockLlm` (an ADK
`BaseLlm`) takes over — it drives real ADK tool-calling (emits `function_call`
parts, consumes `function_response`s) with scripted, reproducible output, so
`make demo` runs offline and identically every time.

**GCP contracts, faked locally.** Two modules define the service contracts and
ship in-memory fakes exposing the same read/write API as the GCP clients:

- `fleetops/events.py` — Pub/Sub: `topic(name)`, `publish(data, **attrs) ->
  message_id`, `subscribe(callback)`, plus the worker path `pop(timeout)` /
  `pending_count` (at-least-once queue; unacked messages survive crashes).
  Stage 3 swaps in `google.cloud.pubsub_v1` with no code change elsewhere.
- `fleetops/store.py` — Firestore: `collection().document().get()/set()`,
  `add()`, `stream()`, plus the doc shapes (`AgentCard`, `SessionDoc`,
  `TraceSpan` incl. Stage 2c's `seq`/`status`, memory-bank docs). Stage 3
  swaps in `google.cloud.firestore`.
- `fleetops/otel.py` — Stage 2c: OTel tracer provider + the span exporter that
  ends each span as one doc in `traces`. Pointing OTLP at Cloud Trace is
  additive (see "OpenTelemetry → Cloud Trace" below) — no other code change.

**Collections:** `agents` (registry: agent cards incl. version, capabilities,
owner dept, approval status), `principals` (identity: token → name, role,
scopes), `sessions` (incident state; per-task
pending/running/done for crash-resume), `traces` (trace spans), `memory`
(memory bank keyed by principal+topic).

## Run it

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) (or pip).

```bash
git clone https://github.com/mskutlu/fleetops-agent-fleet
cd fleetops-agent-fleet
make demo          # offline; uses the deterministic mock LLM
```

`make demo` runs all checks (registry, crash-resume, memory recall, gateway,
armor) and then **ends by serving the observability dashboard** — it prints the
URL of one incident's full chain (incl. a rejection + a guardrail block, red-
highlighted), e.g. `http://127.0.0.1:8080/trace/inc-…`. Ctrl-C stops the server;
`NO_SERVE=1 make demo` exits right after the checks instead (CI);
if 8080 is in use on your machine, `DEMO_PORT=8090 make demo` serves there.

With Gemini (optional):

```bash
export GEMINI_API_KEY=...   # https://aistudio.google.com/apikey
# optional: override the pinned 3.x model id if your key serves a different one
export GEMINI_MODEL=gemini-3.6-flash
make demo
```

Run the HTTP service directly:

```bash
uv run uvicorn fleetops.service:create_app --factory --port 8080
curl -s localhost:8080/agents                      # approved cards only
curl -s localhost:8080/capabilities/incident.diagnose   # discovery -> serving agent
curl -s -X POST localhost:8080/incidents \
  -H 'content-type: application/json' \
  -H 'Authorization: Bearer tok-orchestrator-a1b2' \
  -d '{"description": "payment-service 500s and timeouts since 14:00 deploy", "service": "payment-service"}'
curl -s localhost:8080/incidents/<id> && curl -s localhost:8080/traces
# Stage 2c — observability dashboard (one page, no JS):
curl -s localhost:8080/trace/<incident-id> | less   # timeline; red = rejected/blocked
curl -s localhost:8080/                            # index of incidents + trace links
```

Demo principal tokens (synthetic, seeded by the gateway): orchestrator
`tok-orchestrator-a1b2` (dispatch+publish), diagnoser
`tok-diagnoser-c3d4` / remediator `tok-remediator-e5f6` (execute only —
publishing with them returns 403).

## HTTP surface

| Method | Path                      | Auth    | Purpose                                          |
|--------|---------------------------|---------|--------------------------------------------------|
| POST   | `/incidents`              | dispatch| Accept incident; jobs run off-request (202)      |
| GET    | `/incidents/{id}`         | —       | Session doc: status, plan, findings, actions     |
| GET    | `/agents`                 | —       | **Approved-only** registry cards                 |
| POST   | `/agents`                 | publish | Publish/register an agent card (defaults pending)|
| GET    | `/capabilities/{cap}`     | —       | Discovery: approved server of a capability, else 404 with reason |
| GET    | `/traces`                 | —       | Full ordered trace chain (emission order), `?incident_id=` to filter |
| GET    | `/trace/{incident_id}`    | —       | **Stage 2c: one-page observability dashboard** (HTML) for the incident's full chain |
| GET    | `/`                       | —       | Index of known incidents with trace links        |

## Deploy to Google Cloud Run (Stage 3a)

**Currently live** (project `feetops-devpos`, deployed 2026-08-30):
`https://fleetops-qiedvqu63a-ew.a.run.app` — running on the deterministic
MockLlm (`GEMINI_API_KEY` not yet attached; adding it later is one
`gcloud run services update fleetops --region europe-west1 --update-env-vars GEMINI_API_KEY=...` away).

One command, idempotent — provisions everything and deploys:

```bash
gcloud auth login
git clone https://github.com/mskutlu/fleetops-agent-fleet && cd fleetops-agent-fleet
export GOOGLE_CLOUD_PROJECT=<project-id>     # region defaults to europe-west1
export GEMINI_API_KEY=<key>                  # optional — without it agents run on the deterministic MockLlm
./deploy.sh
```

What `deploy.sh` does (equivalent manual `gcloud` commands, for judges who prefer them):

```bash
gcloud services enable run.googleapis.com pubsub.googleapis.com firestore.googleapis.com cloudbuild.googleapis.com
gcloud pubsub topics create fleetops-incidents
gcloud pubsub subscriptions create fleetops-incidents-worker --topic=fleetops-incidents --ack-deadline=600
gcloud firestore databases create --location=europe-west1          # skip if the project already has one
gcloud run deploy fleetops --source . --region europe-west1 \
  --allow-unauthenticated --no-cpu-throttling --max-instances 1 \
  --set-env-vars "FLEETOPS_BACKEND=gcp,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,PUBSUB_TOPIC=fleetops-incidents,GEMINI_MODEL=gemini-3.6-flash,GEMINI_API_KEY=$GEMINI_API_KEY"
gcloud run services describe fleetops --region europe-west1 --format 'value(status.url)'
```

**Topology.** Single Cloud Run service runs both the HTTP surface and the
worker: the in-process worker **pulls** from the
`fleetops-incidents-worker` subscription via `Topic.pop()` (pull-and-ack,
at-least-once — same contract as the local fake). No separate push endpoint.
This needs `--no-cpu-throttling` (CPU stays allocated between requests so the
pull loop keeps running) and `--max-instances 1` (one worker, cheapest demo).

**Backend swap.** `FLEETOPS_BACKEND=gcp` routes `fleetops/gcp.py` to real
`google-cloud-pubsub` / `google-cloud-firestore` clients with the exact
interfaces of the local fakes — no other code changes. Locally (default
`FLEETOPS_BACKEND=memory`) nothing touches GCP and `make demo` stays
offline. The gateway seeds its synthetic demo principals into the Firestore
`principals` collection on first boot.

**Verify the live URL** (`$URL` from the deploy output; note `/healthz` is
reserved by Google's edge on `*.run.app` and 404s before reaching the service —
smoke-check `/agents` instead):

```bash
curl -s $URL/agents
ID=$(curl -s -X POST $URL/incidents -H 'content-type: application/json' \
  -H 'Authorization: Bearer tok-orchestrator-a1b2' \
  -d '{"description": "payment-service 500s and timeouts since 14:00 deploy", "service": "payment-service"}' | jq -r .id)
watch -n2 "curl -s $URL/incidents/$ID | jq -c '{status, plan: [.plan[].status], findings, actions}'"   # -> resolved
curl -s "$URL/traces?incident_id=$ID" | jq -r '.[] | "\(.ts) \(.agent) \(.step)"'                      # full reasoning chain
```

**Cost / teardown.** Scale-to-zero with a handful of demo incidents:
Cloud Run + Pub/Sub + Firestore all stay inside their always-free tiers —
effectively $0 for the hackathon window (the only real charge is
`--no-cpu-throttling` CPU while the single instance is up, ≈ $0.09/hour idle;
the stage rules allow stopping the service after submission:
`gcloud run services delete fleetops --region europe-west1` — full teardown:
delete the subscription, topic, and Firestore database too).

`GEMINI_API_KEY` is set via `--set-env-vars` on the service (never committed);
move it to Secret Manager for anything beyond the demo.

### OpenTelemetry → Cloud Trace (Stage 2c wiring for deploy)

Spans are emitted through the opentelemetry SDK, so pointing them at GCP's
Cloud Trace is additive — the Firestore exporter keeps working as-is and a
second processor sends the same spans over OTLP:

1. `uv add opentelemetry-exporter-otlp-proto-http`
2. In `fleetops/otel.py:configure()`, alongside the existing
   `SimpleSpanProcessor(FirestoreSpanExporter(db))`:

   ```python
   from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
   from opentelemetry.sdk.trace.export import BatchSpanProcessor

   provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
       endpoint=f"https://{PROJECT}-{REGION}.otlp.googleapis.com/v1/traces",
       headers={"x-goog-api-key": os.environ["GCP_API_KEY"]},  # or a service account token
   )))
   ```

3. Resource attributes are already set by the SDK provider: `service.name`
   = `fleetops`, `service.version` — Cloud Trace groups traces by them. If you
   prefer env-only config, `OTEL_SERVICE_NAME=fleetops` is honored upstream of
   any custom resource.
4. The span attribute contract travels with the spans (`incident_id`,
   `agent`, task id, masked principal, `model` = active Gemini 3.x id on every
   hop) — Cloud Trace's trace detail shows them per-span; filter traces by
   `incident_id` to get the same chain the dashboard renders.
5. Keep the model pin: deploy with `GEMINI_API_KEY` + `GEMINI_MODEL`
   (3-series id). The traces will then show that exact id on every agent hop —
   compliance evidence in the observability data itself.

## Project layout

```
fleetops/
  agents.py    ADK LlmAgents (planner, diagnoser, remediator) + registry cards
  runner.py    orchestration: request path + worker path (plan/execute/resume)
  gateway.py   Stage 2b: identity/principals, gateway policy+routing, Model Armor
  registry.py  agent registry: publish / list approved / resolve capability
  memory.py    memory bank: principal+topic keyed cross-session context
  llm.py       pinned Gemini 3.x when keyed, deterministic MockLlm otherwise
  tools.py     diagnoser/remediator tools (synthetic fleet state)
  events.py    Pub/Sub contract + in-memory fake (durable queue, at-least-once)
  store.py     Firestore contract, doc shapes + in-memory fake
  gcp.py       Stage 3a: real Pub/Sub/Firestore clients behind the fake contracts
  otel.py      Stage 2c: OTel tracer provider + span exporter -> `traces` docs
  dashboard.py Stage 2c: one-page observability dashboard (server-rendered HTML)
  service.py   FastAPI control plane + background worker thread + /trace/{id}
  demo.py      `make demo` harness — registry, crash-resume, memory recall,
               HTTP surface; fails loudly
```

No secrets are committed; synthetic incident data only.
