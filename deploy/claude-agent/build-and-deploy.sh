#!/bin/bash
# Build and deploy Claude Agent to k3s

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Building and Deploying Claude Agent ==="
echo

# Step 1: Build Docker image inside Vagrant VM
echo "[1/5] Building Docker image..."
vagrant ssh -c "cd /vagrant/deploy/claude-agent && sudo docker build -t claude-agent:latest ." || {
    echo "ERROR: Docker build failed"
    exit 1
}
echo "✓ Docker build complete"
echo

# Step 2: Import image into k3s
echo "[2/5] Importing image into k3s..."
vagrant ssh -c "sudo docker save claude-agent:latest | sudo k3s ctr images import -" > /dev/null
echo "✓ Image imported to k3s"
echo

# Step 3: Deploy to Kubernetes
echo "[3/5] Deploying to Kubernetes..."
vagrant ssh -c "kubectl apply -f /vagrant/deploy/claude-agent/deployment.yaml"
echo "✓ Deployment applied"
echo

# Step 4: Wait for pod to be ready
echo "[4/5] Waiting for pod to be ready..."
for i in {1..30}; do
    STATUS=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent -o jsonpath='{.items[0].status.phase}' 2>/dev/null" || echo "Unknown")
    READY=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent -o jsonpath='{.items[0].status.conditions[?(@.type==\"Ready\")].status}' 2>/dev/null" || echo "False")

    if [ "$STATUS" = "Running" ] && [ "$READY" = "True" ]; then
        echo "✓ Agent is ready!"
        break
    fi

    echo -n "."
    sleep 2
done
echo

# Step 5: Show usage information
POD_NAME=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent -o jsonpath='{.items[0].metadata.name}' 2>/dev/null" || echo "")

echo "=== Deployment Complete ==="
echo
echo "Claude Agent pod: ${POD_NAME}"
echo
echo "Usage examples:"
echo
echo "1. Execute Claude Code command:"
echo "   vagrant ssh -c \"kubectl exec -n ai-pipeline ${POD_NAME} -- claude -p 'Explain the codebase structure'\""
echo
echo "2. Interactive shell in agent container:"
echo "   vagrant ssh -c \"kubectl exec -it -n ai-pipeline ${POD_NAME} -- bash\""
echo
echo "3. Check credentials are mounted:"
echo "   vagrant ssh -c \"kubectl exec -n ai-pipeline ${POD_NAME} -- ls -la /home/agent/.config/gcloud/\""
echo
echo "4. View agent logs:"
echo "   vagrant ssh -c \"kubectl logs -n ai-pipeline ${POD_NAME}\""
echo
echo "5. Delete the deployment:"
echo "   vagrant ssh -c \"kubectl delete -f /vagrant/deploy/claude-agent/deployment.yaml\""
echo
echo "Environment variables configured:"
echo "  - CLAUDE_CODE_USE_VERTEX=1"
echo "  - CLOUD_ML_REGION=us-east5"
echo "  - ANTHROPIC_VERTEX_PROJECT_ID (from pipeline-secrets)"
echo "  - GOOGLE_APPLICATION_CREDENTIALS=/home/agent/.config/gcloud/credentials.json"
echo
