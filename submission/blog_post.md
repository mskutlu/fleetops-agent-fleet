# We built a control plane for AI agent fleets — registry, guardrails, memory, and traces that actually work

*This project was created for the All Things Agentic Hackathon (#AllThingsAgenticHackathon).*

Every team we know is deploying AI agents. Almost none of them can answer the three questions that matter in
production: **who is approved to act, what did the agent decide last time, and who blocked the bad call?**

We built **FleetOps** — an open-source agent-fleet control plane on Google Cloud — to answer all three, with
receipts. It's running live, and you can clone and run the whole thing offline in under a minute.

## The one-flow demo

Post an incident — "checkout-service p99 latency spiked 2400ms after deploy". What happens:

1. **The planner** (a Google ADK agent) decomposes it into subtasks: diagnose, then remediate.
2. **The gateway** checks every hop: is this principal registered, approved, and scoped for this capability?
   A specialist token trying to dispatch incidents gets a clean `403` — and the rejection becomes a trace span.
3. **Specialists execute through inline guardrails.** Before any tool call, arguments are checked for prompt
   injection and PII. One test call carried an injected instruction and a canary email — the tool never ran;
   the block was logged with three machine-readable reasons.
4. **The memory bank carries context across sessions.** A follow-up incident hours later read the earlier
   incident's outcome *before* acting — no re-diagnosis, straight to continuation. You can watch the
   `memory_read` span quote the recalled text.
5. **Every hop is an OpenTelemetry-compliant span** — planner decisions, gateway allow/deny, guardrail blocks,
   tool calls, memory reads/writes — persisted and rendered in a one-page dashboard you can replay.

## Why it's built this way

The hard parts of agent fleets are systems problems, not prompt problems. So the architecture is boring on
purpose: a single FastAPI entrypoint on **Cloud Run**, an async runtime driven by **Pub/Sub** (a job survives a
simulated crash and resumes from persisted state), **Firestore** as the registry/memory/trace store, and
**Google ADK** agents on the **Gemini API** (pinned `gemini-3.6-flash`; a deterministic mock LLM shares the same
code path so `make demo` runs with zero keys). The same contracts run against in-memory fakes locally and real
GCP services in production — that's what makes the demo reproducible for a judge and honest for us.

## What we learned

- Inline, deterministic guardrails beat "we asked the model to be careful" — blocks you can log with reasons are
  blocks you can audit.
- Cross-session memory changes agent behavior measurably: the follow-up incident didn't re-diagnose; it continued.
- Crash-resume is what makes "long-running async agent work" credible instead of aspirational.

## Try it

- Repo: https://github.com/mskutlu/fleetops-agent-fleet (`make demo` — no keys, no cloud)
- Live: https://fleetops-qiedvqu63a-ew.a.run.app (registry + trace dashboards in your browser)

*This project was created for the All Things Agentic Hackathon.*
