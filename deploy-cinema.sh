#!/bin/bash
# CinemaOps container entrypoint: start ClickHouse (official image entrypoint —
# it handles dirs + default-user password from CLICKHOUSE_PASSWORD), wait for
# the HTTP port, seed the deterministic demo dataset (idempotent drop+recreate),
# then serve the API.

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
echo "ClickHouse ready: $(wget -qO- 'http://127.0.0.1:8123/?query=SELECT%20version()')"

# Seed the studio dataset (same code path as `make cinema-demo` step [2]).
python - <<'EOF'
from cinema import dataset
print("seeded:", dataset.load(base_url="http://127.0.0.1:8123", password="cinema"))
EOF

# ponytail: ephemeral CH state on Cloud Run — re-seeded at every cold start; a
# mounted disk or ClickHouse Cloud (CH_* env) is the upgrade if it ever matters.
exec uvicorn cinema.service:create_app --factory --host 0.0.0.0 --port "${PORT:-8080}"
