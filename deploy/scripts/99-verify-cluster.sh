#!/bin/bash
# Verify K3s cluster health

set -euo pipefail

echo "==> Verifying K3s cluster health..."
echo ""

echo "--- Nodes ---"
kubectl get nodes -o wide
echo ""

echo "--- System Pods ---"
kubectl get pods -A
echo ""

echo "--- cert-manager Status ---"
kubectl get pods -n cert-manager
echo ""

echo "--- Certificate Infrastructure ---"
kubectl get clusterissuer -A
kubectl get certificate -A
echo ""

echo "--- AI Pipeline Namespace ---"
kubectl get all -n ai-pipeline
echo ""

echo "==> Cluster verification complete!"
