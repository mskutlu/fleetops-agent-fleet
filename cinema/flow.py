"""CinemaOps flow: question -> PLANNER (ADK) -> 1..3 subtasks -> ANALYST per
subtask, each running SQL through the mcp-clickhouse MCP server. Memory bank
recall before acting, write-back after; a scheduled-style anomaly digest job
rounds out the studio-ops workflow."""

from __future__ import annotations

import json
import re
import uuid

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agents import build_agents
from .llm import _route


def _parse_plan(text: str) -> list[dict]:
    """Planner reply must be a subtask JSON; tolerate code fences/whitespace."""
    t = text.strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError(f"planner did not return JSON: {t[:120]!r}")
    plan = json.loads(m.group(0))
    subs = plan.get("subtasks") or []
    if not all(isinstance(s, dict) and s.get("title") for s in subs):
        raise ValueError(f"planner subtasks malformed: {plan!r}")
    return subs[:3]


class _RecordingMcp:
    """Shim so every run_query the agents issue is captured (evidence trail)."""

    def __init__(self, mcp, queries: list):
        self._m = mcp
        self._q = queries

    async def list_tables(self, database: str = "studio"):
        """List tables in a database with column metadata."""
        return await self._m.list_tables(database)

    async def run_query(self, query: str):
        """Run one read-only SQL query on ClickHouse via the MCP server."""
        res = await self._m.run_query(query)
        self._q.append({
            "sql": query.strip(),
            "rows": len(res.get("rows") or []),
            "columns": res.get("columns"),
            "error": res.get("error"),
            "preview": (res.get("rows") or [])[:3],
        })
        return res


class CinemaOps:
    def __init__(self, mcp, memory):
        self.mcp = mcp
        self.memory = memory
        self.queries: list[dict] = []  # evidence trail; cleared per ask()
        recorder = _RecordingMcp(mcp, self.queries)
        self.planner, self.analyst = build_agents(recorder)

    async def ask(self, question: str) -> dict:
        route = _route(question)
        recalled = self.memory.read(route["show"])
        self.queries.clear()
        ctx_lines = [f"SHOW={route['show']} COUNTRY={route['country']} ROUTE={route['route']}"]
        if recalled:
            ctx_lines.append("Prior findings from earlier sessions on this show (recall before acting):")
            ctx_lines += [f"- {e['ts']}: {e['text']}" for e in recalled[-3:]]

        # -- planner ---------------------------------------------------------
        plan = await self._run(self.planner, app_name="planner", message=question)
        subtasks = _parse_plan(plan)

        # -- one analyst run per subtask (each issues <=1 SQL via MCP) -------
        steps = []
        for i, st in enumerate(subtasks):
            msg = "\n".join(ctx_lines + [f"TASK={i + 1}/{len(subtasks)}: {st['title']}",
                                        f"Question context: {question}"])
            text = await self._run(self.analyst, app_name="analyst", message=msg)
            steps.append({"subtask": st, "summary": text})

        # -- write-back ------------------------------------------------------
        n_rows = sum(q["rows"] for q in self.queries)
        finding = (f"{question} -> {len(subtasks)} subtask(s), "
                   f"{len(self.queries)} SQL via mcp-clickhouse, {n_rows} rows")
        written = self.memory.write(route["show"], finding)

        return {
            "question": question,
            "route": route,
            "plan": subtasks,
            "recalled": recalled,
            "steps": steps,
            "queries": list(self.queries),
            "memory_written": written,
        }

    async def digest(self) -> dict:
        """Anomaly scan (one SQL): daily starts per show/country vs the median
        baseline over the window; |deviation| >= 25% is flagged. Findings land
        in the memory bank for later recall — the 'automated summary' beat."""

        async def q(sql: str) -> dict:
            res = await self.mcp.run_query(sql)
            return res if "error" not in res else {"columns": [], "rows": []}

        flags = await q(
            "WITH d AS (SELECT show_id, country, toDate(ts) AS day, sum(starts) AS x "
            "FROM studio.viewership GROUP BY show_id, country, day), "
            "b AS (SELECT show_id, country, median(x) AS med FROM d GROUP BY show_id, country) "
            "SELECT d.show_id, s.title, d.country, toString(d.day) AS day, d.x, "
            "round(b.med) AS baseline, round(100 * (d.x - b.med) / greatest(1, b.med)) AS deviation_pct "
            "FROM d JOIN studio.shows s ON s.show_id = d.show_id "
            "JOIN b ON b.show_id = d.show_id AND b.country = d.country "
            "WHERE abs(d.x - b.med) >= 0.25 * b.med ORDER BY abs(deviation_pct) DESC LIMIT 8")

        rows = flags.get("rows", [])
        lines, by_show = [], {}
        for show_id, title, country, day, x, baseline, dev in rows:
            line = (f"{title} ({country}) {day}: starts {x:,} vs baseline ~{baseline:,} "
                    f"({dev:+.0f}%)")
            lines.append(line)
            by_show.setdefault(show_id, []).append(line)

        events = await q("SELECT toString(event_ts), severity, component, message "
                         "FROM studio.ops_events WHERE severity IN ('warn','crit') "
                         "ORDER BY event_ts DESC LIMIT 3")
        for ts, sev, comp, msg in events.get("rows", []):
            lines.append(f"ops {sev} @ {ts}: [{comp}] {msg}")

        written = {}
        for show_id, ls in by_show.items():
            written[show_id] = self.memory.write(show_id, "digest: " + "; ".join(ls))

        return {"flags": rows, "lines": lines, "memory_written": written}

    # -- internals -----------------------------------------------------------

    async def _run(self, agent, app_name: str, message: str) -> str:
        runner = InMemoryRunner(agent=agent, app_name=f"cinema-{app_name}")
        session_id = f"s-{uuid.uuid4().hex[:12]}"
        await runner.session_service.create_session(
            app_name=f"cinema-{app_name}", user_id="studio", session_id=session_id)
        final = ""
        async for event in runner.run_async(
                user_id="studio", session_id=session_id,
                new_message=types.Content(role="user", parts=[types.Part(text=message)])):
            if event.is_final_response and event.content and event.content.parts:
                final = "".join(p.text or "" for p in event.content.parts if p.text)
        return final
