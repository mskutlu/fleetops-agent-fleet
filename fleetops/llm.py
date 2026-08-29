"""LLM layer: Gemini via ADK when GEMINI_API_KEY is set, else a deterministic
MockLlm so `make demo` runs offline and stays reproducible.

Model pin (hackathon mandatory stack — "Gemini 3.5 or newer"):
    The model id is always explicit. `GEMINI_MODEL` overrides the default,
    which is pinned at a 3-series id. ADK never falls back to its built-in
    default silently: an empty override raises. If your key serves a different
    3-series id, pin THAT via GEMINI_MODEL and note it in README/writeup."""

from __future__ import annotations

import json
import os
import re

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


# Default pin: a Gemini 3.x series id (hackathon mandatory stack).
DEFAULT_GEMINI_MODEL = "gemini-3-flash"


def pinned_model() -> str:
    """The explicit Gemini model id every ADK agent is created with."""
    model = (os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
    if not model:
        raise ValueError(
            "GEMINI_MODEL is empty — pin an explicit 3.x model id "
            f"(default: {DEFAULT_GEMINI_MODEL})"
        )
    return model


def make_model(agent_name: str):
    """Return the pinned Gemini model id when a key exists, else the mock."""
    if os.environ.get("GEMINI_API_KEY"):
        return pinned_model()
    return MockLlm(model="mock", agent_name=agent_name)


def _system_text(llm_request: LlmRequest) -> str:
    cfg = llm_request.config
    si = getattr(cfg, "system_instruction", None) if cfg else None
    if si is None:
        return ""
    return si if isinstance(si, str) else "".join(p.text or "" for p in si.parts or [])


def _user_text(llm_request: LlmRequest) -> str:
    for content in reversed(llm_request.contents):
        text = "".join(p.text or "" for p in content.parts or [])
        if text:
            return text  # skip tool-response contents (role=user, no text)
    return ""


def _responded_tools(llm_request: LlmRequest) -> set[str]:
    out = set()
    for content in llm_request.contents:
        for part in content.parts or []:
            if part.function_response:
                out.add(part.function_response.name)
    return out


def _service_from(text: str) -> str:
    m = re.search(r"Service:\s*([A-Za-z0-9._-]+)", text)
    return m.group(1) if m else "app"


def _plan(service: str, description: str) -> dict:
    d = description.lower()
    if any(w in d for w in ("latency", "slow", "timeout", "spike")):
        fix = (f"Scale up {service} and confirm latency recovery", "scale")
    elif any(w in d for w in ("crash", "oom", "restart", "5xx", "500")):
        fix = (f"Restart {service} and verify recovery", "restart")
    else:
        fix = (f"Apply standard remediation to {service}", "restart")
    return {
        "subtasks": [
            {"id": "t1", "kind": "diagnose", "title": f"Diagnose {service} incident", "service": service},
            {"id": "t2", "kind": "remediate", "title": fix[0], "service": service},
        ]
    }


class MockLlm(BaseLlm):
    """Deterministic stand-in for Gemini. Routes on a token in the agent
    instruction (PLANNER / DIAGNOSER / REMEDIATOR); drives ADK tool calling
    by emitting function_call parts, then a final text response."""

    agent_name: str

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["mock"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False):
        sys_text = _system_text(llm_request)
        user_text = _user_text(llm_request)
        done = _responded_tools(llm_request)
        service = _service_from(user_text)

        def _text(t: str):
            return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=t)]))

        def _call(name: str, args: dict):
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))],
                )
            )

        if "PLANNER" in sys_text:
            yield _text(json.dumps(_plan(service, user_text.splitlines()[0])))
        elif "DIAGNOSER" in sys_text:
            if "query_logs" not in done:
                yield _call("query_logs", {"service": service, "minutes": 15})
            elif "check_metrics" not in done:
                yield _call("check_metrics", {"service": service})
            else:
                yield _text(f"Diagnosis complete for {service}: logs show repeated errors "
                            f"and metrics confirm the regression. Findings recorded.")
        elif "REMEDIATOR" in sys_text:
            if "restart_service" not in done and "scale_service" not in done:
                if "scale" in user_text:
                    yield _call("scale_service", {"service": service, "replicas": 4})
                else:
                    yield _call("restart_service", {"service": service})
            else:
                yield _text(f"Remediation applied to {service} using recorded findings; "
                            f"health checks pass.")
        else:
            yield _text("ok")
