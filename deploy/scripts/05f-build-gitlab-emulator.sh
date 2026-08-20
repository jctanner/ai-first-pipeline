#!/bin/bash
# Build and import gitlab-emulator image for k3s

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"

# Use docker or podman
if command -v docker &> /dev/null; then
  CONTAINER_CMD="docker"
elif command -v podman &> /dev/null; then
  CONTAINER_CMD="podman"
else
  echo "ERROR: Neither docker nor podman found"
  echo "Docker should have been installed by Vagrantfile provisioning"
  exit 1
fi

echo "==> Building gitlab-emulator image with ${CONTAINER_CMD}..."

# Build gitlab-emulator if the repo exists
if [ -d ${PROJECT_ROOT}/checkouts/gitlab-emulator ]; then
  echo "--- Building gitlab-emulator image for k3s ---"
  cd ${PROJECT_ROOT}/checkouts/gitlab-emulator

  ${CONTAINER_CMD} build -t gitlab-emulator:latest .
  sudo k3s ctr images rm docker.io/library/gitlab-emulator:latest localhost/gitlab-emulator:latest 2>/dev/null || true
  ${CONTAINER_CMD} save gitlab-emulator:latest | sudo k3s ctr images import -
  sudo k3s ctr images tag localhost/gitlab-emulator:latest docker.io/library/gitlab-emulator:latest 2>/dev/null || true
  echo "Successfully built and imported gitlab-emulator:latest"
else
  echo "ERROR: gitlab-emulator repo not found at ${PROJECT_ROOT}/checkouts/gitlab-emulator"
  exit 1
fi

echo ""
echo "==> Image build complete!"
echo ""
echo "Imported images:"
sudo k3s ctr images ls | grep gitlab-emulator || echo "No gitlab-emulator images found"
