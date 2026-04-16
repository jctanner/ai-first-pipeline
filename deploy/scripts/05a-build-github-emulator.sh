#!/bin/bash
# Build and import github-emulator image for k3s

set -euo pipefail

# Use docker or podman (docker should be installed by Vagrantfile)
if command -v docker &> /dev/null; then
  CONTAINER_CMD="docker"
elif command -v podman &> /dev/null; then
  CONTAINER_CMD="podman"
else
  echo "ERROR: Neither docker nor podman found"
  echo "Docker should have been installed by Vagrantfile provisioning"
  exit 1
fi

echo "==> Building github-emulator image with ${CONTAINER_CMD}..."

# Build github-emulator if the repo exists
if [ -d /vagrant/deploy/repos/github-emulator ]; then
  echo "--- Building github-emulator image for k3s ---"
  cd /vagrant/deploy/repos/github-emulator

  if [ -f Dockerfile.k3s ]; then
    ${CONTAINER_CMD} build -f Dockerfile.k3s -t github-emulator:k3s .
    ${CONTAINER_CMD} save github-emulator:k3s | sudo k3s ctr images import -
    echo "Successfully built and imported github-emulator:k3s"
  else
    echo "ERROR: github-emulator Dockerfile.k3s not found"
    exit 1
  fi
else
  echo "ERROR: github-emulator repo not found at /vagrant/deploy/repos/github-emulator"
  exit 1
fi

echo ""
echo "==> Image build complete!"
echo ""
echo "Imported images:"
sudo k3s ctr images ls | grep github-emulator || echo "No github-emulator images found"
