#!/usr/bin/env bash
# Sync the pipeline project and start the standalone SME/refine-loop demo.
#
# Usage:
#   scripts/run_strat_dashboard_sme_loop_test.sh
#   scripts/run_strat_dashboard_sme_loop_test.sh continue-sme-loop \
#     --var strat_issue=RHAISTRAT-1

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
MARKOVD_CLI="${MARKOVD_CLI:-${REPO_ROOT}/checkouts/markovd/bin/markovd-cli}"
PROJECT="${MARKOVD_PROJECT:-ai-first-pipeline}"
DEMO="${MARKOVD_DEMO:-var-demos-strat-dashboard-sme-loop-test}"
DEMO_PATH="${MARKOVD_DEMO_PATH:-var/demos/strat-dashboard-sme-loop-test}"
WORKFLOW="${1:-main}"

if [[ $# -gt 0 ]]; then
  shift
fi

if [[ ! -x "${MARKOVD_CLI}" ]]; then
  echo "markovd-cli not found or not executable: ${MARKOVD_CLI}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

"${MARKOVD_CLI}" projects sync "${PROJECT}" --wait
"${MARKOVD_CLI}" projects import "${PROJECT}" "${DEMO_PATH}" --kind directory
"${MARKOVD_CLI}" runs create "${DEMO}" --workflow "${WORKFLOW}" "$@" --wait
