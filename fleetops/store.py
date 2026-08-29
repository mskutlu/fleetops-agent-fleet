"""Firestore contracts + local in-memory fake with the same read/write API.

Doc shapes (collections):
    agents   -> AgentCard   {name, role, description, model, tools, skills}
    sessions -> SessionDoc  {incident_id, status, description, service,
                             plan, findings, actions, created_at, updated_at}
    traces   -> TraceSpan   {id, incident_id, agent, step, detail, ts}
    memory   -> dict        {service: {findings: [...], updated_at}} (memory bank)

Contract (identical to `google.cloud.firestore`):
    db.collection(name)              -> CollectionReference
    collection.document(id=None)     -> DocumentReference
    doc.get()                        -> DocumentSnapshot (.exists, .to_dict())
    doc.set(data) / doc.delete()
    collection.add(data)             -> DocumentReference
    collection.stream()              -> iterator of DocumentSnapshot

GCP swap for Stage 3 (no code change elsewhere):
    from google.cloud import firestore
    db = firestore.Client()
"""

from __future__ import annotations

import itertools
import threading
import uuid
from dataclasses import asdict, dataclass, field


@dataclass
class AgentCard:
    name: str
    role: str
    description: str
    model: str
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)


@dataclass
class SessionDoc:
    incident_id: str
    status: str  # accepted | planning | executing | resolved
    description: str
    service: str
    plan: list[dict] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


@dataclass
class TraceSpan:
    id: str
    incident_id: str
    agent: str  # system | planner | diagnoser | remediator
    step: str  # incident_accepted | planner_plan | memory_read | tool_call | ...
    detail: dict
    ts: str

    def to_doc(self) -> dict:
        return asdict(self)


class DocumentSnapshot:
    def __init__(self, id: str, data: dict | None):
        self.id = id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return self._data


class DocumentReference:
    def __init__(self, collection: "CollectionReference", id: str):
        self.id = id
        self._collection = collection

    def get(self) -> DocumentSnapshot:
        return DocumentSnapshot(self.id, self._collection._store.get(self.id))

    def set(self, data: dict) -> None:
        self._collection._store[self.id] = dict(data)

    def delete(self) -> None:
        self._collection._store.pop(self.id, None)


class CollectionReference:
    def __init__(self, store: dict):
        self._store = store
        self._ids = itertools.count(1)

    def document(self, id: str | None = None) -> DocumentReference:
        if id is None:
            # ponytail: uuid auto-id mirrors Firestore's random doc ids; a
            # monotonic counter per store would do if collisions ever matter
            id = uuid.uuid4().hex[:12]
        return DocumentReference(self, id)

    def add(self, data: dict) -> DocumentReference:
        ref = self.document()
        ref.set(data)
        return ref

    def stream(self) -> list[DocumentSnapshot]:
        return [DocumentSnapshot(k, v) for k, v in list(self._store.items())]


class InMemoryFirestore:
    """Thread-safe single-document-per-id fake."""

    def __init__(self):
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def collection(self, name: str) -> CollectionReference:
        with self._lock:
            self._data.setdefault(name, {})
            return CollectionReference(self._data[name])
