#!/bin/bash

# Focused, network-free regression for commit-pinned skill FQNs.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
CLONE_DIR=/tmp/skills/test-owner-commit-repo
trap 'rm -rf "$WORK" "$CLONE_DIR"' EXIT

SOURCE="$WORK/source"
BARE="$WORK/commit-repo.git"
mkdir -p "$SOURCE/.claude/skills/demo-skill"
git -C "$SOURCE" init -q
git -C "$SOURCE" branch -M main
git -C "$SOURCE" config user.name test
git -C "$SOURCE" config user.email test@example.com
printf '%s\n' '---' 'name: demo-skill' '---' > \
  "$SOURCE/.claude/skills/demo-skill/SKILL.md"
git -C "$SOURCE" add .
git -C "$SOURCE" commit -qm 'add skill'
PINNED_COMMIT=$(git -C "$SOURCE" rev-parse HEAD)

printf '%s\n' 'newer branch content' > "$SOURCE/README.md"
git -C "$SOURCE" add README.md
git -C "$SOURCE" commit -qm 'advance branch'
BRANCH_COMMIT=$(git -C "$SOURCE" rev-parse HEAD)
git clone -q --bare "$SOURCE" "$BARE"

# Replace mounted /app paths so the resolver can run as an ordinary user.
sed "s|/app|$WORK/app|g" "$ROOT/scripts/resolve_fqn.sh" > "$WORK/resolve_fqn.sh"

run_resolver() {
  local ref=$1
  (
    export FQN="github.local/test-owner/commit-repo@${ref}:demo-skill"
    export FQN_CLONE_URL="file://${BARE}"
    # shellcheck source=/dev/null
    source "$WORK/resolve_fqn.sh"
  )
}

rm -rf "$CLONE_DIR"
run_resolver "$PINNED_COMMIT"
test "$(git -C "$CLONE_DIR" rev-parse HEAD)" = "$PINNED_COMMIT"
test -f "$CLONE_DIR/.claude/skills/demo-skill/SKILL.md"

# Reusing an existing clone must also resolve a different ref exactly.
run_resolver main
test "$(git -C "$CLONE_DIR" rev-parse HEAD)" = "$BRANCH_COMMIT"

echo "commit-pinned and branch FQN resolution passed"
