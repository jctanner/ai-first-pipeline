#!/bin/bash
# Clean up benchmark artifacts so a fresh run starts from scratch.
# Run from the project root.
#
# Usage: bash scripts/clean-benchmark.sh [--dry-run]

set -euo pipefail

MLFLOW_URL="${MLFLOW_URL:-https://mlflow.local}"
MLFLOW_EXPERIMENT="arch-context-access-benchmark"
PVC_RESULTS_DIR="/app/artifacts/benchmarks/arch-context/results"
NAMESPACE="ai-pipeline"
DRY_RUN=false

if [[ "${1:-}" == "--dry-run" ]]; then
    DRY_RUN=true
    echo "[DRY RUN] No changes will be made."
    echo
fi

run() {
    if $DRY_RUN; then
        echo "  [skip] $*"
    else
        "$@"
    fi
}

echo "=== Benchmark Cleanup ==="
echo

# ── 1. Delete old benchmark results from PVC ─────────────────────
echo "[1/3] Clearing benchmark results on PVC..."
DASHBOARD_POD=$(kubectl get pods -n $NAMESPACE -l app=pipeline-dashboard --field-selector=status.phase=Running -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

if [[ -z "$DASHBOARD_POD" ]]; then
    echo "  Dashboard pod not available, using temporary pod to clear PVC..."
    if $DRY_RUN; then
        echo "  [skip] would delete $PVC_RESULTS_DIR/{answers,judgments,benchmark-summary.*,.scripts}"
    else
        kubectl run pvc-clean --rm -i --restart=Never --image=busybox -n $NAMESPACE \
            --overrides="{\"spec\":{\"containers\":[{\"name\":\"pvc-clean\",\"image\":\"busybox\",\"command\":[\"sh\",\"-c\",\"rm -rf $PVC_RESULTS_DIR/answers $PVC_RESULTS_DIR/judgments $PVC_RESULTS_DIR/benchmark-summary.* $PVC_RESULTS_DIR/.scripts && echo done\"],\"volumeMounts\":[{\"name\":\"artifacts\",\"mountPath\":\"/app/artifacts\"}]}],\"volumes\":[{\"name\":\"artifacts\",\"persistentVolumeClaim\":{\"claimName\":\"pipeline-artifacts\"}}]}}" 2>&1 | tail -5
    fi
else
    run kubectl exec -n $NAMESPACE $DASHBOARD_POD -c dashboard -- sh -c "rm -rf $PVC_RESULTS_DIR/answers $PVC_RESULTS_DIR/judgments $PVC_RESULTS_DIR/benchmark-summary.* $PVC_RESULTS_DIR/.scripts && echo done" 2>&1
fi
echo "  ✓ PVC results cleared"
echo

# ── 2. Delete MLflow experiment and recreate empty ────────────────
echo "[2/3] Resetting MLflow experiment..."
EXPERIMENT_ID=$(curl -sk "$MLFLOW_URL/api/2.0/mlflow/experiments/get-by-name?experiment_name=$MLFLOW_EXPERIMENT" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('experiment',{}).get('experiment_id',''))" 2>/dev/null || true)

if [[ -n "$EXPERIMENT_ID" && "$EXPERIMENT_ID" != "None" ]]; then
    echo "  Found experiment $EXPERIMENT_ID"

    # Delete experiment (moves to trash)
    run curl -sk -X POST "$MLFLOW_URL/api/2.0/mlflow/experiments/delete" \
        -H 'Content-Type: application/json' \
        -d "{\"experiment_id\": \"$EXPERIMENT_ID\"}" -o /dev/null

    # Recreate with same name
    run curl -sk -X POST "$MLFLOW_URL/api/2.0/mlflow/experiments/create" \
        -H 'Content-Type: application/json' \
        -d "{\"name\": \"$MLFLOW_EXPERIMENT\"}" -o /dev/null

    echo "  ✓ Experiment deleted and recreated"
else
    echo "  No existing experiment found, nothing to clean"
fi
echo

# ── 3. Kill markov jobs ───────────────────────────────────────────
echo "[3/3] Cleaning up markov jobs..."
run make host-markov-kill
echo

echo "=== Cleanup Complete ==="
