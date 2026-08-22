#!/usr/bin/env bash
# Configure in-cluster .local DNS and deploy the GitHub emulator Actions runner.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
TOKEN="${GITHUB_EMULATOR_TOKEN:-ghp_admin_default_token}"

echo "==> Configuring in-cluster .local DNS"
kubectl apply -f "${PROJECT_ROOT}/deploy/k8s/22-fullsend-networking.yaml"
kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout=120s

echo "==> Creating runner credential secret"
kubectl -n ai-pipeline create secret generic github-actions-runner-credentials \
  --from-literal=token="${TOKEN}" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Deploying GitHub emulator Actions runner"
kubectl apply -f "${PROJECT_ROOT}/deploy/k8s/23-github-actions-runner.yaml"
kubectl -n ai-pipeline rollout restart deployment/github-actions-runner
kubectl -n ai-pipeline rollout status deployment/github-actions-runner --timeout=180s

echo "==> Runner status"
kubectl -n ai-pipeline get deployment/github-actions-runner
kubectl -n ai-pipeline get pods -l app=github-actions-runner -o wide
