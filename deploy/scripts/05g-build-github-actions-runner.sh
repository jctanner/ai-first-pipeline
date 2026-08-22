#!/usr/bin/env bash
# Build and import the GitHub emulator's deterministic Python Actions runner.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
RUNNER_CONTEXT="${PROJECT_ROOT}/checkouts/github-emulator/runner"
IMAGE="github-emulator-actions-runner:k3s"

if command -v docker >/dev/null 2>&1; then
  CONTAINER_CMD=docker
elif command -v podman >/dev/null 2>&1; then
  CONTAINER_CMD=podman
else
  echo "ERROR: docker or podman is required" >&2
  exit 1
fi

if [[ ! -f "${RUNNER_CONTEXT}/Dockerfile" ]]; then
  echo "ERROR: GitHub emulator runner checkout is missing: ${RUNNER_CONTEXT}" >&2
  exit 1
fi

echo "==> Building ${IMAGE} with ${CONTAINER_CMD}"
"${CONTAINER_CMD}" build -f "${RUNNER_CONTEXT}/Dockerfile" -t "${IMAGE}" "${RUNNER_CONTEXT}"

echo "==> Importing ${IMAGE} into k3s"
sudo k3s ctr images rm "docker.io/library/${IMAGE}" "localhost/${IMAGE}" 2>/dev/null || true
"${CONTAINER_CMD}" save "${IMAGE}" | sudo k3s ctr images import -
sudo k3s ctr images tag "localhost/${IMAGE}" "docker.io/library/${IMAGE}" 2>/dev/null || true

echo "==> Imported images"
sudo k3s ctr images ls | grep github-emulator-actions-runner
