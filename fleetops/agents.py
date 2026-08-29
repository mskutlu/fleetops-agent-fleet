"""ADK agents: Planner decomposes incidents; Diagnoser/Remediator execute
subtasks with tools. Each agent is also exported as an AgentCard doc."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from .llm import make_model
from .store import AgentCard
from .tools import check_metrics, query_logs, restart_service, scale_service

_PLANNER_INSTRUCTION = (
    "You are the PLANNER agent of an incident-response fleet. "
    "Decompose the incident into 2-4 subtasks. Reply ONLY with JSON: "
    '{"subtasks": [{"id": "t1", "kind": "diagnose"|"remediate", '
    '"title": "...", "service": "..."}]}. '
    "Every incident needs at least one diagnose and one remediate subtask."
)
_DIAGNOSER_INSTRUCTION = (
    "You are the DIAGNOSER agent. Investigate the incident subtask using your "
    "tools (query_logs, check_metrics), then state your diagnosis concisely. "
    "Use the provided memory context from prior runs before acting."
)
_REMEDIATOR_INSTRUCTION = (
    "You are the REMEDIATOR agent. Execute the remediation subtask using your "
    "tools (restart_service, scale_service), respecting the memory context "
    "(findings from the diagnoser). Confirm the fix."
)


def build_agents():
    planner = LlmAgent(
        name="planner",
        model=make_model("planner"),
        description="Decomposes incidents into 2-4 executable subtasks.",
        instruction=_PLANNER_INSTRUCTION,
    )
    diagnoser = LlmAgent(
        name="diagnoser",
        model=make_model("diagnoser"),
        description="Diagnoses incidents using log/metric tools.",
        instruction=_DIAGNOSER_INSTRUCTION,
        tools=[query_logs, check_metrics],
    )
    remediator = LlmAgent(
        name="remediator",
        model=make_model("remediator"),
        description="Remediates incidents using restart/scale tools.",
        instruction=_REMEDIATOR_INSTRUCTION,
        tools=[restart_service, scale_service],
    )
    cards = [
        AgentCard(
            name="planner",
            role="planner",
            description=planner.description,
            model=str(planner.model),
            tools=[],
            skills=["incident_decomposition"],
        ),
        AgentCard(
            name="diagnoser",
            role="specialist",
            description=diagnoser.description,
            model=str(diagnoser.model),
            tools=["query_logs", "check_metrics"],
            skills=["root_cause_analysis"],
        ),
        AgentCard(
            name="remediator",
            role="specialist",
            description=remediator.description,
            model=str(remediator.model),
            tools=["restart_service", "scale_service"],
            skills=["automated_remediation"],
        ),
    ]
    return planner, diagnoser, remediator, cards
