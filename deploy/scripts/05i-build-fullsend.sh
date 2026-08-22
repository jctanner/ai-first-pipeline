#!/usr/bin/env bash
# Build/import the Fullsend host launcher and local OpenShell sandbox images.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
FULLSEND_ROOT="${PROJECT_ROOT}/checkouts.tmp/fullsend"
OPENSHELL_ROOT="${PROJECT_ROOT}/checkouts/openshell"
FULLSEND_PATCHES=(
  "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/patches/fullsend/0001-openshell-compatible-sandbox-and-dummy-env.patch"
  "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/patches/fullsend/0002-allow-insecure-dev-mint-url.patch"
)
RUNNER_CONTEXT="${PROJECT_ROOT}/deploy/fullsend-runner-dev"
SANDBOX_CONTEXT="${PROJECT_ROOT}/deploy/fullsend-sandbox-dev"
RUNNER_IMAGE="fullsend-runner-dev:k3s"
SANDBOX_IMAGE="fullsend-sandbox-dev:k3s"

if command -v docker >/dev/null 2>&1; then
  CONTAINER_CMD=docker
elif command -v podman >/dev/null 2>&1; then
  CONTAINER_CMD=podman
else
  echo "ERROR: docker or podman is required" >&2
  exit 1
fi

for required in "${FULLSEND_ROOT}/go.mod" "${OPENSHELL_ROOT}/Cargo.toml" "${FULLSEND_PATCHES[@]}"; do
  if [[ ! -f "${required}" ]]; then
    echo "ERROR: required checkout file is missing: ${required}" >&2
    exit 1
  fi
done

BUILD_CONTEXT="$(mktemp -d /tmp/fullsend-runner-build.XXXXXX)"
FULLSEND_BUILD_ROOT="$(mktemp -d /tmp/fullsend-source-build.XXXXXX)"
cleanup() { rm -rf "${BUILD_CONTEXT}" "${FULLSEND_BUILD_ROOT}"; }
trap cleanup EXIT

echo "==> Building Fullsend host launcher from ${FULLSEND_ROOT}"
git -C "${FULLSEND_ROOT}" archive HEAD | tar -xf - -C "${FULLSEND_BUILD_ROOT}"
for patch in "${FULLSEND_PATCHES[@]}"; do
  echo "==> Applying Fullsend patch $(basename "${patch}")"
  git -C "${FULLSEND_BUILD_ROOT}" apply --unidiff-zero "${patch}"
done
(cd "${FULLSEND_BUILD_ROOT}" && GOTOOLCHAIN=auto go build -buildvcs=false -trimpath -ldflags '-s -w' -o "${BUILD_CONTEXT}/fullsend" ./cmd/fullsend)

echo "==> Building OpenShell CLI from pinned checkout"
(cd "${OPENSHELL_ROOT}" && cargo build --release -p openshell-cli)
cp "${OPENSHELL_ROOT}/target/release/openshell" "${BUILD_CONTEXT}/openshell"

echo "==> Building ${RUNNER_IMAGE}"
"${CONTAINER_CMD}" build -f "${RUNNER_CONTEXT}/Containerfile" -t "${RUNNER_IMAGE}" "${BUILD_CONTEXT}"

echo "==> Building ${SANDBOX_IMAGE}"
"${CONTAINER_CMD}" build -f "${SANDBOX_CONTEXT}/Containerfile" -t "${SANDBOX_IMAGE}" "${SANDBOX_CONTEXT}"

for image in "${RUNNER_IMAGE}" "${SANDBOX_IMAGE}"; do
  echo "==> Importing ${image} into k3s"
  sudo k3s ctr images rm "docker.io/library/${image}" "localhost/${image}" 2>/dev/null || true
  "${CONTAINER_CMD}" save "${image}" | sudo k3s ctr images import -
  sudo k3s ctr images tag "localhost/${image}" "docker.io/library/${image}" 2>/dev/null || true
done

echo "==> Imported Fullsend/OpenShell images"
sudo k3s ctr images ls | grep -E 'fullsend-(runner|sandbox)-dev'
