#!/bin/bash
# K8s job wrapper - installs skills from registry and runs via Claude CLI

set -euo pipefail

# Save full pod log as artifact
LOG_DIR="/app/artifacts/jobs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
exec > >(tee -a "${LOG_DIR}/${PIPELINE_JOB_NAME:-$(hostname)}.log") 2>&1

# Parse arguments
SKILL=""
FQN=""
ISSUE_KEY=""
MODEL="opus"
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
    --skill-load-mode)
      SKILL_LOAD_MODE="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

# Export SKILL_LOAD_MODE so resolve_fqn.sh can pick it up (defaults to auto)
export SKILL_LOAD_MODE="${SKILL_LOAD_MODE:-auto}"

if [ -z "$SKILL" ] && [ -z "$FQN" ]; then
  echo "Usage: $0 --skill <skill-name> [--issue <issue-key>] [--model <model>] [--force]"
  echo "   or: $0 --fqn <host/owner/repo@ref:skill> [--issue <issue-key>] [--model <model>] [--force]"
  exit 1
fi

# Include skill+issue in job tag so strace/apibodies dirs are discoverable by issue key
SKILL_TAG="${SKILL}"
if [ -z "$SKILL_TAG" ] && [ -n "$FQN" ]; then
  SKILL_TAG="${FQN##*:}"
fi
if [ -n "$ISSUE_KEY" ]; then
  export PIPELINE_JOB_NAME="${SKILL_TAG}-${ISSUE_KEY}"
fi

echo "============================================================"
echo "Running skill: ${FQN:-$SKILL}"
echo "Issue: $ISSUE_KEY"
echo "Model: $MODEL"
echo "============================================================"
echo

# Debug: dump full environment so we can verify extra_env injection
echo "=== Environment ==="
env | sort
echo "=== End environment ==="
echo

# Configure SSL certificate bundle for Python requests
if [ -f /shared/ca-certificates.crt ]; then
  export SSL_CERT_FILE=/shared/ca-certificates.crt
  export REQUESTS_CA_BUNDLE=/shared/ca-certificates.crt
  echo "✓ Using custom CA certificate bundle"
fi

# Configure git to use HTTPS instead of SSH for GitHub
git config --global url."https://github.com/".insteadOf "git@github.com:"

# ---------------------------------------------------------------------------
# FQN resolution: clone repo if --fqn was provided
# ---------------------------------------------------------------------------
FQN_CLONE_DIR=""
if [ -n "$FQN" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  source "$SCRIPT_DIR/resolve_fqn.sh"
fi

# Configure Claude CLI to use Vertex AI
echo "Configuring Claude CLI for Vertex AI..."
CLAUDE_SETTINGS_FILE="$HOME/.claude/settings.json"

# Use Python to merge settings (Python is already installed)
python3 -c "
import json
import os

settings_file = os.path.expanduser('~/.claude/settings.json')
settings_dir = os.path.dirname(settings_file)
settings = {}

# Create .claude directory if it doesn't exist
os.makedirs(settings_dir, exist_ok=True)

# Load existing settings if file exists
if os.path.exists(settings_file):
    with open(settings_file, 'r') as f:
        settings = json.load(f)

# Add Vertex AI configuration
settings['apiProvider'] = 'vertex'
settings['vertexProjectId'] = os.environ.get('ANTHROPIC_VERTEX_PROJECT_ID', '')
settings['vertexRegion'] = os.environ.get('CLOUD_ML_REGION', 'global')

# Add Atlassian MCP server if configured
atlassian_mcp_url = os.environ.get('ATLASSIAN_MCP_URL', '')
if atlassian_mcp_url:
    if 'mcpServers' not in settings:
        settings['mcpServers'] = {}
    settings['mcpServers']['atlassian'] = {
        'type': 'sse',
        'url': atlassian_mcp_url
    }
    print('✓ Atlassian MCP server configured')

# Write back
with open(settings_file, 'w') as f:
    json.dump(settings, f, indent=2)

print('✓ Vertex AI settings merged')
"

echo

# Configure MLflow tracing for Claude CLI
if [ -n "${MLFLOW_TRACKING_URI:-}" ]; then
  echo "Configuring MLflow tracing for Claude CLI..."
  # Use home directory so hooks are written to ~/.claude/settings.json (not ~/.claude/.claude/settings.json)
  MLFLOW_AUTOLOG_ARGS=(-u "$MLFLOW_TRACKING_URI" -d /home/pipelineagent)
  if [ -n "${MLFLOW_EXPERIMENT_NAME:-}" ]; then
    MLFLOW_AUTOLOG_ARGS+=(-n "$MLFLOW_EXPERIMENT_NAME")
  fi
  /app/.venv/bin/mlflow autolog claude "${MLFLOW_AUTOLOG_ARGS[@]}"
  /app/.venv/bin/python /app/scripts/bound_mlflow_claude_hooks.py \
    "$CLAUDE_SETTINGS_FILE"
  echo "✓ MLflow tracing configured"
else
  echo "⚠ Warning: MLFLOW_TRACKING_URI not set, skipping MLflow tracing setup"
fi

echo

# Register skill marketplaces
echo "Registering skill marketplaces..."
claude plugin marketplace add opendatahub-io/skills-registry || true

# Install only the plugin needed for the current skill
REGISTRY=$(python3 -c "
import yaml
with open('/app/var/pipeline-skills.yaml') as f:
    cfg = yaml.safe_load(f)
skills = cfg.get('skills') or {}
skill_cfg = skills.get('${SKILL}', {})
source = skill_cfg.get('source', '')
if source:
    repo = (cfg.get('skill_repos') or {}).get(source, {})
    reg = repo.get('registry', '')
    if reg:
        print(reg)
" 2>/dev/null)

if [ -n "$REGISTRY" ]; then
  echo "  Installing plugin: $REGISTRY"
  claude plugin install "$REGISTRY" || true
else
  echo "  No external plugin needed for skill: $SKILL"
fi

echo
echo "Setting up artifact symlinks..."

# Set up symlinks for all installed plugins
if [ -d ~/.claude/plugins/cache ]; then
  for CACHE_ROOT in ~/.claude/plugins/cache/*/; do
    for PLUGIN_BASE in "$CACHE_ROOT"*/; do
      PLUGIN_NAME=$(basename "$PLUGIN_BASE")
      for VERSION_DIR in "$PLUGIN_BASE"*/; do
        VERSION_DIR="${VERSION_DIR%/}"
        if [ -d "$VERSION_DIR" ]; then
          rm -rf "$VERSION_DIR/artifacts" "$VERSION_DIR/tmp" "$VERSION_DIR/.context"
          ln -s /app/artifacts "$VERSION_DIR/artifacts"
          ln -s /app/tmp "$VERSION_DIR/tmp"
          ln -s /app/.context "$VERSION_DIR/.context"
          echo "✓ Created symlinks for $PLUGIN_NAME/$(basename $VERSION_DIR)"
        fi
      done
    done
  done

  # Hotpatch: remove "context: fork" from installed skills so streaming output works
  echo "Patching context:fork from installed skills..."
  find ~/.claude/plugins/cache -name "SKILL.md" -exec sed -i '/^context: *fork/d' {} +
fi

echo
echo "Running skill..."
echo

# Resolve skill name from pipeline-skills.yaml (falls back to dash-to-dot conversion)
# When --fqn was used, SKILL_NAME is already set by resolve_fqn.sh
if [ -z "${SKILL_NAME:-}" ]; then
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

# Verify MLflow is accessible
if [ -n "${MLFLOW_TRACKING_URI:-}" ]; then
  echo "MLflow tracking enabled: $MLFLOW_TRACKING_URI"
  # Test MLflow connectivity
  if command -v curl >/dev/null 2>&1; then
    if curl -s -f "$MLFLOW_TRACKING_URI/health" >/dev/null 2>&1; then
      echo "✓ MLflow server is accessible"
    else
      echo "⚠ Warning: MLflow server may not be accessible"
    fi
  fi
else
  echo "⚠ Warning: MLFLOW_TRACKING_URI not set"
fi

echo

# Export extra variables as environment variables
for VAR in "${EXTRA_VARS[@]}"; do
  KEY="${VAR%%=*}"
  VALUE="${VAR#*=}"
  export "$KEY"="$VALUE"
  echo "  $KEY=$VALUE"
done

# Build the skill invocation prompt
# Skills accept issue keys as positional arguments, not flags
# Example: /rfe.review --headless RHAIRFE-953
# --headless flag suppresses interactive prompts and end-of-run summary
if [ "${FQN_LOAD_MODE_RESOLVED:-}" = "plugin" ] && [ -n "${FQN_PLUGIN_NAME:-}" ]; then
  PROMPT="/${FQN_PLUGIN_NAME}:${SKILL_NAME} --headless${FORCE:+ $FORCE}${ISSUE_KEY:+ $ISSUE_KEY}"
else
  PROMPT="/$SKILL_NAME --headless${FORCE:+ $FORCE}${ISSUE_KEY:+ $ISSUE_KEY}"
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

# Resolve which plugin source this skill needs
# When --fqn was used, the repo is already cloned by resolve_fqn.sh
if [ -n "$FQN_CLONE_DIR" ]; then
  echo "Using FQN-cloned repo: $FQN_CLONE_DIR"
  # Hotpatch: remove "context: fork" so streaming output works
  find "$FQN_CLONE_DIR" -name "SKILL.md" -exec sed -i '/^context: *fork/d' {} +

  # Hotpatch: replace hardcoded github.com with emulator hostname
  # Skills like epic-code-gen have API_BASE, git URLs, and slug parsing
  # that reference github.com. Replace with the resolved clone host so
  # they talk to the in-cluster GitHub emulator instead.
  if [ -n "$CLONE_HOST" ] && [ "$CLONE_HOST" != "github.com" ]; then
    echo "Hotpatching github.com → $CLONE_HOST in skill scripts"
    find "$FQN_CLONE_DIR" -name "*.py" -not -path "*/__pycache__/*" -exec \
      sed -i \
        -e "s|api\.github\.com|${CLONE_HOST}/api/v3|g" \
        -e "s|github\.com|${CLONE_HOST}|g" \
      {} +
  fi
else
  SKILL_SOURCE=$(python3 -c "
import yaml
with open('/app/var/pipeline-skills.yaml') as f:
    cfg = yaml.safe_load(f)
skills = cfg.get('skills') or cfg.get('phases') or {}
sc = skills.get('${SKILL}', {})
source = sc.get('source', '')
if source:
    repos = cfg.get('skill_repos', {})
    repo = repos.get(source, {})
    # Print the plugin directory name (repo key)
    print(source)
" 2>/dev/null)

  if [ -n "$SKILL_SOURCE" ] && [ -d ~/.claude/plugins/cache ]; then
    PLUGIN_DIR=$(find ~/.claude/plugins/cache -name "$SKILL_SOURCE" -type d | head -1)
    if [ -z "$PLUGIN_DIR" ]; then
      echo "WARNING: Plugin $SKILL_SOURCE not found in cache, continuing without it"
    else
      echo "Plugin directory: $PLUGIN_DIR"
      echo "✓ $SKILL_SOURCE plugin installed"
    fi
  elif [ -n "$SKILL_SOURCE" ]; then
    echo "WARNING: No plugin cache, skipping $SKILL_SOURCE lookup"
  else
    echo "Using local skill"
  fi
fi

mkdir -p \
  /app/artifacts/rfe-tasks \
  /app/artifacts/strat-tasks \
  /app/artifacts/epic-tasks \
  /app/artifacts/epic-reviews \
  /app/artifacts/decompose-runs \
  /app/artifacts/investigations \
  /app/tmp \
  /app/.context

# Claude Code subagents spawned by the Agent tool do not always inherit the
# parent process cwd. Keep common fallback working directories pointed at the
# shared PVC so relative writes like artifacts/epic-tasks/... do not disappear
# into the container filesystem.
setup_shared_links() {
  local base="$1"
  [ -n "$base" ] || return 0
  mkdir -p "$base" 2>/dev/null || true

  for name in artifacts tmp .context; do
    local target="/app/$name"
    local link="$base/$name"
    if [ -L "$link" ]; then
      ln -sfn "$target" "$link"
    elif [ ! -e "$link" ]; then
      ln -s "$target" "$link" 2>/dev/null || true
    else
      echo "WARNING: $link exists and is not a symlink; leaving it unchanged"
    fi
  done
}

setup_shared_links "/home/pipelineagent"
setup_shared_links "$HOME"

# Change to FQN clone directory if applicable
if [ -n "$FQN_CLONE_DIR" ]; then
  cd "$FQN_CLONE_DIR"
fi

# Build plugin args for Claude CLI
PLUGIN_ARGS=()
if [ "${FQN_LOAD_MODE_RESOLVED:-}" = "plugin" ] && [ -n "${FQN_PLUGIN_DIR:-}" ]; then
  PLUGIN_ARGS=(--plugin-dir "$FQN_PLUGIN_DIR")
fi

echo "Resolved skill load mode: ${FQN_LOAD_MODE_RESOLVED:-skill}"

# Debug: Show what we're about to run
echo "Executing: claude --model $MODEL --print ${PLUGIN_ARGS[*]:+${PLUGIN_ARGS[*]} }\"$PROMPT\""
echo "Working directory: $(pwd)"
echo "Starting execution at: $(date)"
echo

# OpenTelemetry → Observatory (enabled by default)
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
  echo "OTel telemetry enabled: OTLP → ${OBSERVATORY_URL}/otel, API bodies → $APIBODIES_DIR"
else
  echo "OTel telemetry disabled"
fi

# Set up FIFO for streaming output (proven pattern from rfe-autofixer GitLab CI)
claude_fifo="/tmp/claude-stream.fifo"
rm -f "$claude_fifo"
mkfifo "$claude_fifo"

# Optional strace wrapper
STRACE_CMD=""
if [ "${ENABLE_STRACE:-}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  STRACE_DIR="/app/artifacts/strace/${JOB_TAG}"
  mkdir -p "$STRACE_DIR"
  STRACE_CMD="strace -ffttv -s 1024 -o ${STRACE_DIR}/${JOB_TAG}"
  echo "strace enabled: output → $STRACE_DIR"
fi

# Run Claude in background, streaming to FIFO
# --dangerously-skip-permissions: Auto-allow file writes (safe in sandboxed K8s container)
# --output-format stream-json: Stream events in real-time
# --include-partial-messages: Show progress as it happens
# --include-hook-events: Show hook events
# --verbose: Required for stream-json with --print
$STRACE_CMD claude --model "$MODEL" --print --dangerously-skip-permissions \
  --output-format stream-json --include-partial-messages \
  --include-hook-events --verbose "${PLUGIN_ARGS[@]}" "$PROMPT" 2>/tmp/claude-stderr.log > "$claude_fifo" &
claude_pid=$!

# Parse stream with dedicated parser (shows tool use, thinking, token counts)
python3 -u /app/scripts/stream-claude.py --claude-pid "$claude_pid" < "$claude_fifo"

EXIT_CODE=$?

# Best-effort recovery for any local artifact directories created before the
# fallback symlinks existed, or by tools that intentionally bypass symlinks.
for candidate in "/home/pipelineagent/artifacts" "$HOME/artifacts"; do
  if [ -d "$candidate" ] && [ ! -L "$candidate" ] && [ "$candidate" != "/app/artifacts" ]; then
    echo "Recovering local artifacts from $candidate to /app/artifacts"
    cp -a "$candidate"/. /app/artifacts/ 2>/dev/null || true
  fi
done

echo
echo "Execution finished at: $(date)"
echo "Exit code: $EXIT_CODE"

echo
echo "============================================================"
echo "Skill execution complete"
echo "============================================================"
