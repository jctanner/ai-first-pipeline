#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../../../../" && pwd)"
EMULATOR_DIR="${ROOT_DIR}/checkouts/github-emulator"

if [ ! -f "${EMULATOR_DIR}/pyproject.toml" ]; then
  echo "github-emulator checkout is required: ${EMULATOR_DIR}" >&2
  exit 2
fi

cd "${EMULATOR_DIR}"
exec uv run python -m pytest tests/test_actions_execution.py -q
