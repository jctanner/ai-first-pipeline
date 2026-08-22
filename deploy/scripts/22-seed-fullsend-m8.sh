#!/usr/bin/env bash
# Seed the repeatable M8 GitHub App/OIDC/action fixture after the emulators are ready.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
export PYTHONPATH="${PROJECT_ROOT}/var/demos/fullsend-dev-stack/scripts"

python3 "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/scripts/m8_seed.py"
python3 "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/scripts/m8_mirror.py"
