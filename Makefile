.PHONY: demo run

demo:
	uv sync
	uv run python -m fleetops.demo

run:
	uv sync
	uv run uvicorn fleetops.service:create_app --factory --port 8080
