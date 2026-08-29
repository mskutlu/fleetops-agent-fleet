"""Real GCP clients (Stage 3a) behind the same contracts as the local fakes.

`make_backends()` picks (db, pubsub) from `FLEETOPS_BACKEND`:
  - "memory" (default) -> the local fakes; `make demo` never touches GCP.
  - "gcp"              -> real Pub/Sub + Firestore. Requires
                          GOOGLE_CLOUD_PROJECT and Application Default
                          Credentials (on Cloud Run these come from the
                          service account automatically).

Deployment shape: single Cloud Run service runs the HTTP surface AND the
worker — the worker pulls from the `<topic>-worker` subscription via
`Topic.pop()` (pull mode), so no separate push endpoint is needed. Requires
`--no-cpu-throttling` so the background pull loop keeps its CPU between
requests. `google-cloud-*` imports stay inside the classes so the local
fakes never need the packages installed.
"""

from __future__ import annotations

import json
import os

TOPIC_ENV = "PUBSUB_TOPIC"  # deployed topic: fleetops-incidents


def make_backends():
    """(db, pubsub) for the current FLEETOPS_BACKEND — same interfaces as the fakes."""
    if os.environ.get("FLEETOPS_BACKEND", "memory") == "gcp":
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or _metadata_project()
        return GcpFirestore(project), GcpPubSub(project)
    from .events import InMemoryPubSub
    from .store import InMemoryFirestore

    return InMemoryFirestore(), InMemoryPubSub()


def _metadata_project() -> str:
    """Project id from the Cloud Run metadata server (fallback when the env
    var is unset). Raises a clear error locally, where there is no server."""
    import urllib.request

    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/project/project-id",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.read().decode()
    except OSError as e:
        raise RuntimeError(
            "FLEETOPS_BACKEND=gcp needs GOOGLE_CLOUD_PROJECT (or ADC from a "
            "GCP metadata server — running locally? export GOOGLE_CLOUD_PROJECT)"
        ) from e


class GcpPubSub:
    """Pub/Sub with the InMemoryPubSub contract. pop() acks — exactly the
    fake's at-least-once semantics: a crash between pull and handle leaves
    the message to redeliver; an acked message is consumed."""

    def __init__(self, project: str):
        from google.cloud import pubsub_v1

        self._project = project
        self._publisher = pubsub_v1.PublisherClient()
        self._subscriber = pubsub_v1.SubscriberClient()

    def topic(self, name: str) -> "GcpTopic":
        sub = os.environ.get("PUBSUB_SUBSCRIPTION", f"{name}-worker")
        return GcpTopic(self._publisher, self._subscriber, self._project, name, sub)


class GcpTopic:
    def __init__(self, publisher, subscriber, project: str, name: str, subscription: str):
        self.name = name
        self._publisher, self._subscriber = publisher, subscriber
        self._topic_path = publisher.topic_path(project, name)
        self._sub_path = subscriber.subscription_path(project, subscription)

    def publish(self, data: dict, **attributes: str) -> str:
        future = self._publisher.publish(
            self._topic_path,
            json.dumps(data).encode(),
            **{k: str(v) for k, v in attributes.items()},
        )
        return future.result(timeout=30)

    def pop(self, timeout: float | None = None) -> dict | None:
        """Pull one message and ack it. None when the queue is idle."""
        from google.api_core.exceptions import DeadlineExceeded

        try:
            resp = self._subscriber.pull(
                request={"subscription": self._sub_path, "max_messages": 1},
                timeout=timeout if timeout and timeout > 0 else 1.0,
            )
        except DeadlineExceeded:
            return None
        received = resp.received_messages[0]
        self._subscriber.acknowledge(
            request={"subscription": self._sub_path, "ack_ids": [received.ack_id]}
        )
        return {
            "message_id": received.message.message_id,
            "data": json.loads(received.message.data.decode()),
            "attributes": dict(received.message.attributes),
        }

    @property
    def pending_count(self) -> int:
        # ponytail: real Pub/Sub has no cheap backlog count; demo-only stat,
        # swap in a Cloud Monitoring query if the dashboard ever needs it.
        return -1

    def subscribe(self, callback) -> str:
        raise NotImplementedError("worker path uses pop(); push mode not deployed")


class GcpFirestore:
    """Firestore with the InMemoryFirestore contract. Document/collection
    objects pass through natively — only add()'s return shape is adapted
    (real client returns a (write_result, ref) tuple, the fake a bare ref)."""

    def __init__(self, project: str):
        from google.cloud import firestore

        self._db = firestore.Client(project=project)

    def collection(self, name: str):
        return _GcpCollection(self._db.collection(name))


class _GcpCollection:
    def __init__(self, coll):
        self._coll = coll

    def document(self, id: str | None = None):
        return self._coll.document(id) if id is not None else self._coll.document()

    def add(self, data: dict):
        return self._coll.add(data)[1]  # bare ref, like the fake

    def stream(self):
        return list(self._coll.stream())
