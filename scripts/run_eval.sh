#!/bin/bash
# K8s job wrapper - runs agent-eval-harness evaluations

set -euo pipefail

# Save full pod log as artifact
LOG_DIR="/app/artifacts/jobs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
exec > >(tee -a "${LOG_DIR}/${PIPELINE_JOB_NAME:-$(hostname)}.log") 2>&1

# Parse arguments
DATASET_FQN=""
MODEL="opus"
BASELINE=""
RUN_ID=""
CONTEXT_REPO="https://github.com/opendatahub-io/architecture-context"
CONTEXT_REF="main"
CONTEXT_MODE="files"
EVAL_HARNESS="https://github.com/opendatahub-io/agent-eval-harness"

while [[ $# -gt 0 ]]; do
  case $1 in
    --dataset-fqn)
      DATASET_FQN="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --baseline)
      BASELINE="$2"
      shift 2
      ;;
    --run-id)
      RUN_ID="$2"
      shift 2
      ;;
    --context-repo)
      CONTEXT_REPO="$2"
      shift 2
      ;;
    --context-ref)
      CONTEXT_REF="$2"
      shift 2
      ;;
    --context-mode)
      CONTEXT_MODE="$2"
      shift 2
      ;;
    --eval-harness)
      EVAL_HARNESS="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [ -z "$DATASET_FQN" ]; then
  echo "Usage: $0 --dataset-fqn <host/owner/repo@ref:eval-config> [--model <model>] [--context-ref <branch>] [--context-mode <files|arch-query>] [--baseline <run-id>] [--run-id <id>] [--eval-harness <url>]"
  exit 1
fi

# Parse FQN: host/owner/repo@ref:eval-config
FQN_REMAINDER="$DATASET_FQN"
EVAL_CONFIG="${FQN_REMAINDER##*:}"
FQN_REMAINDER="${FQN_REMAINDER%:*}"
DATASET_REF="${FQN_REMAINDER##*@}"
FQN_REMAINDER="${FQN_REMAINDER%@*}"
IFS='/' read -r DATASET_HOST DATASET_OWNER DATASET_REPO <<< "$FQN_REMAINDER"

if [ -z "$DATASET_HOST" ] || [ -z "$DATASET_OWNER" ] || [ -z "$DATASET_REPO" ] || [ -z "$DATASET_REF" ] || [ -z "$EVAL_CONFIG" ]; then
  echo "ERROR: Failed to parse FQN: $DATASET_FQN"
  echo "  Expected format: host/owner/repo@ref:eval-config"
  exit 1
fi

# Map short hostnames to cluster-internal FQDNs
map_host() {
  local h="$1"
  case "$h" in
    github.local) echo "github-emulator.ai-pipeline.svc.cluster.local" ;;
    *) echo "$h" ;;
  esac
}

GITHUB_HOST=$(map_host "$DATASET_HOST")

echo "============================================================"
echo "Running eval: $EVAL_CONFIG"
echo "Dataset: ${DATASET_OWNER}/${DATASET_REPO}@${DATASET_REF}"
echo "Model: $MODEL"
echo "Context repo: $CONTEXT_REPO"
echo "Context ref: $CONTEXT_REF"
echo "Context mode: $CONTEXT_MODE"
echo "Eval harness: $EVAL_HARNESS"
echo "Baseline: ${BASELINE:-none}"
echo "============================================================"
echo

# Configure SSL certificate bundle
if [ -f /shared/ca-certificates.crt ]; then
  export SSL_CERT_FILE=/shared/ca-certificates.crt
  export REQUESTS_CA_BUNDLE=/shared/ca-certificates.crt
  echo "Using custom CA certificate bundle"
fi

# Configure git to use HTTPS instead of SSH
git config --global url."https://github.com/".insteadOf "git@github.com:"

# ---------------------------------------------------------------------------
# Clone and install agent-eval-harness
# ---------------------------------------------------------------------------
# Map github.local in the harness URL to the cluster-internal FQDN
EVAL_HARNESS_URL="$EVAL_HARNESS"
EVAL_HARNESS_URL="${EVAL_HARNESS_URL/https:\/\/github.local/https:\/\/github-emulator.ai-pipeline.svc.cluster.local}"
EVAL_HARNESS_URL="${EVAL_HARNESS_URL/http:\/\/github.local/https:\/\/github-emulator.ai-pipeline.svc.cluster.local}"

EVAL_HARNESS_DIR="/tmp/eval-workspace/agent-eval-harness"
if [ ! -d "$EVAL_HARNESS_DIR" ]; then
  echo "Cloning agent-eval-harness from $EVAL_HARNESS_URL..."
  mkdir -p /tmp/eval-workspace
  git clone --depth 1 "$EVAL_HARNESS_URL" "$EVAL_HARNESS_DIR"
fi
echo "Installing agent-eval-harness..."
pip install -e "$EVAL_HARNESS_DIR" 2>&1 | tail -5
export PATH="/home/pipelineagent/.local/bin:$PATH"

# ---------------------------------------------------------------------------
# Clone dataset repo
# ---------------------------------------------------------------------------
DATASET_DIR="/tmp/eval-workspace/${DATASET_OWNER}-${DATASET_REPO}"
if [ -d "$DATASET_DIR" ]; then
  echo "Dataset repo already cloned, fetching latest..."
  git -C "$DATASET_DIR" fetch origin "$DATASET_REF" --depth 1 2>/dev/null || true
  git -C "$DATASET_DIR" checkout FETCH_HEAD 2>/dev/null || true
else
  echo "Cloning dataset repo: ${DATASET_OWNER}/${DATASET_REPO}@${DATASET_REF}..."
  git clone --depth 1 -b "$DATASET_REF" "https://${GITHUB_HOST}/${DATASET_OWNER}/${DATASET_REPO}.git" "$DATASET_DIR"
fi

# ---------------------------------------------------------------------------
# Clone architecture-context at specified ref
# ---------------------------------------------------------------------------
CONTEXT_CLONE_URL="$CONTEXT_REPO"
CONTEXT_CLONE_URL="${CONTEXT_CLONE_URL/https:\/\/github.local/https:\/\/github-emulator.ai-pipeline.svc.cluster.local}"
CONTEXT_CLONE_URL="${CONTEXT_CLONE_URL/http:\/\/github.local/https:\/\/github-emulator.ai-pipeline.svc.cluster.local}"

CONTEXT_DIR="/tmp/eval-workspace/architecture-context"
if [ -d "$CONTEXT_DIR" ]; then
  echo "Architecture-context already cloned, switching to ref: $CONTEXT_REF..."
  git -C "$CONTEXT_DIR" fetch origin "$CONTEXT_REF" --depth 1 2>/dev/null || true
  git -C "$CONTEXT_DIR" checkout FETCH_HEAD 2>/dev/null || true
else
  echo "Cloning architecture-context from $CONTEXT_CLONE_URL at ref: $CONTEXT_REF..."
  git clone --depth 1 -b "$CONTEXT_REF" "$CONTEXT_CLONE_URL" "$CONTEXT_DIR"
fi

# ---------------------------------------------------------------------------
# Context mode setup
# ---------------------------------------------------------------------------
export ARCH_CONTEXT_MODE="$CONTEXT_MODE"

if [ "$CONTEXT_MODE" = "arch-query" ]; then
  echo "Building arch-query binary..."
  if command -v go >/dev/null 2>&1; then
    (cd "$CONTEXT_DIR" && make build 2>&1) || {
      echo "WARNING: arch-query build failed, falling back to files mode"
      CONTEXT_MODE="files"
      export ARCH_CONTEXT_MODE="files"
    }
    if [ "$CONTEXT_MODE" = "arch-query" ]; then
      export PATH="${CONTEXT_DIR}/bin:$PATH"
      echo "arch-query binary available on PATH"
    fi
  else
    echo "WARNING: Go not available, falling back to files mode"
    CONTEXT_MODE="files"
    export ARCH_CONTEXT_MODE="files"
  fi
fi

if [ "$CONTEXT_MODE" = "files" ]; then
  export ARCH_CONTEXT_PATH="${CONTEXT_DIR}/architecture"
  echo "Context mode: files (ARCH_CONTEXT_PATH=$ARCH_CONTEXT_PATH)"
else
  export ARCH_CONTEXT_PATH="${CONTEXT_DIR}"
  echo "Context mode: arch-query"
fi

# ---------------------------------------------------------------------------
# Configure Claude CLI for Vertex AI
# ---------------------------------------------------------------------------
echo "Configuring Claude CLI for Vertex AI..."
python3 -c "
import json
import os

settings_file = os.path.expanduser('~/.claude/settings.json')
settings_dir = os.path.dirname(settings_file)
settings = {}

os.makedirs(settings_dir, exist_ok=True)

if os.path.exists(settings_file):
    with open(settings_file, 'r') as f:
        settings = json.load(f)

settings['apiProvider'] = 'vertex'
settings['vertexProjectId'] = os.environ.get('ANTHROPIC_VERTEX_PROJECT_ID', '')
settings['vertexRegion'] = os.environ.get('CLOUD_ML_REGION', 'global')

with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print('Vertex AI settings merged')
"

echo

# ---------------------------------------------------------------------------
# Configure MLflow
# ---------------------------------------------------------------------------
if [ -n "${MLFLOW_TRACKING_URI:-}" ]; then
  echo "Configuring MLflow tracing for Claude CLI..."
  MLFLOW_AUTOLOG_ARGS=(-u "$MLFLOW_TRACKING_URI" -d /home/pipelineagent)
  if [ -n "${MLFLOW_EXPERIMENT_NAME:-}" ]; then
    MLFLOW_AUTOLOG_ARGS+=(-n "$MLFLOW_EXPERIMENT_NAME")
  fi
  /app/.venv/bin/mlflow autolog claude "${MLFLOW_AUTOLOG_ARGS[@]}"
  echo "MLflow tracing configured"
else
  echo "Warning: MLFLOW_TRACKING_URI not set, skipping MLflow tracing setup"
fi

echo

# ---------------------------------------------------------------------------
# OpenTelemetry
# ---------------------------------------------------------------------------
if [ "${ENABLE_OTEL:-1}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  APIBODIES_DIR="/app/artifacts/apibodies/${JOB_TAG}"
  mkdir -p "$APIBODIES_DIR"
  OBSERVATORY_URL="${OBSERVATORY_URL:-http://observatory.ai-pipeline.svc.cluster.local:8000}"
  export CLAUDE_CODE_ENABLE_TELEMETRY=1
  export CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1
  export OTEL_EXPORTER_OTLP_PROTOCOL=http/json
  export OTEL_EXPORTER_OTLP_ENDPOINT="${OBSERVATORY_URL}/otel"
  export OTEL_METRICS_EXPORTER=otlp
  export OTEL_LOGS_EXPORTER=otlp
  export OTEL_TRACES_EXPORTER=otlp
  export OTEL_LOG_USER_PROMPTS=1
  export OTEL_LOG_TOOL_DETAILS=1
  export OTEL_LOG_TOOL_CONTENT=1
  export OTEL_LOG_RAW_API_BODIES="file:${APIBODIES_DIR}"
  export OTEL_METRIC_EXPORT_INTERVAL=10000
  export OTEL_LOGS_EXPORT_INTERVAL=5000
  export OTEL_TRACES_EXPORT_INTERVAL=5000
  echo "OTel telemetry enabled: OTLP -> ${OBSERVATORY_URL}/otel, API bodies -> $APIBODIES_DIR"
else
  echo "OTel telemetry disabled"
fi

# ---------------------------------------------------------------------------
# Strace
# ---------------------------------------------------------------------------
STRACE_CMD=""
if [ "${ENABLE_STRACE:-}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  STRACE_DIR="/app/artifacts/strace/${JOB_TAG}"
  mkdir -p "$STRACE_DIR"
  STRACE_CMD="strace -ffttv -s 1024 -o ${STRACE_DIR}/${JOB_TAG}"
  echo "strace enabled: output -> $STRACE_DIR"
fi

# ---------------------------------------------------------------------------
# Prepare artifacts directory
# ---------------------------------------------------------------------------
mkdir -p /app/artifacts/eval-runs

# ---------------------------------------------------------------------------
# Build the eval prompt
# ---------------------------------------------------------------------------
PROMPT="/eval-run --config ${EVAL_CONFIG}/eval.yaml --model $MODEL"
if [ -n "$RUN_ID" ]; then
  PROMPT="$PROMPT --run-id $RUN_ID"
fi
if [ -n "$BASELINE" ]; then
  PROMPT="$PROMPT --baseline $BASELINE"
fi

echo
echo "Working directory: $DATASET_DIR"
echo "Executing: claude --model $MODEL --print \"$PROMPT\""
echo "Starting execution at: $(date)"
echo

# ---------------------------------------------------------------------------
# Run Claude with streaming
# ---------------------------------------------------------------------------
claude_fifo="/tmp/claude-stream.fifo"
rm -f "$claude_fifo"
mkfifo "$claude_fifo"

cd "$DATASET_DIR"

$STRACE_CMD claude --model "$MODEL" --print --dangerously-skip-permissions \
  --plugin-dir "$EVAL_HARNESS_DIR" \
  --output-format stream-json --include-partial-messages \
  --include-hook-events --verbose "$PROMPT" 2>/tmp/claude-stderr.log > "$claude_fifo" &
claude_pid=$!

python3 -u /app/scripts/stream-claude.py --claude-pid "$claude_pid" < "$claude_fifo"

EXIT_CODE=$?
echo
echo "Execution finished at: $(date)"
echo "Exit code: $EXIT_CODE"

# Copy results to persistent artifacts — the agent may have generated its own run-id
mkdir -p /app/artifacts/eval-runs
for run_dir in eval/runs/*/; do
  [ -d "$run_dir" ] || continue
  run_name=$(basename "$run_dir")
  cp -r "$run_dir" "/app/artifacts/eval-runs/"
  echo "Results copied to /app/artifacts/eval-runs/$run_name"
done

echo
echo "============================================================"
echo "Eval execution complete"
echo "============================================================"
