#!/bin/bash
# K8s job wrapper - installs skills from registry and runs via Claude Python SDK

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
  export PIPELINE_JOB_NAME="${SKILL}-${ISSUE_KEY}"
fi

echo "============================================================"
echo "Running skill: ${FQN:-$SKILL}"
echo "Issue: $ISSUE_KEY"
echo "Model: $MODEL"
echo "Runner: SDK (Python)"
echo "============================================================"
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

# Register skill marketplaces
echo "Registering skill marketplaces..."
claude plugin marketplace add opendatahub-io/skills-registry || true
claude plugin marketplace add /app/skills-registry || true

# Discover and install plugins from pipeline-skills.yaml
REGISTRIES=$(python3 -c "
import yaml
with open('/app/var/pipeline-skills.yaml') as f:
    cfg = yaml.safe_load(f)
for repo in (cfg.get('skill_repos') or {}).values():
    reg = repo.get('registry', '')
    if reg:
        print(reg)
" 2>/dev/null | sort -u)

for REG in $REGISTRIES; do
  echo "  Installing plugin: $REG"
  claude plugin install "$REG" || true
done

echo
echo "Setting up artifact symlinks..."

# Set up symlinks for all installed plugins
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

echo

# Create artifact and context directories if they don't exist
mkdir -p /app/artifacts/rfe-tasks /app/artifacts/strat-tasks /app/tmp /app/.context

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
echo "Working directory: /app"
echo "Starting execution at: $(date)"
echo

# Optional strace wrapper
STRACE_CMD=""
if [ "${ENABLE_STRACE:-}" = "1" ]; then
  JOB_TAG="${PIPELINE_JOB_NAME:-$(hostname)}"
  STRACE_DIR="/app/artifacts/strace/${JOB_TAG}"
  mkdir -p "$STRACE_DIR"
  STRACE_CMD="strace -ffttv -s 1024 -o ${STRACE_DIR}/${JOB_TAG}"
  echo "strace enabled: output → $STRACE_DIR"
fi

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

# Build extra-vars prompt suffix
EXTRA_VARS_PROMPT=""
if [ ${#EXTRA_VARS[@]} -gt 0 ]; then
  EXTRA_VARS_PROMPT=$'\n\n## Inputs'
  for VAR in "${EXTRA_VARS[@]}"; do
    KEY="${VAR%%=*}"
    VALUE="${VAR#*=}"
    EXTRA_VARS_PROMPT="$EXTRA_VARS_PROMPT"$'\n'"- $KEY: $VALUE"
  done
fi

# Run via Python SDK with MLflow integration
$STRACE_CMD python3 -u << PYEOF
import asyncio
import json
import os
import sys
from pathlib import Path

# Add /app to path so we can import our modules
sys.path.insert(0, '/app')

from src.cli.skill_config import get_phase_config, get_mcp_servers, get_allowed_tools
from src.cli.agent_runner import get_model_id

# Import SDK
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    HookMatcher,
)

# MLflow integration (optional - only if MLFLOW_TRACKING_URI is set)
try:
    import mlflow
    MLFLOW_AVAILABLE = bool(os.getenv("MLFLOW_TRACKING_URI"))
    if MLFLOW_AVAILABLE:
        mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI"))
        exp_name = os.getenv("MLFLOW_EXPERIMENT_NAME", "").strip()
        if exp_name:
            mlflow.set_experiment(exp_name)
            print("✓ MLflow experiment:", exp_name)
        print("✓ MLflow tracking configured:", os.getenv("MLFLOW_TRACKING_URI"))
    else:
        print("⚠ MLflow tracking URI not set")
except ImportError:
    MLFLOW_AVAILABLE = False
    print("⚠ MLflow not available")

async def log_tool_use(input_data, tool_use_id, context):
    """Hook to log each tool use to MLflow."""
    if not MLFLOW_AVAILABLE:
        return {}

    tool_name = input_data.get("tool_name", "unknown")
    try:
        # Log tool usage count
        mlflow.log_metric(f"tool_use_count", 1)
        mlflow.log_metric(f"tool_{tool_name}", 1)
    except Exception as e:
        print(f"Warning: MLflow logging failed: {e}")

    return {}

async def run_skill():
    skill_name = "${SKILL_NAME}"
    issue_key = "${ISSUE_KEY}"
    model = "${MODEL}"

    # Look up skill key (the pipeline-skills.yaml key, e.g. "rfe-create")
    skill_key = "${SKILL}"
    fqn_clone_dir = "${FQN_CLONE_DIR}" or None

    if fqn_clone_dir:
        # FQN mode: use cloned repo, skip pipeline-skills.yaml lookup
        phase_config = {
            "skill": skill_name,
            "invoke": "native",
        }
        plugin_dir = fqn_clone_dir
    else:
        try:
            phase_config = get_phase_config(skill_key)
        except KeyError:
            print(f"ERROR: Could not find skill config for {skill_key}")
            sys.exit(1)

        # Get plugin directory for source skills
        plugin_dir = None
        source = phase_config.get('source')
        if source:
            import subprocess
            result = subprocess.run(
                ['find', os.path.expanduser('~/.claude/plugins/cache'),
                 '-name', source, '-type', 'd'],
                capture_output=True, text=True
            )
            if result.stdout.strip():
                plugin_dir = result.stdout.strip().split('\\n')[0]
                # Find versioned subdir (e.g. 0.1.0) or branch name (e.g. main)
                subdirs = [d for d in Path(plugin_dir).iterdir() if d.is_dir()]
                if subdirs:
                    plugin_dir = str(subdirs[0])

    # Build prompt
    force_part = " --force" if """${FORCE}""" else ""
    issue_part = f" {issue_key}" if issue_key else ""
    extra_vars = """${EXTRA_VARS_PROMPT}"""
    prompt = f"/{skill_name} --headless{force_part}{issue_part}{extra_vars}"

    # Set working directory
    cwd = plugin_dir if plugin_dir else "/app"

    print(f"Plugin directory: {plugin_dir or 'N/A'}")
    print(f"Working directory: {cwd}")
    print(f"Prompt: {prompt}")
    print()

    # Configure agent options
    if fqn_clone_dir:
        allowed_tools = ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"]
        mcp_servers = {}
    else:
        allowed_tools = get_allowed_tools(skill_key)
        mcp_servers = get_mcp_servers(skill_key)

    # Set up hooks for MLflow tool tracking
    hooks = {}
    if MLFLOW_AVAILABLE:
        hooks = {
            "PostToolUse": [
                HookMatcher(matcher=None, hooks=[log_tool_use])
            ]
        }

    options = ClaudeAgentOptions(
        model=get_model_id(model),
        allowed_tools=allowed_tools,
        mcp_servers=mcp_servers,
        cwd=cwd,
        hooks=hooks,
        permission_mode="auto",  # Auto-approve in sandboxed container
    )

    # Start MLflow run if available
    if MLFLOW_AVAILABLE:
        # Enable tracing to capture conversation
        mlflow.tracing.enable()

        mlflow.start_run(run_name=f"{skill_name}-{issue_key}-sdk")
        mlflow.log_params({
            "skill": skill_name,
            "issue": issue_key,
            "model": model,
            "runner": "sdk",
            "cwd": cwd,
        })

    # Run agent wrapped in a trace
    @mlflow.trace(name=f"{skill_name}", span_type="LLM")
    async def execute_agent():
        async with ClaudeSDKClient(options=options) as client:
            print("=== Agent Output ===")
            print()

            await client.query(prompt)

            result_msg = None
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    # Print text blocks
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            print(block.text)
                        elif isinstance(block, ToolUseBlock):
                            print(f"🔧 {block.name}")

                elif isinstance(msg, ResultMessage):
                    result_msg = msg
                    print()
                    print("=== Execution Complete ===")
                    print(f"Duration: {msg.duration_ms}ms")
                    print(f"Turns: {msg.num_turns}")
                    print(f"Cost: \${msg.total_cost_usd or 0.0:.4f}")
                    print(f"Error: {msg.is_error}")
                    if msg.stop_reason:
                        print(f"Stop reason: {msg.stop_reason}")

            return result_msg

    try:
        result_msg = await execute_agent()

        # Set trace attributes with token usage and model info
        if MLFLOW_AVAILABLE and result_msg:
            trace_id = mlflow.get_last_active_trace_id()
            if trace_id:
                # Set attributes for usage reporting
                mlflow.set_trace_tag(trace_id, "mlflow.traceModel", get_model_id(model))

                # Add token usage attributes
                if result_msg.usage:
                    for key, value in result_msg.usage.items():
                        if isinstance(value, (int, float)):
                            mlflow.set_trace_tag(trace_id, f"usage.{key}", str(int(value)))

        # Log final metrics to MLflow run
        if MLFLOW_AVAILABLE and result_msg:
            mlflow.log_metrics({
                "duration_ms": result_msg.duration_ms,
                "duration_api_ms": result_msg.duration_api_ms,
                "num_turns": result_msg.num_turns,
                "cost_usd": result_msg.total_cost_usd or 0.0,
                "is_error": 1 if result_msg.is_error else 0,
            })

            if result_msg.usage:
                for key, value in result_msg.usage.items():
                    if isinstance(value, (int, float)):
                        mlflow.log_metric(f"usage_{key}", value)

            mlflow.end_run()

        # Exit with error code if execution failed
        if result_msg and result_msg.is_error:
            sys.exit(1)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if MLFLOW_AVAILABLE:
            mlflow.log_param("error", str(e))
            mlflow.end_run(status="FAILED")
        sys.exit(1)

# Run the async function
asyncio.run(run_skill())
PYEOF

EXIT_CODE=$?
echo
echo "Execution finished at: $(date)"
echo "Exit code: $EXIT_CODE"

echo
echo "============================================================"
echo "Skill execution complete"
echo "============================================================"

exit $EXIT_CODE
