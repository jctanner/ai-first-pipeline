#!/bin/bash
# Install K3s directly on the host (not in a VM)

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "This script must be run as root (use sudo)"
  exit 1
fi

CALLING_USER="${SUDO_USER:-$USER}"
CALLING_HOME=$(eval echo "~${CALLING_USER}")

echo "==> Installing K3s on host..."
echo "  User: ${CALLING_USER}"
echo "  Home: ${CALLING_HOME}"

echo "==> Installing deployment prerequisites..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl git jq

K3S_FLAGS="--disable traefik --write-kubeconfig-mode 644 --tls-san 127.0.0.1 --node-name ai-pipeline-k3s"

if mountpoint -q /data 2>/dev/null; then
  echo "  /data is a mount point, using /data/k3s for k3s storage"
  mkdir -p /data/k3s
  K3S_FLAGS="${K3S_FLAGS} --data-dir /data/k3s"
else
  echo "  /data not found, using default k3s storage (/var/lib/rancher/k3s)"
fi

echo ""
echo "==> K3s flags: ${K3S_FLAGS}"
echo ""

curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server ${K3S_FLAGS}" sh -

echo "==> Waiting for K3s to be ready..."
timeout 120s bash -c 'until kubectl get nodes 2>/dev/null | grep -q Ready; do sleep 2; done'

echo "==> Setting up kubeconfig for ${CALLING_USER}..."
mkdir -p "${CALLING_HOME}/.kube"
cp /etc/rancher/k3s/k3s.yaml "${CALLING_HOME}/.kube/config"
chown -R "${CALLING_USER}:${CALLING_USER}" "${CALLING_HOME}/.kube"
chmod 600 "${CALLING_HOME}/.kube/config"

if ! grep -q "KUBECONFIG" "${CALLING_HOME}/.bashrc" 2>/dev/null; then
  echo "export KUBECONFIG=${CALLING_HOME}/.kube/config" >> "${CALLING_HOME}/.bashrc"
fi

echo ""
echo "==> K3s installation complete!"
echo ""
kubectl get nodes
echo ""
echo "==> Next: Run deploy-all.sh with PROJECT_ROOT set to your project directory"
