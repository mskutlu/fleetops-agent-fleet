# CinemaOps deploy image — one self-contained container:
#   ClickHouse (stock official image, its own entrypoint handles user setup)
# + the Python app (venv with `pip install .` deps), seeded at boot.
#
# Base = clickhouse/clickhouse-server (Ubuntu 22.04) because it ships a working
# server binary + config layout; python:3.11-slim's Ubuntu would also work but
# needs the CH binary added, and 22.04 apt has no py3.11 — hence deadsnakes.

FROM clickhouse/clickhouse-server:latest

ENV PATH=/opt/venv/bin:$PATH \
    CLICKHOUSE_USER=default \
    CLICKHOUSE_PASSWORD=cinema \
    CH_HOST=127.0.0.1 \
    CH_HTTP_PORT=8123 \
    CH_SECURE=false \
    PORT=8080

RUN apt-get update \
 && apt-get install -y --no-install-recommends software-properties-common ca-certificates gnupg \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update \
 && apt-get install -y --no-install-recommends python3.11 python3.11-venv \
 && rm -rf /var/lib/apt/lists/* \
 && python3.11 -m venv /opt/venv

WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
# Run from source (same as local `make cinema-run`): the wheel packages only
# `fleetops`; both packages are importable from /app.
COPY fleetops ./fleetops
COPY cinema ./cinema
COPY deploy-cinema.sh /deploy-cinema.sh
RUN chmod +x /deploy-cinema.sh

ENTRYPOINT ["/deploy-cinema.sh"]
