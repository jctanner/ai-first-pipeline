#!/bin/bash
# Build and deploy Pipeline Agent container to K3s

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Building Pipeline Agent Container ==="
echo "Project root: $PROJECT_ROOT"
echo

# Build from project root (to include all source files)
echo "[1/3] Building Docker image..."
cd "$PROJECT_ROOT"
vagrant ssh -c "cd /vagrant && sudo docker build -f deploy/pipeline-agent/Dockerfile -t pipeline-agent:latest ."

echo
echo "[2/3] Importing image into K3s..."
vagrant ssh -c "sudo docker save pipeline-agent:latest | sudo k3s ctr images import -" > /dev/null

echo
echo "[3/3] Verifying image..."
vagrant ssh -c "sudo k3s ctr images ls | grep pipeline-agent"

echo
echo "=== Build Complete ==="
echo
echo "✓ Image: pipeline-agent:latest"
echo "✓ Available in K3s cluster"
echo
echo "Test the image with:"
echo "  vagrant ssh -c \"kubectl run test-agent --image=pipeline-agent:latest --restart=Never --rm -it -- python main.py --help\""
echo
