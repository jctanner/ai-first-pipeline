#!/bin/bash
# Build pipeline-agent image (job runner with Claude CLI)

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"

# Use docker or podman
if command -v docker &> /dev/null; then
  CONTAINER_CMD="docker"
elif command -v podman &> /dev/null; then
  CONTAINER_CMD="podman"
else
  echo "ERROR: Neither docker nor podman found"
  exit 1
fi

echo "==> Building pipeline-agent image..."
cd "${PROJECT_ROOT}"

if [ ! -f deploy/pipeline-agent/Dockerfile ]; then
  echo "ERROR: deploy/pipeline-agent/Dockerfile not found"
  exit 1
fi

# Extract internal CA cert from ConfigMap so it can be baked into the image
echo "  Extracting CA certificate from ConfigMap..."
CA_CERT=$(kubectl get configmap internal-ca-cert \
  -n ai-pipeline \
  -o jsonpath='{.data.ca\.crt}' 2>/dev/null || true)

if [ -z "$CA_CERT" ]; then
  echo "WARNING: Could not extract CA cert from ConfigMap, using empty placeholder"
  echo "" > internal-ca.crt
else
  echo "$CA_CERT" > internal-ca.crt
  echo "  CA certificate extracted successfully"
fi

${CONTAINER_CMD} build ${DOCKER_BUILD_ARGS:-} -f deploy/pipeline-agent/Dockerfile -t pipeline-agent:latest .

# Clean up extracted cert
rm -f internal-ca.crt

# Import into k3s (remove old image first so containerd doesn't skip the import)
echo "  Removing old pipeline-agent image from k3s..."
sudo k3s ctr images rm docker.io/library/pipeline-agent:latest localhost/pipeline-agent:latest 2>/dev/null || true
echo "  Importing pipeline-agent image into k3s..."
${CONTAINER_CMD} save pipeline-agent:latest | sudo k3s ctr images import -
sudo k3s ctr images tag localhost/pipeline-agent:latest docker.io/library/pipeline-agent:latest 2>/dev/null || true

echo "✓ Successfully built and imported pipeline-agent:latest"
