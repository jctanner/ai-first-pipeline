#!/bin/bash
# Access script for GitHub and Jira emulators
# Run this to create port forwards from host to emulators
# Bypasses Caddy and goes directly to backend application ports

echo "=== AI-First Pipeline Emulator Access ==="
echo
echo "Setting up port forwarding to access emulators from your host machine..."
echo

# Check if emulators are deployed
JIRA_EXISTS=$(vagrant ssh -c "kubectl get deployment -n ai-pipeline jira-emulator 2>/dev/null" || echo "")
GITHUB_EXISTS=$(vagrant ssh -c "kubectl get deployment -n ai-pipeline github-emulator 2>/dev/null" || echo "")

if [ -z "$JIRA_EXISTS" ]; then
    echo "⚠️  Jira Emulator is not deployed yet."
    echo "   Deploy it first with: vagrant ssh -c 'kubectl apply -f /vagrant/deploy/k8s/11-jira-emulator-config.yaml -f /vagrant/deploy/k8s/12-jira-emulator.yaml'"
    echo
fi

if [ -z "$GITHUB_EXISTS" ]; then
    echo "⚠️  GitHub Emulator is not deployed yet."
    echo
fi

echo "Starting port forwards to backend applications (bypassing Caddy):"
echo
if [ -n "$GITHUB_EXISTS" ]; then
    echo "  GitHub Emulator:         http://localhost:8000"
fi
if [ -n "$JIRA_EXISTS" ]; then
    echo "  Jira Emulator:           http://localhost:8080"
    echo "  Jira MCP Server:         http://localhost:8081"
fi
echo "  Pipeline Dashboard:      http://localhost:5000 (already forwarded in Vagrantfile)"
echo
echo "Note: Accessing backend ports directly (no TLS)"
echo "Press Ctrl+C to stop port forwarding"
echo

# Build port forward command based on what's deployed
GITHUB_POD=""
JIRA_POD=""
FORWARDS=""
TUNNELS=""

if [ -n "$GITHUB_EXISTS" ]; then
    GITHUB_POD=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=github-emulator -o jsonpath='{.items[0].metadata.name}' 2>/dev/null" || echo "")
    if [ -n "$GITHUB_POD" ]; then
        FORWARDS="kubectl port-forward -n ai-pipeline pod/$GITHUB_POD 8000:8000 &"
        TUNNELS="$TUNNELS -L 8000:localhost:8000"
    fi
fi

if [ -n "$JIRA_EXISTS" ]; then
    JIRA_POD=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=jira-emulator -o jsonpath='{.items[0].metadata.name}' 2>/dev/null" || echo "")
    if [ -n "$JIRA_POD" ]; then
        FORWARDS="$FORWARDS kubectl port-forward -n ai-pipeline pod/$JIRA_POD 8080:8080 8081:8081 &"
        TUNNELS="$TUNNELS -L 8080:localhost:8080 -L 8081:localhost:8081"
    fi
fi

if [ -z "$FORWARDS" ]; then
    echo "ERROR: No emulator pods found"
    exit 1
fi

# Run port forwards via SSH tunnel
vagrant ssh -- $TUNNELS "
    echo 'Port forwarding active. Press Ctrl+C to stop.'
    $FORWARDS
    wait
"
