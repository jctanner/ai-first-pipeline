#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../../../../" && pwd)"
IMAGE="ghemu-actions-real-runner-test:latest"
CONTAINER="ghemu-actions-real-runner-m8"
CA_FILE="$(mktemp /tmp/m8-runner-ca.XXXXXX.crt)"

if ! docker image inspect "${IMAGE}" >/dev/null 2>&1; then
  echo "Missing ${IMAGE}; build it from checkouts/github-emulator/runner-real first." >&2
  exit 2
fi

cleanup() {
  docker stop "${CONTAINER}" >/dev/null 2>&1 || true
  rm -f "${CA_FILE}"
}
trap cleanup EXIT

kubectl -n ai-pipeline get secret internal-ca-secret \
  -o jsonpath='{.data.ca\.crt}' | base64 -d >"${CA_FILE}"

docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
docker run --rm --name "${CONTAINER}" --user root \
  --add-host github.local:host-gateway \
  -e RUNNER_ALLOW_RUNASROOT=1 \
  -e GITHUB_EMULATOR_URL=https://github.local \
  -e GITHUB_EMULATOR_API_URL=https://github.local/api/v3 \
  -e GITHUB_EMULATOR_TOKEN=ghp_admin_default_token \
  -e RUNNER_REPO=fullsend-dev/triage-target \
  -e RUNNER_NAME=fullsend-real-runner \
  -e RUNNER_LABELS=self-hosted,linux,fullsend-real \
  -v "${CA_FILE}:/mnt/breadboard-ca.crt:ro" \
  --entrypoint /bin/bash \
  "${IMAGE}" -lc 'cp /mnt/breadboard-ca.crt /usr/local/share/ca-certificates/breadboard-internal-ca.crt && update-ca-certificates >/dev/null && exec /entrypoint.sh' \
  >"${ROOT_DIR}/var/demos/fullsend-dev-stack/m8-real-runner.log" 2>&1 &

runner_pid=$!
sleep 15
python3 "${ROOT_DIR}/var/demos/fullsend-dev-stack/scripts/m8_real_runner_seed.py"
kill "${runner_pid}" >/dev/null 2>&1 || true
wait "${runner_pid}" >/dev/null 2>&1 || true
