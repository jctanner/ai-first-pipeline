#!/bin/bash
# Install K3s on the VM

set -euo pipefail

echo "==> Installing K3s..."

# Install K3s without Traefik (we'll use our own ingress setup)
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --disable traefik \
  --write-kubeconfig-mode 644 \
  --tls-san 192.168.56.10 \
  --node-name ai-pipeline-k3s" sh -

# Wait for K3s to be ready
echo "==> Waiting for K3s to be ready..."
timeout 120s bash -c 'until kubectl get nodes 2>/dev/null | grep -q Ready; do sleep 2; done'

# Set up kubectl for vagrant user
mkdir -p /home/vagrant/.kube
cp /etc/rancher/k3s/k3s.yaml /home/vagrant/.kube/config
chown -R vagrant:vagrant /home/vagrant/.kube
chmod 600 /home/vagrant/.kube/config

# Also set KUBECONFIG in bashrc for convenience
if ! grep -q "KUBECONFIG" /home/vagrant/.bashrc; then
  echo 'export KUBECONFIG=/home/vagrant/.kube/config' >> /home/vagrant/.bashrc
fi

echo "==> K3s installation complete!"
echo ""
kubectl get nodes
echo ""
echo "==> Cluster is ready. Next: Run 02-install-cert-manager.sh"
