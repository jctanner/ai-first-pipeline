#!/bin/bash
# K8s job wrapper - installs skills from registry and runs via Claude CLI

set -euo pipefail

# Parse arguments
SKILL=""
ISSUE_KEY=""
MODEL="opus"
FORCE=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --skill)
      SKILL="$2"
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
    *)
      echo "Unknown argument: $1"
      exit 1
      ;;
  esac
done

if [ -z "$SKILL" ] || [ -z "$ISSUE_KEY" ]; then
  echo "Usage: $0 --skill <skill-name> --issue <issue-key> [--model <model>] [--force]"
  exit 1
fi

echo "============================================================"
echo "Running skill: $SKILL"
echo "Issue: $ISSUE_KEY"
echo "Model: $MODEL"
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
settings['vertexRegion'] = os.environ.get('CLOUD_ML_REGION', 'us-east5')

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
  /app/.venv/bin/mlflow autolog claude -u "$MLFLOW_TRACKING_URI" -d /home/pipelineagent
  echo "✓ MLflow tracing configured"
else
  echo "⚠ Warning: MLFLOW_TRACKING_URI not set, skipping MLflow tracing setup"
fi

echo

# Install skills from opendatahub-io registry
echo "Installing skills from opendatahub-io/skills-registry..."
claude plugin marketplace add opendatahub-io/skills-registry || true
claude plugin install rfe-creator@opendatahub-skills || true

echo
echo "Setting up artifact symlinks..."

# Find the installed plugin directory (with version subdirectory)
PLUGIN_BASE=$(find ~/.claude/plugins/cache -name "rfe-creator" -type d | head -1)

if [ -n "$PLUGIN_BASE" ]; then
  # Find all version subdirectories and create symlinks in each
  for VERSION_DIR in "$PLUGIN_BASE"/*/ ; do
    if [ -d "$VERSION_DIR" ]; then
      # Remove existing directories in versioned plugin dir if they exist
      rm -rf "$VERSION_DIR/artifacts" "$VERSION_DIR/tmp" "$VERSION_DIR/.context"

      # Create symlinks from versioned plugin directory to persistent volumes
      ln -s /app/artifacts "$VERSION_DIR/artifacts"
      ln -s /app/tmp "$VERSION_DIR/tmp"
      ln -s /app/.context "$VERSION_DIR/.context"

      echo "✓ Created symlinks in $(basename $VERSION_DIR):"
      echo "  $VERSION_DIR/artifacts -> /app/artifacts"
      echo "  $VERSION_DIR/tmp -> /app/tmp"
      echo "  $VERSION_DIR/.context -> /app/.context"
    fi
  done
else
  echo "⚠ Warning: Could not find plugin directory for symlink setup"
fi

echo
echo "Running skill..."
echo

# Map phase names (dashes) to skill names (dots)
# Phase names: rfe-review, rfe-create, strat-create, etc.
# Skill names: rfe.review, rfe.create, strat.create, etc.
SKILL_NAME="${SKILL//-/.}"

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

# Build the skill invocation prompt
# Skills accept issue keys as positional arguments, not flags
# Example: /rfe.review --headless RHAIRFE-953
# --headless flag suppresses interactive prompts and end-of-run summary
PROMPT="/$SKILL_NAME --headless $ISSUE_KEY"

# Verify rfe-creator plugin is installed (but don't cd to it)
PLUGIN_DIR=$(find ~/.claude/plugins/cache -name "rfe-creator" -type d | head -1)

if [ -z "$PLUGIN_DIR" ]; then
  echo "ERROR: rfe-creator plugin not found in ~/.claude/plugins/cache"
  exit 1
fi

echo "Plugin directory: $PLUGIN_DIR"
echo "✓ rfe-creator plugin installed"

# Create artifact and context directories if they don't exist
# Skills will write to these via symlinks from the plugin directory
mkdir -p /app/artifacts/rfe-tasks /app/artifacts/strat-tasks /app/tmp /app/.context

# Debug: Show what we're about to run
echo "Executing: claude --model $MODEL --print \"$PROMPT\""
echo "Working directory: $(pwd)"
echo "Starting execution at: $(date)"
echo

# Set up FIFO for streaming output (proven pattern from rfe-autofixer GitLab CI)
claude_fifo="/tmp/claude-stream.fifo"
rm -f "$claude_fifo"
mkfifo "$claude_fifo"

# Run Claude in background, streaming to FIFO
# --dangerously-skip-permissions: Auto-allow file writes (safe in sandboxed K8s container)
# --output-format stream-json: Stream events in real-time
# --include-partial-messages: Show progress as it happens
# --include-hook-events: Show hook events
# --verbose: Required for stream-json with --print
claude --model "$MODEL" --print --dangerously-skip-permissions \
  --output-format stream-json --include-partial-messages \
  --include-hook-events --verbose "$PROMPT" 2>/tmp/claude-stderr.log > "$claude_fifo" &
claude_pid=$!

# Parse stream with dedicated parser (shows tool use, thinking, token counts)
python3 -u /app/scripts/stream-claude.py --claude-pid "$claude_pid" < "$claude_fifo"

EXIT_CODE=$?
echo
echo "Execution finished at: $(date)"
echo "Exit code: $EXIT_CODE"

echo
echo "============================================================"
echo "Skill execution complete"
echo "============================================================"
