#!/bin/bash
# Build and import observatory image for k3s

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

echo "==> Building observatory image with ${CONTAINER_CMD}..."

if [ -d "${PROJECT_ROOT}/deploy/repos/observatory" ]; then
  echo "--- Building observatory image for k3s ---"
  cd "${PROJECT_ROOT}/deploy/repos/observatory"

  ${CONTAINER_CMD} build -t observatory:latest .
  ${CONTAINER_CMD} save observatory:latest | sudo k3s ctr images import -
  sudo k3s ctr images tag localhost/observatory:latest docker.io/library/observatory:latest 2>/dev/null || true
  echo "Successfully built and imported observatory:latest"
else
  echo "ERROR: observatory repo not found at ${PROJECT_ROOT}/deploy/repos/observatory"
  exit 1
fi

echo ""
echo "==> Image build complete!"
echo ""
echo "Imported images:"
sudo k3s ctr images ls | grep observatory || echo "No observatory images found"
