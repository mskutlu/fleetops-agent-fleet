# Devpost submission — FleetOps (final, paste-ready)

> Every required field of https://allthingsagentichackathon.devpost.com/ ("What to Submit"), filled from real
> artifacts as of 2026-08-30. This is the canonical text for the owner to paste into the Devpost form.
> Evidence for every claim lives in the repo (`evidence/`, `docs/`, `submission/`).

## 1. Project name

**FleetOps**

## 2. Category / Devpost track

**Fortified Enterprise Fleet** (agent registry · runtime · memory bank · identity · gateway · Model Armor-style guardrails · observability)

## 3. URL to the hosted project (Live Demo)

```
https://fleetops-qiedvqu63a-ew.a.run.app
```

- Cloud Run service `fleetops`, project `feetops-devpos`, region `europe-west1` (canonical `.run.app` URL).
- Same host serves the API (`POST /incidents`, `GET /incidents/{id}`, `GET /agents`, `GET /traces`) and the
  observability dashboards (`/` overview, `/trace/{incident_id}`).
- Try it read-only right now: open `/` and `/agents` in a browser.
- Note: the service currently runs the deterministic MockLlm fallback (per the offline-first design) because the
  owner's Gemini API key is rate-limited (429 RESOURCE_EXHAUSTED — prepayment credits). One env-var swap with a
  funded key switches the exact same code path to Gemini 3.6-flash:
  `gcloud run services update fleetops --region europe-west1 --update-env-vars GEMINI_API_KEY=<key>`.

## 4. URL to your code repository

```
https://github.com/mskutlu/fleetops-agent-fleet
```

Public repo. Spin-up from zero (no keys needed):

```bash
git clone https://github.com/mskutlu/fleetops-agent-fleet && cd fleetops-agent-fleet
make demo        # full planner → gateway-routed specialist flow on local fakes, 7/7 checks green
```

## 5. Brief description (short overview)

Enterprise teams are deploying fleets of AI agents, but production-grade fleet management — who may act, what
they may touch, how context survives across sessions and restarts, and a trace you can audit after the fact — is
usually hand-rolled per team or missing entirely. FleetOps is an agent-fleet control plane that runs an
operational incident end-to-end: a planner decomposes the incident, a gateway routes work to registered, approved
specialists under zero-trust identity, inline guardrails block prompt injection and PII before any tool executes,
a memory bank carries context across sessions so follow-up incidents don't re-diagnose from scratch — and every
hop is captured as an OpenTelemetry-compliant trace you can replay in a dashboard.

## 6. Features & functionality (what it does, verified)

All five Fortified Enterprise Fleet pillars, each demonstrated in `make demo` (7/7 green) AND against the live URL:

- **Agent Registry** — agent cards in Firestore (name, version, capabilities, owner dept, approval status);
  `GET /agents` lists approved agents; the planner dispatches only to registered + approved agents; an
  unapproved capability is rejected with a traced reason. Live: `GET /agents` → planner / diagnoser / remediator.
- **Agent Runtime** — incident processing is async off the request path: Pub/Sub task events drive execution;
  a job resumes after a simulated crash from persisted state (kill-and-resume step in `make demo`).
- **Memory Bank** — session docs in Firestore keyed by principal+topic; specialists read prior context BEFORE
  acting and write a summary back. Live proof: follow-up incident `inc-d22e3923` recalled
  `inc-ff635782`'s outcome before planning (`memory_read` span, quoted text in the trace).
- **Agent Identity** — every request carries a principal token; gateway validates + enforces scopes
  (planner dispatches, specialists execute, specialists may not publish/dispatch). Live proof: specialist token
  on `POST /incidents` → `403 {"detail":"principal 'svc-diagnoser' (specialist) may not dispatch (scopes: execute)"}`,
  traced as `gateway_rejected`.
- **Agent Gateway** — single entrypoint routes capability → registered agent, records an allow/deny span for
  every hop. Live: 17-span chain for `inc-01b9a1c8` with three `gateway_route` allow decisions.
- **Model Armor (inline guardrails)** — pre-tool-call check on tool arguments; blocks injection markers and PII
  patterns (canary `demo.user@example.test`), logs the block with reasons, tool never executes. Demonstrated in
  `make demo`: three block reasons (`prompt-injection: instruction override`, `data exfiltration`,
  `pii: email address`) on one call. The live HTTP surface deliberately never exposes attacker-controlled tool
  arguments (structured fields win arg extraction), so the block path is exercised where args are attacker-shaped.
- **Agent Observability** — OTel-compliant spans for every hop (planner decision, gateway route+policy,
  guardrail block, tool call, memory read/write) persisted to Firestore; one-page dashboard renders the ordered
  chain with rejections/blocks highlighted. Live: `/trace/inc-01b9a1c8` (17 spans), model id recorded on every span.

## 7. Technologies used (mandatory combo, all five)

| Technology | Role |
|---|---|
| **Gemini API** (model pin `gemini-3.6-flash`, ≥3.5 per rules, via `GEMINI_MODEL`; deterministic MockLlm fallback shares the same code path) | LLM backend for planner + specialists |
| **Google ADK (Python)** | agent definitions, tool wiring, LLM integration |
| **Cloud Run** | hosting — single service: HTTP API + Pub/Sub pull worker |
| **Pub/Sub** | topic `fleetops-incidents` — async task events drive the runtime |
| **Firestore** | agent cards (registry), session/memory docs, OTel trace spans |

Supporting: Python 3.11+, FastAPI, OpenTelemetry SDK span model. No other external services.

## 8. Data sources used

- Synthetic operational incidents generated by the local harness; no real PII anywhere.
- Canary PII value for the guardrail block case: `demo.user@example.test`.
- Registry seed data: synthetic agent cards (names, versions, capabilities, synthetic departments).

## 9. Architecture diagram

`docs/architecture.png` (and `docs/architecture.svg`) in the repo — clients → gateway (identity + policy) →
planner/specialists (ADK/Gemini) ↔ memory bank (Firestore), Pub/Sub async lane, Model Armor block point on the
tool-call path, trace pipeline to dashboard/Cloud Trace-compatible store.

## 10. Demo video (~4 min, captions, real runs only)

**In-repo: `docs/demo_video.mp4`** (3:55, 1920×1080 H.264, burned-in captions).

Content, in order: problem framing → value prop → **live incident flow against the `.run` URL** (202 → planner
decomposition → specialist execution → 17-span trace; rejected specialist principal; Model Armor block with
reasons; cross-session memory recall of a prior incident's outcome) → **Google Cloud proof shots** (live Cloud
Run URL, registry, live trace dashboard) → architecture diagram walk-through → end card with repo + hashtag.

Every frame is a verbatim capture of a real run (live curl outputs, live dashboard screenshots, local
`make demo` output) — assembled with the reproducible pipeline in `submission/tools/`.
`submission/video_script.md` is the original beat-by-beat script this video follows.

## 11. Bonus: blog + social

- Blog post draft (dev.to/medium-ready) with the required hackathon sentence: `submission/blog_post.md`.
- Social post draft with **#AllThingsAgenticHackathon**: `submission/social_post.md`.

## 12. Findings & learnings (backed by runs, not slides)

1. **Fleet-grade behavior is a systems problem, not a prompt one.** The differentiating work was
   registry/identity/gateway/memory/trace; the model did what it does anywhere — the fleet made it trustworthy
   (unknown principal rejected in one hop, injection blocked before any tool, state surviving restarts).
2. **Guardrails must be inline and deterministic to be demoable and auditable.** The heuristic pre-tool-call
   layer blocks at near-zero latency/cost, logs machine-readable reasons, and can host an LLM classifier behind
   it without changing the contract.
3. **Cross-session memory measurably changes behavior.** Incident `inc-d22e3923` planned and executed as a
   continuation of `inc-ff635782` after a `memory_read` — no re-diagnosis (visible in the live trace).
4. **Interface-identical local fakes make "async on GCP" reproducible offline.** The same code path runs
   in-memory (CI, no network) and on real Pub/Sub/Firestore (live deploy) — which is why a judge can run
   `make demo` from zero in under a minute.
5. **Crash-resume makes "long-running async" credible** — persisted state + event-driven workers turned the
   kill-and-resume step into a real recovery path, not a slide.
