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
