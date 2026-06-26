#!/bin/bash
# Deploy Observatory

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"

echo "==> Deploying Observatory..."

# Deploy Observatory
kubectl apply -f "${PROJECT_ROOT}/deploy/k8s/18-observatory.yaml"

# Wait for deployment
echo "  Waiting for Observatory to be ready..."
kubectl wait --for=condition=Available --timeout=120s \
  deployment/observatory -n ai-pipeline || true

# Check service
SVC_IP=$(kubectl get svc -n ai-pipeline observatory -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "pending")

echo "==> Observatory deployed successfully"
echo ""
echo "Access Observatory:"
echo "  - Internal: http://observatory.ai-pipeline.svc.cluster.local:8000"
echo "  - Via Ingress: https://observatory.local"
echo "  - ClusterIP: ${SVC_IP}:8000"
echo ""
echo "Observatory is configured with:"
echo "  - Database: SQLite (/data/observatory.db)"
echo "  - Storage: 2Gi PVC (observatory-data)"
echo ""

# Seed data sources
echo "==> Seeding Observatory data sources..."
OBS_API="http://observatory.ai-pipeline.svc.cluster.local:8000/api/v1/data-sources"

# Wait for the API to be reachable
for i in $(seq 1 10); do
  if kubectl exec -n ai-pipeline deployment/observatory -- curl -sf http://localhost:8000/healthz >/dev/null 2>&1; then
    break
  fi
  echo "  Waiting for Observatory API... ($i/10)"
  sleep 3
done

seed_source() {
  local name="$1" type="$2" endpoint="$3" desc="$4" config="${5:-}"
  local payload
  if [ -n "$config" ]; then
    payload="{\"name\":\"$name\",\"source_type\":\"$type\",\"endpoint\":\"$endpoint\",\"description\":\"$desc\",\"config\":$config}"
  else
    payload="{\"name\":\"$name\",\"source_type\":\"$type\",\"endpoint\":\"$endpoint\",\"description\":\"$desc\"}"
  fi
  kubectl exec -n ai-pipeline deployment/observatory -- \
    curl -sf -X POST http://localhost:8000/api/v1/data-sources \
    -H 'Content-Type: application/json' \
    -d "$payload" >/dev/null 2>&1 \
    && echo "  ✓ $name" || echo "  ⚠ $name (already exists or failed)"
}

seed_source "MLflow Tracking Server" "mlflow" \
  "http://mlflow.ai-pipeline.svc.cluster.local:5000" \
  "Experiment traces with token usage, cost, duration, and model metadata for pipeline agent runs"

seed_source "AI Pipeline Kubernetes" "kubernetes" \
  "" \
  "K8s cluster running pipeline agent jobs in the ai-pipeline namespace" \
  '{"namespace":"ai-pipeline"}'

seed_source "RHOAI Jira" "jira" \
  "https://jira-emulator.ai-pipeline.svc.cluster.local" \
  "Issue tracker for RHOAIENG bugs, RHAIRFE feature requests, and RHAISTRAT strategies" \
  '{"projects":["RHOAIENG","RHAIRFE","RHAISTRAT"]}'

seed_source "Pipeline Artifacts" "artifact_storage" \
  "/app/artifacts" \
  "Local filesystem storing claims, verification logs, explanations, strace output, and K8s job logs" \
  '{"subdirs":["claims","verification","explanations","strace","jobs","apibodies"]}'

seed_source "Architecture Context" "artifact_storage" \
  "/app/.context" \
  "Git-cloned architecture docs, component maps, and test recipes for RHOAI subsystems" \
  '{"readonly":true}'
