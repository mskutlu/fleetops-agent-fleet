> **[Stage 4a]** Skeleton preserved as drafted; the FINAL filled submission text is [`devpost_submission.md`](devpost_submission.md).

# FleetOps — Devpost Writeup (Stage 1b skeleton)

> **Status**: Skeleton drafted against the BUG-7 plan and stage issues (BUG-8 → BUG-14). Stage 4a fills the `[PLACEHOLDER]`s from live evidence. Fields are mapped 1:1 to the "What to Submit" list on https://allthingsagentichackathon.devpost.com (verified 2026-08-29).
> **Placeholder legend**: `[LIVE URL]`, `[REPO]`, `[DIAGRAM]`, `[STAGE n]` = not yet produced by that stage. No feature is claimed here that the plan comment does not scope.

---

## 1. Category

**Fortified Enterprise Fleet.**

FleetOps covers every sub-requirement of this track:

| Track requirement | FleetOps component (planned/built per BUG-8…BUG-12) |
|---|---|
| Agent Registry — publish, versioning, discovery of enterprise-approved agents | Agent cards in Firestore; `GET /agents` lists approved; planner dispatches only to registered + approved agents `[STAGE 2a]` |
| Agent Runtime — long-running asynchronous execution | Pub/Sub-driven task events off the request path; crash-resume from persisted state `[STAGE 2a]` |
| Memory Bank — persistent, secure cross-session context | Session docs keyed by principal+topic; specialists read prior context before acting, write summary after `[STAGE 2a]` |
| Agent Identity — zero-trust access control | Principal token validated at the gateway before routing; scoped capabilities per agent `[STAGE 2b]` |
| Agent Gateway — unified routing + policy enforcement | Single entrypoint routes capability → registered agent, enforces policy, records decision per hop `[STAGE 2b]` |
| Model Armor — inline guardrails (prompt injection, tool poisoning, PII leaks) | Pre-tool-call checks on arguments; blocks injection markers and canary PII patterns; blocked attempts logged with reason. Deterministic heuristic layer implementing the track's Model Armor requirement for auditability `[STAGE 2b]` |
| Agent Observability — OTel-compliant audit logs + end-to-end reasoning chain traces | OpenTelemetry spans for every agent hop (planner decision, gateway route+policy, tool calls incl. blocked guardrail events, memory reads/writes); ordered chain per incident; one-page dashboard `[STAGE 2c]` |

## 2. URL to the hosted Project

`[LIVE URL]` — Cloud Run service endpoint (e.g., `https://fleetops-xxxx.a.run.app`). Same host serves the API (`POST /incidents`, `GET /incidents/{id}`, `GET /agents`) and the observability dashboard for a given incident id.

> Rules note: "Your app does not need to be publicly accessible or live at the exact moment of submission … You just need to provide clear proof that it was built and deployed on Google Cloud." We intend to have both — live URL **and** console/dashboard evidence in the video (Beat 4) — so this fallback is belt-and-braces only.

## 3. Text description (short overview of the problem)

Enterprise teams are deploying fleets of AI agents, but production-grade fleet management — who may act, what they may touch, how context survives across sessions and restarts, and a trace you can audit after the fact — is usually hand-rolled per team or missing entirely. FleetOps is an agent-fleet control plane that runs an operational incident end-to-end: a planner decomposes the incident, a gateway routes work to registered, approved specialists under zero-trust identity, inline guardrails (Model Armor) block prompt injection and PII before any tool executes, a memory bank carries context across sessions so follow-up incidents don't re-diagnose from scratch — and every hop is captured as an OpenTelemetry-compliant trace you can replay in a dashboard.

## 4. Features & functionality

**Core flow (Stage 1a — BUG-8)**
- Incident intake API: `POST /incidents` accepts an incident description; planner agent decomposes it into subtasks; `GET /incidents/{id}` tracks state through completion.
- **Planner** ADK agent (Gemini): takes the incident, produces 2–4 subtask assignments.
- **Specialist** ADK agents — *diagnoser* and *remediator*: execute one subtask each, can call tools, pull prior context from the memory bank before acting.
- HTTP service surface: `POST /incidents`, `GET /incidents/{id}`, `GET /agents`, `GET /traces` (Stage 2 wraps this with gateway/identity/guardrails).
- Async job events via Pub/Sub (in-memory fake locally, identical contract to GCP): incident accepted → task events emitted.
- Firestore contracts: agent cards, session/state docs, trace spans — local in-memory fakes with the same read/write API as real clients.
- Local harness `make demo`: runs the full flow offline with a deterministic mock LLM and prints the reasoning chain + emitted events.

**Fleet pillars (Stage 2a/2b/2c — BUG-10…BUG-12)** `[STAGE 2]`
- **Registry**: agent cards in Firestore (name, version, capabilities, owner dept, approval status); `GET /agents` lists approved; planner dispatches only to registered + approved agents; gateway rejects an unregistered capability with a clear error.
- **Runtime**: incident processing moves off the request path — Pub/Sub task events drive execution; a job resumes after a simulated crash/restart using persisted state in Firestore (kill-and-resume step in `make demo`).
- **Memory Bank**: session docs keyed by principal+topic; specialists read prior context BEFORE acting and write back a summary afterward; cross-session recall demonstrated (incident B references A's outcome, recalled text visible in output).
- **Identity**: every request carries an agent principal token; gateway validates before routing; unknown/unregistered principal gets a clean rejection with reason logged to traces; scoped capabilities (planner may dispatch, specialist may execute but not publish).
- **Gateway**: single entrypoint that routes by capability → registered agent, enforces policy, records route + decision in the trace span for every hop.
- **Model Armor guardrails**: pre-tool-call check on tool arguments — blocks injection markers and PII patterns (canary `demo.user@example.test`), logs the blocked attempt with reason; deterministic + cheap heuristic layer `[STAGE 2b]`.
- **Observability**: OpenTelemetry SDK spans for every agent hop (planner decision, gateway route+policy, tool calls incl. blocked guardrail events, memory reads/writes) with attributes: principal, agent name/version, task id, status, reason on rejection/block; traces persisted to Firestore; one-page dashboard renders the full ordered chain per incident with rejected/blocked spans highlighted `[STAGE 2c]`.

**Demo & delivery (Stage 3a/4a — BUG-13…BUG-14)** `[STAGE 3][STAGE 4]`
- Deployed on Cloud Run with real Pub/Sub + Firestore clients; live end-to-end verification against the `.run` URL.
- Architecture diagram, ~4-minute uncut demo video (see `submission/video_script.md`), README spin-up instructions.

## 5. Technologies used

Mandatory combination for this hackathon — all five in play:

| Technology | Role |
|---|---|
| **Gemini API** (Gemini 3.x) `[STAGE 3a]` | LLM backend for planner + specialist reasoning (`GEMINI_API_KEY`; deterministic mock-LLM fallback keeps `make demo` runnable offline — same code path, no fork) |
| **Google ADK (Python)** | Agent framework: agent definitions, tool wiring, LLM integration for planner/specialists |
| **Cloud Run** | Service hosting; single-service pattern with Pub/Sub pull subscription documented in README |
| **Pub/Sub** | Async event bus — topic `fleetops-incidents`; incident accepted → task events drive the runtime off the request path |
| **Firestore** | State: agent cards (registry), session + memory docs, trace spans; same query surface behind fakes and real client |

Supporting stack: Python 3.11+, FastAPI (HTTP surface), OpenTelemetry SDK (trace API) for OTel-compliant spans, uv/pip packaging. No other external services.

## 6. Other data sources used

- **Synthetic incident dataset** generated by the local harness — operational scenarios only; no real user PII anywhere in demo or prod traces.
- **Canary test values** where a PII pattern must be exercised: `demo.user@example.test` (Model Armor block case).
- **Agent capability cards** authored as registry seed data (name, version, capabilities, owner dept, approval status) — synthetic departments/owners.
- No external SaaS integrations or third-party datasets in scope for this entry.

## 7. Findings & learnings

*(Stage 4a finalizes with real numbers from `make demo` output and the live run; these are the intended claims, all within plan scope.)*

1. **Fleet-grade behavior is a systems problem, not a prompt one.** The differentiating work was registry/identity/gateway/memory/trace — the model did what it does anywhere; the fleet made it trustworthy in production-shaped conditions (unknown principals rejected, injections blocked, state surviving restarts).
2. **Guardrails must be inline and deterministic to be both demoable and auditable.** A heuristic pre-tool-call layer keeps latency and cost near zero while every block is logged with a reason — an LLM classifier can sit behind it without changing the contract.
3. **Cross-session memory measurably changes agent behavior.** On incident B, the specialist reads incident A's outcome from the memory bank before acting instead of re-diagnosing — visible in `make demo` output `[STAGE 2a]`.
4. **Interface-identical local fakes make "async on GCP" reproducible offline.** The same code path runs against in-memory Pub/Sub/Firestore (CI, no network) and the real services (Cloud Run deploy) — which is what lets a judge run `make demo` from zero.
5. **Crash-resume is what makes "long-running async" credible rather than aspirational** — persisted state + event-driven workers means the kill-and-resume step in the demo is a real recovery path, not a slide `[STAGE 2a]`.

## 8. URL to your code repository

`[REPO]` — public GitHub repo (BUG-8: `fleetops-agent-fleet`). Public; no sharing with testing@devpost.com needed unless it must stay private (in which case share per rules with testing@devpost.com + cloudhackathons@google.com).

## 9. Spin-up Instructions (README.md in repo)

*(Stage 1a commits the README; condensed version for the submission field:)*

```bash
git clone <repo-url> && cd fleetops-agent-fleet
# Optional: export GEMINI_API_KEY=...   # without it, make demo uses the deterministic mock LLM
make demo        # full planner -> gateway-routed specialist flow with local fakes; prints reasoning chain + events
```

GCP deploy (Stage 3a fills exact commands): `gcloud` project setup → enable Cloud Run/Pub/Sub/Firestore APIs → create topic `fleetops-incidents` → set env vars (`GEMINI_API_KEY`) → deploy service to Cloud Run. Full reproducible command list in README `[STAGE 3]`.

## 10. Architecture diagram

`[DIAGRAM]` — `docs/architecture.png` (or SVG), produced in Stage 4a. Content: clients → **gateway** (identity + policy) → **planner / specialists** (ADK/Gemini) ↔ **memory bank** (Firestore), Pub/Sub task events, Model Armor block point on the tool-call path, trace pipeline to dashboard/Cloud Trace. Clean labels — this is a judging-criterion artifact, not an afterthought.

## 11. Demo video (~4 min)

`[VIDEO]` — uncut, real runs only; follows `submission/video_script.md`: problem (15s) → value prop (30s) → live incident flow incl. one rejected principal, one Model Armor block, cross-session memory recall (90s) → Google Cloud proof shots: GCP console / Cloud Run dashboard / `.run` URL (60s) → architecture recap + close (30s).

---

## Placeholder status at a glance

| Field | State now | Filled by |
|---|---|---|
| Hosted URL | `[LIVE URL]` | Stage 3a verification comment (BUG-13) |
| Repo URL | `[REPO]` | Stage 1a final comment (BUG-8) |
| Registry/runtime/memory/identity/gateway/armor/observability feature text | Drafted against plan; verify wording after build | Stages 2a–2c output pastes on BUG-10…12 |
| Findings & learnings numbers/output excerpts | Intended claims listed; no real output cited yet | `make demo` + live run outputs (Stage 3a) |
| Architecture diagram | Spec only | Stage 4a (BUG-14) |
| Demo video | Scripted beat-by-beat | Stage 4a capture session |
