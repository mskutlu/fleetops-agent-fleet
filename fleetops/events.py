"""Async job events — in-memory fake with the GCP Pub/Sub contract.

Contract (identical to `google.cloud.pubsub_v1`):
    client.topic(name)                      -> Topic
    topic.publish(data: dict, **attrs)      -> message_id: str
    topic.subscribe(callback(msg: dict))    -> subscription_id: str   (push mode)

Worker path (pull mode — how Stage 2a executes work off the request path):
    topic.pop(timeout=None)                 -> msg | None             (dequeue = ack)
    topic.pending_count                     -> int                    (unacked backlog)

Semantics: publish is durable + asynchronous. Messages sit in the topic queue
until a worker pops (= acks) them — at-least-once delivery, exactly like GCP:
a crashed worker leaves unacked messages on the topic, and a restarted worker
resumes from there. That is what `make demo`'s kill-and-resume step exercises.

GCP swap for Stage 3 (no code change elsewhere):
    from google.cloud import pubsub_v1
    publisher = pubsub_v1.PublisherClient()
    future = publisher.publish(topic_path, json.dumps(data).encode(), **attrs)
"""

from __future__ import annotations

import itertools
import queue as _queue
import threading


class Topic:
    def __init__(self, name: str):
        self.name = name
        self._pending = _queue.Queue()  # unacked messages, FIFO (durable fake)
        self._callbacks: list = []      # push-mode subscribers (contract compat)
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        # Durability hook for demos/tests: every published message, in order.
        self.log: list[dict] = []

    def publish(self, data: dict, **attributes: str) -> str:
        msg_id = f"{self.name}-{next(self._ids)}"
        message = {"message_id": msg_id, "data": dict(data), "attributes": attributes}
        with self._lock:
            self.log.append(message)
            callbacks = list(self._callbacks)
        self._pending.put(message)  # worker path — acked by pop()
        for cb in callbacks:       # push-mode subscribers (contract compat)
            cb(message)
        return msg_id

    def subscribe(self, callback) -> str:
        with self._lock:
            self._callbacks.append(callback)
        return f"{self.name}-sub-{len(self._callbacks)}"

    def pop(self, timeout: float | None = None) -> dict | None:
        """Worker path: dequeue the next unacked message (ack). None when idle."""
        try:
            return self._pending.get(timeout=timeout)
        except _queue.Empty:
            return None

    @property
    def pending_count(self) -> int:
        """Unacked backlog — survives worker crashes until drained or redelivered."""
        return self._pending.qsize()


class InMemoryPubSub:
    def __init__(self):
        self._topics: dict[str, Topic] = {}

    def topic(self, name: str) -> Topic:
        if name not in self._topics:
            self._topics[name] = Topic(name)
        return self._topics[name]
