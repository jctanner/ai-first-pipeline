#!/usr/bin/env bash
# Run the upstream-main contradiction reproduction demo.
#
# Usage:
#   var/demos/strat-contradiction-reconciliation-test/run.sh [main|fixed|resolved]
#   var/demos/strat-contradiction-reconciliation-test/run.sh \
#     fixed --var rfe_issue=RHAIRFE-42

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../../.." && pwd)"
MARKOVD_CLI="${MARKOVD_CLI:-${REPO_ROOT}/deploy/repos/markovd/bin/markovd-cli}"
PROJECT="${MARKOVD_PROJECT:-ai-first-pipeline}"
DEMO="${MARKOVD_DEMO:-var-demos-strat-contradiction-reconciliation-test}"
WORKFLOW="${1:-main}"

if [[ $# -gt 0 && "${1}" != --* ]]; then
  shift
fi

if [[ ! -x "${MARKOVD_CLI}" ]]; then
  echo "markovd-cli not found or not executable: ${MARKOVD_CLI}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

"${MARKOVD_CLI}" projects sync "${PROJECT}" --wait
"${MARKOVD_CLI}" projects import "${PROJECT}" \
  "var/demos/strat-contradiction-reconciliation-test" --kind directory
"${MARKOVD_CLI}" runs create "${DEMO}" --workflow "${WORKFLOW}" "$@" --wait
