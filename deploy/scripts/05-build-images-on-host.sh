#!/bin/bash
# Build container images on the HOST machine and import to VM
# Run this script on your HOST (not in the VM)

set -euo pipefail

echo "==> Building container images on host..."

# Check if docker or podman is available
if command -v docker &> /dev/null; then
  CONTAINER_CMD="docker"
elif command -v podman &> /dev/null; then
  CONTAINER_CMD="podman"
else
  echo "ERROR: Neither docker nor podman found on host"
  exit 1
fi

echo "Using: ${CONTAINER_CMD}"

# Build the main pipeline image
echo "--- Building ai-first-pipeline image ---"

# Create a simple Dockerfile if it doesn't exist
if [ ! -f Dockerfile ]; then
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
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy project files
COPY . .

# Install Python dependencies
RUN uv sync

# Expose dashboard port
EXPOSE 5000

# Default command - run dashboard
CMD ["uv", "run", "python", "main.py", "dashboard", "--port", "5000", "--host", "0.0.0.0"]
EOF
  echo "Created default Dockerfile"
fi

${CONTAINER_CMD} build -t ai-first-pipeline:latest .

# Save to tar file
echo "==> Saving image to tar..."
${CONTAINER_CMD} save ai-first-pipeline:latest -o /tmp/ai-first-pipeline.tar

# Copy to VM and import
echo "==> Copying to VM and importing..."
vagrant ssh -c "sudo k3s ctr images import -" < /tmp/ai-first-pipeline.tar

# Clean up tar file
rm /tmp/ai-first-pipeline.tar

echo "==> Verifying import..."
vagrant ssh -c "sudo k3s ctr images ls | grep ai-first-pipeline"

echo ""
echo "==> Image build complete!"
echo "Next: Run deployment or restart pods to use new image"
echo "  kubectl rollout restart deployment/pipeline-dashboard -n ai-pipeline"
