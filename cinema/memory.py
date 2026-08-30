"""Memory bank — cross-session findings, JSON-file backed (same read/write
contract shape as fleetops' Firestore-backed bank; here the file IS the store).

Keyed by topic (the show id): specialists recall prior findings BEFORE acting
and write a summary back AFTER. A restarted service or a brand-new session sees
them — that's the cross-session recall beat in `make cinema-demo`."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

MAX_ENTRIES = 8  # ponytail: bounded ring per topic; paginate if it ever matters


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MemoryBank:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("CINEMA_MEMORY_FILE", ".cinema_memory.json")
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(data, f, indent=1)

    def read(self, topic: str) -> list[dict]:
        """Prior findings for a topic (show id), oldest -> newest."""
        with self._lock:
            return list(self._load().get(topic, []))

    def write(self, topic: str, text: str) -> dict:
        """Append one finding; keeps the last MAX_ENTRIES per topic."""
        entry = {"ts": _now(), "text": text}
        with self._lock:
            data = self._load()
            data[topic] = (data.get(topic, [])[-(MAX_ENTRIES - 1):]) + [entry]
            self._save(data)
        return entry
