#!/usr/bin/env bash
# Build and import the development-only Fullsend token mint.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
CONTEXT="${PROJECT_ROOT}/deploy/fullsend-mint-dev"
IMAGE="fullsend-mint-dev:k3s"

if command -v docker >/dev/null 2>&1; then
  CONTAINER_CMD=docker
elif command -v podman >/dev/null 2>&1; then
  CONTAINER_CMD=podman
else
  echo "ERROR: docker or podman is required to build ${IMAGE}" >&2
  exit 1
fi

echo "==> Building ${IMAGE}"
"${CONTAINER_CMD}" build -t "${IMAGE}" "${CONTEXT}"

echo "==> Importing ${IMAGE} into k3s"
"${CONTAINER_CMD}" save "${IMAGE}" | sudo k3s ctr images import -
sudo k3s ctr images tag "localhost/${IMAGE}" "docker.io/library/${IMAGE}" 2>/dev/null || true

echo "==> Imported image"
sudo k3s ctr images ls | grep fullsend-mint-dev
