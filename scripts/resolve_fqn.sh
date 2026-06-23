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

if [ -z "$FQN_HOST" ] || [ -z "$FQN_OWNER" ] || [ -z "$FQN_REPO" ] || [ -z "$FQN_REF" ] || [ -z "$FQN_SKILL" ]; then
  echo "ERROR: Failed to parse FQN: $FQN"
  echo "  Expected format: host/owner/repo@ref:skill-name"
  echo "  Parsed: host=$FQN_HOST owner=$FQN_OWNER repo=$FQN_REPO ref=$FQN_REF skill=$FQN_SKILL"
  return 1 2>/dev/null || exit 1
fi

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

# Set up artifact symlinks (same pattern as plugin setup)
if [ -d "$FQN_CLONE_DIR" ]; then
  rm -rf "$FQN_CLONE_DIR/artifacts" "$FQN_CLONE_DIR/tmp" "$FQN_CLONE_DIR/.context"
  ln -sf /app/artifacts "$FQN_CLONE_DIR/artifacts"
  ln -sf /app/tmp "$FQN_CLONE_DIR/tmp"
  ln -sf /app/.context "$FQN_CLONE_DIR/.context"
  echo "Artifact symlinks created in $FQN_CLONE_DIR"
fi

export FQN_HOST FQN_OWNER FQN_REPO FQN_REF FQN_SKILL FQN_CLONE_DIR SKILL_NAME
