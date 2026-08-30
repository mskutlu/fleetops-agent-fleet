"""Synthetic streaming-studio dataset for CinemaOps (all values fictional,
no real user PII). Deterministic (seeded) so `make cinema-demo` is reproducible.

Schema (database `studio`):
    shows(show_id, title, genre, season)
    viewership(ts DateTime UTC, show_id, country LowCardinality(String),
               starts UInt32, completions UInt32)        -- hourly aggregates
    ops_events(event_ts, severity Enum8(info|warn|crit), component, message)

Planted signals (what the demo questions target):
    DROP   sable-peak US, ANCHOR-1 day 17:00-24:00 UTC (full prime-time evening)
           -> daily starts deviate roughly -35% vs baseline
           -> ops_events crit "cdn-us-east" edge-pool drain in that window
    SPIKE  neon-harbor UK, ANCHOR-3 day 18:00-24:00      starts ~x4.5 (S2 premiere push)

Load path is plain ClickHouse HTTP (JSONEachRow) — this is ETL/setup, NOT the
agent's query path: every agent SQL goes through mcp-clickhouse MCP."""

from __future__ import annotations

import json
import random
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

ANCHOR = datetime(2026, 8, 25)          # "now" for the demo narrative (UTC)
DAYS = 14                               # ANCHOR-13 .. ANCHOR inclusive

SHOWS = [
    ("sable-peak",   "Sable Peak",     "thriller",     2),
    ("neon-harbor",  "Neon Harbor",    "sci-fi",       2),
    ("kingdom-of-ash","Kingdom of Ash","fantasy",      4),
    ("casbah-crime", "Casbah Crime",   "crime",        3),
    ("static-love",  "Static Love",    "romance",      1),
    ("orbit-diet",   "Orbit Diet",     "documentary",  1),
]

COUNTRY_SHARE = {"US": 0.52, "UK": 0.28, "DE": 0.20}
COMPLETION_RATE = {s[0]: r for s, r in zip(SHOWS, (0.71, 0.64, 0.69, 0.58, 0.61, 0.74))}

# Prime-time shape: deep at 04-08h, peak 20-22h (UTC studio feed).
HOUR_CURVE = [0.38, 0.34, 0.31, 0.30, 0.33, 0.45, 0.62, 0.85, 0.95, 0.90,
              0.88, 0.92, 0.98, 1.00, 0.97, 0.93, 0.95, 1.05, 1.25, 1.55,
              1.80, 1.95, 1.60, 1.05]

# Base hourly starts (all countries combined) per show — popularity tiering.
BASE_HOURLY = {s[0]: b for s, b in zip(SHOWS, (5200, 3800, 4600, 2900, 1700, 1400))}


def generate(seed: int = 42) -> dict[str, list[dict]]:
    """(tables -> JSONEachRow-ready rows), deterministic for a given seed."""
    rng = random.Random(seed)
    viewership: list[dict] = []

    drop_show, drop_country = "sable-peak", "US"
    # full prime-time evening: an edge-pool drain that eats the whole US evening
    drop_window = (ANCHOR - timedelta(days=1)).replace(hour=17, minute=0), \
                  (ANCHOR - timedelta(days=1)).replace(hour=23, minute=59)
    spike_show, spike_country = "neon-harbor", "UK"
    spike_window = (ANCHOR - timedelta(days=3)).replace(hour=18, minute=0), \
                   (ANCHOR - timedelta(days=3)).replace(hour=23, minute=59)

    for day in range(DAYS):
        d = ANCHOR.date() - timedelta(days=DAYS - 1 - day)
        weekday_boost = 1.15 if d.weekday() >= 4 else 1.0   # Fri/Sat bump
        for show_id, _title, _genre, _season in SHOWS:
            base = BASE_HOURLY[show_id]
            for country, share in COUNTRY_SHARE.items():
                for hour in range(24):
                    ts = datetime(d.year, d.month, d.day, hour)
                    starts = base * share * HOUR_CURVE[hour] * weekday_boost * rng.uniform(0.92, 1.08)
                    if (show_id, country) == (drop_show, drop_country) and drop_window[0] <= ts <= drop_window[1]:
                        starts *= 0.28
                    if (show_id, country) == (spike_show, spike_country) and spike_window[0] <= ts <= spike_window[1]:
                        starts *= 4.5
                    s = max(1, int(starts))
                    c = max(0, int(s * COMPLETION_RATE[show_id] * rng.uniform(0.97, 1.03)))
                    viewership.append({
                        "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
                        "show_id": show_id, "country": country,
                        "starts": s, "completions": c,
                    })

    ops_events = [
        {"event_ts": (ANCHOR - timedelta(days=3)).replace(hour=16, minute=5).strftime("%Y-%m-%d %H:%M:%S"),
         "severity": "info", "component": "marketing-uk",
         "message": "Season 2 premiere push for Neon Harbor live in UK (paid social + partner placements)"},
        {"event_ts": (ANCHOR - timedelta(days=1)).replace(hour=16, minute=58).strftime("%Y-%m-%d %H:%M:%S"),
         "severity": "crit", "component": "cdn-us-east",
         "message": "Edge pool drained after autoscale misfire; playback error rate 12.4% on US stream origin"},
        {"event_ts": (ANCHOR - timedelta(days=1)).replace(hour=23, minute=55).strftime("%Y-%m-%d %H:%M:%S"),
         "severity": "info", "component": "cdn-us-east",
         "message": "Edge pool restored; playback error rate back under 0.3%"},
        {"event_ts": (ANCHOR - timedelta(days=5)).replace(hour=9, minute=20).strftime("%Y-%m-%d %H:%M:%S"),
         "severity": "warn", "component": "transcode-de",
         "message": "Bitrate drift on DE transcode lane for Casbah Crime; re-encoded"},
    ]

    shows = [{"show_id": s, "title": t, "genre": g, "season": n} for s, t, g, n in SHOWS]
    return {"shows": shows, "viewership": viewership, "ops_events": ops_events}


# Idempotent for demo/dev: drop then create so repeated runs give identical row
# counts. Note: CH 26.x requires explicit enum assignments ('name' = n).
DDL = [
    (None, "CREATE DATABASE IF NOT EXISTS studio"),
    ("studio", "DROP TABLE IF EXISTS studio.shows"),
    ("studio", "DROP TABLE IF EXISTS studio.viewership"),
    ("studio", "DROP TABLE IF EXISTS studio.ops_events"),
    ("studio", "CREATE TABLE IF NOT EXISTS studio.shows ("
              "show_id String, title String, genre String, season Int32) "
              "ENGINE = MergeTree ORDER BY show_id"),
    ("studio", "CREATE TABLE IF NOT EXISTS studio.viewership ("
              "ts DateTime, show_id String, country LowCardinality(String), "
              "starts UInt32, completions UInt32) "
              "ENGINE = MergeTree ORDER BY (show_id, country, ts)"),
    ("studio", "CREATE TABLE IF NOT EXISTS studio.ops_events ("
              "event_ts DateTime, severity Enum8('info' = 1, 'warn' = 2, 'crit' = 3), "
              "component String, message String) "
              "ENGINE = MergeTree ORDER BY event_ts"),
]


def _http(url: str, method: str = "GET", body: bytes | None = None) -> str:
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        detail = e.read()[:400].decode(errors="replace")
        raise RuntimeError(f"CH HTTP {e.code} for {method} {url.split('query=')[0]}…: {detail}") from None


def load(base_url: str = "http://127.0.0.1:8123", password: str = "", seed: int = 42) -> dict[str, int]:
    """(Re)create the `studio` schema and load a fresh deterministic dataset.

    Idempotent for demo/dev: drops + recreates tables so repeated runs give
    identical row counts (ponytail: dedup-by-insert is the prod upgrade)."""
    q = f"&password={urllib.request.quote(password)}" if password else ""

    def post(db: str | None, sql_or_data: bytes) -> str:
        # CH HTTP: GET implies readonly — DDL/INSERT go over POST with the SQL/
        # rows in the BODY (no URL-encoding surprises). Query text as body.
        url = base_url + "/?" + (f"database={db}&" if db else "") + q.lstrip("&")
        return _http(url, method="POST", body=sql_or_data)

    for db, stmt in DDL:
        post(db, stmt.encode())

    rows = generate(seed=seed)
    counts: dict[str, int] = {}
    for table in ("shows", "viewership", "ops_events"):
        data = b"\n".join(json.dumps(r).encode() for r in rows[table])
        body = f"INSERT INTO {table} FORMAT JSONEachRow\n".encode() + data + b"\n"
        post("studio", body)
        counts[table] = len(rows[table])

    # Verify through the same HTTP surface (agent path uses MCP — see mcp_client).
    for table in ("shows", "viewership", "ops_events"):
        url = base_url + "/?" + "database=studio" + q + "&query=" + urllib.request.quote(f"SELECT count() FROM {table}")
        got = int(_http(url).strip())
        assert got == counts[table], f"{table}: expected {counts[table]} rows, ClickHouse has {got}"
    return counts
