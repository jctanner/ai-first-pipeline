#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
kubectl apply -f "${PROJECT_ROOT}/deploy/k8s/26-fullsend-dashboard.yaml"
kubectl rollout restart deployment/fullsend-dashboard -n ai-pipeline
kubectl rollout status deployment/fullsend-dashboard -n ai-pipeline --timeout=180s
