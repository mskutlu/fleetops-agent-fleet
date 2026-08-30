"""Model layer for CinemaOps.

Keyed (GEMINI_API_KEY set): every agent runs on the pinned Gemini 3.x id —
same pin logic as fleetops (imported, not duplicated). Unkeyed: a deterministic
MockLlm so `make cinema-demo` is reproducible offline and proves the full
MCP round-trip without a key."""

from __future__ import annotations

import json
import os
import re

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

# One codebase: reuse the fleetops pin (explicit 3.x id, GEMINI_MODEL override).
from fleetops.llm import pinned_model


def make_model(agent_name: str):
    if os.environ.get("GEMINI_API_KEY"):
        return pinned_model()
    return CinemaMockLlm(model="mock", agent_name=agent_name)


def _system_text(req: LlmRequest) -> str:
    cfg = req.config
    si = getattr(cfg, "system_instruction", None) if cfg else None
    if si is None:
        return ""
    return si if isinstance(si, str) else "".join(p.text or "" for p in si.parts or [])


def _user_text(req: LlmRequest) -> str:
    for content in reversed(req.contents):
        text = "".join(p.text or "" for p in content.parts or [])
        if text:
            return text
    return ""


def _responded_tools(req: LlmRequest) -> set[str]:
    out = set()
    for content in req.contents:
        for part in content.parts or []:
            if part.function_response:
                out.add(part.function_response.name)
    return out


SHOW_TITLES = {  # title (lowercased) -> show_id, for mock routing only
    "sable peak": "sable-peak", "neon harbor": "neon-harbor",
    "kingdom of ash": "kingdom-of-ash", "casbah crime": "casbah-crime",
    "static love": "static-love", "orbit diet": "orbit-diet",
}


def _route(question: str) -> dict:
    q = question.lower()
    show = next((sid for t, sid in SHOW_TITLES.items() if t in q), "sable-peak")
    country = next((c.upper() for c in ("US", "UK", "DE") if re.search(rf"\b{c}\b", question.upper())), "US")
    if any(w in q for w in ("drop", "decline", "fell", "down", "dip")):
        route = "decline"
    elif any(w in q for w in ("spike", "surge", "jump", "premiere", "blowup")):
        route = "spike"
    else:
        route = "top"
    return {"show": show, "country": country, "route": route}


class CinemaMockLlm(BaseLlm):
    """Deterministic stand-in for Gemini. Routes on instruction tokens
    (CINEMA_PLANNER / CINEMA_ANALYST). One run_query call per analyst subtask,
    then a short text line — the runner assembles the final answer from the
    actual ClickHouse rows."""

    agent_name: str

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["mock"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        sys_text = _system_text(llm_request)
        user_text = _user_text(llm_request)

        def _text(t: str):
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t)]))

        def _call(sql: str):
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(name="run_query", args={"query": sql}))],
                )
            )

        if "CINEMA_PLANNER" in sys_text:
            r = _route(user_text)
            if r["route"] == "decline":
                plan = {"subtasks": [
                    {"id": "t1", "kind": "locate_decline",
                     "title": f"Pull 14-day daily starts for {r['show']} by country"},
                    {"id": "t2", "kind": "correlate_ops",
                     "title": "Pull recent ops events (warn/crit) to correlate the decline window"},
                ]}
            elif r["route"] == "spike":
                plan = {"subtasks": [
                    {"id": "t1", "kind": "locate_spike",
                     "title": f"Pull 14-day daily starts for {r['show']} by country"},
                    {"id": "t2", "kind": "correlate_ops",
                     "title": "Pull recent ops/marketing events to explain the spike window"},
                ]}
            else:
                plan = {"subtasks": [
                    {"id": "t1", "kind": "top_shares",
                     "title": "Rank shows by total starts over the last 14 days"}]}
            yield _text(json.dumps(plan))
        elif "CINEMA_ANALYST" in sys_text:
            r = _route(user_text)
            if "run_query" in _responded_tools(llm_request):
                # Tool result is back in context: close with a short note; the
                # runner assembles the real answer from the ClickHouse rows.
                yield _text("Subtask query complete — findings are in the returned rows.")
            else:
                task = re.search(r"TASK=(\d+)", user_text)
                step = int(task.group(1)) if task else 1
                base_day = "2026-08-12"  # ANCHOR(2026-08-25) - 13 days; dataset.py is the source of truth
                daily_sql = (f"SELECT toDate(ts) AS day, country, sum(starts) AS starts "
                             f"FROM studio.viewership WHERE show_id = '{r['show']}' AND ts >= '{base_day}' "
                             f"GROUP BY day, country ORDER BY day, country")
                if r["route"] == "top":
                    sql = ("SELECT s.title, sum(v.starts) AS starts FROM studio.viewership v "
                           "JOIN studio.shows s ON s.show_id = v.show_id GROUP BY s.title "
                           "ORDER BY starts DESC LIMIT 5")
                elif step >= 2:
                    sev = "('warn', 'crit')" if r["route"] == "decline" else "('info',)"
                    sql = (f"SELECT event_ts, severity, component, message FROM studio.ops_events "
                           f"WHERE severity IN {sev} ORDER BY event_ts DESC LIMIT 5")
                else:
                    sql = daily_sql
                yield _call(sql)
        else:
            yield _text("ok")
