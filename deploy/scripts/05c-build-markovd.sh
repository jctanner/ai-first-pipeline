#!/bin/bash
# Build and import markovd image for k3s

set -euo pipefail

if command -v docker &> /dev/null; then
  CONTAINER_CMD="docker"
elif command -v podman &> /dev/null; then
  CONTAINER_CMD="podman"
else
  echo "ERROR: Neither docker nor podman found"
  exit 1
fi

echo "==> Building markovd image..."

if [ ! -d /vagrant/deploy/repos/markovd ]; then
  echo "ERROR: markovd repo not found at /vagrant/deploy/repos/markovd"
  exit 1
fi

cd /vagrant/deploy/repos/markovd

${CONTAINER_CMD} build -t markovd:latest .

echo "  Importing markovd image into k3s..."
${CONTAINER_CMD} save markovd:latest | sudo k3s ctr images import -

echo "Successfully built and imported markovd:latest"
