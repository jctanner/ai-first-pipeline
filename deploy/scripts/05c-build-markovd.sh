#!/bin/bash
# Build and import markovd image for k3s

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

echo "==> Building markovd image..."

if [ ! -d ${PROJECT_ROOT}/checkouts/markovd ]; then
  echo "ERROR: markovd repo not found at ${PROJECT_ROOT}/checkouts/markovd"
  exit 1
fi

cd ${PROJECT_ROOT}/checkouts/markovd

${CONTAINER_CMD} build -t markovd:latest .

echo "  Importing markovd image into k3s..."
sudo k3s ctr images rm docker.io/library/markovd:latest localhost/markovd:latest 2>/dev/null || true
${CONTAINER_CMD} save markovd:latest | sudo k3s ctr images import -
sudo k3s ctr images tag localhost/markovd:latest docker.io/library/markovd:latest 2>/dev/null || true

echo "Successfully built and imported markovd:latest"
