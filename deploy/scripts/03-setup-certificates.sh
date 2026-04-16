#!/bin/bash
# Apply certificate infrastructure manifests

set -euo pipefail

echo "==> Setting up certificate infrastructure..."

# Apply manifests in order
kubectl apply -f /vagrant/deploy/k8s/00-namespace.yaml
kubectl apply -f /vagrant/deploy/k8s/01-ca-issuer.yaml

echo "==> Waiting for CA certificate to be ready..."
# Wait for the internal-ca certificate to be issued first
kubectl wait --for=condition=Ready --timeout=120s \
  -n ai-pipeline certificate/internal-ca

echo "==> Verifying CA secret exists..."
kubectl get secret internal-ca-secret -n ai-pipeline >/dev/null 2>&1 || {
  echo "ERROR: CA secret not created"
  exit 1
}

echo "==> Waiting for CA Issuer to be ready..."
sleep 5
kubectl wait --for=condition=Ready --timeout=60s \
  -n ai-pipeline issuer/internal-ca-issuer || {
  echo "WARNING: Issuer not ready yet, continuing anyway..."
}

# Apply service certificates
kubectl apply -f /vagrant/deploy/k8s/02-certificates.yaml

echo "==> Waiting for certificates to be issued..."
sleep 10
kubectl wait --for=condition=Ready --timeout=120s \
  -n ai-pipeline certificate/github-emulator-tls || true
kubectl wait --for=condition=Ready --timeout=120s \
  -n ai-pipeline certificate/pipeline-dashboard-tls || true

echo "==> Certificate infrastructure ready!"
echo ""
kubectl get certificate -n ai-pipeline
echo ""
echo "==> Next: Run 04-extract-ca-cert.sh to prepare client trust"
