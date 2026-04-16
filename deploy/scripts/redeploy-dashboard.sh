#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== AI-First Pipeline Dashboard Redeploy ==="
echo

# Step 1: Build Docker image inside Vagrant VM
echo "[1/5] Building Docker image inside Vagrant VM..."
vagrant ssh -c "cd /vagrant && sudo docker build -t ai-first-pipeline:latest . -q" || {
    echo "ERROR: Docker build failed"
    exit 1
}
echo "✓ Docker build complete"
echo

# Step 2: Import image into k3s
echo "[2/5] Importing image into k3s..."
vagrant ssh -c "sudo docker save ai-first-pipeline:latest | sudo k3s ctr images import -" > /dev/null
echo "✓ Image imported to k3s"
echo

# Step 3: Remove disk-pressure taint if present
echo "[3/5] Checking for disk-pressure taint..."
if vagrant ssh -c "kubectl get nodes -o jsonpath='{.items[0].spec.taints[?(@.key==\"node.kubernetes.io/disk-pressure\")].key}'" 2>/dev/null | grep -q "disk-pressure"; then
    echo "  Removing disk-pressure taint..."
    vagrant ssh -c "sudo kubectl taint nodes ai-pipeline-k3s node.kubernetes.io/disk-pressure:NoSchedule- || true" > /dev/null 2>&1
    echo "  ✓ Taint removed"
else
    echo "  ✓ No taint present"
fi
echo

# Step 4: Delete existing pods to trigger restart
echo "[4/5] Restarting dashboard pods..."
vagrant ssh -c "kubectl delete pod -n ai-pipeline -l app=pipeline-dashboard --wait=false" > /dev/null 2>&1 || echo "  (no existing pods)"
sleep 3
echo "✓ Pods restarted"
echo

# Step 5: Wait for pod to be ready
echo "[5/5] Waiting for pod to be ready..."
for i in {1..30}; do
    STATUS=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=pipeline-dashboard -o jsonpath='{.items[0].status.phase}' 2>/dev/null" || echo "Unknown")
    READY=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=pipeline-dashboard -o jsonpath='{.items[0].status.conditions[?(@.type==\"Ready\")].status}' 2>/dev/null" || echo "False")

    if [ "$STATUS" = "Running" ] && [ "$READY" = "True" ]; then
        echo "✓ Dashboard is ready!"
        echo
        echo "Dashboard URL: http://localhost:5000"
        echo
        echo "To view logs:"
        echo "  vagrant ssh -c 'kubectl logs -n ai-pipeline -l app=pipeline-dashboard -f'"
        exit 0
    fi

    echo -n "."
    sleep 2
done

echo
echo "WARNING: Pod did not become ready within 60 seconds"
echo "Check status with:"
echo "  vagrant ssh -c 'kubectl get pods -n ai-pipeline -l app=pipeline-dashboard'"
echo "  vagrant ssh -c 'kubectl describe pod -n ai-pipeline -l app=pipeline-dashboard'"
exit 1
