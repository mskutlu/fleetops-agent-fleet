#!/bin/bash
# CinemaOps container entrypoint: start ClickHouse (official image entrypoint —
# it handles dirs + default-user password from CLICKHOUSE_PASSWORD), wait for
# the HTTP port, bind the API immediately (Cloud Run start-gate is on :8080),
# then seed the deterministic demo dataset (idempotent drop+recreate).

set -eo pipefail

export CLICKHOUSE_USER="${CLICKHOUSE_USER:-default}"
export CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:-cinema}"

bash /entrypoint.sh &
CH_PID=$!

ready=0
for _ in $(seq 1 240); do   # up to ~120s
    if wget -q --spider "http://127.0.0.1:8123/ping" 2>/dev/null; then ready=1; break; fi
    sleep 0.5
done
if [ "$ready" != "1" ]; then
    echo "ClickHouse did not become ready on :8123" >&2
    kill "$CH_PID" 2>/dev/null || true
    exit 1
fi
echo "ClickHouse ready: $(wget -qO- "http://127.0.0.1:8123/?password=${CLICKHOUSE_PASSWORD}&query=SELECT%20version()")"

# Bind the API first so Cloud Run's start-gate (port :8080) is satisfied while
# the dataset loads; a request racing the seed just gets an empty result set.
uvicorn cinema.service:create_app --factory --host 0.0.0.0 --port "${PORT:-8080}" &
UV_PID=$!
trap 'kill $UV_PID 2>/dev/null' INT TERM

# Seed the studio dataset (same code path as `make cinema-demo` step [2]).
if ! python - <<'EOF'
from cinema import dataset
print("seeded:", dataset.load(base_url="http://127.0.0.1:8123", password="cinema"))
EOF
then
    echo "dataset seed failed" >&2
    kill "$UV_PID" 2>/dev/null || true
    exit 1
fi

# ponytail: ephemeral CH state on Cloud Run — re-seeded at every cold start; a
# mounted disk or ClickHouse Cloud (CH_* env) is the upgrade if it ever matters.
wait "$UV_PID"
