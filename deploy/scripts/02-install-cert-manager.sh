#!/bin/bash
# Install cert-manager for certificate management

set -euo pipefail

CERT_MANAGER_VERSION="v1.14.4"

echo "==> Installing cert-manager ${CERT_MANAGER_VERSION}..."

# Install cert-manager CRDs and deployment
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.yaml

echo "==> Waiting for cert-manager to be ready..."
kubectl wait --for=condition=Available --timeout=300s \
  -n cert-manager deployment/cert-manager
kubectl wait --for=condition=Available --timeout=300s \
  -n cert-manager deployment/cert-manager-webhook
kubectl wait --for=condition=Available --timeout=300s \
  -n cert-manager deployment/cert-manager-cainjector

echo "==> cert-manager installation complete!"
echo ""
kubectl get pods -n cert-manager
echo ""
echo "==> Next: Apply certificate infrastructure from deploy/k8s/"
