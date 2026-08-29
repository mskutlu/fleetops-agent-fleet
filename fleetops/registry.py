"""Agent registry — publish / version / discover enterprise-approved agents.

Cards live in the Firestore `agents` collection (one doc per agent name; a
version bump is a republish under the same name). The planner may only
dispatch to registered+approved agents, and discovery resolves a capability
to an approved server so the gateway can reject unknowns with a clear reason:

    registry.resolve("incident.diagnose")   -> AgentCard | None
    registry.candidates_for(cap)            -> names that register the cap
                                              (any approval status) — used to
                                              build the rejection message
"""

from __future__ import annotations

from .store import AgentCard, InMemoryFirestore


class Registry:
    def __init__(self, db: InMemoryFirestore):
        self._agents = db.collection("agents")

    def publish(self, card: AgentCard) -> str:
        ref = self._agents.document(card.name)
        ref.set(card.__dict__)
        return ref.id

    def get(self, name: str) -> AgentCard | None:
        doc = self._agents.document(name).get().to_dict()
        return None if doc is None else AgentCard(**doc)

    def list_approved(self) -> list[AgentCard]:
        cards = [AgentCard(**s.to_dict()) for s in self._agents.stream()]
        return sorted(
            (c for c in cards if c.approval_status == "approved"), key=lambda c: c.name
        )

    def resolve(self, capability: str) -> AgentCard | None:
        """Approved agent serving `capability`, else None."""
        for card in self.list_approved():
            if capability in card.capabilities:
                return card
        return None

    def candidates_for(self, capability: str) -> list[str]:
        names: list[str] = []
        for s in self._agents.stream():
            d = s.to_dict() or {}
            if capability in (d.get("capabilities") or []) and d["name"] not in names:
                names.append(d["name"])
        return sorted(names)
