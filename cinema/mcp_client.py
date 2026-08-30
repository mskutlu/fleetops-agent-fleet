"""ClickHouse access — exclusively through the official `mcp-clickhouse` MCP
server (track rule: "actively use ClickHouse at runtime via the official
ClickHouse MCP server").

We spawn the server as a stdio subprocess and speak MCP over it. The server's
own config env is built from CH_* vars here; everything else passes through so
the child sees the same environment except our overrides.

Local defaults target the docker cluster in `make cinema-up`
(127.0.0.1:8123 HTTP, user default/cinema). Point CH_* at ClickHouse Cloud
and flip CH_SECURE=true to switch targets — no code change."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def server_launcher() -> tuple[str, list[str], dict]:
    """(command, args, env) for the official MCP server subprocess.

    mcp SDK 2.x StdioServerParameters takes command as a string + separate args."""
    host = os.environ.get("CH_HOST", "127.0.0.1")
    port = os.environ.get("CH_HTTP_PORT", "8123")
    user = os.environ.get("CH_USER", "default")
    # local default matches `make cinema-up` (docker cluster, user default)
    password = os.environ.get("CH_PASSWORD", "cinema")
    secure = os.environ.get("CH_SECURE", "false").lower() == "true"
    env = {**os.environ,
           "CLICKHOUSE_HOST": host,
           "CLICKHOUSE_PORT": port,
           "CLICKHOUSE_USER": user,
           "CLICKHOUSE_PASSWORD": password,
           "CLICKHOUSE_SECURE": str(secure).lower(),
           "CLICKHOUSE_VERIFY": "true" if secure else "false"}
    # mcp-clickhouse is installed in this venv; entrypoint mcp_clickhouse.main:main.
    # Pre-quiet the loggers so stdio carries only MCP frames (fastmcp defaults
    # to INFO on stderr, which would pollute any stdout-based harness).
    script = (
        "import logging\n"
        "logging.basicConfig(level=logging.WARNING, force=True)\n"
        "for _n in ('mcp', 'mcp.server.lowlevel.server', 'mcp-clickhouse', 'uvicorn'):\n"
        "    logging.getLogger(_n).setLevel(logging.WARNING)\n"
        "from mcp_clickhouse.main import main\n"
        "main()\n")
    return sys.executable, ["-c", script], env


class ClickHouseMcp:
    """One long-lived stdio session to the MCP server.

    The methods below are also the ADK agent tools (bound methods with typed
    signatures + docstrings): list_databases / list_tables / run_query."""

    def __init__(self) -> None:
        self._command, self._args, self._env = server_launcher()
        self._cm = None          # stdio_client context
        self._session_cm = None  # ClientSession context
        self.session: ClientSession | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self.session is not None:
            return
        async with self._lock:
            if self.session is not None:
                return
            self._cm = stdio_client(
                StdioServerParameters(command=self._command, args=self._args, env=self._env))
            read, write = await self._cm.__aenter__()
            self._session_cm = ClientSession(read, write)
            self.session = await self._session_cm.__aenter__()
            await self.session.initialize()

    async def stop(self) -> None:
        if self.session is not None and self._session_cm is not None:
            await self._session_cm.__aexit__(None, None, None)
            self.session = None
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None

    async def _call(self, tool: str, args: dict) -> dict:
        assert self.session is not None, "ClickHouseMcp.start() first"
        res = await self.session.call_tool(tool, args)
        text = "".join(c.text for c in res.content if getattr(c, "text", None))
        payload = json.loads(text) if text.strip().startswith(("{", "[")) else {"raw": text}
        if res.isError:
            return {"error": payload.get("raw") if isinstance(payload, dict) else str(payload)}
        return payload

    async def list_databases(self) -> dict:
        """List databases on the ClickHouse cluster (MCP tool: list_databases)."""
        await self.start()
        return await self._call("list_databases", {})

    async def list_tables(self, database: str = "studio") -> dict:
        """List tables in a database with column metadata (MCP tool: list_tables)."""
        await self.start()
        return await self._call("list_tables", {"database": database})

    async def run_query(self, query: str) -> dict:
        """Run one read-only SQL query on ClickHouse via the MCP server.

        Returns {"columns": [...], "rows": [[...]]}; errors come back as
        {"error": "..."} so the calling agent can react instead of crashing."""
        await self.start()
        return await self._call("run_query", {"query": query})


# Module-level convenience for one-shot scripts (demo, health checks).
def run_once(query: str) -> dict:
    """Start the MCP server, run ONE query, shut down. For quick probes only —
    long-lived callers should use ClickHouseMcp() and keep it warm."""

    async def _go():
        m = ClickHouseMcp()
        try:
            return await m.run_query(query)
        finally:
            await m.stop()

    return asyncio.run(_go())
