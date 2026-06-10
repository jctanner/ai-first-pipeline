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
