#!/bin/bash
# K8s job wrapper - runs skills via OpenCode v2 API server
#
# Flow:
#   1. Start `opencode serve --port <port>` in background
#   2. Wait for health check
#   3. Drive the session via REST API from embedded Python
#   4. Stream SSE events for real-time output
#   5. Kill server on exit

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
  export PIPELINE_JOB_NAME="${SKILL:-opencode}-${ISSUE_KEY}"
fi

echo "============================================================"
echo "Running skill: ${FQN:-$SKILL}"
echo "Issue: $ISSUE_KEY"
echo "Model: $MODEL"
echo "Harness: OpenCode (SDK/API)"
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
if [ -n "${MLFLOW_TRACKING_URI:-}" ] && [ -n "${MLFLOW_EXPERIMENT_NAME:-}" ]; then
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

export WORK_DIR
export MODEL
export PROMPT

echo "Working directory: $(pwd)"
echo "Starting execution at: $(date)"
echo

# OpenTelemetry (generic OTEL env vars)
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

# Pick a port for the OpenCode API server
OC_PORT="${OPENCODE_PORT:-4096}"
export OPENCODE_PORT="$OC_PORT"

# Set a known password for server auth (both server and Python driver use it)
export OPENCODE_SERVER_PASSWORD="${OPENCODE_SERVER_PASSWORD:-pipeline-agent-local}"

# Start OpenCode serve in background (with strace if enabled)
echo "Starting OpenCode API server on port $OC_PORT ..."
SERVE_STRACE_CMD=""
if [ "${ENABLE_STRACE:-}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  STRACE_DIR="/app/artifacts/strace/${JOB_TAG}"
  mkdir -p "$STRACE_DIR"
  SERVE_STRACE_CMD="strace -ffttv -s 1024 -o ${STRACE_DIR}/serve"
  echo "strace enabled for serve process: output -> $STRACE_DIR/serve.*"
fi
SERVE_LOG="${LOG_DIR}/opencode-serve.log"
$SERVE_STRACE_CMD opencode serve --port "$OC_PORT" > "$SERVE_LOG" 2>&1 &
OC_PID=$!

# Ensure server is killed on exit
trap "kill $OC_PID 2>/dev/null || true" EXIT

# Wait for server health
echo -n "Waiting for server health check"
for i in $(seq 1 30); do
  if curl -sf -u "opencode:${OPENCODE_SERVER_PASSWORD}" "http://127.0.0.1:${OC_PORT}/api/health" > /dev/null 2>&1; then
    echo " ready"
    break
  fi
  if ! kill -0 "$OC_PID" 2>/dev/null; then
    echo " FAILED (server exited)"
    cat ${SERVE_LOG}
    exit 1
  fi
  echo -n "."
  sleep 1
done

# Verify server is up
if ! curl -sf -u "opencode:${OPENCODE_SERVER_PASSWORD}" "http://127.0.0.1:${OC_PORT}/api/health" > /dev/null 2>&1; then
  echo "OpenCode server failed to start within 30s"
  cat ${SERVE_LOG}
  exit 1
fi

echo

# Optional strace for the Python driver
STRACE_CMD=""
if [ "${ENABLE_STRACE:-}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  STRACE_DIR="/app/artifacts/strace/${JOB_TAG}"
  mkdir -p "$STRACE_DIR"
  STRACE_CMD="strace -ffttv -s 1024 -o ${STRACE_DIR}/driver"
  echo "strace enabled for driver: output -> $STRACE_DIR/driver.*"
fi

# Export base URL for the SDK
export OPENCODE_BASE_URL="http://127.0.0.1:${OC_PORT}"

# Drive the session via Python SDK (disable set -e so we capture the exit code
# and still run the MLflow grace period on failure)
set +e
$STRACE_CMD python3 -u << 'PYEOF'
import base64
import os
import sys
import threading
import time

from opencode_ai import Opencode
from opencode_ai.types.event_list_response import (
    EventMessagePartUpdated,
    EventSessionError,
    EventSessionIdle,
)
from opencode_ai.types.tool_part import ToolPart
from opencode_ai.types.text_part import TextPart
from opencode_ai.types.snapshot_part import SnapshotPart
from opencode_ai.types.step_finish_part import StepFinishPart

MODEL = os.environ["MODEL"]
PROMPT = os.environ["PROMPT"]

THINK_COLOR = "\033[3;31m"
TOOL_COLOR = "\033[1;90m"
RED = "\033[31m"
RESET = "\033[0m"

# Build auth header for the SDK client
_password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
_username = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
headers = {}
if _password:
    b64 = base64.b64encode(f"{_username}:{_password}".encode()).decode()
    headers["Authorization"] = f"Basic {b64}"

client = Opencode(
    base_url=os.environ["OPENCODE_BASE_URL"],
    default_headers=headers,
    timeout=1800.0,
)

# Split model into providerID and modelID
parts = MODEL.split("/", 1)
if len(parts) == 2:
    provider_id, model_id = parts
else:
    provider_id, model_id = "anthropic", parts[0]


def format_tool(name, params):
    if not params:
        return ""
    if name in ("bash", "Bash"):
        return str(params.get("command", ""))
    if name in ("read", "Read"):
        return str(params.get("file_path", params.get("path", "")))
    if name in ("write", "Write", "edit", "Edit"):
        return str(params.get("file_path", params.get("path", "")))
    return ", ".join(f"{k}={v}" for k, v in list(params.items())[:3])


# Create session
print("Creating session...")
session = client.session.create()
session_id = session.id
print(f"Session: {session_id}")
print()

# SSE listener for real-time output
session_error = None
events_done = threading.Event()


def listen_events():
    global session_error
    try:
        for event in client.event.list():
            if isinstance(event, EventMessagePartUpdated):
                part = event.properties.part
                if getattr(part, "session_id", None) != session_id:
                    continue

                if isinstance(part, ToolPart):
                    if part.state.status == "completed":
                        params = part.state.input
                        summary = format_tool(part.tool, params)
                        line = f"  {TOOL_COLOR}\U0001f527 {part.tool}"
                        if summary:
                            line += f" {summary}"
                        line += RESET
                        print(line, flush=True)
                    elif part.state.status == "error":
                        err = part.state.error
                        print(f"  {RED}✗ {part.tool} error: {err}{RESET}", flush=True)

                elif isinstance(part, SnapshotPart):
                    if part.snapshot:
                        print(f"{THINK_COLOR}\U0001f9e0 Thinking {part.snapshot[:200]}{RESET}", flush=True)

                elif isinstance(part, StepFinishPart):
                    t = part.tokens
                    if t:
                        cache_r = t.cache.read
                        cache_w = t.cache.write
                        total = int(t.input + t.output + t.reasoning + cache_r + cache_w)
                        cost_str = f" cost=${part.cost:.4f}" if part.cost else ""
                        print(
                            f"{TOOL_COLOR}  \U0001f4ca TOKENS in={int(t.input)} out={int(t.output)} "
                            f"reasoning={int(t.reasoning)} cache_r={int(cache_r)} cache_w={int(cache_w)} "
                            f"total={total}{cost_str}{RESET}",
                            flush=True,
                        )

                elif isinstance(part, TextPart):
                    if part.time and part.time.end:
                        text = part.text.strip()
                        if text:
                            print(f"\U0001f4ac {text}", flush=True)

            elif isinstance(event, EventSessionError):
                if getattr(event.properties, "session_id", None) != session_id:
                    continue
                err = event.properties.error
                err_msg = str(getattr(err, "name", "unknown")) if err else "unknown"
                session_error = err_msg
                print(f"{RED}✗ Session error: {err_msg}{RESET}", flush=True)

            elif isinstance(event, EventSessionIdle):
                if event.properties.session_id != session_id:
                    continue
                events_done.set()
                return

    except Exception as e:
        print(f"{RED}SSE listener error: {e}{RESET}", file=sys.stderr)
        session_error = str(e)
        events_done.set()


listener = threading.Thread(target=listen_events, daemon=True)
listener.start()

time.sleep(0.5)

print("=== Agent Output ===")
print()

try:
    response = client.session.chat(
        session_id,
        model_id=model_id,
        provider_id=provider_id,
        parts=[{"type": "text", "text": PROMPT, "time": {"start": int(time.time() * 1000)}}],
    )
except Exception as e:
    print(f"{RED}Chat error: {e}{RESET}", file=sys.stderr)
    sys.exit(1)

# Wait for SSE to catch up (chat() blocks until response, but events may lag)
events_done.wait(timeout=30)

print()
print("=== Execution Complete ===")

if response.tokens:
    t = response.tokens
    cost_str = f"${response.cost:.4f}" if response.cost else "n/a"
    print(
        f"{TOOL_COLOR}\U0001f4ca TOTAL in={int(t.input)} out={int(t.output)} "
        f"reasoning={int(t.reasoning)} cost={cost_str}{RESET}"
    )
else:
    cost_str = f"${response.cost:.4f}" if response.cost else "n/a"
    print(f"{TOOL_COLOR}\U0001f4ca cost={cost_str}{RESET}")

if response.error:
    err_name = getattr(response.error, "name", "unknown")
    print(f"{RED}Response error: {err_name}{RESET}")
    sys.exit(1)

if session_error:
    print(f"{RED}Session had errors: {session_error}{RESET}")
    sys.exit(1)
PYEOF

EXIT_CODE=$?
set -e

# Grace period: let the @mlflow/opencode plugin flush traces to the MLflow server.
# The plugin fires on session.idle (async, fire-and-forget inside the serve process).
# Without this sleep, the EXIT trap kills the server before the HTTP POST completes.
if [ -n "${MLFLOW_EXPERIMENT_ID:-}" ]; then
  FLUSH_WAIT="${OPENCODE_MLFLOW_FLUSH_GRACE_SECONDS:-10}"
  echo "Waiting ${FLUSH_WAIT}s for MLflow plugin to flush traces..."
  sleep "$FLUSH_WAIT"
fi

echo
echo "Execution finished at: $(date)"
echo "Exit code: $EXIT_CODE"

# Dump serve log for debugging plugin/server issues
if [ -f ${SERVE_LOG} ]; then
  echo
  echo "=== OpenCode serve log ==="
  cat ${SERVE_LOG}
  echo "=== End serve log ==="
fi

echo
echo "============================================================"
echo "Skill execution complete (OpenCode SDK)"
echo "============================================================"

exit $EXIT_CODE
