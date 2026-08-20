#!/usr/bin/env bash
# Clone source repositories used to build locally deployed platform components.

set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
CHECKOUTS_DIR="${PROJECT_ROOT}/checkouts"

repos=(
  "github-emulator|https://github.com/jctanner/github-emulator.git"
  "gitlab-emulator|https://github.com/jctanner/gitlab-emulator.git"
  "jira-emulator|https://github.com/jctanner/jira-emulator.git"
  "markov|https://github.com/jctanner/markov.git"
  "markovd|https://github.com/jctanner/markovd.git"
  "observatory|https://github.com/opendatahub-io/observatory.git"
)

mkdir -p "${CHECKOUTS_DIR}"

for repo in "${repos[@]}"; do
  name="${repo%%|*}"
  url="${repo#*|}"
  destination="${CHECKOUTS_DIR}/${name}"

  if [ -d "${destination}/.git" ]; then
    echo "==> ${name} already exists; keeping current checkout"
    continue
  fi

  if [ -e "${destination}" ]; then
    echo "ERROR: ${destination} exists but is not a Git checkout" >&2
    exit 1
  fi

  echo "==> Cloning ${name} into ${destination}"
  git clone "${url}" "${destination}"
done

echo "Component repositories are available in ${CHECKOUTS_DIR}"
