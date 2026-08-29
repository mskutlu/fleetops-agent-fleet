"""Async job events — in-memory fake with the GCP Pub/Sub contract.

Contract (identical to `google.cloud.pubsub_v1`):
    client.topic(name)                      -> Topic
    topic.publish(data: dict, **attrs)      -> message_id: str
    topic.subscribe(callback(msg: dict))    -> subscription_id: str

GCP swap for Stage 3 (no code change elsewhere):
    from google.cloud import pubsub_v1
    publisher = pubsub_v1.PublisherClient()
    future = publisher.publish(topic_path, json.dumps(data).encode(), **attrs)
"""

from __future__ import annotations

import itertools
import threading


class Topic:
    def __init__(self, name: str):
        self.name = name
        self._callbacks: list = []
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        # Durability hook for demos/tests: every published message, in order.
        self.log: list[dict] = []

    def publish(self, data: dict, **attributes: str) -> str:
        msg_id = f"{self.name}-{next(self._ids)}"
        message = {"message_id": msg_id, "data": data, "attributes": attributes}
        with self._lock:
            self.log.append(message)
            callbacks = list(self._callbacks)
        for cb in callbacks:
            cb(message)
        return msg_id

    def subscribe(self, callback) -> str:
        with self._lock:
            self._callbacks.append(callback)
        return f"{self.name}-sub-{len(self._callbacks)}"


class InMemoryPubSub:
    def __init__(self):
        self._topics: dict[str, Topic] = {}

    def topic(self, name: str) -> Topic:
        if name not in self._topics:
            self._topics[name] = Topic(name)
        return self._topics[name]
