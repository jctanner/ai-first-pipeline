#!/bin/bash
# Create GCP credentials secret for Vertex AI access

set -euo pipefail

echo "==> Creating GCP credentials secret for Vertex AI..."
echo

# Check if running inside Vagrant VM or on host
if [ -f /vagrant/.env ]; then
  # Running inside VM - check if credentials file is accessible
  CREDS_SOURCE="/vagrant/.gcloud/application_default_credentials.json"

  if [ ! -f "$CREDS_SOURCE" ]; then
    echo "ERROR: GCP credentials not found at $CREDS_SOURCE"
    echo
    echo "Please run on your HOST machine:"
    echo "  1. gcloud auth application-default login"
    echo "  2. mkdir -p .gcloud"
    echo "  3. cp ~/.config/gcloud/application_default_credentials.json .gcloud/"
    echo
    echo "Then run this script again inside the Vagrant VM"
    exit 1
  fi
else
  # Running on host - need to copy credentials to shared location
  echo "Running on host machine..."
  echo

  # Check if user has authenticated
  CREDS_FILE="${HOME}/.config/gcloud/application_default_credentials.json"

  if [ ! -f "$CREDS_FILE" ]; then
    echo "ERROR: No GCP credentials found"
    echo
    echo "Please authenticate first:"
    echo "  gcloud auth application-default login"
    echo
    exit 1
  fi

  # Copy credentials to project directory (will be gitignored)
  echo "Copying credentials to .gcloud/ directory..."
  mkdir -p .gcloud
  cp "$CREDS_FILE" .gcloud/application_default_credentials.json
  chmod 600 .gcloud/application_default_credentials.json

  echo "✓ Credentials copied to .gcloud/"
  echo
  echo "Now run this script inside the Vagrant VM:"
  echo "  vagrant ssh -c 'cd /vagrant/deploy/scripts && sudo bash 11-create-gcp-credentials-secret.sh'"
  exit 0
fi

# Create the secret
echo "Creating Kubernetes secret..."

kubectl create secret generic gcp-credentials \
  -n ai-pipeline \
  --from-file=credentials.json="$CREDS_SOURCE" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✓ Secret 'gcp-credentials' created in namespace 'ai-pipeline'"
echo

# Verify the secret
echo "Verifying secret contents..."
SECRET_TYPE=$(kubectl get secret gcp-credentials -n ai-pipeline -o jsonpath='{.data.credentials\.json}' | base64 -d | jq -r .type 2>/dev/null || echo "invalid")

if [ "$SECRET_TYPE" = "authorized_user" ] || [ "$SECRET_TYPE" = "service_account" ]; then
  echo "✓ Secret contains valid GCP credentials (type: $SECRET_TYPE)"
else
  echo "⚠ WARNING: Secret may not contain valid credentials"
fi

echo
echo "==> GCP credentials secret created successfully!"
echo
echo "You can now deploy Claude agents that use Vertex AI:"
echo "  cd /vagrant/deploy/claude-agent"
echo "  bash build-and-deploy.sh"
echo
