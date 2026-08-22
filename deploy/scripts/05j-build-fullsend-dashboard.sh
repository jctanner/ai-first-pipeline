#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-/vagrant}"
cd "${PROJECT_ROOT}"

if command -v docker >/dev/null 2>&1; then
  CONTAINER_CMD=docker
elif command -v podman >/dev/null 2>&1; then
  CONTAINER_CMD=podman
else
  echo "ERROR: Neither docker nor podman found" >&2
  exit 1
fi

"${CONTAINER_CMD}" build -f deploy/fullsend-dashboard/Dockerfile -t fullsend-dashboard:latest .
sudo k3s ctr images rm docker.io/library/fullsend-dashboard:latest localhost/fullsend-dashboard:latest 2>/dev/null || true
"${CONTAINER_CMD}" save fullsend-dashboard:latest | sudo k3s ctr images import -
sudo k3s ctr images tag localhost/fullsend-dashboard:latest docker.io/library/fullsend-dashboard:latest 2>/dev/null || true
echo "Built and imported fullsend-dashboard:latest"
