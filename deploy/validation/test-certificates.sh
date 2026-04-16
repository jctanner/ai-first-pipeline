#!/bin/bash
# Validate certificate infrastructure

set -euo pipefail

NAMESPACE="ai-pipeline"

echo "==> Validating certificate infrastructure..."

# Check ClusterIssuer
echo "--- Checking ClusterIssuers ---"
kubectl get clusterissuer selfsigned-issuer -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' | grep -q True || {
  echo "ERROR: selfsigned-issuer not ready"
  exit 1
}
echo "✓ selfsigned-issuer is Ready"

kubectl get issuer internal-ca-issuer -n ${NAMESPACE} -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' | grep -q True || {
  echo "ERROR: internal-ca-issuer not ready"
  exit 1
}
echo "✓ internal-ca-issuer is Ready"

# Check Certificates
echo "--- Checking Certificates ---"
for cert in github-emulator-tls pipeline-dashboard-tls jira-emulator-tls; do
  CERT_STATUS=$(kubectl get certificate ${cert} -n ${NAMESPACE} -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "NotFound")
  if [ "$CERT_STATUS" != "True" ]; then
    echo "ERROR: Certificate ${cert} not ready (status: ${CERT_STATUS})"
    kubectl describe certificate ${cert} -n ${NAMESPACE} 2>/dev/null || true
    exit 1
  fi
  echo "✓ Certificate ${cert} is Ready"
done

# Check Secrets exist
echo "--- Checking TLS Secrets ---"
for secret in github-emulator-tls pipeline-dashboard-tls jira-emulator-tls; do
  kubectl get secret ${secret} -n ${NAMESPACE} >/dev/null 2>&1 || {
    echo "ERROR: Secret ${secret} not found"
    exit 1
  }

  for key in ca.crt tls.crt tls.key; do
    # Escape dots in the key name for jsonpath
    escaped_key="${key//./\\.}"
    kubectl get secret ${secret} -n ${NAMESPACE} -o jsonpath="{.data.${escaped_key}}" | grep -q . || {
      echo "ERROR: Missing ${key} in Secret ${secret}"
      exit 1
    }
  done
  echo "✓ Secret ${secret} has all required keys"
done

# Check CA ConfigMap
echo "--- Checking CA ConfigMap ---"
kubectl get configmap internal-ca-cert -n ${NAMESPACE} >/dev/null 2>&1 || {
  echo "ERROR: CA ConfigMap not found"
  exit 1
}
kubectl get configmap internal-ca-cert -n ${NAMESPACE} -o jsonpath='{.data.ca\.crt}' | grep -q "BEGIN CERTIFICATE" || {
  echo "ERROR: CA ConfigMap does not contain valid certificate"
  exit 1
}
echo "✓ CA ConfigMap exists and contains certificate"

echo ""
echo "==> Certificate validation PASSED"
