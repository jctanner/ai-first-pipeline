#!/usr/bin/env bash
# Run the M6 Fullsend/Claude smoke and verify its emulator-side issue comment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
SOURCE_MANIFEST="${PROJECT_ROOT}/deploy/k8s/25-fullsend-m4-smoke.yaml"
MANIFEST="$(mktemp)"
trap 'rm -f "${MANIFEST}" "${MANIFEST}.tmp"' EXIT

sed \
  -e 's/fullsend-m4-smoke/fullsend-m6-result/g' \
  -e 's/m4-smoke/m6-result/g' \
  -e 's/runtime: dummy/runtime: claude/g' \
  -e 's/name: triage/name: claude/g' \
  -e 's/fullsend run triage/fullsend run claude/g' \
  -e 's/milestone: m4/milestone: m6/g' \
  -e 's/M4/M6/g' \
  -e 's/--forge github \\/--forge github/' \
  -e '/--no-post-script/d' \
  "${SOURCE_MANIFEST}" > "${MANIFEST}"

awk '
/^    env:$/ && !runner_env_added {
  print "    host_files:"
  print "      - src: /var/run/secrets/gcp/credentials.json"
  print "        dest: /sandbox/workspace/gcp-credentials.json"
  print "        optional: true"
  print
  print "      runner:"
  print "        FULLSEND_STATUS_REPO: fullsend-dev/triage-target"
  print "        FULLSEND_STATUS_NUMBER: \"1\""
  runner_env_added = 1
  next
}
/^[[:space:]]+GITHUB_API_URL: http:\/\/github\.local\/api\/v3$/ {
  print
  print "        CLAUDE_CODE_USE_VERTEX: ${CLAUDE_CODE_USE_VERTEX}"
  print "        CLOUD_ML_REGION: ${CLOUD_ML_REGION}"
  print "        ANTHROPIC_VERTEX_PROJECT_ID: ${ANTHROPIC_VERTEX_PROJECT_ID}"
  print "        GOOGLE_APPLICATION_CREDENTIALS: /sandbox/workspace/gcp-credentials.json"
  next
}
/^[[:space:]]+role: triage$/ && !post_script_added {
  print
  print "    post_script: scripts/post-triage.sh"
  post_script_added = 1
  next
}
/^---$/ && !post_script_data_added {
  print "  post-triage.sh: |"
  print "    #!/bin/sh"
  print "    set -eu"
  print "    api=\"${GITHUB_API_URL:-http://github.local/api/v3}\""
  print "    repo=\"${FULLSEND_STATUS_REPO:?FULLSEND_STATUS_REPO is required}\""
  print "    number=\"${FULLSEND_STATUS_NUMBER:?FULLSEND_STATUS_NUMBER is required}\""
  print "    token=\"${GITHUB_TOKEN:?GITHUB_TOKEN is required}\""
  print "    body=\"<!-- fullsend-dev-stack:triage -->\\nFullsend M6 Claude/Vertex triage completed through OpenShell.\""
  print "    curl_args=\"\""
  print "    if [ \"${NO_SSL_VERIFY:-0}\" = \"1\" ]; then curl_args=\"-k\"; fi"
  print "    curl ${curl_args} -fsS -o /dev/null -X POST \"${api}/repos/${repo}/issues/${number}/comments\" -H \"Authorization: token ${token}\" -H \"Content-Type: application/json\" -d \"$(jq -nc --arg body \"${body}\" \x27{body:$body}\x27)\""
  print "    echo \"Fullsend M6 result comment posted to ${repo}#${number}\""
  post_script_data_added = 1
}
/^[[:space:]]+- key: behaviour-current-scenario\.yaml$/ {
  print
  getline
  print
  print "              - key: post-triage.sh"
  print "                path: scripts/post-triage.sh"
  next
}
{ print }
' "${MANIFEST}" > "${MANIFEST}.tmp"
mv "${MANIFEST}.tmp" "${MANIFEST}"

if [ -n "${M6_MANIFEST_OUTPUT:-}" ]; then
  cp "${MANIFEST}" "${M6_MANIFEST_OUTPUT}"
  exit 0
fi

kubectl -n ai-pipeline delete job fullsend-m6-result --ignore-not-found --wait=true
kubectl -n ai-pipeline delete pods -l job-name=fullsend-m6-result --ignore-not-found --wait=true
kubectl apply -f "${MANIFEST}"

POD=""
for _ in $(seq 1 600); do
  POD="$(kubectl -n ai-pipeline get pods -l job-name=fullsend-m6-result -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
  if [ -n "${POD}" ] && kubectl -n ai-pipeline exec "${POD}" -c artifact-holder -- test -f /artifacts/.fullsend-done >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if [ -z "${POD}" ] || ! kubectl -n ai-pipeline exec "${POD}" -c artifact-holder -- test -f /artifacts/.fullsend-done >/dev/null 2>&1; then
  echo "Fullsend M6 result smoke did not produce completion marker" >&2
  kubectl -n ai-pipeline get pods -l job-name=fullsend-m6-result -o wide >&2 || true
  exit 1
fi

kubectl -n ai-pipeline logs "${POD}"
mkdir -p "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/artifacts/m6"
kubectl -n ai-pipeline cp "${POD}:/artifacts" "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/artifacts/m6" --container=artifact-holder --retries=2
STATUS="$(kubectl -n ai-pipeline exec "${POD}" -c artifact-holder -- cat /artifacts/.fullsend-status)"

GITHUB_URL="${GITHUB_EMULATOR_URL:-https://github.local}"
GITHUB_API="${GITHUB_URL%/}/api/v3"
GITHUB_TOKEN="${GITHUB_EMULATOR_TOKEN:-ghp_admin_default_token}"
COMMENTS="$(curl --silent --show-error --fail --insecure \
  -H "Authorization: token ${GITHUB_TOKEN}" \
  -H 'Accept: application/vnd.github+json' \
  "${GITHUB_API}/repos/fullsend-dev/triage-target/issues/1/comments")"
mkdir -p "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/artifacts/m6"
jq '[.[] | {id,body,user:.user.login,created_at}]' <<<"${COMMENTS}" > "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/artifacts/m6/emulator-comments.json"
if ! jq -e 'any(.[]; .body | contains("<!-- fullsend-dev-stack:triage -->"))' "${PROJECT_ROOT}/var/demos/fullsend-dev-stack/artifacts/m6/emulator-comments.json" >/dev/null; then
  echo "Fullsend M6 did not create the expected marked issue comment" >&2
  kubectl -n ai-pipeline delete job fullsend-m6-result --ignore-not-found
  exit 1
fi

kubectl -n ai-pipeline delete job fullsend-m6-result --ignore-not-found

if [ "${STATUS}" != "0" ]; then
  echo "Fullsend M6 result smoke exited with status ${STATUS}" >&2
  exit 1
fi

echo "M6 emulator result verified; artifacts copied to var/demos/fullsend-dev-stack/artifacts/m6"
