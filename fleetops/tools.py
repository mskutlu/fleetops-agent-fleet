"""Specialist tools — mutate a small in-memory fleet state and return evidence.
Every call is recorded as a trace span by the runner."""

from __future__ import annotations

FLEET: dict[str, dict] = {}


def query_logs(service: str, minutes: int = 15) -> dict:
    return {
        "service": service,
        "window_minutes": minutes,
        "errors": [
            f"{service} upstream timeout calling payments-db",
            f"{service} request queue depth above threshold",
        ],
    }


def check_metrics(service: str) -> dict:
    return {
        "service": service,
        "p99_latency_ms": 1840,
        "error_rate_pct": 4.2,
        "verdict": "regression confirmed",
    }


def restart_service(service: str) -> dict:
    state = FLEET.setdefault(service, {"replicas": 2, "restarts": 0, "healthy": False})
    state["restarts"] += 1
    state["healthy"] = True
    return {"service": service, "action": "restart", "state": state}


def scale_service(service: str, replicas: int) -> dict:
    state = FLEET.setdefault(service, {"replicas": 2, "restarts": 0, "healthy": False})
    state["replicas"] = replicas
    state["healthy"] = True
    return {"service": service, "action": "scale", "state": state}
