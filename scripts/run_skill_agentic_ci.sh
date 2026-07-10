#!/bin/bash
# K8s job wrapper - runs skills via agentic-ci (local backend)
#
# Flow:
#   1. Resolve skill (registered or FQN clone)
#   2. Build prompt from SKILL.md
#   3. Run `agentic-ci run --backend local` (handles agent + OTEL)
#   4. Push OTEL traces to MLflow if enabled

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

# Include skill+issue in job tag
if [ -n "$ISSUE_KEY" ]; then
  export PIPELINE_JOB_NAME="${SKILL:-agentic-ci}-${ISSUE_KEY}"
fi

HARNESS="${AGENTIC_CI_HARNESS:-opencode}"

echo "============================================================"
echo "Running skill: ${FQN:-$SKILL}"
echo "Issue: $ISSUE_KEY"
echo "Model: $MODEL"
echo "Harness: $HARNESS (agentic-ci / local backend)"
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

# Ensure OpenCode config dir is writable and enable native OTel
if [ "$HARNESS" = "opencode" ]; then
  OC_CONFIG_DIR="$HOME/.config/opencode"
  if ! mkdir -p "$OC_CONFIG_DIR" 2>/dev/null; then
    export XDG_CONFIG_HOME="/tmp/opencode-config"
    OC_CONFIG_DIR="$XDG_CONFIG_HOME/opencode"
    mkdir -p "$OC_CONFIG_DIR"
    cp "$HOME/.config/opencode/opencode.json" "$OC_CONFIG_DIR/" 2>/dev/null || true
    echo "Using fallback config dir: $XDG_CONFIG_HOME"
  fi

  # Enable native OpenTelemetry so agentic-ci's OTEL collector captures spans.
  # Remove the @mlflow/opencode plugin — agentic-ci handles MLflow push via
  # its own OTEL collector, so the plugin would double-push traces.
  python3 -c "
import json, os
cfg_path = os.path.join('$OC_CONFIG_DIR', 'opencode.json')
cfg = {}
if os.path.exists(cfg_path):
    with open(cfg_path) as f:
        cfg = json.load(f)
cfg.pop('plugin', None)
if '${ENABLE_OTEL:-1}' == '1':
    cfg.setdefault('experimental', {})['openTelemetry'] = True
with open(cfg_path, 'w') as f:
    json.dump(cfg, f, indent=2)
"
  if [ "${ENABLE_OTEL:-1}" = "1" ]; then
    echo "OpenCode native OTel enabled (mlflow plugin removed)"
  fi
fi

# Vertex AI env vars (used by both OpenCode and Claude Code with Vertex)
export GOOGLE_CLOUD_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_LOCATION="${CLOUD_ML_REGION:-global}"

# Resolve skill name from pipeline-skills.yaml
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

# Build the prompt
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

# Append extra vars
if [ ${#EXTRA_VARS[@]} -gt 0 ]; then
  PROMPT="$PROMPT"$'\n\n## Inputs'
  for VAR in "${EXTRA_VARS[@]}"; do
    KEY="${VAR%%=*}"
    VALUE="${VAR#*=}"
    PROMPT="$PROMPT"$'\n'"- $KEY: $VALUE"
  done
fi

# Change to FQN clone directory if applicable
WORK_DIR="/app"
if [ -n "$FQN_CLONE_DIR" ]; then
  WORK_DIR="$FQN_CLONE_DIR"
  cd "$FQN_CLONE_DIR"
fi

echo "Working directory: $(pwd)"
echo "Starting execution at: $(date)"
echo

# ---------------------------------------------------------------------------
# Run via agentic-ci
# ---------------------------------------------------------------------------

OTEL_FLAG=""
if [ "${ENABLE_OTEL:-1}" = "1" ]; then
  export OTEL_BSP_SCHEDULE_DELAY=0
  export CI_PROJECT_DIR="$LOG_DIR"
  echo "OTel telemetry enabled (agentic-ci native collector, BSP_SCHEDULE_DELAY=0)"
else
  OTEL_FLAG="--no-otel"
  echo "OTel telemetry disabled"
fi

echo "=== Agent Output ==="
echo

agentic-ci run \
  --backend local \
  --harness "$HARNESS" \
  --model "$MODEL" \
  --workdir "$WORK_DIR" \
  $OTEL_FLAG \
  "$PROMPT"

EXIT_CODE=$?

echo
echo "=== Execution Complete ==="
echo

# ---------------------------------------------------------------------------
# MLflow trace push
# ---------------------------------------------------------------------------
# agentic-ci copies claude-otel.jsonl to CI_PROJECT_DIR (set to LOG_DIR above)
OTEL_JSONL="$LOG_DIR/claude-otel.jsonl"

if [ -n "${MLFLOW_TRACKING_URI:-}" ] && [ -n "${MLFLOW_EXPERIMENT_NAME:-}" ] && [ -f "$OTEL_JSONL" ]; then
  echo "Pushing OTEL traces to MLflow..."
  agentic-ci mlflow-push "$OTEL_JSONL" \
    --endpoint "$MLFLOW_TRACKING_URI" \
    --experiment "$MLFLOW_EXPERIMENT_NAME" || true
  echo
fi

echo "Execution finished at: $(date)"
echo "Exit code: $EXIT_CODE"

echo
echo "============================================================"
echo "Skill execution complete (agentic-ci / $HARNESS)"
echo "============================================================"

exit $EXIT_CODE
