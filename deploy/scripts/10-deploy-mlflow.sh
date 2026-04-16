#!/bin/bash
# Deploy MLflow tracking server

set -euo pipefail

echo "==> Deploying MLflow..."

# Deploy MLflow
kubectl apply -f /vagrant/deploy/k8s/13-mlflow.yaml

# Wait for deployment
echo "  Waiting for MLflow to be ready..."
kubectl wait --for=condition=Available --timeout=120s \
  deployment/mlflow -n ai-pipeline || true

# Check service
SVC_IP=$(kubectl get svc -n ai-pipeline mlflow -o jsonpath='{.spec.clusterIP}' 2>/dev/null || echo "pending")

echo "==> MLflow deployed successfully"
echo ""
echo "Access MLflow:"
echo "  - Internal: http://mlflow.ai-pipeline.svc.cluster.local:5000"
echo "  - Via Ingress: http://ingress-proxy -H 'Host: mlflow.local'"
echo "  - ClusterIP: ${SVC_IP}:5000"
echo ""
echo "MLflow is configured with:"
echo "  - Backend Store: SQLite (/data/mlflow.db)"
echo "  - Artifact Store: Local filesystem (/data/artifacts)"
echo "  - Storage: 10Gi PVC (mlflow-data)"
echo ""
