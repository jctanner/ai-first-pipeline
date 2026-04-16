#!/bin/bash
# Create Kubernetes secrets from .env file

set -euo pipefail

echo "==> Creating secrets from .env file..."

if [ ! -f /vagrant/.env ]; then
  echo "ERROR: .env file not found at /vagrant/.env"
  echo "Please create it with required credentials before running this script"
  exit 1
fi

# Source the .env file
source /vagrant/.env

# Create the main pipeline secrets
kubectl create secret generic pipeline-secrets \
  -n ai-pipeline \
  --from-literal=CLAUDE_CODE_USE_VERTEX="${CLAUDE_CODE_USE_VERTEX:-1}" \
  --from-literal=CLOUD_ML_REGION="${CLOUD_ML_REGION:-us-east5}" \
  --from-literal=ANTHROPIC_VERTEX_PROJECT_ID="${ANTHROPIC_VERTEX_PROJECT_ID:-}" \
  --from-literal=JIRA_SERVER="${JIRA_SERVER:-https://issues.redhat.com}" \
  --from-literal=JIRA_USER="${JIRA_USER:-}" \
  --from-literal=JIRA_TOKEN="${JIRA_TOKEN:-}" \
  --from-literal=ATLASSIAN_MCP_URL="${ATLASSIAN_MCP_URL:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✓ Created pipeline-secrets"

# Create a placeholder GitHub token for the emulator
# This should be replaced with actual token from the emulator once it's running
kubectl create secret generic github-token \
  -n ai-pipeline \
  --from-literal=token="ghe_PLACEHOLDER_REPLACE_AFTER_EMULATOR_SETUP" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "✓ Created github-token (placeholder - update after emulator setup)"

# If there are GCP service account credentials, create a secret for them
if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
  kubectl create secret generic gcp-credentials \
    -n ai-pipeline \
    --from-file=credentials.json="$GOOGLE_APPLICATION_CREDENTIALS" \
    --dry-run=client -o yaml | kubectl apply -f -
  echo "✓ Created gcp-credentials from $GOOGLE_APPLICATION_CREDENTIALS"
else
  echo "⚠ GOOGLE_APPLICATION_CREDENTIALS not set, skipping GCP credentials secret"
  echo "  If you need Vertex AI access, create this secret manually"
fi

echo ""
echo "==> Secrets created successfully!"
kubectl get secrets -n ai-pipeline
