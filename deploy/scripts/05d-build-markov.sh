#!/bin/bash
# Build and import markov image for k3s

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"

if command -v docker &> /dev/null; then
  CONTAINER_CMD="docker"
elif command -v podman &> /dev/null; then
  CONTAINER_CMD="podman"
else
  echo "ERROR: Neither docker nor podman found"
  exit 1
fi

echo "==> Building markov image..."

if [ ! -d ${PROJECT_ROOT}/deploy/repos/markov ]; then
  echo "ERROR: markov repo not found at ${PROJECT_ROOT}/deploy/repos/markov"
  exit 1
fi

cd ${PROJECT_ROOT}/deploy/repos/markov

${CONTAINER_CMD} build -t markov:latest .

echo "  Importing markov image into k3s..."
sudo k3s ctr images rm docker.io/library/markov:latest localhost/markov:latest 2>/dev/null || true
${CONTAINER_CMD} save markov:latest | sudo k3s ctr images import -
sudo k3s ctr images tag localhost/markov:latest docker.io/library/markov:latest 2>/dev/null || true

echo "Successfully built and imported markov:latest"
