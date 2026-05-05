#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="ai-pipeline"
SKIP_CONFIRM=false

usage() {
  echo "Usage: restore.sh [--yes] <backup-dir>"
  echo ""
  echo "Restores all ai-pipeline service data from a backup directory."
  echo "WARNING: This wipes all current data before restoring."
  echo ""
  echo "Flags:"
  echo "  --yes  Skip confirmation prompt"
  exit 1
}

while [[ $# -gt 0 ]]; do
  case $1 in
    --yes|-y) SKIP_CONFIRM=true; shift ;;
    -h|--help) usage ;;
    -*) echo "Unknown flag: $1"; usage ;;
    *) BACKUP_DIR="$1"; shift ;;
  esac
done

if [[ -z "${BACKUP_DIR:-}" ]]; then
  usage
fi

if [[ ! -f "${BACKUP_DIR}/manifest.json" ]]; then
  echo "ERROR: No manifest.json found in ${BACKUP_DIR}"
  exit 1
fi

echo "=========================================="
echo "AI Pipeline System Restore"
echo "=========================================="
echo ""
echo "Backup directory: ${BACKUP_DIR}"
echo "Backup timestamp: $(jq -r .timestamp "${BACKUP_DIR}/manifest.json")"
echo "Backed up services: $(jq -r '.backed_up | join(", ")' "${BACKUP_DIR}/manifest.json")"
echo ""

if [[ "$SKIP_CONFIRM" != "true" ]]; then
  echo "WARNING: This will wipe ALL current data and replace with backup contents."
  read -p "Continue? [y/N] " confirm
  [[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }
  echo ""
fi

if ! kubectl get namespace ${NAMESPACE} >/dev/null 2>&1; then
  echo "ERROR: Namespace ${NAMESPACE} not found. Is k3s running?"
  exit 1
fi

get_pod() {
  kubectl get pods -n ${NAMESPACE} -l "app=$1" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo ""
}

wait_for_no_pods() {
  local label=$1
  local timeout=120
  local elapsed=0
  while [[ $elapsed -lt $timeout ]]; do
    local count
    count=$(kubectl get pods -n ${NAMESPACE} -l "app=${label}" --no-headers 2>/dev/null | wc -l)
    if [[ $count -eq 0 ]]; then
      return 0
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  echo "  WARNING: Pods for app=${label} did not terminate within ${timeout}s"
  return 1
}

wait_for_pod_ready() {
  local label=$1
  kubectl wait --for=condition=Ready --timeout=120s pod -l "app=${label}" -n ${NAMESPACE} 2>/dev/null || {
    echo "  WARNING: Pod app=${label} not ready after 120s"
  }
}

run_restore_helper() {
  local pvc_name=$1 mount_path=$2 tarball=$3
  local helper_name="restore-${pvc_name}"

  kubectl delete pod -n ${NAMESPACE} "${helper_name}" --ignore-not-found=true >/dev/null 2>&1
  sleep 1

  kubectl run "${helper_name}" \
    --image=alpine:3.19 \
    --restart=Never \
    -n ${NAMESPACE} \
    --overrides="{
      \"spec\": {
        \"volumes\": [{
          \"name\": \"data\",
          \"persistentVolumeClaim\": {\"claimName\": \"${pvc_name}\"}
        }],
        \"containers\": [{
          \"name\": \"restore\",
          \"image\": \"alpine:3.19\",
          \"command\": [\"sleep\", \"3600\"],
          \"volumeMounts\": [{
            \"name\": \"data\",
            \"mountPath\": \"${mount_path}\"
          }]
        }]
      }
    }" >/dev/null 2>&1

  kubectl wait --for=condition=Ready --timeout=60s pod "${helper_name}" -n ${NAMESPACE} >/dev/null 2>&1

  echo "    Clearing existing data..."
  kubectl exec -n ${NAMESPACE} "${helper_name}" -- sh -c "rm -rf ${mount_path}/* ${mount_path}/.[!.]* 2>/dev/null || true" >/dev/null 2>&1

  echo "    Extracting backup..."
  kubectl exec -i -n ${NAMESPACE} "${helper_name}" -- tar xzf - -C "${mount_path}" < "${tarball}"

  kubectl delete pod -n ${NAMESPACE} "${helper_name}" --ignore-not-found=true >/dev/null 2>&1
}

RESTORED=()
FAILED=()

# --- Step 1: Scale down all services ---
echo "--- Step 1: Scaling down services ---"

DEPLOYMENTS_TO_STOP=()
[[ -d "${BACKUP_DIR}/jira-emulator" ]] && DEPLOYMENTS_TO_STOP+=("jira-emulator")
[[ -d "${BACKUP_DIR}/github-emulator" ]] && DEPLOYMENTS_TO_STOP+=("github-emulator")
[[ -d "${BACKUP_DIR}/mlflow" ]] && DEPLOYMENTS_TO_STOP+=("mlflow")
[[ -d "${BACKUP_DIR}/markovd" ]] && DEPLOYMENTS_TO_STOP+=("markovd")
[[ -d "${BACKUP_DIR}/pipeline" ]] && DEPLOYMENTS_TO_STOP+=("pipeline-dashboard")

for deploy in "${DEPLOYMENTS_TO_STOP[@]}"; do
  if kubectl get deployment "${deploy}" -n ${NAMESPACE} >/dev/null 2>&1; then
    echo "  Scaling down ${deploy}..."
    kubectl scale deployment "${deploy}" -n ${NAMESPACE} --replicas=0 >/dev/null 2>&1
  fi
done

echo "  Waiting for pods to terminate..."
for deploy in "${DEPLOYMENTS_TO_STOP[@]}"; do
  wait_for_no_pods "${deploy}" || true
done
echo ""

# --- Step 2: Restore Jira Emulator ---
if [[ -f "${BACKUP_DIR}/jira-emulator/data.tar.gz" ]]; then
  echo "--- Step 2: Restoring Jira Emulator ---"
  if run_restore_helper "jira-emulator-data" "/data" "${BACKUP_DIR}/jira-emulator/data.tar.gz"; then
    echo "  Done"
    RESTORED+=("jira-emulator")
  else
    echo "  FAILED"
    FAILED+=("jira-emulator")
  fi
  echo ""
fi

# --- Step 3: Restore GitHub Emulator ---
if [[ -f "${BACKUP_DIR}/github-emulator/data.tar.gz" ]]; then
  echo "--- Step 3: Restoring GitHub Emulator ---"
  if run_restore_helper "github-emulator-data" "/data" "${BACKUP_DIR}/github-emulator/data.tar.gz"; then
    echo "  Done"
    RESTORED+=("github-emulator")
  else
    echo "  FAILED"
    FAILED+=("github-emulator")
  fi
  echo ""
fi

# --- Step 4: Restore MLflow ---
if [[ -f "${BACKUP_DIR}/mlflow/data.tar.gz" ]]; then
  echo "--- Step 4: Restoring MLflow ---"
  if run_restore_helper "mlflow-data" "/data" "${BACKUP_DIR}/mlflow/data.tar.gz"; then
    echo "  Done"
    RESTORED+=("mlflow")
  else
    echo "  FAILED"
    FAILED+=("mlflow")
  fi
  echo ""
fi

# --- Step 5: Restore Markovd PostgreSQL ---
if [[ -f "${BACKUP_DIR}/markovd/markovd.sql" ]]; then
  echo "--- Step 5: Restoring Markovd PostgreSQL ---"
  PG_POD=$(get_pod "markovd-postgres")
  if [[ -n "$PG_POD" ]]; then
    echo "  Dropping and recreating database..."
    kubectl exec -n ${NAMESPACE} "${PG_POD}" -- dropdb -U markovd --if-exists markovd 2>/dev/null
    kubectl exec -n ${NAMESPACE} "${PG_POD}" -- createdb -U markovd markovd 2>/dev/null
    echo "  Loading SQL dump..."
    if kubectl exec -i -n ${NAMESPACE} "${PG_POD}" -- psql -U markovd -q markovd < "${BACKUP_DIR}/markovd/markovd.sql" >/dev/null 2>&1; then
      echo "  Done"
      RESTORED+=("markovd-postgres")
    else
      echo "  FAILED: psql restore error"
      FAILED+=("markovd-postgres")
    fi
  else
    echo "  WARNING: markovd-postgres pod not found (it should still be running)"
    FAILED+=("markovd-postgres")
  fi
  echo ""
fi

# --- Step 6: Restore Pipeline PVCs ---
echo "--- Step 6: Restoring Pipeline PVCs ---"

PVC_MAP=(
  "issues:pipeline-issues:/data"
  "logs:pipeline-logs:/data"
  "artifacts:pipeline-artifacts:/data"
  "workspace:pipeline-workspace:/data"
  "context:pipeline-context:/data"
  "remote-skills:pipeline-remote-skills:/data"
)

for entry in "${PVC_MAP[@]}"; do
  IFS=: read -r name pvc mount <<< "$entry"
  tarball="${BACKUP_DIR}/pipeline/${name}/data.tar.gz"
  if [[ -f "$tarball" ]]; then
    echo "  [pipeline-${name}]"
    if run_restore_helper "${pvc}" "${mount}" "${tarball}"; then
      echo "    Done"
      RESTORED+=("pipeline-${name}")
    else
      echo "    FAILED"
      FAILED+=("pipeline-${name}")
    fi
  fi
done
echo ""

# --- Step 7: Scale services back up ---
echo "--- Step 7: Scaling services back up ---"

for deploy in "${DEPLOYMENTS_TO_STOP[@]}"; do
  if kubectl get deployment "${deploy}" -n ${NAMESPACE} >/dev/null 2>&1; then
    echo "  Scaling up ${deploy}..."
    kubectl scale deployment "${deploy}" -n ${NAMESPACE} --replicas=1 >/dev/null 2>&1
  fi
done

echo "  Waiting for services to become ready..."
for deploy in "${DEPLOYMENTS_TO_STOP[@]}"; do
  wait_for_pod_ready "${deploy}"
done
echo ""

echo "=========================================="
echo "Restore Complete"
echo "=========================================="
echo ""
echo "Restored: ${#RESTORED[@]} services"
if [[ ${#RESTORED[@]} -gt 0 ]]; then
  echo "  ${RESTORED[*]}"
fi
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo ""
  echo "FAILED: ${#FAILED[@]} services"
  echo "  ${FAILED[*]}"
  exit 1
fi
