"""CinemaOps HTTP surface (deploy target: Cloud Run, same as fleetops).

    POST /query         {"question": "..."} -> plan + steps + SQL executed via
                        mcp-clickhouse + memory recall/write trail
    GET  /digests       last anomaly digest (run it first with POST /digests/run)
    POST /digests/run   trigger the scheduled-style anomaly scan (|deviation| >= 25%)
    GET  /healthz       MCP round-trip probe against ClickHouse

Every SQL answer path goes through the official mcp-clickhouse MCP server;
this app never opens a raw driver connection to ClickHouse."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .agents import model_label
from .flow import CinemaOps
from .mcp_client import ClickHouseMcp
from .memory import MemoryBank


class Question(BaseModel):
    question: str


def create_app(ops: CinemaOps | None = None) -> FastAPI:
    mcp = ClickHouseMcp() if ops is None else ops.mcp
    memory = MemoryBank() if ops is None else ops.memory
    ops = ops or CinemaOps(mcp=mcp, memory=memory)
    app = FastAPI(title="CinemaOps — studio operations agent", version="0.1.0")

    @app.get("/", include_in_schema=False)
    async def landing() -> HTMLResponse:
        return HTMLResponse("""<!doctype html>
<html><head><meta charset="utf-8"><title>CinemaOps — studio operations agent</title><style>
body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:56px;max-width:900px}
h1{color:#58a6ff;font-size:40px;margin:0 0 8px}.sub{color:#8b949e;font-size:17px;margin-bottom:30px}
h2{color:#79c0ff;font-size:19px;margin:26px 0 10px}
code,pre{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:2px 8px;font-size:14px}
pre{padding:14px;overflow:auto}
a{color:#58a6ff}
li{margin:8px 0;line-height:1.5}
</style></head><body>
<h1>🎬 CinemaOps</h1>
<div class="sub">Agentic media-distribution copilot — Gemini 3 Flash agent · ClickHouse via the official MCP server · Devpost Agentic Cinema, ClickHouse track</div>
<h2>Try it now</h2>
<ul>
<li><b>Interactive API</b> — <a href="/docs">/docs</a> (open <b>POST /query</b>, ask e.g. <i>"Why did Sable Peak drop in the US?"</i>)</li>
<li><b>Digest snapshot</b> — <a href="/digests">/digests</a> (last run's detected anomalies)</li>
<li><b>Run a fresh digest</b> — <code>curl -X POST /digests/run</code></li>
<li><b>Health</b> — <a href="/healthz">/healthz</a></li>
</ul>
<h2>Example</h2>
<pre>curl -X POST /query -H "Content-Type: application/json" -d '{"question":"Why did Sable Peak drop in the US?"}'</pre>
<h2>How it works</h2>
<ul>
<li>A Gemini 3 Flash planner breaks your question into subtasks; each subtask's SQL runs through the official <code>mcp-clickhouse</code> MCP server — the agent never touches a DB driver.</li>
<li>Every answer cites the rows it read; digests flag viewership anomalies against per-show baselines and file ops events into a memory bank.</li>
<li>Boot seeds a deterministic 6,048-row studio dataset with two planted incidents — every number in the demo reproduces exactly.</li>
</ul>
<h2>Source &amp; demo</h2>
<ul>
<li>Repo: <a href="https://github.com/mskutlu/fleetops-agent-fleet">github.com/mskutlu/fleetops-agent-fleet</a> (branch <code>cinema/main</code>)</li>
<li>Demo video: see our Devpost submission</li>
</ul>
</body></html>""")

    @app.on_event("startup")
    async def _start():
        await mcp.start()

    @app.on_event("shutdown")
    async def _stop():
        await mcp.stop()

    @app.post("/query")
    async def query(body: Question) -> dict[str, Any]:
        if not body.question.strip():
            raise HTTPException(status_code=422, detail="question must be non-empty")
        try:
            return await asyncio.wait_for(ops.ask(body.question), timeout=90)
        except Exception as e:  # one bad question must not kill the service
            raise HTTPException(status_code=502, detail=f"agent flow failed: {e!r}") from e

    @app.post("/digests/run")
    async def run_digest() -> dict[str, Any]:
        try:
            d = await asyncio.wait_for(ops.digest(), timeout=90)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"digest failed: {e!r}") from e
        app.state.last_digest = {"lines": d["lines"], "flags": d["flags"],
                                "memory_written": list(d["memory_written"])}
        return app.state.last_digest

    app.state.last_digest = {"lines": [], "flags": [], "note": "run POST /digests/run first"}

    @app.get("/digests")
    async def get_digests() -> dict[str, Any]:
        return app.state.last_digest

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        res = await mcp.run_query("SELECT 1 AS ok")
        if "error" in res:
            raise HTTPException(status_code=503, detail=res["error"])
        return {"ok": True, "model": model_label(), "clickhouse_via": "mcp-clickhouse (MCP stdio)"}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8090)
