#!/bin/bash
# Extract CA certificate and create ConfigMap for client pods

set -euo pipefail

echo "==> Extracting CA certificate..."

# Wait a moment for the certificate Secret to be fully populated
sleep 5

# Extract the CA certificate from the issued certificate
CA_CERT=$(kubectl get secret github-emulator-tls \
  -n ai-pipeline \
  -o jsonpath='{.data.ca\.crt}' | base64 -d)

if [ -z "$CA_CERT" ]; then
  echo "ERROR: Could not extract CA certificate from Secret"
  exit 1
fi

# Create the ConfigMap with the CA certificate
kubectl create configmap internal-ca-cert \
  -n ai-pipeline \
  --from-literal=ca.crt="$CA_CERT" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> CA certificate extracted and stored in ConfigMap"
echo ""
kubectl get configmap internal-ca-cert -n ai-pipeline
echo ""
echo "==> Certificate infrastructure complete!"
echo "==> Next: Create secrets and deploy the application"
