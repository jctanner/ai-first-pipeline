#!/usr/bin/env bash
# Install the pinned Helm binary used by local deployment scripts.

set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "ERROR: run this script as root (use sudo)" >&2
  exit 1
fi

if command -v helm >/dev/null 2>&1; then
  echo "==> Helm already installed: $(helm version --short)"
  exit 0
fi

HELM_VERSION="${HELM_VERSION:-v4.2.0}"
case "$(uname -m)" in
  x86_64) HELM_ARCH=amd64 ;;
  aarch64|arm64) HELM_ARCH=arm64 ;;
  *) echo "ERROR: unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

tmp_dir="$(mktemp -d /tmp/breadboard-helm.XXXXXX)"
trap 'rm -rf "${tmp_dir}"' EXIT
archive="helm-${HELM_VERSION}-linux-${HELM_ARCH}.tar.gz"

echo "==> Installing Helm ${HELM_VERSION}"
curl -fsSL "https://get.helm.sh/${archive}" -o "${tmp_dir}/${archive}"
tar -xzf "${tmp_dir}/${archive}" -C "${tmp_dir}"
install -m 0755 "${tmp_dir}/linux-${HELM_ARCH}/helm" /usr/local/bin/helm
helm version --short
