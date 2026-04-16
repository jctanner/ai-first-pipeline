#!/bin/bash
# Deploy the Go reverse proxy (ingress controller)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/../.."

echo "==> Deploying Go Reverse Proxy (Ingress Controller)..."

# Build the proxy image
cd "${PROJECT_ROOT}/deploy/golang-reverse-proxy"
echo "  Building Docker image..."
sudo docker build -t ingress-proxy:latest . -q

# Import to k3s
echo "  Importing image to k3s..."
sudo docker save ingress-proxy:latest | sudo k3s ctr images import - > /dev/null

# Deploy to cluster
echo "  Deploying to Kubernetes..."
kubectl apply -f deployment.yaml

# Wait for deployment
echo "  Waiting for ingress-proxy to be ready..."
kubectl wait --for=condition=Available --timeout=120s \
  deployment/ingress-proxy -n ai-pipeline || true

# Wait for certificate
echo "  Waiting for TLS certificate..."
for i in {1..30}; do
    STATUS=$(kubectl get certificate -n ai-pipeline ingress-proxy-tls -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "")
    if [ "$STATUS" = "True" ]; then
        echo "  ✓ Certificate ready"
        break
    fi
    sleep 2
done

# Get LoadBalancer IP
LB_IP=$(kubectl get svc -n ai-pipeline ingress-proxy -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

echo "==> Ingress proxy deployed successfully"
echo ""
echo "LoadBalancer IP: ${LB_IP}"
echo ""
echo "Access services via:"
echo "  - GitHub:    http://${LB_IP} -H 'Host: github.local'"
echo "  - Jira:      http://${LB_IP} -H 'Host: jira.local'"
echo "  - Dashboard: http://${LB_IP} -H 'Host: dashboard.local'"
echo "  - MLflow:    http://${LB_IP} -H 'Host: mlflow.local'"
echo ""
