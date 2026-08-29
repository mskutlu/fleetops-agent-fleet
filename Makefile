# NO_SERVE=1 make demo -> run the checks and exit (CI); default ends by serving
# the observability dashboard at http://127.0.0.1:8080/trace/<incident>
.PHONY: demo run

demo:
	uv sync
	NO_SERVE=$(NO_SERVE) uv run python -u -m fleetops.demo

run:
	uv sync
	uv run uvicorn fleetops.service:create_app --factory --port 8080
