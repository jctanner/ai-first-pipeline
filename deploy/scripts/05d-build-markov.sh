#!/bin/bash
# Build and import markov image for k3s

set -euo pipefail

if command -v docker &> /dev/null; then
  CONTAINER_CMD="docker"
elif command -v podman &> /dev/null; then
  CONTAINER_CMD="podman"
else
  echo "ERROR: Neither docker nor podman found"
  exit 1
fi

echo "==> Building markov image..."

if [ ! -d /vagrant/deploy/repos/markov ]; then
  echo "ERROR: markov repo not found at /vagrant/deploy/repos/markov"
  exit 1
fi

cd /vagrant/deploy/repos/markov

${CONTAINER_CMD} build -t markov:latest .

echo "  Importing markov image into k3s..."
${CONTAINER_CMD} save markov:latest | sudo k3s ctr images import -

echo "Successfully built and imported markov:latest"
