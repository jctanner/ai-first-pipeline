#!/bin/bash
# Build and import jira-emulator image for k3s

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

echo "==> Building jira-emulator image with ${CONTAINER_CMD}..."

# Build jira-emulator if the repo exists
if [ -d ${PROJECT_ROOT}/checkouts/jira-emulator ]; then
  echo "--- Building jira-emulator image for k3s ---"
  cd ${PROJECT_ROOT}/checkouts/jira-emulator

  if [ -f Dockerfile.k3s ]; then
    ${CONTAINER_CMD} build -f Dockerfile.k3s -t jira-emulator:k3s .
    sudo k3s ctr images rm docker.io/library/jira-emulator:k3s localhost/jira-emulator:k3s 2>/dev/null || true
    ${CONTAINER_CMD} save jira-emulator:k3s | sudo k3s ctr images import -
    sudo k3s ctr images tag localhost/jira-emulator:k3s docker.io/library/jira-emulator:k3s 2>/dev/null || true
    echo "Successfully built and imported jira-emulator:k3s"
  else
    echo "ERROR: jira-emulator Dockerfile.k3s not found"
    exit 1
  fi
else
  echo "ERROR: jira-emulator repo not found at ${PROJECT_ROOT}/checkouts/jira-emulator"
  exit 1
fi

echo ""
echo "==> Image build complete!"
echo ""
echo "Imported images:"
sudo k3s ctr images ls | grep jira-emulator || echo "No jira-emulator images found"
