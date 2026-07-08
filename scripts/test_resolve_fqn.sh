#!/bin/bash
# Test resolve_fqn.sh against real upstream repos on github.com.
#
# Verifies:
#   1. FQN parsing (host, owner, repo, ref, skill)
#   2. Repo cloned successfully
#   3. skills/ → .claude/skills/ symlink for repos not using .claude/skills/
#   4. hooks/hooks.json → .claude/settings.json when present
#   5. Artifact subdirectories created under /app/artifacts/
#
# Usage:
#   bash scripts/test_resolve_fqn.sh          # run all tests
#   bash scripts/test_resolve_fqn.sh --quick   # skip clone, reuse existing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESOLVE_SCRIPT="$SCRIPT_DIR/resolve_fqn.sh"
PASS=0
FAIL=0
SKIP=0

# Use a temp dir for /app/artifacts so the mkdir -p calls work
APP_ARTIFACTS=$(mktemp -d)
trap 'rm -rf "$APP_ARTIFACTS"' EXIT

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  ✓ $label"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $label"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    FAIL=$((FAIL + 1))
  fi
}

assert_exists() {
  local label="$1" path="$2"
  if [ -e "$path" ]; then
    echo "  ✓ $label"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $label (not found: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_symlink() {
  local label="$1" path="$2" target="$3"
  if [ -L "$path" ]; then
    local actual_target
    actual_target=$(readlink "$path")
    if [ "$actual_target" = "$target" ]; then
      echo "  ✓ $label"
      PASS=$((PASS + 1))
    else
      echo "  ✗ $label (symlink target mismatch)"
      echo "    expected: $target"
      echo "    actual:   $actual_target"
      FAIL=$((FAIL + 1))
    fi
  else
    echo "  ✗ $label (not a symlink: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_not_exists() {
  local label="$1" path="$2"
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    echo "  ✓ $label"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $label (unexpectedly exists: $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_file_contains() {
  local label="$1" path="$2" pattern="$3"
  if [ -f "$path" ] && grep -q "$pattern" "$path"; then
    echo "  ✓ $label"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $label (pattern not found in $path)"
    FAIL=$((FAIL + 1))
  fi
}

assert_file_not_contains() {
  local label="$1" path="$2" pattern="$3"
  if [ -f "$path" ] && ! grep -q "$pattern" "$path"; then
    echo "  ✓ $label"
    PASS=$((PASS + 1))
  else
    echo "  ✗ $label (pattern found in $path but should not be)"
    FAIL=$((FAIL + 1))
  fi
}

# Patch resolve_fqn.sh on the fly: replace /app/artifacts with our temp dir
# so mkdir -p calls succeed without root access
run_resolve() {
  local fqn="$1"
  (
    export FQN="$fqn"
    # Unset any leftover state
    unset FQN_HOST FQN_OWNER FQN_REPO FQN_REF FQN_SKILL FQN_CLONE_DIR SKILL_NAME 2>/dev/null || true

    # Source the script with /app replaced by our temp dir
    eval "$(sed "s|/app|$APP_ARTIFACTS|g" "$RESOLVE_SCRIPT")"
  )
}

# ─── Test 1: epic-creator (skills/, hooks/, artifacts/) ──────────

echo
echo "═══ Test 1: epic-creator (jwforres/epic-creator) ═══"
echo "  Expects: skills/ symlink, hooks installed, artifact subdirs"

# Clean any previous clone
rm -rf /tmp/skills/jwforres-epic-creator

run_resolve "github.com/jwforres/epic-creator@main:epic-decompose" 2>&1 | sed 's/^/  | /'

CLONE="/tmp/skills/jwforres-epic-creator"

echo
echo "  Parsing:"
# Re-source in a subshell to get vars
eval "$(
  FQN="github.com/jwforres/epic-creator@main:epic-decompose"
  # Just parse, don't clone
  FQN_REMAINDER="$FQN"
  FQN_SKILL="${FQN_REMAINDER##*:}"
  FQN_REMAINDER="${FQN_REMAINDER%:*}"
  FQN_REF="${FQN_REMAINDER##*@}"
  FQN_REMAINDER="${FQN_REMAINDER%@*}"
  IFS='/' read -r FQN_HOST FQN_OWNER FQN_REPO <<< "$FQN_REMAINDER"
  echo "P_HOST=$FQN_HOST P_OWNER=$FQN_OWNER P_REPO=$FQN_REPO P_REF=$FQN_REF P_SKILL=$FQN_SKILL"
)"
assert_eq "host=github.com" "github.com" "$P_HOST"
assert_eq "owner=jwforres" "jwforres" "$P_OWNER"
assert_eq "repo=epic-creator" "epic-creator" "$P_REPO"
assert_eq "ref=main" "main" "$P_REF"
assert_eq "skill=epic-decompose" "epic-decompose" "$P_SKILL"

echo
echo "  Clone:"
assert_exists "repo cloned" "$CLONE/.git"
assert_exists "CLAUDE.md present" "$CLONE/CLAUDE.md"

echo
echo "  Skill symlink:"
assert_exists "skills/epic-decompose/SKILL.md exists in repo" "$CLONE/skills/epic-decompose/SKILL.md"
assert_symlink ".claude/skills/epic-decompose is symlink" \
  "$CLONE/.claude/skills/epic-decompose" \
  "../../skills/epic-decompose"

echo
echo "  Hooks:"
assert_exists ".claude/settings.json created" "$CLONE/.claude/settings.json"
assert_file_contains "SessionStart hook present" "$CLONE/.claude/settings.json" "SessionStart"
assert_file_contains "pipeline_state.py command present" "$CLONE/.claude/settings.json" "pipeline_state.py"
assert_file_not_contains "CLAUDE_PLUGIN_ROOT replaced" "$CLONE/.claude/settings.json" 'CLAUDE_PLUGIN_ROOT'
assert_file_contains "clone dir substituted" "$CLONE/.claude/settings.json" "$CLONE"

echo
echo "  Artifact subdirs (under $APP_ARTIFACTS):"
assert_exists "strat-tasks/" "$APP_ARTIFACTS/artifacts/strat-tasks"
assert_exists "epic-tasks/" "$APP_ARTIFACTS/artifacts/epic-tasks"
assert_exists "epic-reviews/" "$APP_ARTIFACTS/artifacts/epic-reviews"
assert_exists "decompose-runs/" "$APP_ARTIFACTS/artifacts/decompose-runs"

echo
echo "  Artifact symlinks:"
assert_symlink "artifacts → app artifacts dir" "$CLONE/artifacts" "$APP_ARTIFACTS/artifacts"

# ─── Test 2: epic-investigator (skills/, .claude-plugin/, artifacts/) ────

echo
echo "═══ Test 2: epic-investigator (jwforres/epic-investigator) ═══"
echo "  Expects: skills/ symlink, no hooks, artifact subdirs"

rm -rf /tmp/skills/jwforres-epic-investigator

run_resolve "github.com/jwforres/epic-investigator@main:epic-investigate" 2>&1 | sed 's/^/  | /'

CLONE="/tmp/skills/jwforres-epic-investigator"

echo
echo "  Skill symlink:"
assert_exists "skills/epic-investigate/SKILL.md exists" "$CLONE/skills/epic-investigate/SKILL.md"
assert_symlink ".claude/skills/epic-investigate is symlink" \
  "$CLONE/.claude/skills/epic-investigate" \
  "../../skills/epic-investigate"

echo
echo "  Hooks:"
# epic-investigator has no hooks/ directory
if [ -f "$CLONE/hooks/hooks.json" ]; then
  assert_file_contains "hooks installed" "$CLONE/.claude/settings.json" "hooks"
else
  echo "  ✓ no hooks/hooks.json — correctly skipped"
  PASS=$((PASS + 1))
fi

echo
echo "  Artifact subdirs:"
assert_exists "investigations/" "$APP_ARTIFACTS/artifacts/investigations"

# ─── Test 3: epic-code-gen (.claude/skills/, no hooks) ───────────

echo
echo "═══ Test 3: epic-code-gen (ederign/epic-code-gen) ═══"
echo "  Expects: no symlink needed, no hooks, .claude/skills/ already exists"

rm -rf /tmp/skills/ederign-epic-code-gen

run_resolve "github.com/ederign/epic-code-gen@main:epic-codegen" 2>&1 | sed 's/^/  | /'

CLONE="/tmp/skills/ederign-epic-code-gen"

echo
echo "  Skill location:"
assert_exists ".claude/skills/epic-codegen/SKILL.md exists natively" "$CLONE/.claude/skills/epic-codegen/SKILL.md"
# Should NOT have created a symlink since it already exists at .claude/skills/
if [ -L "$CLONE/.claude/skills/epic-codegen" ]; then
  echo "  ✗ .claude/skills/epic-codegen should not be a symlink (it exists natively)"
  FAIL=$((FAIL + 1))
else
  echo "  ✓ .claude/skills/epic-codegen is not a symlink (native)"
  PASS=$((PASS + 1))
fi

echo
echo "  Hooks:"
if [ ! -f "$CLONE/hooks/hooks.json" ]; then
  echo "  ✓ no hooks/hooks.json — correctly skipped"
  PASS=$((PASS + 1))
else
  echo "  ✗ unexpected hooks/hooks.json"
  FAIL=$((FAIL + 1))
fi

# ─── Test 4: rfe-creator (.claude/skills/, standard layout) ──────

echo
echo "═══ Test 4: rfe-creator (opendatahub-io/rfe-creator) ═══"
echo "  Expects: no symlink needed, no hooks, standard layout"

rm -rf /tmp/skills/opendatahub-io-rfe-creator

run_resolve "github.com/opendatahub-io/rfe-creator@main:rfe.speedrun" 2>&1 | sed 's/^/  | /'

CLONE="/tmp/skills/opendatahub-io-rfe-creator"

echo
echo "  Skill location:"
# rfe-creator may use .claude/skills/ or skills/ — check which
if [ -f "$CLONE/.claude/skills/rfe.speedrun/SKILL.md" ]; then
  echo "  ✓ skill found at .claude/skills/rfe.speedrun/SKILL.md"
  PASS=$((PASS + 1))
elif [ -L "$CLONE/.claude/skills/rfe.speedrun" ] && [ -f "$CLONE/.claude/skills/rfe.speedrun/SKILL.md" ]; then
  echo "  ✓ skill found via symlink at .claude/skills/rfe.speedrun/SKILL.md"
  PASS=$((PASS + 1))
elif [ -f "$CLONE/skills/rfe.speedrun/SKILL.md" ]; then
  echo "  ✓ skill found at skills/rfe.speedrun/SKILL.md (symlink should exist)"
  PASS=$((PASS + 1))
  assert_symlink ".claude/skills/rfe.speedrun symlinked" \
    "$CLONE/.claude/skills/rfe.speedrun" \
    "../../skills/rfe.speedrun"
else
  echo "  ✗ skill SKILL.md not found in either location"
  FAIL=$((FAIL + 1))
fi

echo
echo "  Artifact symlinks:"
assert_symlink "artifacts symlink" "$CLONE/artifacts" "$APP_ARTIFACTS/artifacts"
assert_symlink "tmp symlink" "$CLONE/tmp" "$APP_ARTIFACTS/tmp"
assert_symlink ".context symlink" "$CLONE/.context" "$APP_ARTIFACTS/.context"

# ═══════════════════════════════════════════════════════════════════
# Local-fixture edge case tests (no network required)
# ═══════════════════════════════════════════════════════════════════

FIXTURE_DIR=$(mktemp -d)

# Helper: create a minimal git repo with given structure
make_fixture_repo() {
  local repo_dir="$1"
  mkdir -p "$repo_dir"
  git -C "$repo_dir" init -q
  git -C "$repo_dir" config user.email "test@test.com"
  git -C "$repo_dir" config user.name "test"
}

# Helper: run resolve against a local fixture (already "cloned")
run_resolve_local() {
  local fqn="$1" clone_dir="$2"
  (
    export FQN="$fqn"
    unset FQN_HOST FQN_OWNER FQN_REPO FQN_REF FQN_SKILL FQN_CLONE_DIR SKILL_NAME 2>/dev/null || true

    # Patch: skip clone (repo already exists), replace /app with temp dir
    local patched
    patched=$(sed "s|/app|$APP_ARTIFACTS|g" "$RESOLVE_SCRIPT")
    eval "$patched"
  )
}

# ─── Test 5: Missing skill (should fail) ─────────────────────────

echo
echo "═══ Test 5: Missing skill (local fixture) ═══"
echo "  Expects: script fails with clear error"

REPO5="$FIXTURE_DIR/test-owner-test-repo"
make_fixture_repo "$REPO5"
mkdir -p "$REPO5/skills/real-skill"
echo "---" > "$REPO5/skills/real-skill/SKILL.md"
git -C "$REPO5" add -A && git -C "$REPO5" commit -qm "init"

# Pre-place the repo where resolve_fqn.sh expects it
rm -rf /tmp/skills/test-owner-test-repo
cp -a "$REPO5" /tmp/skills/test-owner-test-repo

output=$(run_resolve_local "github.com/test-owner/test-repo@main:not-a-skill" "/tmp/skills/test-owner-test-repo" 2>&1 || true)
if echo "$output" | grep -q "ERROR.*not-a-skill.*not found"; then
  echo "  ✓ missing skill produces clear error"
  PASS=$((PASS + 1))
else
  echo "  ✗ missing skill did not produce expected error"
  echo "    output: $output"
  FAIL=$((FAIL + 1))
fi

rm -rf /tmp/skills/test-owner-test-repo

# ─── Test 6: Malformed FQN (parse rejection) ────────────────────

echo
echo "═══ Test 6: Malformed FQN ═══"
echo "  Expects: script fails at parse stage with 'Failed to parse FQN'"

for bad_fqn in "no-at-sign" "host/owner@ref:skill" "host/owner/repo:skill" "" \
               "host/owner/repo/extra@ref:skill" "host/owner/re po@ref:skill"; do
  output=$(
    (
      export FQN="$bad_fqn"
      unset FQN_HOST FQN_OWNER FQN_REPO FQN_REF FQN_SKILL FQN_CLONE_DIR SKILL_NAME 2>/dev/null || true
      eval "$(cat "$RESOLVE_SCRIPT")"
    ) 2>&1 || true
  )
  if echo "$output" | grep -q "Failed to parse FQN\|FQN variable not set"; then
    echo "  ✓ '$bad_fqn' rejected at parse stage"
    PASS=$((PASS + 1))
  else
    echo "  ✗ '$bad_fqn' was not rejected at parse stage"
    echo "    output: $output"
    FAIL=$((FAIL + 1))
  fi
done

# ─── Test 6b: Slash in ref (valid FQN) ───────────────────────────

echo
echo "═══ Test 6b: Slash in ref (feature/foo) ═══"
echo "  Expects: accepted by parser, ref parsed correctly"

output=$(
  (
    export FQN="github.com/owner/repo@feature/foo:my-skill"
    unset FQN_HOST FQN_OWNER FQN_REPO FQN_REF FQN_SKILL FQN_CLONE_DIR SKILL_NAME 2>/dev/null || true
    # Only run the parsing section, skip clone
    eval "$(head -40 "$RESOLVE_SCRIPT")"
    echo "PARSED_REF=$FQN_REF"
  ) 2>&1 || true
)
if echo "$output" | grep -q "PARSED_REF=feature/foo"; then
  echo "  ✓ ref=feature/foo parsed correctly"
  PASS=$((PASS + 1))
else
  echo "  ✗ ref with slash not parsed correctly"
  echo "    output: $output"
  FAIL=$((FAIL + 1))
fi

# ─── Test 6c: Clone failure (valid FQN, nonexistent repo) ────────

echo
echo "═══ Test 6b: Clone failure (valid FQN, nonexistent repo) ═══"
echo "  Expects: script fails at clone with 'Failed to clone'"

rm -rf /tmp/skills/nonexistent-owner-nonexistent-repo
output=$(run_resolve "github.com/nonexistent-owner/nonexistent-repo@main:some-skill" 2>&1 || true)
if echo "$output" | grep -q "Failed to clone"; then
  echo "  ✓ nonexistent repo fails at clone stage"
  PASS=$((PASS + 1))
else
  echo "  ✗ nonexistent repo did not fail at clone stage"
  echo "    output: $output"
  FAIL=$((FAIL + 1))
fi
rm -rf /tmp/skills/nonexistent-owner-nonexistent-repo

# ─── Test 7: Existing .claude/skills/<name>/ dir without SKILL.md ─

echo
echo "═══ Test 7: Existing empty .claude/skills/<name>/ directory ═══"
echo "  Expects: rm -rf replaces dir with symlink, skill found"

REPO7="$FIXTURE_DIR/test-owner-symlink-repo"
make_fixture_repo "$REPO7"
mkdir -p "$REPO7/skills/my-skill"
echo -e "---\nname: my-skill\n---\nHello" > "$REPO7/skills/my-skill/SKILL.md"
mkdir -p "$REPO7/.claude/skills/my-skill"
# .claude/skills/my-skill/ exists as empty dir (no SKILL.md inside)
git -C "$REPO7" add -A && git -C "$REPO7" commit -qm "init"

rm -rf /tmp/skills/test-owner-symlink-repo
cp -a "$REPO7" /tmp/skills/test-owner-symlink-repo

output=$(run_resolve_local "github.com/test-owner/symlink-repo@main:my-skill" "/tmp/skills/test-owner-symlink-repo" 2>&1 || true)
CLONE7="/tmp/skills/test-owner-symlink-repo"

if [ -L "$CLONE7/.claude/skills/my-skill" ]; then
  echo "  ✓ empty dir replaced with symlink"
  PASS=$((PASS + 1))
else
  echo "  ✗ empty dir was not replaced with symlink"
  FAIL=$((FAIL + 1))
fi

if [ -f "$CLONE7/.claude/skills/my-skill/SKILL.md" ]; then
  echo "  ✓ SKILL.md is now discoverable through symlink"
  PASS=$((PASS + 1))
else
  echo "  ✗ SKILL.md not discoverable"
  FAIL=$((FAIL + 1))
fi

rm -rf /tmp/skills/test-owner-symlink-repo

# ─── Test 8: Hook merging preserves existing hooks ────────────────

echo
echo "═══ Test 8: Hook merging preserves existing hooks ═══"
echo "  Expects: new hooks merged, existing hooks kept"

REPO8="$FIXTURE_DIR/test-owner-hook-merge"
make_fixture_repo "$REPO8"
mkdir -p "$REPO8/.claude/skills/some-skill"
echo -e "---\nname: some-skill\n---\nHello" > "$REPO8/.claude/skills/some-skill/SKILL.md"
mkdir -p "$REPO8/hooks"
cat > "$REPO8/hooks/hooks.json" <<'HOOKEOF'
{
  "hooks": {
    "SessionStart": [
      {"matcher": "compact", "hooks": [{"type": "command", "command": "echo new-hook"}]}
    ]
  }
}
HOOKEOF
# Pre-existing settings with a different hook event
mkdir -p "$REPO8/.claude"
cat > "$REPO8/.claude/settings.json" <<'SETEOF'
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo existing-hook"}]}
    ]
  }
}
SETEOF
git -C "$REPO8" add -A && git -C "$REPO8" commit -qm "init"

rm -rf /tmp/skills/test-owner-hook-merge
cp -a "$REPO8" /tmp/skills/test-owner-hook-merge

run_resolve_local "github.com/test-owner/hook-merge@main:some-skill" "/tmp/skills/test-owner-hook-merge" 2>&1 | sed 's/^/  | /'

CLONE8="/tmp/skills/test-owner-hook-merge"
assert_file_contains "SessionStart hook added" "$CLONE8/.claude/settings.json" "SessionStart"
assert_file_contains "PreToolUse hook preserved" "$CLONE8/.claude/settings.json" "PreToolUse"
assert_file_contains "existing hook command kept" "$CLONE8/.claude/settings.json" "existing-hook"
assert_file_contains "new hook command added" "$CLONE8/.claude/settings.json" "new-hook"

rm -rf /tmp/skills/test-owner-hook-merge

# ─── Cleanup fixtures ────────────────────────────────────────────

rm -rf "$FIXTURE_DIR"

# ─── Summary ─────────────────────────────────────────────────────

echo
echo "═══════════════════════════════════════════════════════"
echo "  Results: $PASS passed, $FAIL failed"
echo "═══════════════════════════════════════════════════════"

# Cleanup cloned repos
rm -rf /tmp/skills/jwforres-epic-creator \
       /tmp/skills/jwforres-epic-investigator \
       /tmp/skills/ederign-epic-code-gen \
       /tmp/skills/opendatahub-io-rfe-creator

exit $FAIL
