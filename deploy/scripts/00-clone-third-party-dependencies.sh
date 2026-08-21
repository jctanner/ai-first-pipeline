#!/usr/bin/env bash
# Populate third-party source and deployment dependencies under checkouts/.

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
MANIFEST="${PROJECT_ROOT}/deploy/dependencies.json"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required to read ${MANIFEST}" >&2
  exit 1
fi

if [ ! -f "${MANIFEST}" ]; then
  echo "ERROR: dependency manifest not found: ${MANIFEST}" >&2
  exit 1
fi

openshell_repo=$(jq -er '.dependencies[] | select(.name == "openshell") | .repository' "${MANIFEST}")
openshell_ref=$(jq -er '.dependencies[] | select(.name == "openshell") | .ref' "${MANIFEST}")
openshell_checkout=$(jq -er '.dependencies[] | select(.name == "openshell") | .checkout' "${MANIFEST}")
openshell_chart=$(jq -er '.dependencies[] | select(.name == "openshell") | .chart' "${MANIFEST}")

checkout_path="${PROJECT_ROOT}/${openshell_checkout}"
chart_path="${checkout_path}/${openshell_chart}"
mkdir -p "$(dirname "${checkout_path}")"

if [ -d "${checkout_path}/.git" ]; then
  if [ -n "$(git -C "${checkout_path}" status --short)" ]; then
    echo "ERROR: refusing to modify dirty checkout: ${checkout_path}" >&2
    exit 1
  fi
  current_ref=$(git -C "${checkout_path}" rev-parse HEAD)
  if [ "${current_ref}" != "${openshell_ref}" ]; then
    echo "==> Updating OpenShell checkout to ${openshell_ref}"
    git -C "${checkout_path}" fetch --tags origin
    git -C "${checkout_path}" checkout --detach "${openshell_ref}"
  else
    echo "==> OpenShell checkout already matches ${openshell_ref}"
  fi
elif [ -e "${checkout_path}" ]; then
  echo "ERROR: ${checkout_path} exists but is not a Git checkout" >&2
  exit 1
else
  echo "==> Cloning OpenShell into ${checkout_path}"
  git clone "${openshell_repo}" "${checkout_path}"
  git -C "${checkout_path}" checkout --detach "${openshell_ref}"
fi

if [ ! -d "${chart_path}" ]; then
  echo "ERROR: OpenShell Helm chart not found: ${chart_path}" >&2
  exit 1
fi

echo "OpenShell source is available at ${checkout_path}"
echo "Agent Sandbox is installed from the pinned manifest declared in ${MANIFEST}"
