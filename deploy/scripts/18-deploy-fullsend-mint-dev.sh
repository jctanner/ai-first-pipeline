#!/usr/bin/env bash
# Bootstrap emulator PATs and deploy the development-only Fullsend mint.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
GITHUB_URL="${GITHUB_EMULATOR_URL:-https://github.local}"
GITHUB_TOKEN="${GITHUB_EMULATOR_TOKEN:-ghp_admin_default_token}"
OIDC_TOKEN="${FULLSEND_DEV_OIDC_TOKEN:-fullsend-dev-oidc}"
API="${GITHUB_URL%/}/api/v3"

mint_pat() {
  local role="$1"
  local scopes="$2"
  local response
  response="$(curl --silent --show-error --fail --insecure \
    -X POST "${API}/admin/tokens" \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H 'Content-Type: application/json' \
    -d "$(jq -nc --arg name "fullsend-dev-${role}" --argjson scopes "${scopes}" \
      '{login:"admin",name:$name,scopes:$scopes}')")"
  jq -er '.token' <<<"${response}"
}

echo "==> Creating development role tokens in the GitHub emulator"
readonly READ_SCOPES='["repo:status","read:org"]'
readonly ISSUE_SCOPES='["repo","repo:status","read:org"]'
TRIAGE_TOKEN="$(mint_pat triage "${ISSUE_SCOPES}")"
SCRIBE_TOKEN="$(mint_pat scribe "${ISSUE_SCOPES}")"
CODER_TOKEN="$(mint_pat coder "${ISSUE_SCOPES}")"
REVIEW_TOKEN="$(mint_pat review "${READ_SCOPES}")"
FIX_TOKEN="$(mint_pat fix "${ISSUE_SCOPES}")"
FULLSEND_TOKEN="$(mint_pat fullsend "${ISSUE_SCOPES}")"

ROLE_TOKENS="$(jq -nc \
  --arg triage "${TRIAGE_TOKEN}" \
  --arg scribe "${SCRIBE_TOKEN}" \
  --arg coder "${CODER_TOKEN}" \
  --arg review "${REVIEW_TOKEN}" \
  --arg fix "${FIX_TOKEN}" \
  --arg fullsend "${FULLSEND_TOKEN}" \
  '{triage:$triage,scribe:$scribe,coder:$coder,review:$review,fix:$fix,fullsend:$fullsend}')"

echo "==> Creating fullsend-mint-dev credentials secret"
kubectl -n ai-pipeline create secret generic fullsend-mint-dev-credentials \
  --from-literal=oidc-token="${OIDC_TOKEN}" \
  --from-literal=role-tokens="${ROLE_TOKENS}" \
  --dry-run=client -o yaml | kubectl apply -f - >/dev/null

echo "==> Deploying fullsend-mint-dev"
kubectl apply -f "${PROJECT_ROOT}/deploy/k8s/24-fullsend-mint-dev.yaml"
kubectl -n ai-pipeline rollout status deployment/fullsend-mint-dev --timeout=120s
echo "==> fullsend-mint-dev is ready"
