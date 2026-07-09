#!/bin/bash
# Resolve a URI-style FQN (host/owner/repo@ref:skill-name) by cloning
# the repo and setting variables for the caller.
#
# Usage: source this file after setting FQN="host/owner/repo@ref:skill"
#
# Outputs (exported):
#   FQN_HOST, FQN_OWNER, FQN_REPO, FQN_REF, FQN_SKILL
#   FQN_CLONE_DIR  - path to the cloned repo
#   SKILL_NAME     - the skill name (same as FQN_SKILL)

if [ -z "$FQN" ]; then
  echo "ERROR: FQN variable not set"
  return 1 2>/dev/null || exit 1
fi

# Validate FQN structure: host/owner/repo@ref:skill
# Components restricted to alphanumeric, dot, dash, underscore; ref also allows /
if ! echo "$FQN" | grep -qE '^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+@[A-Za-z0-9._/-]+:[A-Za-z0-9._-]+$'; then
  echo "ERROR: Failed to parse FQN: $FQN"
  echo "  Expected format: host/owner/repo@ref:skill-name"
  echo "  host, owner, repo, and skill may not contain @, :, or /; ref may contain /"
  return 1 2>/dev/null || exit 1
fi

# Parse: host/owner/repo@ref:skill
FQN_REMAINDER="$FQN"

# Extract skill (after last colon)
FQN_SKILL="${FQN_REMAINDER##*:}"
FQN_REMAINDER="${FQN_REMAINDER%:*}"

# Extract ref (after @)
FQN_REF="${FQN_REMAINDER##*@}"
FQN_REMAINDER="${FQN_REMAINDER%@*}"

# Split host/owner/repo
IFS='/' read -r FQN_HOST FQN_OWNER FQN_REPO <<< "$FQN_REMAINDER"

echo "FQN parsed:"
echo "  Host:  $FQN_HOST"
echo "  Owner: $FQN_OWNER"
echo "  Repo:  $FQN_REPO"
echo "  Ref:   $FQN_REF"
echo "  Skill: $FQN_SKILL"

SKILL_NAME="$FQN_SKILL"
FQN_CLONE_DIR="/tmp/skills/${FQN_OWNER}-${FQN_REPO}"

# Map short hostnames to cluster-internal service FQDNs
CLONE_HOST="$FQN_HOST"
case "$CLONE_HOST" in
  github.local) CLONE_HOST="github-emulator.ai-pipeline.svc.cluster.local" ;;
esac

# Clone repo if not already present
if [ -d "$FQN_CLONE_DIR" ]; then
  echo "Repo already cloned at $FQN_CLONE_DIR, fetching latest..."
  git -C "$FQN_CLONE_DIR" fetch origin "$FQN_REF" --depth 1 2>/dev/null || true
  git -C "$FQN_CLONE_DIR" checkout FETCH_HEAD 2>/dev/null || true
else
  CLONE_URL="https://${CLONE_HOST}/${FQN_OWNER}/${FQN_REPO}.git"
  echo "Cloning $CLONE_URL (branch: $FQN_REF)..."
  mkdir -p /tmp/skills
  if ! git clone --depth 1 -b "$FQN_REF" "$CLONE_URL" "$FQN_CLONE_DIR" 2>&1; then
    echo "ERROR: Failed to clone $CLONE_URL"
    return 1 2>/dev/null || exit 1
  fi
fi

echo "Clone directory: $FQN_CLONE_DIR"

# Ensure Claude can discover the skill — some repos use skills/ instead of .claude/skills/
if [ ! -f "$FQN_CLONE_DIR/.claude/skills/$SKILL_NAME/SKILL.md" ] && \
   [ -f "$FQN_CLONE_DIR/skills/$SKILL_NAME/SKILL.md" ]; then
  mkdir -p "$FQN_CLONE_DIR/.claude/skills"
  rm -rf "$FQN_CLONE_DIR/.claude/skills/$SKILL_NAME"
  ln -sf "../../skills/$SKILL_NAME" "$FQN_CLONE_DIR/.claude/skills/$SKILL_NAME"
  echo "Symlinked skills/$SKILL_NAME → .claude/skills/$SKILL_NAME for Claude discovery"
fi

# Verify the skill is discoverable after setup
if [ ! -f "$FQN_CLONE_DIR/.claude/skills/$SKILL_NAME/SKILL.md" ]; then
  echo "ERROR: Skill '$SKILL_NAME' not found in repo $FQN_OWNER/$FQN_REPO"
  echo "  Checked: .claude/skills/$SKILL_NAME/SKILL.md"
  echo "  Checked: skills/$SKILL_NAME/SKILL.md"
  return 1 2>/dev/null || exit 1
fi

# Install hooks — translate hooks/hooks.json into .claude/settings.json
if [ -f "$FQN_CLONE_DIR/hooks/hooks.json" ]; then
  mkdir -p "$FQN_CLONE_DIR/.claude"
  HOOKS_PATH="$FQN_CLONE_DIR/hooks/hooks.json" \
  SETTINGS_PATH="$FQN_CLONE_DIR/.claude/settings.json" \
  CLONE_DIR="$FQN_CLONE_DIR" \
  python3 -c "
import json, os

hooks_path = os.environ['HOOKS_PATH']
settings_path = os.environ['SETTINGS_PATH']
clone_dir = os.environ['CLONE_DIR']

with open(hooks_path) as f:
    hooks_data = json.load(f)

if os.path.exists(settings_path):
    with open(settings_path) as f:
        settings = json.load(f)
else:
    settings = {}

# Rewrite \${CLAUDE_PLUGIN_ROOT} to the clone directory
hooks_json = json.dumps(hooks_data)
hooks_json = hooks_json.replace('\${CLAUDE_PLUGIN_ROOT}', clone_dir)
new_hooks = json.loads(hooks_json).get('hooks', {})

# Merge by event key, preserving existing matchers
existing_hooks = settings.get('hooks', {})
for event, matchers in new_hooks.items():
    if event in existing_hooks:
        existing_hooks[event].extend(matchers)
    else:
        existing_hooks[event] = matchers
settings['hooks'] = existing_hooks

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)

print(f'Installed hooks from hooks/hooks.json into .claude/settings.json')
for event in settings['hooks']:
    print(f'  {event}: {len(settings[\"hooks\"][event])} matcher(s)')
"
fi

# Set up artifact symlinks (same pattern as plugin setup)
if [ -d "$FQN_CLONE_DIR" ]; then
  rm -rf "$FQN_CLONE_DIR/artifacts" "$FQN_CLONE_DIR/tmp" "$FQN_CLONE_DIR/.context"
  ln -sf /app/artifacts "$FQN_CLONE_DIR/artifacts"
  ln -sf /app/tmp "$FQN_CLONE_DIR/tmp"
  ln -sf /app/.context "$FQN_CLONE_DIR/.context"

  # Create artifact subdirectories the repo expects (from its artifacts/ tree).
  # Relies on .gitkeep files; untracked empty dirs cannot be inferred.
  if [ -d "$FQN_CLONE_DIR/.git" ]; then
    git -C "$FQN_CLONE_DIR" ls-tree -r --name-only HEAD -- artifacts/ 2>/dev/null \
      | while read -r path; do
          subdir=$(dirname "/app/${path}")
          mkdir -p "$subdir"
        done
  fi

  echo "Artifact symlinks created in $FQN_CLONE_DIR"
fi

export FQN_HOST FQN_OWNER FQN_REPO FQN_REF FQN_SKILL FQN_CLONE_DIR SKILL_NAME CLONE_HOST
