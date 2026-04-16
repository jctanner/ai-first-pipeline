#!/bin/bash
# Build and deploy the Go reverse proxy to k3s

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Building Go Reverse Proxy ==="
echo

# Step 1: Build Docker image inside Vagrant VM
echo "[1/5] Building Docker image..."
vagrant ssh -c "cd /vagrant/deploy/golang-reverse-proxy && sudo docker build -t ingress-proxy:latest . -q" || {
    echo "ERROR: Docker build failed"
    exit 1
}
echo "✓ Docker build complete"
echo

# Step 2: Import image into k3s
echo "[2/5] Importing image into k3s..."
vagrant ssh -c "sudo docker save ingress-proxy:latest | sudo k3s ctr images import -" > /dev/null
echo "✓ Image imported to k3s"
echo

# Step 3: Apply the deployment
echo "[3/5] Deploying to Kubernetes..."
vagrant ssh -c "kubectl apply -f /vagrant/deploy/golang-reverse-proxy/deployment.yaml"
echo "✓ Deployment applied"
echo

# Step 4: Wait for certificate to be ready
echo "[4/5] Waiting for TLS certificate..."
for i in {1..30}; do
    STATUS=$(vagrant ssh -c "kubectl get certificate -n ai-pipeline ingress-proxy-tls -o jsonpath='{.status.conditions[?(@.type==\"Ready\")].status}' 2>/dev/null" || echo "")
    if [ "$STATUS" = "True" ]; then
        echo "✓ Certificate ready"
        break
    fi
    echo -n "."
    sleep 2
done
echo

# Step 5: Wait for pod to be ready
echo "[5/5] Waiting for pod to be ready..."
for i in {1..30}; do
    STATUS=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=ingress-proxy -o jsonpath='{.items[0].status.phase}' 2>/dev/null" || echo "Unknown")
    READY=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=ingress-proxy -o jsonpath='{.items[0].status.conditions[?(@.type==\"Ready\")].status}' 2>/dev/null" || echo "False")

    if [ "$STATUS" = "Running" ] && [ "$READY" = "True" ]; then
        echo "✓ Proxy is ready!"
        echo

        # Get LoadBalancer IP
        LB_IP=$(vagrant ssh -c "kubectl get svc -n ai-pipeline ingress-proxy -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null" || echo "")

        echo "=== Deployment Complete ==="
        echo
        echo "LoadBalancer IP: $LB_IP"
        echo
        echo "Test endpoints:"
        echo "  curl -k -H 'Host: jira.local' https://$LB_IP/"
        echo "  curl -k -H 'Host: github.local' https://$LB_IP/"
        echo "  curl -k -H 'Host: dashboard.local' https://$LB_IP/"
        echo
        echo "View logs:"
        echo "  vagrant ssh -c 'kubectl logs -n ai-pipeline -l app=ingress-proxy -f'"
        exit 0
    fi

    echo -n "."
    sleep 2
done

echo
echo "WARNING: Pod did not become ready within 60 seconds"
echo "Check status with:"
echo "  vagrant ssh -c 'kubectl get pods -n ai-pipeline -l app=ingress-proxy'"
echo "  vagrant ssh -c 'kubectl describe pod -n ai-pipeline -l app=ingress-proxy'"
exit 1
