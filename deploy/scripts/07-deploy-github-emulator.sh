#!/bin/bash
# Deploy GitHub Emulator to k3s with cert-manager certificates

set -euo pipefail

echo "==> Deploying GitHub Emulator to k3s..."

# Ensure we're in the right directory
cd /vagrant/deploy/k8s

# Apply resources in order
echo "--- Creating namespace ---"
kubectl apply -f 00-namespace.yaml

echo "--- Setting up certificate infrastructure ---"
kubectl apply -f 01-ca-issuer.yaml

echo "--- Creating certificates ---"
kubectl apply -f 02-certificates.yaml

echo "--- Waiting for certificates to be ready ---"
kubectl wait --for=condition=ready certificate/github-emulator-tls -n ai-pipeline --timeout=120s || {
  echo "WARNING: Certificate not ready after 120s"
  echo "Check cert-manager status:"
  kubectl get certificate -n ai-pipeline
  kubectl describe certificate github-emulator-tls -n ai-pipeline
}

echo "--- Creating storage ---"
kubectl apply -f 03-storage.yaml

echo "--- Creating GitHub Emulator configuration ---"
kubectl apply -f 09-github-emulator-config.yaml

echo "--- Deploying GitHub Emulator ---"
kubectl apply -f 10-github-emulator.yaml

echo ""
echo "==> Deployment complete!"
echo ""
echo "Checking status:"
kubectl get pods -n ai-pipeline -l app=github-emulator
echo ""
echo "To watch the deployment:"
echo "  kubectl get pods -n ai-pipeline -w"
echo ""
echo "To view logs:"
echo "  kubectl logs -n ai-pipeline deployment/github-emulator -f"
echo ""
echo "To test the service:"
echo "  kubectl run -it --rm debug --image=alpine --restart=Never -- sh"
echo "  # then inside the pod:"
echo "  # apk add curl"
echo "  # curl -k https://github-emulator.ai-pipeline.svc.cluster.local"
