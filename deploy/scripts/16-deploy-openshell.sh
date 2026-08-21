#!/usr/bin/env bash
# Install Agent Sandbox and the local OpenShell gateway.

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST="${PROJECT_ROOT}/deploy/dependencies.json"
VALUES="${PROJECT_ROOT}/deploy/k8s/openshell-values.yaml"
RBAC="${PROJECT_ROOT}/deploy/k8s/openshell-gateway-sandbox-rbac.yaml"

if ! command -v helm >/dev/null 2>&1; then
  bash "${SCRIPT_DIR}/00-install-helm.sh"
fi

for command in jq curl kubectl helm git; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "ERROR: required command not found: ${command}" >&2
    exit 1
  fi
done

openshell_checkout=$(jq -er '.dependencies[] | select(.name == "openshell") | .checkout' "${MANIFEST}")
openshell_ref=$(jq -er '.dependencies[] | select(.name == "openshell") | .ref' "${MANIFEST}")
openshell_chart=$(jq -er '.dependencies[] | select(.name == "openshell") | .chart' "${MANIFEST}")
agent_sandbox_manifest=$(jq -er '.dependencies[] | select(.name == "agent-sandbox") | .manifest' "${MANIFEST}")
agent_sandbox_ref=$(jq -er '.dependencies[] | select(.name == "agent-sandbox") | .ref' "${MANIFEST}")

checkout_path="${PROJECT_ROOT}/${openshell_checkout}"
chart_path="${checkout_path}/${openshell_chart}"

if [ ! -d "${checkout_path}/.git" ]; then
  echo "ERROR: OpenShell checkout is missing; run 00-clone-third-party-dependencies.sh" >&2
  exit 1
fi
if [ "$(git -C "${checkout_path}" rev-parse HEAD)" != "${openshell_ref}" ]; then
  echo "ERROR: OpenShell checkout is not at pinned ref ${openshell_ref}" >&2
  exit 1
fi
if [ ! -f "${chart_path}/Chart.yaml" ]; then
  echo "ERROR: OpenShell chart is missing: ${chart_path}" >&2
  exit 1
fi

echo "==> Installing Agent Sandbox ${agent_sandbox_ref}"
curl -fsSL "${agent_sandbox_manifest}" | kubectl apply -f -
kubectl wait --for=condition=Available --timeout=300s \
  deployment --all -n agent-sandbox-system

echo "==> Preparing OpenShell sandbox namespace"
kubectl create namespace ai-pipeline --dry-run=client -o yaml | kubectl apply -f -

echo "==> Installing OpenShell gateway from ${chart_path}"
helm upgrade --install openshell "${chart_path}" \
  --namespace openshell-system \
  --create-namespace \
  --values "${VALUES}" \
  --wait \
  --timeout 10m

echo "==> Applying gateway sandbox RBAC"
kubectl apply -f "${RBAC}"

gateway_workload=$(kubectl get statefulset,deploy -n openshell-system \
  -l app.kubernetes.io/instance=openshell -o name | head -1)
if [ -z "${gateway_workload}" ]; then
  echo "ERROR: OpenShell gateway workload was not created" >&2
  exit 1
fi
kubectl rollout status "${gateway_workload}" -n openshell-system --timeout=300s

echo "OpenShell deployment is ready"
