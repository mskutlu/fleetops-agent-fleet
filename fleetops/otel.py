"""Stage 2c — OpenTelemetry-compliant trace emission + Firestore persistence.

Every agent hop (planner decision, gateway route+policy, tool call incl.
blocked guardrail events, memory read/write) is emitted as an OTel span via the
opentelemetry SDK trace API; `FleetOpsRunner.trace` is the single choke point,
so no call site changes shape. A `SpanExporter` persists each ended span as ONE
doc in the existing Firestore `traces` collection — same query surface as
GET /traces (now ordered by a monotonic per-incident `seq`), no new store.

Local: SimpleSpanProcessor exports synchronously on span end, so the doc is
present before `trace()` returns (deterministic for `make demo`).
GCP: spans flow through the SDK, so pointing OTLP at Cloud Trace is additive —
see README "OpenTelemetry -> Cloud Trace".

Deps added by Stage 2c: opentelemetry-api + opentelemetry-sdk only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from opentelemetry import trace as otel_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import StatusCode

TRACER_NAME = "fleetops"
SERVICE_NAME = "fleetops"
SERVICE_VERSION = "0.3.0"  # keep in sync with the FastAPI app version


def tracer() -> otel_trace.Tracer:
    """Per-call lookup so a provider configured after import is honored."""
    return otel_trace.get_tracer(TRACER_NAME)


class FirestoreSpanExporter(SpanExporter):
    """Ends each OTel span as one doc in the `traces` collection.

    Doc shape (additive over Stage 1a's TraceSpan — same query surface):
        {id, incident_id, agent, step, detail, ts, seq, status}
    `seq` is a monotonic emission order (deterministic top-to-bottom chain);
    `status` = "ok" | "error" (rejected/blocked hop; the reason stays in
    `detail` as before)."""

    def __init__(self, db):
        self._db = db

    def export(self, spans: list[ReadableSpan]) -> None:  # noqa: D102
        for span in spans:
            attrs = dict(span.attributes or {})
            try:
                detail = json.loads(attrs.pop("span.detail_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                detail = {}
            is_error = span.status.status_code == StatusCode.ERROR
            end_ns = span.end_time or 0
            self._db.collection("traces").add({
                "id": f"span-{format(span.context.span_id, '016x')}",
                "incident_id": attrs.get("incident_id", "-"),
                "agent": attrs.get("agent", "system"),
                "step": attrs.get("step") or span.name,
                "detail": detail,
                "ts": datetime.fromtimestamp(end_ns / 1e9, tz=timezone.utc).isoformat(),
                "seq": int(attrs.get("seq") or 0),
                "status": "error" if is_error else "ok",
                # active model id on every hop (mandatory-stack compliance,
                # visible in GET /traces JSON and the dashboard)
                "model": attrs.get("model"),
            })

    def shutdown(self) -> None:  # synchronous export; nothing to flush
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # ditto
        return True


_provider: TracerProvider | None = None


def configure(db) -> TracerProvider:
    """Idempotent global tracer provider wired to the Firestore exporter."""
    global _provider
    if _provider is not None:
        return _provider
    resource = Resource.create({
        "service.name": SERVICE_NAME,
        "service.version": SERVICE_VERSION,
    })
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(SimpleSpanProcessor(FirestoreSpanExporter(db)))
    otel_trace.set_tracer_provider(provider)
    _provider = provider
    return provider
