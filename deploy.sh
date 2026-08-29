#!/usr/bin/env bash
# FleetOps Stage 3a — one-shot deploy to Cloud Run (Cloud Run + Pub/Sub + Firestore).
# Idempotent: safe to re-run; existing resources are reused.
#
# Prereqs:  gcloud auth login
#           export GOOGLE_CLOUD_PROJECT=<project-id>
# Optional: export GEMINI_API_KEY=<key>          (omit -> deterministic MockLlm)
#           export REGION=europe-west1           (default)
set -euo pipefail

: "${GOOGLE_CLOUD_PROJECT:?export GOOGLE_CLOUD_PROJECT=<project-id> first (gcloud auth login if needed)}"
REGION="${REGION:-europe-west1}"
SVC="fleetops"
TOPIC="fleetops-incidents"
SUB="${TOPIC}-worker"

echo "== APIs =="
gcloud services enable run.googleapis.com pubsub.googleapis.com firestore.googleapis.com cloudbuild.googleapis.com

echo "== Pub/Sub topic $TOPIC + pull subscription $SUB =="
gcloud pubsub topics create "$TOPIC" 2>/dev/null || echo "topic exists"
gcloud pubsub subscriptions create "$SUB" --topic="$TOPIC" --ack-deadline=600 2>/dev/null || echo "subscription exists"

echo "== Firestore (native, $REGION) =="
gcloud firestore databases create --location="$REGION" 2>/dev/null || echo "firestore database exists"

echo "== Env =="
ENVARS="FLEETOPS_BACKEND=gcp,GOOGLE_CLOUD_PROJECT=${GOOGLE_CLOUD_PROJECT},PUBSUB_TOPIC=${TOPIC},GEMINI_MODEL=${GEMINI_MODEL:-gemini-3-flash}"
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  ENVARS+=",GEMINI_API_KEY=${GEMINI_API_KEY}"   # demo path; move to Secret Manager for anything longer-lived
else
  echo "NOTE: GEMINI_API_KEY not set -> agents run on the deterministic MockLlm"
fi

echo "== Cloud Run deploy ($REGION, single service: HTTP + pull worker) =="
gcloud run deploy "$SVC" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --no-cpu-throttling \
  --max-instances 1 \
  --set-env-vars "$ENVARS"

URL="$(gcloud run services describe "$SVC" --region "$REGION" --format 'value(status.url)')"
echo
echo "LIVE URL: $URL"
echo "Smoke: curl -s $URL/healthz"
