#!/usr/bin/env bash
# Clone or fetch repos at specified branches and list candidate files.
#
# Usage:
#   bash gather-context.sh <repo-slug> <branch> [path-pattern...]
#
# Examples:
#   bash gather-context.sh opendatahub-io/opendatahub-documentation main "modules/**/*.adoc" "assemblies/**/*.adoc"
#   bash gather-context.sh red-hat-data-services/rhods-operator main "api/**/*_types.go"
#
# Output (JSON to stdout):
# {
#   "repo": "opendatahub-io/opendatahub-documentation",
#   "branch": "main",
#   "clone_path": "workspace/repos/opendatahub-io/opendatahub-documentation",
#   "candidates": [
#     {
#       "file_path": "modules/serving/pages/con_model-serving.adoc",
#       "size_bytes": 4521,
#       "source_type": "documentation"
#     }
#   ]
# }

set -euo pipefail

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(pwd)"

# Load .env if available (GITHUB_TOKEN, etc.)
source "${SCRIPTS_DIR}/load-env.sh"

WORKSPACE="${PROJECT_ROOT}/workspace/repos"

REPO_SLUG="${1:?Usage: gather-context.sh <repo-slug> <branch> [path-pattern...]}"
BRANCH="${2:?Usage: gather-context.sh <repo-slug> <branch> [path-pattern...]}"
shift 2
PATH_PATTERNS=("$@")

# Determine clone target
CLONE_DIR="${WORKSPACE}/${REPO_SLUG}"

# Clone or fetch
if [[ -d "${CLONE_DIR}/.git" ]]; then
    git -C "${CLONE_DIR}" fetch origin "${BRANCH}" --depth=1 2>/dev/null || true
    git -C "${CLONE_DIR}" checkout "origin/${BRANCH}" --force 2>/dev/null || \
        git -C "${CLONE_DIR}" checkout "${BRANCH}" --force 2>/dev/null || true
else
    mkdir -p "$(dirname "${CLONE_DIR}")"
    if ! git clone --depth=1 --branch "${BRANCH}" "https://github.com/${REPO_SLUG}.git" "${CLONE_DIR}" 2>/dev/null; then
        echo "Error: failed to clone ${REPO_SLUG} at branch ${BRANCH}" >&2
        # Output empty result
        jq -n --arg repo "$REPO_SLUG" --arg branch "$BRANCH" --arg path "$CLONE_DIR" \
            '{repo: $repo, branch: $branch, clone_path: $path, candidates: []}'
        exit 0
    fi
fi

# Collect candidate files
CANDIDATES="[]"

if [[ ${#PATH_PATTERNS[@]} -eq 0 ]]; then
    # No patterns: list all tracked files
    PATH_PATTERNS=("**/*")
fi

for pattern in "${PATH_PATTERNS[@]}"; do
    # Use find with glob-like matching via bash globstar
    while IFS= read -r -d '' file; do
        rel_path="${file#${CLONE_DIR}/}"
        size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
        CANDIDATES=$(echo "$CANDIDATES" | jq --arg fp "$rel_path" --argjson sz "$size" \
            '. + [{"file_path": $fp, "size_bytes": $sz}]')
    done < <(cd "${CLONE_DIR}" && find . -path "./${pattern}" -type f -print0 2>/dev/null || \
             cd "${CLONE_DIR}" && eval "shopt -s globstar nullglob; printf '%s\0' ${pattern}" 2>/dev/null || true)
done

# Deduplicate by file_path
CANDIDATES=$(echo "$CANDIDATES" | jq 'unique_by(.file_path)')

jq -n --arg repo "$REPO_SLUG" --arg branch "$BRANCH" --arg path "$CLONE_DIR" --argjson candidates "$CANDIDATES" \
    '{repo: $repo, branch: $branch, clone_path: $path, candidates: $candidates}'
