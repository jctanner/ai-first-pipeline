#!/bin/bash
# Complete deployment automation script
# Run this after "vagrant up" and "vagrant ssh"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo "AI-First Pipeline K3s Deployment"
echo "=========================================="
echo ""

# Check if running as root (needed for some commands)
if [ "$EUID" -ne 0 ]; then
  echo "This script should be run as root (use sudo)"
  exit 1
fi

# Check if .env exists
if [ ! -f /vagrant/.env ]; then
  echo "ERROR: /vagrant/.env file not found"
  echo "Please create it with required credentials before running this script"
  echo ""
  echo "Required variables:"
  echo "  CLAUDE_CODE_USE_VERTEX=1"
  echo "  CLOUD_ML_REGION=us-east5"
  echo "  ANTHROPIC_VERTEX_PROJECT_ID=your-project-id"
  echo "  JIRA_SERVER=https://issues.redhat.com"
  echo "  JIRA_USER=your-email"
  echo "  JIRA_TOKEN=your-token"
  exit 1
fi

# Step 1: Install K3s
echo "Step 1/15: Installing K3s..."
bash "${SCRIPT_DIR}/01-install-k3s.sh"
echo ""

# Step 2: Install cert-manager
echo "Step 2/15: Installing cert-manager..."
bash "${SCRIPT_DIR}/02-install-cert-manager.sh"
echo ""

# Step 3: Setup certificates
echo "Step 3/15: Setting up certificates..."
bash "${SCRIPT_DIR}/03-setup-certificates.sh"
echo ""

# Step 4: Extract CA cert
echo "Step 4/15: Extracting CA certificate..."
bash "${SCRIPT_DIR}/04-extract-ca-cert.sh"
echo ""

# Step 5: Create secrets
echo "Step 5/15: Creating Kubernetes secrets..."
bash "${SCRIPT_DIR}/06-create-secrets.sh"
echo ""

# Step 6: Build images
echo "Step 6/15: Building container images..."
bash "${SCRIPT_DIR}/05-build-images.sh"
echo ""

# Step 7: Deploy storage
echo "Step 7/15: Deploying storage..."
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml
kubectl apply -f /vagrant/deploy/k8s/14-pipeline-storage.yaml
echo ""

# Step 8: Deploy RBAC
echo "Step 8/15: Deploying RBAC..."
kubectl apply -f /vagrant/deploy/k8s/16-pipeline-rbac.yaml
echo ""

# Step 9: Deploy emulator ConfigMaps
echo "Step 9/15: Deploying emulator configurations..."
kubectl apply -f /vagrant/deploy/k8s/09-github-emulator-config.yaml
kubectl apply -f /vagrant/deploy/k8s/11-jira-emulator-config.yaml
echo ""

# Step 10: Deploy GitHub emulator
echo "Step 10/15: Deploying GitHub emulator..."
bash "${SCRIPT_DIR}/07-deploy-github-emulator.sh"
echo ""

# Step 11: Deploy Jira emulator
echo "Step 11/15: Deploying Jira emulator..."
bash "${SCRIPT_DIR}/08-deploy-jira-emulator.sh"
echo ""

# Step 12: Deploy pipeline dashboard
echo "Step 12/15: Deploying pipeline dashboard..."
kubectl apply -f /vagrant/deploy/k8s/20-pipeline-dashboard.yaml
echo ""

# Step 13: Deploy MLflow
echo "Step 13/15: Deploying MLflow..."
bash "${SCRIPT_DIR}/10-deploy-mlflow.sh"
echo ""

# Step 14: Deploy ingress proxy
echo "Step 14/15: Deploying ingress proxy (Go reverse proxy)..."
bash "${SCRIPT_DIR}/09-deploy-ingress-proxy.sh"
echo ""

# Step 15: Wait for all deployments
echo "Step 15/15: Waiting for all deployments to be ready..."
kubectl wait --for=condition=Available --timeout=300s \
  deployment/pipeline-dashboard -n ai-pipeline || true
kubectl wait --for=condition=Available --timeout=300s \
  deployment/github-emulator -n ai-pipeline || true
kubectl wait --for=condition=Available --timeout=300s \
  deployment/jira-emulator -n ai-pipeline || true
kubectl wait --for=condition=Available --timeout=300s \
  deployment/mlflow -n ai-pipeline || true
kubectl wait --for=condition=Available --timeout=300s \
  deployment/ingress-proxy -n ai-pipeline || true
echo ""

# Run validations
echo "=========================================="
echo "Running validations..."
echo "=========================================="
echo ""

cd /vagrant/deploy/validation
bash test-cluster.sh
echo ""
bash test-certificates.sh
echo ""
bash test-application.sh
echo ""

# Display access information
echo "=========================================="
echo "Deployment Complete!"
echo "=========================================="
echo ""
echo "Access Information:"
echo ""

# Get LoadBalancer IP for ingress proxy
INGRESS_IP=$(kubectl get svc ingress-proxy -n ai-pipeline -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")

echo "All services are accessible via Ingress Proxy:"
echo "  LoadBalancer IP: ${INGRESS_IP}"
echo ""

echo "Pipeline Dashboard:"
echo "  - http://${INGRESS_IP} -H 'Host: dashboard.local'"
echo "  - http://localhost:5000 (Vagrantfile port forward)"
echo ""

echo "GitHub Emulator:"
echo "  - http://${INGRESS_IP} -H 'Host: github.local'"
echo "  - https://${INGRESS_IP} -H 'Host: github.local' (TLS)"
echo ""

echo "Jira Emulator:"
echo "  - http://${INGRESS_IP} -H 'Host: jira.local'"
echo "  - https://${INGRESS_IP} -H 'Host: jira.local' (TLS)"
echo "  - Default credentials: admin / admin"
echo ""

echo "MLflow Tracking Server:"
echo "  - http://${INGRESS_IP} -H 'Host: mlflow.local'"
echo "  - https://${INGRESS_IP} -H 'Host: mlflow.local' (TLS)"
echo ""

echo "Internal Service URLs (from pods):"
echo "  - GitHub:    https://github-emulator.ai-pipeline.svc.cluster.local:443"
echo "  - Jira:      https://jira-emulator.ai-pipeline.svc.cluster.local:443"
echo "  - Dashboard: http://pipeline-dashboard.ai-pipeline.svc.cluster.local:5000"
echo "  - MLflow:    http://mlflow.ai-pipeline.svc.cluster.local:5000"
echo ""

echo "Cluster Status:"
kubectl get all -n ai-pipeline
echo ""

echo "=========================================="
echo "Next Steps:"
echo "=========================================="
echo ""
echo "1. Access the dashboard: http://localhost:5000"
echo "2. Run pipeline phases:"
echo "   kubectl exec -it deployment/pipeline-dashboard -n ai-pipeline -- bash"
echo "   uv run python main.py bug-fetch --limit 10"
echo ""
echo "3. View logs:"
echo "   kubectl logs -f deployment/pipeline-dashboard -n ai-pipeline"
echo ""
echo "4. Run a Job:"
echo "   kubectl create -f /vagrant/deploy/k8s/30-pipeline-job-template.yaml"
echo ""
echo "See /vagrant/deploy/README.md for more information"
echo "=========================================="
