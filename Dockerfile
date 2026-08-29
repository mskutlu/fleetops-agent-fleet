FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml ./
COPY fleetops ./fleetops
RUN pip install --no-cache-dir ".[gcp]"

ENV PORT=8080
CMD exec uvicorn fleetops.service:create_app --factory --host 0.0.0.0 --port ${PORT}
