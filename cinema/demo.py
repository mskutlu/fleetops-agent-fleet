"""Local harness — `make cinema-demo` MUST pass before commit (house rule).

  [1] MCP ROUND-TRIP    list_databases + SELECT version() through the official
                        mcp-clickhouse server over stdio -> green round-trip
  [2] DATASET           deterministic synthetic studio data, HTTP-loaded into
                        ClickHouse, row counts verified
  [3] NL -> SQL FLOW    "Why did Sable Peak drop in the US?" -> planner JSON ->
                        analyst subtasks -> real SQL via MCP -> answer + evidence;
                        memory write-back
  [4] ANOMALY DIGEST    median-baseline scan flags the planted sable-peak US
                        decline AND neon-harbor UK premiere spike; ops events
                        attached; findings to memory bank
  [5] CROSS-SESSION     a second question on Sable Peak recalls step [3]'s
                        finding BEFORE acting (memory read-back)

Offline-capable: with no GEMINI_API_KEY the deterministic mock LLM drives the
same ADK tool-calling path. Exits non-zero if anything breaks."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from . import dataset
from .agents import model_label
from .flow import CinemaOps
from .mcp_client import ClickHouseMcp
from .memory import MemoryBank

import warnings

warnings.filterwarnings("ignore", message=".*JSON_SCHEMA_FOR_FUNC_DECL.*")
logging.basicConfig(level=logging.WARNING, force=True)
for _n in ("google.adk", "google_adk", "adk", "mcp"):
    logging.getLogger(_n).setLevel(logging.ERROR)


def _section(title: str) -> None:
    print(f"\n{'=' * 64}\n[{title}]\n{'=' * 64}")


async def main() -> int:
    keyed = bool(os.environ.get("GEMINI_API_KEY"))
    model = f"{model_label()} ({'Gemini via ADK' if keyed else 'mock, deterministic offline'})"
    ch_base = os.environ.get("CH_HOST", "127.0.0.1")
    ch_port = os.environ.get("CH_HTTP_PORT", "8123")
    ch_pw = os.environ.get("CH_PASSWORD", "cinema")  # matches `make cinema-up` default
    print(f"CinemaOps demo — model: {model} | ClickHouse: http://{ch_base}:{ch_port} (via mcp-clickhouse MCP)")

    memory_file = ".cinema_memory_demo.json"
    if os.path.exists(memory_file):
        os.remove(memory_file)  # fresh, deterministic demo state

    mcp = ClickHouseMcp()
    ops = CinemaOps(mcp=mcp, memory=MemoryBank(path=memory_file))
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'ok ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    await mcp.start()
    try:
        return await _run_checks(mcp=mcp, ops=ops, check=check, failures=failures, ch_base=ch_base, ch_port=ch_port, ch_pw=ch_pw)
    finally:
        # close the stdio session in the task that opened it (anyio is strict)
        await mcp.stop()


def _serve() -> None:
    """Serve phase — own event loop, no running one (uvicorn.run requirement)."""
    import uvicorn
    from .service import create_app

    print("\nServing CinemaOps on http://127.0.0.1:8090 — try:")
    print('  curl -s localhost:8090/healthz')
    print('  curl -s -X POST localhost:8090/query -H content-type:application/json '
          '-d \'{"question":"Why did Sable Peak drop in the US?"}\'')
    app = create_app(ops=CinemaOps(mcp=ClickHouseMcp(), memory=MemoryBank(path=".cinema_memory_demo.json")))
    uvicorn.run(app, host="127.0.0.1", port=8090)


async def _run_checks(*, mcp, ops, check, failures, ch_base, ch_port, ch_pw) -> int:
    # [1] MCP round-trip ------------------------------------------------------
    _section("[1] MCP ROUND-TRIP via official mcp-clickhouse server (stdio)")
    dbs = await mcp.list_databases()
    db_list = dbs.get("databases") if isinstance(dbs, dict) and "databases" in dbs else dbs
    db_names = [d["name"] if isinstance(d, dict) else d for d in (db_list or [])]
    print(f"  databases: {db_names}")
    check("list_databases via MCP", True)
    ver = await mcp.run_query("SELECT version() AS v")
    print(f"  SELECT version() -> {ver.get('rows')}")
    check("run_query via MCP returns rows", bool(ver.get("rows")), str(ver))

    # [2] dataset -------------------------------------------------------------
    _section("[2] DATASET — synthetic studio data (deterministic) loaded over CH HTTP")
    counts = dataset.load(f"http://{ch_base}:{ch_port}", password=ch_pw)
    print(f"  loaded: {counts}")
    check("viewership rows > 0", counts.get("viewership", 0) > 4000, str(counts))
    via_mcp = await mcp.run_query("SELECT count() AS n FROM studio.viewership")
    print(f"  verify via MCP: {via_mcp.get('rows')}")
    check("MCP sees the loaded table", (via_mcp.get("rows") or [[0]])[0][0] == counts["viewership"])

    # [3] NL -> SQL flow -------------------------------------------------------
    _section('[3] NL -> SQL FLOW — "Why did Sable Peak drop in the US?"')
    Q1 = "Why did Sable Peak drop in the US last night? Was it a content problem or infrastructure?"
    r1 = await ops.ask(Q1)
    print(f"  route: {r1['route']}")
    print(f"  plan : {[s['title'] for s in r1['plan']]}")
    for i, (st, qz) in enumerate(zip(r1["steps"], r1["queries"]), 1):
        print(f"  step{i}: {st['subtask']['title']}")
        print(f"         SQL: {qz['sql']}")
        print(f"         rows={qz['rows']} preview={qz['preview'][:2]}... summary: {st['summary'][:100]}")
    check("plan has 2 subtasks", len(r1["plan"]) == 2, str(r1["plan"]))
    check("both SQL executed via MCP without error",
          len(r1["queries"]) >= 2 and all(not q.get("error") for q in r1["queries"]),
          str([q.get("error") for q in r1["queries"]]))
    daily = [q for q in r1["queries"] if "viewership" in q["sql"]]
    check("decline-window query returned 14d x 3 countries rows",
          bool(daily) and daily[0]["rows"] == 42, str([q["rows"] for q in r1["queries"]]))
    ops_sql = [q for q in r1["queries"] if "ops_events" in q["sql"]]
    check("ops correlation found the cdn-us-east crit event",
          bool(ops_sql) and any("cdn-us-east" in str(row) for row in (ops_sql[0]["preview"] or [])),
          str(ops_sql[:1]))
    print(f"  memory written: {r1['memory_written']}")

    # [4] anomaly digest -------------------------------------------------------
    _section("[4] ANOMALY DIGEST — median-baseline scan + ops events (the 'automated summary' beat)")
    d = await ops.digest()
    for line in d["lines"]:
        print(f"  {line}")
    flag_map = {(f[0], f[2]): f[6] for f in d["flags"]}
    check("digest flags sable-peak US decline (negative deviation)",
          flag_map.get(("sable-peak", "US")) is not None and flag_map[("sable-peak", "US")] < 0, str(flag_map))
    check("digest flags neon-harbor UK spike (positive deviation)",
          flag_map.get(("neon-harbor", "UK")) is not None and flag_map[("neon-harbor", "UK")] > 0, str(flag_map))
    check("digest attaches ops events", any("cdn-us-east" in l for l in d["lines"]))

    # [5] cross-session recall -------------------------------------------------
    _section("[5] CROSS-SESSION RECALL — second question on Sable Peak")
    Q2 = "What was wrong with Sable Peak in the US?"
    r2 = await ops.ask(Q2)
    if r2["recalled"]:
        print(f"  recalled before acting: {[e['text'] for e in r2['recalled']]}")
    else:
        print("  (nothing recalled)")
    check("prior finding recalled before acting", len(r2["recalled"]) >= 1)

    _section("RESULT")
    if failures:
        print(f"FAILED checks: {failures}")
        return 1
    print("ALL CHECKS GREEN — MCP round-trip, dataset, NL->SQL flow, digest, recall.")
    if os.environ.get("NO_SERVE"):
        return 0
    return None   # signal main(): checks passed -> serve next (own loop world)


if __name__ == "__main__":
    code = asyncio.run(main())   # None => checks passed and serving requested
    if code is not None:
        sys.exit(code)
    _serve()                     # no running loop here: uvicorn owns its world
