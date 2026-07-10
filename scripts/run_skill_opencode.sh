#!/bin/bash
# K8s job wrapper - runs skills via OpenCode CLI

set -euo pipefail

# Save full pod log as artifact
LOG_DIR="/app/artifacts/jobs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
exec > >(tee -a "${LOG_DIR}/${PIPELINE_JOB_NAME:-$(hostname)}.log") 2>&1

# Parse arguments
SKILL=""
FQN=""
ISSUE_KEY=""
MODEL="google-vertex-anthropic/claude-opus-4-6@default"
FORCE=""
declare -a EXTRA_VARS=()

while [[ $# -gt 0 ]]; do
  case $1 in
    --skill)
      SKILL="$2"
      shift 2
      ;;
    --fqn)
      FQN="$2"
      shift 2
      ;;
    --issue)
      ISSUE_KEY="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --force)
      FORCE="--force"
      shift
      ;;
    --extra-vars)
      EXTRA_VARS+=("$2")
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [ -z "$SKILL" ] && [ -z "$FQN" ]; then
  echo "Usage: $0 --skill <skill-name> [--issue <issue-key>] [--model <model>] [--force]"
  echo "   or: $0 --fqn <host/owner/repo@ref:skill> [--issue <issue-key>] [--model <model>] [--force]"
  exit 1
fi

# Include skill+issue in job tag so strace/apibodies dirs are discoverable by issue key
if [ -n "$ISSUE_KEY" ]; then
  export PIPELINE_JOB_NAME="${SKILL:-opencode}-${ISSUE_KEY}"
fi

echo "============================================================"
echo "Running skill: ${FQN:-$SKILL}"
echo "Issue: $ISSUE_KEY"
echo "Model: $MODEL"
echo "Harness: OpenCode (CLI)"
echo "============================================================"
echo

# Configure SSL certificate bundle
if [ -f /shared/ca-certificates.crt ]; then
  export SSL_CERT_FILE=/shared/ca-certificates.crt
  export REQUESTS_CA_BUNDLE=/shared/ca-certificates.crt
  echo "Using custom CA certificate bundle"
fi

# Configure git to use HTTPS instead of SSH for GitHub
git config --global url."https://github.com/".insteadOf "git@github.com:"

# ---------------------------------------------------------------------------
# FQN resolution: clone repo if --fqn was provided
# ---------------------------------------------------------------------------
FQN_CLONE_DIR=""
SKILL_NAME=""
if [ -n "$FQN" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  source "$SCRIPT_DIR/resolve_fqn.sh"
fi

echo

# Ensure OpenCode config dir is writable (K8s volume mounts can make ~/.config root-owned)
if ! mkdir -p "$HOME/.config/opencode" 2>/dev/null; then
  export XDG_CONFIG_HOME="/tmp/opencode-config"
  mkdir -p "$XDG_CONFIG_HOME/opencode"
  cp "$HOME/.config/opencode/opencode.json" "$XDG_CONFIG_HOME/opencode/" 2>/dev/null || true
  echo "Using fallback config dir: $XDG_CONFIG_HOME"
fi

# Resolve MLflow experiment name to ID (required by @mlflow/opencode plugin)
# NOTE: MLflow tracing via @mlflow/opencode does NOT work in CLI mode.
# OpenCode's process.exit() kills the process before the plugin can flush traces.
# Use SDK runner mode (--runner sdk) for MLflow tracing with OpenCode.
if [ -n "${MLFLOW_TRACKING_URI:-}" ] && [ -n "${MLFLOW_EXPERIMENT_NAME:-}" ]; then
  echo "WARNING: MLflow tracing is unreliable in OpenCode CLI mode (use SDK runner instead)"
  MLFLOW_EXPERIMENT_ID=$(python3 -c "
import mlflow, os
mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI'])
exp = mlflow.set_experiment(os.environ['MLFLOW_EXPERIMENT_NAME'])
print(exp.experiment_id)
" 2>/dev/null) || true
  if [ -n "$MLFLOW_EXPERIMENT_ID" ]; then
    export MLFLOW_EXPERIMENT_ID
    echo "MLflow experiment: $MLFLOW_EXPERIMENT_NAME (ID: $MLFLOW_EXPERIMENT_ID)"
  fi
fi

# OpenCode uses environment variables for Vertex AI
export GOOGLE_CLOUD_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_LOCATION="${CLOUD_ML_REGION:-global}"

# Resolve skill name from pipeline-skills.yaml (falls back to dash-to-dot conversion)
# When --fqn was used, SKILL_NAME is already set by resolve_fqn.sh
if [ -z "$SKILL_NAME" ]; then
  SKILL_NAME=$(python3 -c "
import yaml
with open('/app/var/pipeline-skills.yaml') as f:
    cfg = yaml.safe_load(f)
skills = cfg.get('skills') or cfg.get('phases') or {}
if '${SKILL}' in skills:
    print(skills['${SKILL}']['skill'])
else:
    print('${SKILL}'.replace('-', '.'))
" 2>/dev/null)
fi

echo "Skill name: $SKILL_NAME"
echo

# Create artifact and context directories if they don't exist
mkdir -p /app/artifacts/rfe-tasks /app/artifacts/strat-tasks /app/tmp /app/.context

# Build the prompt — OpenCode uses plain text, not /skill slash commands
# Read the SKILL.md content if available in the cloned repo or local skills
SKILL_MD=""
if [ -n "$FQN_CLONE_DIR" ]; then
  SKILL_MD_PATH="$FQN_CLONE_DIR/.claude/skills/$SKILL_NAME/SKILL.md"
  if [ -f "$SKILL_MD_PATH" ]; then
    SKILL_MD=$(cat "$SKILL_MD_PATH")
  fi
elif [ -f "/app/.claude/skills/$SKILL_NAME/SKILL.md" ]; then
  SKILL_MD=$(cat "/app/.claude/skills/$SKILL_NAME/SKILL.md")
fi

PROMPT=""
if [ -n "$SKILL_MD" ]; then
  PROMPT="$SKILL_MD"
  if [ -n "$FORCE" ]; then
    PROMPT="$PROMPT"$'\n\nNote: --force flag is set. Regenerate outputs even if they already exist.'
  fi
  if [ -n "$ISSUE_KEY" ]; then
    PROMPT="$PROMPT"$'\n\nTarget issue: '"$ISSUE_KEY"
  fi
else
  PROMPT="Run the $SKILL_NAME skill${FORCE:+ with --force}${ISSUE_KEY:+ for issue $ISSUE_KEY}"
fi

# Append extra vars as prompt context
if [ ${#EXTRA_VARS[@]} -gt 0 ]; then
  PROMPT="$PROMPT"$'\n\n## Inputs'
  for VAR in "${EXTRA_VARS[@]}"; do
    KEY="${VAR%%=*}"
    VALUE="${VAR#*=}"
    PROMPT="$PROMPT"$'\n'"- $KEY: $VALUE"
  done
fi

# Change to FQN clone directory if applicable
if [ -n "$FQN_CLONE_DIR" ]; then
  cd "$FQN_CLONE_DIR"
fi

echo "Working directory: $(pwd)"
echo "Starting execution at: $(date)"
echo

# OpenTelemetry (generic OTEL env vars — OpenCode may respect these)
if [ "${ENABLE_OTEL:-1}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  APIBODIES_DIR="/app/artifacts/apibodies/${JOB_TAG}"
  mkdir -p "$APIBODIES_DIR"
  OBSERVATORY_URL="${OBSERVATORY_URL:-http://observatory.ai-pipeline.svc.cluster.local:8000}"
  export OTEL_EXPORTER_OTLP_PROTOCOL=http/json
  export OTEL_EXPORTER_OTLP_ENDPOINT="${OBSERVATORY_URL}/otel"
  export OTEL_METRICS_EXPORTER=otlp
  export OTEL_LOGS_EXPORTER=otlp
  export OTEL_TRACES_EXPORTER=otlp
  echo "OTel telemetry enabled: OTLP -> ${OBSERVATORY_URL}/otel"
else
  echo "OTel telemetry disabled"
fi

# Set up FIFO for streaming output
opencode_fifo="/tmp/opencode-stream.fifo"
rm -f "$opencode_fifo"
mkfifo "$opencode_fifo"

# Optional strace wrapper
STRACE_CMD=""
if [ "${ENABLE_STRACE:-}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  STRACE_DIR="/app/artifacts/strace/${JOB_TAG}"
  mkdir -p "$STRACE_DIR"
  STRACE_CMD="strace -ffttv -s 1024 -o ${STRACE_DIR}/${JOB_TAG}"
  echo "strace enabled: output -> $STRACE_DIR"
fi

# Run OpenCode in background, streaming to FIFO
# --model requires provider/model format (e.g. "google-vertex-anthropic/claude-opus-4-6")
$STRACE_CMD opencode run --model "$MODEL" --format json \
  --dangerously-skip-permissions "$PROMPT" 2>/tmp/opencode-stderr.log > "$opencode_fifo" &
opencode_pid=$!

# Parse stream with OpenCode-specific parser
python3 -u /app/scripts/stream-opencode.py --pid "$opencode_pid" < "$opencode_fifo"

EXIT_CODE=$?
echo
echo "Execution finished at: $(date)"
echo "Exit code: $EXIT_CODE"

echo
echo "============================================================"
echo "Skill execution complete (OpenCode CLI)"
echo "============================================================"

exit $EXIT_CODE
