#!/bin/bash
# Build pipeline-dashboard image (Flask web UI)

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

echo "==> Building pipeline-dashboard image..."
cd /vagrant

if [ ! -f deploy/dashboard/Dockerfile ]; then
  echo "ERROR: deploy/dashboard/Dockerfile not found"
  exit 1
fi

${CONTAINER_CMD} build -f deploy/dashboard/Dockerfile -t pipeline-dashboard:latest .

# Import into k3s
echo "  Importing pipeline-dashboard image into k3s..."
${CONTAINER_CMD} save pipeline-dashboard:latest | sudo k3s ctr images import -

echo "✓ Successfully built and imported pipeline-dashboard:latest"
