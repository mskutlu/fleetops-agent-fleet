# FleetOps — Judging-Criteria Checklist

> Criteria and weights taken verbatim from the live hackathon page (verified 2026-08-29): **Innovation & Operational Utility — 40%** · **Architectural Discipline & Tech Stack — 30%** · **Demo & Production Readiness — 30%**.
> For each criterion: what our entry shows → one-line gap risk → must-not-skip items for the builders.

---

## 1. Innovation & Operational Utility — 40%

**Judge's bar (verbatim)**: "How much real-world friction does the agent remove on its own? We reward autonomous, high-value action over simple chat — agents that make decisions and complete tasks with little to no hand-holding."

### What our entry shows
- **Autonomous end-to-end incident handling**: one `POST /incidents` → planner decomposes → gateway-routed specialists execute tools (probe, apply fix) → done. No human in the loop for the happy path — that is "heavy lifting," not chat.
- **Fleet-level autonomy, not single-agent autonomy**: the novelty is a *control plane* — registry decides who may act, identity scopes what they can do, guardrails intercept bad tool calls before execution, memory lets follow-up incidents continue from prior outcomes instead of re-diagnosing. That's the "fortified fleet" differentiator vs. 11k other single-agent entries.
- **Concrete friction removed**: ops incident triage + remediation coordination — a messy multi-step chore with real cost (downtime, context-switching), demonstrated in one reproducible flow (`make demo`).

### Gap risk (one line)
If the demo reads as "a chatbot that calls tools" rather than "a governed fleet," we lose the 40% category to any Taskmaster entry — the framing must stay *fleet control plane* in every sentence of writeup, video narration, and README.

### Must not skip
- [ ] Planner output must be visible decomposition (2–4 subtasks), not a single action — proves planning, Stage 1a
- [ ] Cross-session memory recall with the **recalled text on screen** (video Beat 3d) — this is the strongest "beyond chat loops" moment; losing it from the video costs the most points anywhere, Stage 2a + 4a
- [ ] The incident must be a *realistic operational scenario* (latency spike style), not toy data — synthetic but believable, all stages

---

## 2. Architectural Discipline & Tech Stack — 30%

**Judge's bar (verbatim)**: "How sound are your engineering choices? We look at how you decouple systems, manage state and memory, secure credentials, and handle failures — robust, production-minded agents, not brittle scripts."

### What our entry shows
- **Decoupled by design**: HTTP API / event-driven runtime (Pub/Sub) / state (Firestore) are separate concerns; local fakes keep the *same contract* as GCP clients so CI runs offline and deploy swaps in real services — a defensible, testable boundary.
- **State & memory managed explicitly**: session docs keyed by principal+topic; crash-resume from persisted state (kill-and-restart step) demonstrates failure handling rather than assuming happy path, Stage 2a.
- **Credentials secured**: `GEMINI_API_KEY` via env/Secret Manager, no secrets in repo; agent principals are validated tokens at the gateway — zero-trust as architecture, not a label, Stage 2b + 3a.
- **Failures handled visibly**: unknown principal → clean rejection with reason; injection in tool arg → blocked before execution with logged reason; job crash → resume from persisted state. Three failure modes, all demonstrated rather than described, Stages 2a/2b.
- **Mandatory stack fully satisfied**: Gemini API + Google ADK (Python) + Cloud Run + Pub/Sub + Firestore — every required category covered, no "and also a bit of" hand-waving.

### Gap risk (one line)
The Model Armor layer is a deterministic heuristic (fine for the demo), but if it stays *only* that with zero mention of how production would use Google's actual Model Armor service, a judge who knows the product may read it as name-borrowing rather than design.

### Must not skip
- [ ] **Pin an explicit Gemini model ≥ 3.x in code/env** — "Gemini 3.5 or newer" is a hard requirement; defaulting to whatever the ADK ships (e.g., 2.5) fails it silently, Stages 1a + 3a
- [ ] Keep local fakes **interface-identical** to GCP clients and say so in README — it's our strongest "engineering choices" evidence, Stage 1a
- [ ] Trace spans must carry principal/agent/status/reason attributes (not just names) — that's what makes the observability story audit-grade rather than decorative, Stage 2c
- [ ] No secrets committed; `gcloud` deploy commands reproducible in README, Stages 3a

---

## 3. Demo & Production Readiness — 30%

**Judge's bar (verbatim)**: "How clearly do your video and repo prove it works? We want a live, unedited demo, a clean architecture diagram, reproducible setup, and visible proof it runs on Google Cloud."

### What our entry shows
- **Live, uncut demo**: 3:45 scripted video (see `video_script.md`) with real runs against the `.run` URL — all four required beats present (problem, value prop, live app action, GCP proof), including one rejected principal + one blocked injection + cross-session recall.
- **Clean architecture diagram** specified as a first-class Stage 4a artifact: gateway/identity → planner/specialists ↔ memory bank, Pub/Sub events, guardrail block point, trace pipeline — not an afterthought screenshot.
- **Reproducible setup**: `git clone` → `make demo` works offline (mock LLM fallback); full GCP deploy commands in README; judges can run it from zero with no account.
- **Visible GCP proof** (video Beat 4, one continuous browser session): project console with Cloud Run/Pub/Sub/Firestore APIs enabled → Cloud Run service + invocations/logs correlated to the demo incident → live `.run` URL serving registry and traces.

### Gap risk (one line)
If the video is cut before the GCP proof shots or the diagram ships as a whiteboard photo, we lose this third outright — those two artifacts are named requirements, not polish items.

### Must not skip
- [ ] **Record Beat 4 before stopping the Cloud Run service** (rules allow it to be off at judging time, but the footage must exist), Stage 3a → 4a ordering
- [ ] Architecture diagram with legible labels at presentation size — a blurred PNG is worse than no diagram, Stage 4a
- [ ] README spin-up section present and accurate *before* submission, not retrofitted, Stages 1a/3a
- [ ] **GCP account ready before Stage 3a starts**: the hackathon's $150 credit form closed Aug 28 — we're on the no-cost trial / owner's existing project; confirm it exists so deploy isn't blocked by signup friction at T-minus-hours (flagged on BUG-7)

---

## Cross-cutting: resolved + open items

| Item | State |
|---|---|
| Track fit vs. Fortified Enterprise Fleet sub-requirements (registry/runtime/memory/identity/gateway/armor/observability) | ✅ All seven mapped to a built stage (BUG-10…12); writeup §1 carries the mapping table for judges |
| Türkiye eligibility (owner question on BUG-7) | ✅ **Eligible** — verified against official rules 2026-08-29: excluded list is Italy, Quebec, Crimea, Cuba, Iran, Syria, North Korea, Sudan, Belarus, Russia; Türkiye not listed |
| Deadline math | Submit by Aug 31 17:00 PDT = **Aug 31 24:00 UTC** (PDT=UTC-7); plan's "Aug 31 22:00 UTC" buffer is safe either way — keep the 2h cushion, Stage 4a |
| Gemini model version pinning | ⚠️ Gap flagged on BUG-7 — no stage description names a ≥3.x model explicitly |
| Credit source for GCP spend | ⚠️ Form deadline passed (Aug 28) — rely on no-cost trial / owner account; confirm before Stage 3a, flagged on BUG-7 |
| Real Model Armor service call vs. heuristic layer | ℹ️ Optional enhancement suggested in BUG-7 flag — not required for compliance |
