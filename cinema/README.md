# CinemaOps — Agentic Cinema entry (ClickHouse track)

A streaming-studio **operations agent** built with Gemini + Google ADK
(Agent Builder). It answers natural-language studio questions by having
specialist agents run SQL against ClickHouse **through the official
`mcp-clickhouse` MCP server at runtime**, correlates findings with ops
events, runs an anomaly-digest job, and recalls prior findings across
sessions.

## Why it fits the track

- **Agentic Cinema**: planner → analyst agent topology (ADK `LlmAgent`s),
  real media workflow: "why did a show's starts drop?", premiere-spike
  analysis, catalog ranking — not a toy calculator.
- **ClickHouse via MCP** (the track rule): every agent SQL call goes to the
  official `mcp-clickhouse` server over MCP stdio (`run_query`,
  `list_tables`). The app itself holds no raw ClickHouse driver connection on
  the answer path; dataset loading uses plain CH HTTP, which is ETL, not the
  agent surface.
- **Real Gemini model**: with `GEMINI_API_KEY` set, all agents run on a pinned
  Gemini 3.x id (`gemini-3-flash`, override via `GEMINI_MODEL`). Without a key,
  a deterministic mock LLM drives the *same* ADK tool-calling path so the whole
  flow is reproducible offline.

## Architecture

```
question ──> PLANNER (ADK LlmAgent)
                │ JSON subtasks (1..3), each = one SELECT
                ▼
            ANALYST x N (ADK LlmAgent, tools: list_tables + run_query)
                │ MCP stdio  ──────────────► mcp-clickhouse server
                ▼                            │ CLICKHOUSE_* env
        answer + evidence trail              ▼
memory bank ◄── write-back             ClickHouse (self-hosted or Cloud)
   ▲ recall before acting               schema: studio.{shows, viewership, ops_events}
   └─────────────────────┘

digest job: one median-baseline scan SQL via MCP -> flagged anomalies + ops
events attached -> memory bank (the "automated summary" beat)
```

## Quickstart

```bash
make cinema-up            # docker: self-hosted ClickHouse on 127.0.0.1:8123/9000
NO_SERVE=1 make cinema-demo   # MUST pass: MCP round-trip, dataset, NL->SQL, digest, recall
make cinema-run           # API on http://127.0.0.1:8090

curl -s localhost:8090/healthz
curl -s -X POST localhost:8090/query \
     -H content-type:application/json \
     -d '{"question":"Why did Sable Peak drop in the US last night?"}'
```

Env (all optional, local defaults shown): `CH_HOST=127.0.0.1`,
`CH_HTTP_PORT=8123`, `CH_USER=default`, `CH_PASSWORD=cinema`,
`CH_SECURE=false`. Point these at ClickHouse Cloud and set `CH_SECURE=true` to
switch targets — no code change.

## The dataset (synthetic, deterministic, no real PII)

Six fictional shows × 3 countries × 14 days of hourly starts/completions in
`studio.viewership`, plus a catalog (`studio.shows`) and an ops log
(`studio.ops_events`). Two signals are planted:

- **Decline**: *Sable Peak* US, prime-time window — starts ~×0.28, caused by a
  `cdn-us-east` edge-pool drain (crit event in the same window).
- **Spike**: *Neon Harbor* UK premiere push — starts ~×4.5, with a marketing
  info event preceding it.

## Memory bank

JSON-file backed (`CINEMA_MEMORY_FILE`, default `.cinema_memory.json`), keyed by
show. Agents recall prior findings **before** acting and write back after; the
digest job also lands here. A restarted service or new session sees them — that's
the cross-session recall check in `make cinema-demo`.

## API

| Route | Purpose |
|---|---|
| `POST /query` | `{"question": "..."}` → route, plan, per-step summaries, every SQL executed via MCP with row counts + preview, memory trail |
| `POST /digests/run` · `GET /digests` | anomaly scan (median-baseline deviations ≥ 40%) + ops events; findings persisted to the memory bank |
| `GET /healthz` | live MCP round-trip against ClickHouse (`SELECT 1`) |

## Boundaries

- Read-only agent surface: `run_query` is served by mcp-clickhouse in its default
  read-only mode; no write tools are exposed to agents.
- One parameter class per run, small result sets (GROUP BY + LIMIT), bounded
  memory entries — low-noise by construction.
