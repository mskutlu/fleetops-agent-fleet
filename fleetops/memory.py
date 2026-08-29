"""Memory bank — persistent cross-session context in the Firestore `memory`
collection, keyed by principal+topic (doc id = "principal:topic").

Specialists read prior context BEFORE acting and write a summary back AFTER;
on resolution the runner also records one consolidated fleet-level outcome so
the NEXT incident on the same service can recall it (cross-session recall —
shown in `make demo`). Entries live outside any process, so a restarted worker
or a brand-new session sees them."""

from __future__ import annotations

MAX_ENTRIES = 8  # ponytail: bounded ring per key; paginate if memory ever matters at scale


class MemoryBank:
    def __init__(self, db):
        self._mem = db.collection("memory")

    @staticmethod
    def _key(principal: str, topic: str) -> str:
        return f"{principal}:{topic}"

    def read(self, principal: str, topic: str) -> list[dict]:
        doc = self._mem.document(self._key(principal, topic)).get().to_dict() or {}
        return doc.get("entries") or []

    def write(self, principal: str, topic: str, text: str, ts: str) -> None:
        ref = self._mem.document(self._key(principal, topic))
        doc = ref.get().to_dict() or {"entries": []}
        entries = (doc.get("entries") or [])[-(MAX_ENTRIES - 1):] + [{"ts": ts, "text": text}]
        ref.set({"principal": principal, "topic": topic, "entries": entries, "updated_at": ts})
