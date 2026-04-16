#!/bin/bash
# Build container images for ai-first-pipeline components

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

echo "==> Building container images with ${CONTAINER_CMD}..."

# Build the main pipeline dashboard image
echo "--- Building ai-first-pipeline dashboard image ---"
cd /vagrant

# The Dockerfile should exist in the root
if [ -f Dockerfile ]; then
  ${CONTAINER_CMD} build -t ai-first-pipeline:latest .
  # Import into k3s
  echo "  Importing ai-first-pipeline image into k3s..."
  ${CONTAINER_CMD} save ai-first-pipeline:latest | sudo k3s ctr images import -
  echo "  Successfully built and imported ai-first-pipeline:latest"
else
  # Create a default Dockerfile if it doesn't exist
  echo "  Creating default Dockerfile..."
  cat > Dockerfile <<'EOF'
FROM python:3.13-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Copy project files
COPY . .

# Install Python dependencies
RUN uv sync

# Expose dashboard port
EXPOSE 5000

# Default command - run dashboard
CMD ["uv", "run", "python", "main.py", "dashboard", "--port", "5000", "--host", "0.0.0.0"]
EOF
  echo "  Created default Dockerfile"

  ${CONTAINER_CMD} build -t ai-first-pipeline:latest .
  # Import into k3s
  echo "  Importing ai-first-pipeline image into k3s..."
  ${CONTAINER_CMD} save ai-first-pipeline:latest | sudo k3s ctr images import -
  echo "  Successfully built and imported ai-first-pipeline:latest"
fi
echo ""

# Build github-emulator if the repo exists
if [ -d /vagrant/deploy/repos/github-emulator ]; then
  echo "--- Building github-emulator image for k3s ---"
  cd /vagrant/deploy/repos/github-emulator

  if [ -f Dockerfile.k3s ]; then
    ${CONTAINER_CMD} build -f Dockerfile.k3s -t github-emulator:k3s .
    ${CONTAINER_CMD} save github-emulator:k3s | sudo k3s ctr images import -
    echo "Successfully built and imported github-emulator:k3s"
  else
    echo "WARNING: github-emulator Dockerfile.k3s not found, skipping"
  fi
else
  echo "WARNING: github-emulator repo not found at /vagrant/deploy/repos/github-emulator"
  echo "The deployment will fail"
fi

# Build jira-emulator if the repo exists
if [ -d /vagrant/deploy/repos/jira-emulator ]; then
  echo "--- Building jira-emulator image for k3s ---"
  cd /vagrant/deploy/repos/jira-emulator

  if [ -f Dockerfile.k3s ]; then
    ${CONTAINER_CMD} build -f Dockerfile.k3s -t jira-emulator:k3s .
    ${CONTAINER_CMD} save jira-emulator:k3s | sudo k3s ctr images import -
    echo "Successfully built and imported jira-emulator:k3s"
  else
    echo "WARNING: jira-emulator Dockerfile.k3s not found, skipping"
  fi
else
  echo "WARNING: jira-emulator repo not found at /vagrant/deploy/repos/jira-emulator"
  echo "The deployment will fail"
fi

echo "==> Image build complete!"
echo ""
echo "Imported images:"
sudo k3s ctr images ls | grep -E 'ai-first-pipeline|github-emulator|jira-emulator|ingress-proxy' || echo "No matching images found"
echo ""
echo "Note: ingress-proxy image is built during the ingress deployment step"
