"""ADK agents (Google Agent Builder): Planner decomposes studio questions;
Analyst executes one subtask by running SQL through the mcp-clickhouse MCP
server. Both run on the pinned Gemini 3.x id when keyed, else the mock."""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent

from .llm import make_model, pinned_model

_SCHEMA = (
    "ClickHouse schema (database `studio`, read-only): "
    "shows(show_id String, title String, genre String, season Int32); "
    "viewership(ts DateTime UTC, show_id String, country LowCardinality(String), "
    "starts UInt32, completions UInt32) — hourly aggregates; "
    "ops_events(event_ts DateTime, severity Enum8('info','warn','crit'), "
    "component String, message String)."
)

_PLANNER_INSTRUCTION = (
    "You are the CINEMA_PLANNER agent of CinemaOps, a streaming-studio "
    "operations assistant. Decompose the question into 1-3 focused subtasks, "
    "each fetchable with ONE SQL SELECT against this schema: " + _SCHEMA +
    ' Reply ONLY with JSON {"subtasks": [{"id": "t1", "kind": "...", '
    '"title": "..."}]}. Prefer the smallest set of queries that answers it.'
)

_ANALYST_INSTRUCTION = (
    "You are the CINEMA_ANALYST agent of CinemaOps. Execute ONE subtask by "
    "calling run_query with a single read-only SELECT against this schema: " + _SCHEMA +
    " Use list_tables if you need to confirm column names. Keep results small "
    "(GROUP BY, LIMIT). After the tool returns rows, end with 1-3 sentences "
    "summarizing what the rows show, citing exact numbers and timestamps."
)


def model_label() -> str:
    return pinned_model() if os.environ.get("GEMINI_API_KEY") else "mock"


def build_agents(mcp):
    """mcp = a ClickHouseMcp instance; its bound methods are the agent tools."""

    def _tools(names):  # keep tool set explicit per agent (no write surface)
        return [getattr(mcp, n) for n in names]

    planner = LlmAgent(
        name="planner",
        model=make_model("planner"),
        description="Decomposes studio questions into focused SQL subtasks.",
        instruction=_PLANNER_INSTRUCTION,
    )
    analyst = LlmAgent(
        name="analyst",
        model=make_model("analyst"),
        description="Answers one subtask with a read-only ClickHouse query via MCP.",
        instruction=_ANALYST_INSTRUCTION,
        tools=_tools(["list_tables", "run_query"]),  # run_query is read-only by default server-side
    )
    return planner, analyst
