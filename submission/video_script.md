# FleetOps — Demo Video Script (~4 min)

> Target: **225s (3:45)** — inside the "~4-min" requirement with headroom. Uncut, real runs only (explicit judging criterion). Capture against the **live `.run` URL** where possible; fall back to local `make demo` + dashboard if the service is stopped at record time (rules allow it — proof of GCP deployment still required in Beat 4).
> Narration: voiceover OR burned-in captions, whichever is feasible. All narration lines below are verbatim-ready.

## Beat map

| Beat | Timecode | Duration | Content | Capture source |
|---|---|---|---|---|
| 1 — Problem | 0:00–0:15 | 15s | Why agent fleets need a control plane | Title card / simple text slide |
| 2 — Value prop | 0:15–0:45 | 30s | What FleetOps does, in one pass | Slide or live dashboard idle screen |
| 3 — Live demo (incident flow) | 0:45–2:15 | 90s | Incident A → Model Armor block → cross-session recall | Terminal + dashboard on live URL (or local fakes) |
| 4 — Google Cloud proof shots | 2:15–3:15 | 60s | GCP console / Cloud Run dashboard / `.run` URL | Browser, GCP project |
| 5 — Architecture recap + close | 3:15–3:45 | 30s | Diagram walk-through, end card | `docs/architecture.png` + repo card |

---

## Beat 1 — Problem (0:00–0:15)

**On screen**: dark title slide — "FleetOps" / "Agent fleets ship. Nobody tells them who may act." Then one bullet list appearing in order: *Who is approved? · What did it last decide? · Who blocked the bad call?*

**Narration (verbatin)**:
> "Enterprises are deploying fleets of AI agents — but a fleet without registry, identity, guardrails, and memory is just many chatbots. And when one does something wrong, you have no trace to replay."

**Production notes**: 15s hard max; this beat sells the framing, not the product. No music louder than narration.

## Beat 2 — Value prop (0:15–0:45)

**On screen**: slide with the five pillars as icons/labels in one row — Registry · Identity+Gateway · Model Armor · Memory Bank · Observability — then cut to the live dashboard showing a completed incident chain (static is fine).

**Narration**:
> "FleetOps is an agent-fleet control plane on Google Cloud. A planner breaks an incident into subtasks. A gateway routes each one to a registered, approved specialist under zero-trust identity. Inline guardrails block prompt injection and PII before any tool runs. A memory bank carries context across sessions — so the fleet remembers what it already learned. And every hop is traced end-to-end."

**Production notes**: 30s; name each pillar exactly once — judges map these to track requirements literally. If using live dashboard, make sure a rejected or blocked span is visible somewhere in frame (red highlight).

## Beat 3 — Live demo: incident flow (0:45–2:15)

This beat must contain **all three proof moments**: one valid route, one Model Armor block, cross-session memory recall. Order below is the recommended cut.

### 3a — Incident A accepted + planner decomposes (0:45–1:05, 20s)

**On screen**: terminal at the live URL (or `make demo` locally).
```bash
curl -s -X POST https://<live-url>/incidents \
  -H 'Content-Type: application/json' \
  -d '{"description": "checkout latency spiked 40% in eu-west since 13:05"}'
```
Response JSON visible; then the planner output (subtask list) streaming.

**Narration**:
> "I post one incident — a checkout latency spike. The planner decomposes it into subtasks and hands each to a specialist through the gateway."

### 3b — Specialists execute + trace chain renders (1:05–1:25, 20s)

**On screen**: dashboard page for that incident id; hop list building top-to-bottom: `planner.decide` → `gateway.route (principal=diagnoser, policy=allow)` → `tool.call latency_probe` → `remediator.apply_fix` → `memory.write`. Timestamps visible.

**Narration**:
> "Diagnoser runs its probe tool; remediator applies the fix. Watch the trace — every hop, every principal, every decision is a span you can replay."

### 3c — Model Armor block (1:25–1:45, 20s) ← mandatory proof moment

**On screen**: second `curl POST /incidents` whose payload contains an injection marker or the canary PII value; response shows the guardrail decision. Then dashboard: the blocked span **red-highlighted**, reason string visible (e.g., `blocked: injection_marker in tool arg 'report_to'`).

**Narration**:
> "Now a second incident — this one carries an injected instruction inside a tool argument. Model Armor checks arguments before any tool executes, blocks the call, and logs exactly why. The agent never even saw it."

**Production notes**: if live, use the real canary `demo.user@example.test` or the plan's injection marker — whatever Stage 2b implements; keep the on-screen reason legible (zoom that span). This single frame carries a big chunk of the Architecture score.

### 3d — Cross-session memory recall (1:45–2:15, 30s) ← mandatory proof moment

**On screen**: third incident (B), clearly related to A ("follow-up on the checkout latency incident from this morning"). Output shows the specialist **reading prior context before acting**; the recalled text is visible in the terminal or dashboard (`memory.read → session <principal+topic>`, quoted outcome of A). Then B completes faster / without re-running the diagnosis.

**Narration**:
> "Incident B is a follow-up to A. Before it acts, the specialist pulls A's outcome from the memory bank — no re-diagnosis, just continuation. That's cross-session context, persistent and scoped by principal."

**Production notes**: 30s; this is the strongest "beyond chat loops" moment in the video — give it full time, don't compress. The recalled string must be readable on screen.

## Beat 4 — Google Cloud proof shots (2:15–3:15)

Mandatory per "What to Submit": *Must demonstrate the backend is running on Google Cloud (GCP Console, Cloud Run dashboard, URL of .run, etc).* One continuous browser session, no cuts that could read as staged.

### 4a — GCP console project overview (2:15–2:35, 20s)
**On screen**: `console.cloud.google.com` → project selector showing the FleetOps project; APIs page with **Cloud Run**, **Pub/Sub**, **Firestore** enabled.

**Narration**: "The backend runs on Google Cloud — here's the project."

### 4b — Cloud Run dashboard (2:35–2:55, 20s)
**On screen**: Cloud Run → services list with the FleetOps service; open it → recent invocations / logs showing one of the demo incidents being processed (correlate incident id with Beat 3).

**Narration**: "Cloud Run serves the API and dashboard; here are real invocations from the demo you just watched."

### 4c — Live `.run` URL + supporting services (2:55–3:15, 20s)
**On screen**: browser tab with `https://<live-url>` → `/agents` (registry listing), then the trace/dashboard page for a completed incident. Optional quick hops: Pub/Sub topic `fleetops-incidents` with published messages; one Firestore session/memory doc.

**Narration**: "Same URL, live registry and traces — this is what judges can poke at."

**Production notes**: keep mouse movement slow; avoid hovering over unrelated menu items; if the service will be stopped after submission (allowed by rules), record this beat **before** stopping it.

## Beat 5 — Architecture recap + close (3:15–3:45)

**On screen**: `docs/architecture.png` full-frame, clean labels: clients → gateway (identity+policy) → planner/specialists ↔ memory bank; Pub/Sub events; Model Armor block point on tool path; trace pipeline → dashboard/Cloud Trace. Hold 10s with the diagram fully labeled, then end card: repo URL + "Built for #AllThingsAgenticHackathon".

**Narration**:
> "One gateway, one registry, inline guardrails, persistent memory, full traces — a fortified fleet on Gemini and Google Cloud."

---

## Production checklist (Stage 4a)

- [ ] Record at 1080p+, MP4 H.264; total length ≤ 4:00
- [ ] All three proof moments present and legible: rejected/routed principal, Model Armor block with visible reason, cross-session recall with quoted recalled text
- [ ] Beat 4 is one continuous real browser session against the live project
- [ ] Narration or captions throughout; no silent stretches > 3s
- [ ] End card shows repo URL + hackathon hashtag
- [ ] Upload destination: `[VIDEO HOST]` (YouTube unlisted is fine — rules require public content only for bonus blog, video must be accessible to judges)
