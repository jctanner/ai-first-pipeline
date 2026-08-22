#!/usr/bin/env bash
# Build and exercise Fullsend's real standalone JWKS mint against the emulator.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
FULLSEND="${ROOT}/checkouts.tmp/fullsend"
GITHUB_URL="${GITHUB_EMULATOR_URL:-https://github.local}"
API="${GITHUB_URL%/}/api/v3"
TOKEN="${GITHUB_EMULATOR_TOKEN:-ghp_admin_default_token}"
PORT="${M8_MINT_PORT:-18080}"
TMP="$(mktemp -d /tmp/fullsend-m8-mint.XXXXXX)"
cleanup() {
  if [ -n "${MINT_PID:-}" ]; then kill "${MINT_PID}" 2>/dev/null || true; fi
  rm -rf "${TMP}"
}
trap cleanup EXIT

PYTHONPATH="${ROOT}/var/demos/fullsend-dev-stack/scripts" \
  python3 "${ROOT}/var/demos/fullsend-dev-stack/scripts/m8_seed.py" >/dev/null
app_json="${TMP}/app.json"
curl -ksSf -H "Authorization: token ${TOKEN}" "${API}/admin/apps/1001" >"${app_json}"
mkdir -p "${TMP}/pems"
jq -r '.private_key' "${app_json}" >"${TMP}/pems/triage.pem"
chmod 600 "${TMP}/pems/triage.pem"

(cd "${FULLSEND}/cmd/mint" && go build -o "${TMP}/fullsend-mint" .)

NO_SSL_VERIFY=1 \
OIDC_ISSUER_URL="${GITHUB_URL}" \
GITHUB_API_URL="${API}" \
ROLE_APP_IDS='{"triage":"1001"}' \
PEM_DIR="${TMP}/pems" \
ALLOWED_ORGS="fullsend-dev" \
ALLOWED_WORKFLOW_FILES='*' \
PER_REPO_WIF_REPOS='fullsend-dev/triage-target' \
WORKFLOW_HOST_REPOS='fullsend-dev/fullsend' \
PORT="${PORT}" \
  "${TMP}/fullsend-mint" >"${TMP}/mint.log" 2>&1 &
MINT_PID=$!

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
oidc_token="$(curl -ksSf -H 'Authorization: Bearer fullsend-action-request' "${GITHUB_URL}/actions/oidc/token?audience=fullsend-mint" | jq -r .value)"
response="$(curl -sS -X POST "http://127.0.0.1:${PORT}/v1/token" -H "Authorization: Bearer ${oidc_token}" -H 'Content-Type: application/json' -d '{"role":"triage","repos":["triage-target"]}')"
case "$(jq -r .token <<<"${response}")" in
  ghs_*) ;;
  *) echo "standalone mint did not return an installation token: ${response}" >&2; cat "${TMP}/mint.log" >&2; exit 1 ;;
esac
jq '{status:"passed", token_prefix:(.token | .[0:8]), granted_repos, granted_permissions, repository_selection}' <<<"${response}"
