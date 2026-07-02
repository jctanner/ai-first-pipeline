#!/bin/bash
# Wipe all data from the AI Pipeline stack.
# Scales down services, clears PVC contents, re-registers the GitLab Runner,
# and scales everything back up.
#
# Usage: clean-all.sh [--yes]
#   --yes   Skip confirmation prompt

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
NAMESPACE="ai-pipeline"
RUNNER_NAMESPACE="gitlab-runner"

# --- Confirmation ---
if [[ "${1:-}" != "--yes" ]]; then
  echo "========================================"
  echo "  AI Pipeline — Full Data Wipe"
  echo "========================================"
  echo ""
  echo "This will DELETE ALL DATA from:"
  echo "  - GitHub Emulator  (repos, users, orgs)"
  echo "  - GitLab Emulator  (repos, pipelines, runners)"
  echo "  - Jira Emulator    (issues, projects)"
  echo "  - Markov / Postgres (workflows, history)"
  echo "  - MLflow           (experiments, traces)"
  echo "  - Observatory      (claims, verifications)"
  echo "  - Elasticsearch    (indexed traces)"
  echo "  - Pipeline data    (artifacts, issues, logs, workspace)"
  echo ""
  echo "This is NOT reversible. Run backup.sh first if needed."
  echo ""
  read -rp "Type 'wipe' to confirm: " confirm
  if [[ "$confirm" != "wipe" ]]; then
    echo "Aborted."
    exit 1
  fi
  echo ""
fi

echo "==> Scaling down all services..."

# Scale down services that hold data
DEPLOYMENTS=(
  github-emulator
  gitlab-emulator
  jira-emulator
  markovd
  markovd-postgres
  observatory
  pipeline-dashboard
)

for dep in "${DEPLOYMENTS[@]}"; do
  kubectl scale deployment "$dep" -n "$NAMESPACE" --replicas=0 2>/dev/null || true
done

# MLflow needs a full delete — its SQLite experiment ID auto-increment and
# soft-delete tracking don't reset cleanly on a data wipe. Delete the
# deployment entirely so it gets a fresh process after the PVC is cleared.
echo "  Deleting MLflow deployment (will be reapplied after wipe)..."
kubectl delete deployment mlflow -n "$NAMESPACE" --ignore-not-found=true

kubectl scale deployment gitlab-runner -n "$RUNNER_NAMESPACE" --replicas=0 2>/dev/null || true

echo "  Waiting for pods to terminate..."
for dep in "${DEPLOYMENTS[@]}"; do
  kubectl wait --for=delete pod -l "app=$dep" -n "$NAMESPACE" --timeout=60s 2>/dev/null || true
done
kubectl wait --for=delete pod -l "app=mlflow" -n "$NAMESPACE" --timeout=60s 2>/dev/null || true
kubectl wait --for=delete pod -l "app=gitlab-runner" -n "$RUNNER_NAMESPACE" --timeout=60s 2>/dev/null || true

echo ""
echo "==> Wiping PVC contents..."

wipe_pvc() {
  local pvc_name=$1
  local mount_path=$2
  local ns="${3:-$NAMESPACE}"
  local helper_name="wipe-${pvc_name}"

  kubectl delete pod -n "$ns" "$helper_name" --ignore-not-found=true >/dev/null 2>&1
  sleep 1

  kubectl run "$helper_name" \
    --image=alpine:3.19 \
    --restart=Never \
    -n "$ns" \
    --overrides="{
      \"spec\": {
        \"volumes\": [{
          \"name\": \"data\",
          \"persistentVolumeClaim\": {\"claimName\": \"${pvc_name}\"}
        }],
        \"containers\": [{
          \"name\": \"wipe\",
          \"image\": \"alpine:3.19\",
          \"command\": [\"sh\", \"-c\", \"sleep 3600\"],
          \"volumeMounts\": [{
            \"name\": \"data\",
            \"mountPath\": \"${mount_path}\"
          }]
        }]
      }
    }" \
    -- sh -c "sleep 3600" >/dev/null 2>&1

  kubectl wait --for=condition=Ready pod "$helper_name" -n "$ns" --timeout=60s >/dev/null 2>&1 || {
    echo "  WARNING: helper pod for $pvc_name failed to start, skipping"
    kubectl delete pod -n "$ns" "$helper_name" --ignore-not-found=true >/dev/null 2>&1
    return 0
  }

  echo "  Wiping $pvc_name..."
  kubectl exec -n "$ns" "$helper_name" -- sh -c "rm -rf ${mount_path}/* ${mount_path}/.[!.]* 2>/dev/null; echo done"

  kubectl delete pod -n "$ns" "$helper_name" --ignore-not-found=true >/dev/null 2>&1
}

# Service data PVCs
wipe_pvc "github-emulator-data"  "/data"
wipe_pvc "gitlab-emulator-data"  "/data"
wipe_pvc "jira-emulator-data"    "/data"
wipe_pvc "markovd-pgdata"        "/var/lib/postgresql/data"
wipe_pvc "mlflow-data"           "/data"
wipe_pvc "observatory-data"      "/data"

# Pipeline PVCs
wipe_pvc "pipeline-artifacts"    "/data"
wipe_pvc "pipeline-data"         "/data"
wipe_pvc "pipeline-issues"       "/data"
wipe_pvc "pipeline-logs"         "/data"
wipe_pvc "pipeline-workspace"    "/data"

# Clean up GitLab Runner config and secrets (runner token is now invalid)
echo ""
echo "==> Cleaning GitLab Runner registration..."
kubectl delete configmap gitlab-runner-config -n "$RUNNER_NAMESPACE" --ignore-not-found=true
kubectl delete secret gitlab-runner-ca -n "$RUNNER_NAMESPACE" --ignore-not-found=true

echo ""
echo "==> Scaling services back up..."

for dep in "${DEPLOYMENTS[@]}"; do
  kubectl scale deployment "$dep" -n "$NAMESPACE" --replicas=1 2>/dev/null || true
done

# Reapply MLflow from manifest (was fully deleted, not just scaled)
echo "  Reapplying MLflow deployment..."
kubectl apply -f "${PROJECT_ROOT}/deploy/k8s/13-mlflow.yaml"

echo "  Waiting for services to be ready..."
for dep in "${DEPLOYMENTS[@]}"; do
  kubectl wait --for=condition=Available deployment "$dep" -n "$NAMESPACE" --timeout=120s 2>/dev/null || true
done
kubectl wait --for=condition=Available deployment mlflow -n "$NAMESPACE" --timeout=120s 2>/dev/null || true

echo ""
echo "==> Re-registering GitLab Runner..."
bash "${PROJECT_ROOT}/deploy/scripts/15-deploy-gitlab-runner.sh"

echo ""
echo "========================================"
echo "  Data wipe complete"
echo "========================================"
echo ""
echo "All services are running with empty databases."
echo "GitLab Runner has been re-registered."
echo ""
echo "Next steps:"
echo "  - Import repos into github.local"
echo "  - Create projects in jira.local"
echo "  - Or run a Markov workflow that handles setup"
