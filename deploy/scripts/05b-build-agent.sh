#!/bin/bash
# Build pipeline-agent image (job runner with Claude CLI)

set -euo pipefail

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
cd /vagrant

if [ ! -f deploy/pipeline-agent/Dockerfile ]; then
  echo "ERROR: deploy/pipeline-agent/Dockerfile not found"
  exit 1
fi

${CONTAINER_CMD} build -f deploy/pipeline-agent/Dockerfile -t pipeline-agent:latest .

# Import into k3s
echo "  Importing pipeline-agent image into k3s..."
${CONTAINER_CMD} save pipeline-agent:latest | sudo k3s ctr images import -

echo "✓ Successfully built and imported pipeline-agent:latest"
