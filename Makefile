# NO_SERVE=1 make demo -> run the checks and exit (CI); default ends by serving
# the observability dashboard at http://127.0.0.1:8080/trace/<incident>

.PHONY: demo run

demo:
	uv sync
	NO_SERVE=$(NO_SERVE) uv run python -u -m fleetops.demo

run:
	uv sync
	uv run uvicorn fleetops.service:create_app --factory --port 8080

# ---------------------------------------------------------------- CinemaOps —
# Devpost "Agentic Cinema" entry (ClickHouse track). NO_SERVE=1 make cinema-demo
# runs the checks and exits; default ends by serving on http://127.0.0.1:8090.

cinema-up: ## local self-hosted ClickHouse cluster (docker, idempotent)
	docker rm -f cinema-ch 2>/dev/null || true
	docker run -d --rm --name cinema-ch \
		-p 127.0.0.1:8123:8123 -p 127.0.0.1:9000:9000 \
		-v cinema_ch_data:/var/lib/clickhouse \
		-e CLICKHOUSE_USER=default -e CLICKHOUSE_PASSWORD=cinema \
		clickhouse/clickhouse-server:latest -- --listen_host=0.0.0.0

cinema-down: ## stop the local ClickHouse cluster
	docker rm -f cinema-ch 2>/dev/null || true

cinema-demo: ## CinemaOps checks (MCP round-trip, dataset, NL->SQL, digest, recall)
	uv sync
	NO_SERVE=$(NO_SERVE) uv run python -u -m cinema.demo

cinema-run: ## serve the CinemaOps API on :8090 (needs `make cinema-up` first)
	uv sync
	uv run uvicorn cinema.service:create_app --factory --port 8090

.PHONY: cinema-up cinema-down cinema-demo cinema-run
