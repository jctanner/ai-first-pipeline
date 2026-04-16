#!/bin/bash
# Validate application deployment

set -euo pipefail

NAMESPACE="ai-pipeline"

echo "==> Validating application deployment..."

# Check if deployments exist
echo "--- Checking Deployments ---"
for deployment in pipeline-dashboard github-emulator; do
  kubectl get deployment ${deployment} -n ${NAMESPACE} >/dev/null 2>&1 || {
    echo "⚠ Deployment ${deployment} not found (may not be deployed yet)"
    continue
  }

  # Wait for deployment to be ready
  kubectl wait --for=condition=Available --timeout=120s \
    deployment/${deployment} -n ${NAMESPACE} || {
    echo "ERROR: Deployment ${deployment} not ready"
    kubectl describe deployment ${deployment} -n ${NAMESPACE}
    exit 1
  }
  echo "✓ Deployment ${deployment} is Available"
done

# Check if services exist
echo "--- Checking Services ---"
for service in pipeline-dashboard github-emulator; do
  kubectl get service ${service} -n ${NAMESPACE} >/dev/null 2>&1 || {
    echo "⚠ Service ${service} not found (may not be deployed yet)"
    continue
  }
  echo "✓ Service ${service} exists"

  # Get LoadBalancer IP if available
  EXTERNAL_IP=$(kubectl get service ${service} -n ${NAMESPACE} -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
  echo "  External IP: ${EXTERNAL_IP}"
done

# Check PVCs
echo "--- Checking PersistentVolumeClaims ---"
for pvc in pipeline-data github-emulator-data; do
  kubectl get pvc ${pvc} -n ${NAMESPACE} >/dev/null 2>&1 || {
    echo "⚠ PVC ${pvc} not found"
    continue
  }

  PVC_STATUS=$(kubectl get pvc ${pvc} -n ${NAMESPACE} -o jsonpath='{.status.phase}')
  if [ "$PVC_STATUS" != "Bound" ]; then
    echo "ERROR: PVC ${pvc} not Bound (status: ${PVC_STATUS})"
    exit 1
  fi
  echo "✓ PVC ${pvc} is Bound"
done

# Check secrets
echo "--- Checking Secrets ---"
for secret in pipeline-secrets github-token; do
  kubectl get secret ${secret} -n ${NAMESPACE} >/dev/null 2>&1 || {
    echo "⚠ Secret ${secret} not found"
    continue
  }
  echo "✓ Secret ${secret} exists"
done

# Test DNS resolution
echo "--- Testing DNS Resolution ---"
for service in pipeline-dashboard github-emulator; do
  kubectl run -it --rm dns-test-${service} --image=alpine:3.19 --restart=Never -- \
    nslookup ${service}.${NAMESPACE}.svc.cluster.local 2>&1 | grep -q "Address:" && {
    echo "✓ ${service} DNS resolves"
  } || {
    echo "⚠ ${service} DNS resolution test skipped or failed"
  }
done

echo ""
echo "==> Application validation PASSED"
