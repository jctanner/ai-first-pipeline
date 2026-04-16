#!/bin/bash
# Validate K3s cluster health

set -euo pipefail

echo "==> Validating K3s cluster..."

# Check nodes
echo "--- Checking nodes ---"
kubectl get nodes | grep -q Ready || {
  echo "ERROR: Node not ready"
  exit 1
}
echo "✓ Node is Ready"

# Check core pods
echo "--- Checking core system pods ---"
kubectl wait --for=condition=Ready --timeout=60s pod \
  -l k8s-app=kube-dns -n kube-system
echo "✓ CoreDNS is Ready"

kubectl wait --for=condition=Ready --timeout=60s pod \
  -l app=local-path-provisioner -n kube-system
echo "✓ Local-path-provisioner is Ready"

# Check cert-manager
echo "--- Checking cert-manager ---"
kubectl get pods -n cert-manager | grep -q Running || {
  echo "ERROR: cert-manager pods not running"
  exit 1
}
echo "✓ cert-manager is running"

echo ""
echo "==> Cluster validation PASSED"
