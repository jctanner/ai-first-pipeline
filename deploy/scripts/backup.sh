#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="ai-pipeline"
BACKUP_ROOT="/vagrant/backups"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
BACKUP_DIR="${BACKUP_ROOT}/${TIMESTAMP}"
INCLUDE_WORKSPACE=false
INCLUDE_CONTEXT=false
BACKED_UP=()
SKIPPED=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --include-workspace) INCLUDE_WORKSPACE=true; shift ;;
    --include-context) INCLUDE_CONTEXT=true; shift ;;
    -h|--help)
      echo "Usage: backup.sh [--include-workspace] [--include-context]"
      echo ""
      echo "Backs up all ai-pipeline service data to /vagrant/backups/<timestamp>/"
      echo ""
      echo "Flags:"
      echo "  --include-workspace  Include pipeline-workspace PVC (50Gi, slow)"
      echo "  --include-context    Include pipeline-context and pipeline-remote-skills PVCs"
      exit 0
      ;;
    *) echo "Unknown flag: $1"; exit 1 ;;
  esac
done

echo "=========================================="
echo "AI Pipeline System Backup"
echo "=========================================="
echo ""
echo "Backup directory: ${BACKUP_DIR}"
echo "Timestamp: ${TIMESTAMP}"
echo ""

if ! kubectl get namespace ${NAMESPACE} >/dev/null 2>&1; then
  echo "ERROR: Namespace ${NAMESPACE} not found. Is k3s running?"
  exit 1
fi

mkdir -p "${BACKUP_DIR}"

get_pod() {
  kubectl get pods -n ${NAMESPACE} -l "app=$1" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo ""
}

backup_pod_tar() {
  local label=$1 src_dir=$2 dest_dir=$3 container_flag=""
  if [[ -n "${4:-}" ]]; then
    container_flag="-c $4"
  fi

  local pod
  pod=$(get_pod "$label")
  if [[ -z "$pod" ]]; then
    echo "  WARNING: No pod found for app=${label}, skipping"
    SKIPPED+=("$label")
    return 0
  fi

  mkdir -p "${dest_dir}"
  echo "  Backing up ${src_dir} from pod ${pod}..."
  if kubectl exec -n ${NAMESPACE} ${container_flag} "${pod}" -- tar czf - -C "${src_dir}" . > "${dest_dir}/data.tar.gz" 2>/dev/null; then
    local size
    size=$(du -sh "${dest_dir}/data.tar.gz" | cut -f1)
    echo "  Done (${size})"
    BACKED_UP+=("$label")
  else
    echo "  WARNING: Failed to backup ${label}"
    rm -f "${dest_dir}/data.tar.gz"
    SKIPPED+=("$label")
  fi
}

backup_pvc_tar() {
  local pvc_name=$1 mount_path=$2 dest_dir=$3 label=$4
  local helper_name="backup-${pvc_name}"

  mkdir -p "${dest_dir}"
  echo "  Backing up PVC ${pvc_name} via helper pod..."

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
          \"name\": \"backup\",
          \"image\": \"alpine:3.19\",
          \"command\": [\"sleep\", \"3600\"],
          \"volumeMounts\": [{
            \"name\": \"data\",
            \"mountPath\": \"${mount_path}\"
          }]
        }]
      }
    }" >/dev/null 2>&1

  if ! kubectl wait --for=condition=Ready --timeout=60s pod "${helper_name}" -n ${NAMESPACE} >/dev/null 2>&1; then
    echo "  WARNING: Helper pod failed to start for ${pvc_name}, skipping"
    kubectl delete pod -n ${NAMESPACE} "${helper_name}" --ignore-not-found=true >/dev/null 2>&1
    SKIPPED+=("$label")
    return 0
  fi

  if kubectl exec -n ${NAMESPACE} "${helper_name}" -- tar czf - -C "${mount_path}" . > "${dest_dir}/data.tar.gz" 2>/dev/null; then
    local size
    size=$(du -sh "${dest_dir}/data.tar.gz" | cut -f1)
    echo "  Done (${size})"
    BACKED_UP+=("$label")
  else
    echo "  WARNING: Failed to backup ${label}"
    rm -f "${dest_dir}/data.tar.gz"
    SKIPPED+=("$label")
  fi

  kubectl delete pod -n ${NAMESPACE} "${helper_name}" --ignore-not-found=true >/dev/null 2>&1
}

# --- Step 1: Jira Emulator ---
echo "--- Step 1/5: Jira Emulator ---"
backup_pod_tar "jira-emulator" "/data" "${BACKUP_DIR}/jira-emulator"
echo ""

# --- Step 2: GitHub Emulator ---
echo "--- Step 2/5: GitHub Emulator ---"
backup_pod_tar "github-emulator" "/data" "${BACKUP_DIR}/github-emulator"
echo ""

# --- Step 3: MLflow (image lacks tar, use helper pod against PVC) ---
echo "--- Step 3/5: MLflow ---"
backup_pvc_tar "mlflow-data" "/data" "${BACKUP_DIR}/mlflow" "mlflow"
echo ""

# --- Step 4: Markovd PostgreSQL ---
echo "--- Step 4/5: Markovd PostgreSQL ---"
PG_POD=$(get_pod "markovd-postgres")
if [[ -n "$PG_POD" ]]; then
  mkdir -p "${BACKUP_DIR}/markovd"
  echo "  Running pg_dump on pod ${PG_POD}..."
  if kubectl exec -n ${NAMESPACE} "${PG_POD}" -- pg_dump -U markovd markovd > "${BACKUP_DIR}/markovd/markovd.sql" 2>/dev/null; then
    size=$(du -sh "${BACKUP_DIR}/markovd/markovd.sql" | cut -f1)
    echo "  Done (${size})"
    BACKED_UP+=("markovd-postgres")
  else
    echo "  WARNING: pg_dump failed"
    rm -f "${BACKUP_DIR}/markovd/markovd.sql"
    SKIPPED+=("markovd-postgres")
  fi
else
  echo "  WARNING: No markovd-postgres pod found, skipping"
  SKIPPED+=("markovd-postgres")
fi
echo ""

# --- Step 5: Pipeline PVCs (via helper pods) ---
echo "--- Step 5/5: Pipeline PVCs ---"
mkdir -p "${BACKUP_DIR}/pipeline"

for pvc_info in "pipeline-issues:issues:/data" "pipeline-logs:logs:/data" "pipeline-artifacts:artifacts:/data"; do
  pvc_name="${pvc_info%%:*}"
  rest="${pvc_info#*:}"
  label="${rest%%:*}"
  mount_path="${rest##*:}"
  echo "  [pipeline-${label}]"
  backup_pvc_tar "${pvc_name}" "${mount_path}" "${BACKUP_DIR}/pipeline/${label}" "pipeline-${label}"
done

if [[ "$INCLUDE_WORKSPACE" == "true" ]]; then
  echo "  [pipeline-workspace] (this may take a while)"
  backup_pvc_tar "pipeline-workspace" "/data" "${BACKUP_DIR}/pipeline/workspace" "pipeline-workspace"
else
  echo "  [pipeline-workspace] Skipped (use --include-workspace to include)"
  SKIPPED+=("pipeline-workspace")
fi

if [[ "$INCLUDE_CONTEXT" == "true" ]]; then
  for pvc_info in "pipeline-context:context:/data" "pipeline-remote-skills:remote-skills:/data"; do
    pvc_name="${pvc_info%%:*}"
    rest="${pvc_info#*:}"
    label="${rest%%:*}"
    mount_path="${rest##*:}"
    echo "  [pipeline-${label}]"
    backup_pvc_tar "${pvc_name}" "${mount_path}" "${BACKUP_DIR}/pipeline/${label}" "pipeline-${label}"
  done
else
  echo "  [pipeline-context] Skipped (use --include-context to include)"
  echo "  [pipeline-remote-skills] Skipped (use --include-context to include)"
  SKIPPED+=("pipeline-context" "pipeline-remote-skills")
fi
echo ""

# --- Write manifest ---
K8S_VERSION=$(kubectl version -o json 2>/dev/null | jq -r '.serverVersion.gitVersion // "unknown"')
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)

cat > "${BACKUP_DIR}/manifest.json" <<EOF
{
  "timestamp": "${TIMESTAMP}",
  "hostname": "$(hostname)",
  "k8s_version": "${K8S_VERSION}",
  "namespace": "${NAMESPACE}",
  "flags": {
    "include_workspace": ${INCLUDE_WORKSPACE},
    "include_context": ${INCLUDE_CONTEXT}
  },
  "backed_up": $(printf '%s\n' "${BACKED_UP[@]}" | jq -R . | jq -s .),
  "skipped": $(printf '%s\n' "${SKIPPED[@]}" | jq -R . | jq -s .),
  "total_size": "${TOTAL_SIZE}"
}
EOF

echo "=========================================="
echo "Backup Complete"
echo "=========================================="
echo ""
echo "Location: ${BACKUP_DIR}"
echo "Total size: ${TOTAL_SIZE}"
echo "Backed up: ${#BACKED_UP[@]} services"
if [[ ${#SKIPPED[@]} -gt 0 ]]; then
  echo "Skipped: ${SKIPPED[*]}"
fi
echo ""
echo "To restore: restore.sh ${BACKUP_DIR}"
