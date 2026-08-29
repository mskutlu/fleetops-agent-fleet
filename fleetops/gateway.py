"""Stage 2b — agent identity, gateway routing/policy, Model Armor guardrails.

**Identity (zero-trust).** Every caller — external or agent-to-agent — carries
a principal token (`Authorization: Bearer <token>` on HTTP; token argument on
internal hops). Principals live in the Firestore `principals` collection:
token -> {name, role, scopes}. Tokens are synthetic demo credentials; nothing
real ever appears in code or traces (spans log a masked prefix only).

**Gateway.** `Gateway.check()` is the single entrypoint: authenticate the
principal, enforce the scope policy (planner may `dispatch`, specialists may
`execute` but not `publish`), resolve the requested capability to a
registered+approved agent, and record the route+decision as a trace span for
EVERY hop — `gateway_route` (allow) or `gateway_rejected` (deny, with reason).
Denials that happen before an incident exists are traced under incident_id
"-".

**Model Armor (inline guardrails).** Deterministic, cheap pre-tool-call check
on tool arguments: prompt-injection markers, PII patterns (canary email),
credential shapes. A violating call never reaches the tool — the wrapper
traces `guardrail_blocked` with reasons and returns a structured blocked
result instead. `make demo` includes one live block.
"""

from __future__ import annotations

import functools
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass, field

from .registry import Registry
from .store import AgentCard

# Incident a tool call belongs to (set by the runner around agent execution;
# "-" for calls outside any incident, e.g. direct guard invocations).
INCIDENT_ID: ContextVar[str] = ContextVar("incident_id", default="-")

# Synthetic demo credentials (never real). name -> (token, role, scopes).
_SEED_PRINCIPALS: dict[str, tuple[str, str, list[str]]] = {
    # service orchestrator calls incidents in -> planner scope
    "svc-orchestrator": ("tok-orchestrator-a1b2", "planner", ["dispatch", "publish"]),
    # specialists execute subtasks — deliberately NOT allowed to publish
    "svc-diagnoser": ("tok-diagnoser-c3d4", "specialist", ["execute"]),
    "svc-remediator": ("tok-remediator-e5f6", "specialist", ["execute"]),
}

# agent name -> principal that carries its hops (agent-to-agent identity)
PRINCIPAL_FOR_AGENT = {
    "planner": "svc-orchestrator",
    "diagnoser": "svc-diagnoser",
    "remediator": "svc-remediator",
}

DEFAULT_TOKEN = _SEED_PRINCIPALS["svc-orchestrator"][0]  # internal fallback


class PolicyViolation(Exception):
    """Gateway denial. `status` maps 1:1 to an HTTP status code."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass
class Principal:
    name: str
    role: str
    scopes: list[str] = field(default_factory=list)
    token: str = ""

    @property
    def masked_token(self) -> str:
        return self.token[:12] + "…" if self.token else ""


# (pattern, reason) — deterministic + cheap; a Gemini-based classifier can sit
# behind this later, but the inline layer must stay regex-fast. ponytail:
# single ordered rule list, no per-rule config — add config only if ops needs it.
_ARMOR_RULES: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+|any\s+|previous\s+|prior\s+|above\s+)?instructions", "prompt-injection: instruction override"),
    (r"disregard\s+(all\s+|any\s+|previous\s+|prior\s+)?(instructions|rules|guardrails)", "prompt-injection: instruction override"),
    (r"system\s*prompt", "prompt-injection: system-prompt probing"),
    (r"exfiltrat", "prompt-injection: data exfiltration"),
    (r"tool\s*poison", "tool-poisoning marker"),
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "pii: email address"),
    (r"\b(?:\d[ -]?){13,16}\b", "pii: card-like number"),
    (r"AKIA[0-9A-Z]{16}", "credential: cloud access key"),
    (r"BEGIN [A-Z ]*PRIVATE KEY", "credential: private key"),
]
_ARMOR_COMPILED = [(re.compile(p, re.IGNORECASE), why) for p, why in _ARMOR_RULES]


class Armor:
    """Inline guardrails: pre-tool-call inspection of tool arguments."""

    @staticmethod
    def inspect(payload: object) -> list[str]:
        """Reasons the payload may not reach a tool (empty = allow)."""
        blob = payload if isinstance(payload, str) else json.dumps(payload, default=str)
        return [why for rx, why in _ARMOR_COMPILED if rx.search(blob)]


class Gateway:
    """Authenticates principals, enforces policy, routes by capability,
    traces every decision. Also owns the Armor tool guard."""

    def __init__(self, db, trace_fn):
        self._registry = Registry(db)
        self._principals = db.collection("principals")
        self._trace = trace_fn
        self.armor = Armor()
        self.guarded_tools: dict[str, object] = {}  # name -> wrapped fn (demo access)
        for name, (token, role, scopes) in _SEED_PRINCIPALS.items():
            if self._principals.document(token).get().to_dict() is None:
                self._principals.document(token).set(
                    {"name": name, "role": role, "scopes": scopes, "token": token}
                )

    # -- identity -----------------------------------------------------------

    def _by_token(self, token: str) -> Principal | None:
        doc = self._principals.document(token).get().to_dict()
        if doc is None:
            return None
        return Principal(name=doc["name"], role=doc["role"], scopes=doc["scopes"], token=token)

    @staticmethod
    def _token_from_header(authorization: str) -> str:
        if authorization.startswith("Bearer "):
            return authorization[len("Bearer "):].strip()
        return authorization.strip()

    # -- the single entrypoint ----------------------------------------------

    def check(
        self,
        token_or_header: str,
        action: str,
        capability: str | None,
        incident_id: str,
    ) -> Principal | AgentCard:
        """Authenticate + authorize (+ resolve capability when given).

        Returns the Principal (capability=None) or the approved AgentCard
        serving the capability. Denials raise PolicyViolation AFTER the
        decision is traced."""
        token = self._token_from_header(token_or_header)
        principal = self._by_token(token)
        if principal is None:
            return self._deny(incident_id, token, action, capability,
                              PolicyViolation(401, f"unknown principal token {token[:12] + '…' if token else '(missing)'}"))
        if action not in principal.scopes:
            return self._deny(incident_id, token, action, capability,
                              PolicyViolation(
                                  403,
                                  f"principal '{principal.name}' ({principal.role}) may not {action} "
                                  f"(scopes: {', '.join(principal.scopes)})"))
        if capability is None:
            return principal
        card = self._registry.resolve(capability)
        if card is None:
            names = self._registry.candidates_for(capability)
            reason = f"no registered+approved agent serves capability '{capability}'"
            if names:
                reason += f" (registered but unapproved: {', '.join(names)})"
            return self._deny(incident_id, token, action, capability, PolicyViolation(404, reason))
        self._trace(incident_id, "gateway", "gateway_route", {
            "decision": "allow", "principal": principal.name, "role": principal.role,
            "action": action, "capability": capability, "target": card.name,
            "token": principal.masked_token,
        })
        return card

    def _deny(self, incident_id: str, token: str, action: str, capability: str | None,
              violation: PolicyViolation):
        self._trace(incident_id, "gateway", "gateway_rejected", {
            "decision": "deny", "action": action, "capability": capability,
            "reason": violation.reason, "token": (token[:12] + "…") if token else "",
        })
        raise violation

    # -- Model Armor tool guard ----------------------------------------------

    def guard(self, caller: str, fn):
        """Wrap an agent tool with the pre-call Armor check."""

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            reasons = self.armor.inspect({"args": args, "kwargs": kwargs})
            if reasons:
                self._trace(INCIDENT_ID.get(), caller, "guardrail_blocked", {
                    "tool": fn.__name__, "principal": caller,
                    "args": {k: (v if isinstance(v, (int, float)) else str(v))[:200] for k, v in kwargs.items()},
                    "reasons": reasons,
                })
                return {"status": "blocked", "tool": fn.__name__, "reasons": reasons}
            return fn(*args, **kwargs)

        self.guarded_tools[fn.__name__] = wrapper
        return wrapper
