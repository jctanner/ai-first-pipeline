# GitHub Emulator K3s Deployment Guide

This guide covers deploying the GitHub Emulator to k3s with cert-manager managed certificates.

## Quick Start

```bash
# From your host machine
vagrant ssh

# Inside the VM
cd /vagrant/deploy/scripts

# Build the github-emulator image
sudo bash 05a-build-github-emulator.sh

# Deploy to k3s
sudo bash 07-deploy-github-emulator.sh

# Check status
kubectl get pods -n ai-pipeline
kubectl logs -n ai-pipeline deployment/github-emulator --tail=20
```

## What's Different for K3s

The GitHub Emulator was originally designed for docker-compose deployment with Caddy's auto-generated self-signed certificates. For k3s deployment, we've made these changes:

### 1. **Dockerfile.k3s**
- Separate Dockerfile optimized for Kubernetes
- Does not copy Caddyfile at build time (mounted via ConfigMap instead)
- Pre-configured environment variables for k8s
- Tagged as `github-emulator:k3s`

### 2. **Caddyfile via ConfigMap**
- Caddyfile is mounted from a ConfigMap (`09-github-emulator-config.yaml`)
- Configured to use cert-manager certificates from `/etc/tls/`
- Can be updated without rebuilding the image:
  ```bash
  kubectl edit configmap github-emulator-config -n ai-pipeline
  kubectl rollout restart deployment/github-emulator -n ai-pipeline
  ```

### 3. **Certificate Management**
- Uses cert-manager with an internal CA issuer
- Certificate automatically mounted as a Kubernetes Secret
- Certificate paths: `/etc/tls/tls.crt` and `/etc/tls/tls.key`
- Certificate DNS names include:
  - `github-emulator.ai-pipeline.svc.cluster.local`
  - `github.local`
  - `192.168.56.10` (IP SAN)

### 4. **Critical Fixes**
- **DATABASE_URL**: Fixed to use 4 slashes for absolute path: `sqlite+aiosqlite:////data/github_emulator.db` (was 3 slashes, causing relative path issues)
- **GITHUB_EMULATOR_PORT**: Explicitly set to override Kubernetes auto-generated env vars
- **Container ports**: Changed from 3000 to 443/80 to match Caddy listeners
- **Service targetPorts**: Updated to match container ports (443/80)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Pod: github-emulator               │
│                                                     │
│  ┌──────────────┐         ┌──────────────────┐    │
│  │   Caddy      │  ───>   │    Uvicorn       │    │
│  │   :443       │         │   :8000          │    │
│  │              │         │   (FastAPI)      │    │
│  └──────────────┘         └──────────────────┘    │
│         │                                          │
│         │ Reads TLS certs from                     │
│         ▼                                          │
│  ┌──────────────────────────────────────┐         │
│  │  /etc/tls/                           │         │
│  │    tls.crt  (from cert-manager)      │         │
│  │    tls.key  (from cert-manager)      │         │
│  └──────────────────────────────────────┘         │
│         │                                          │
│         │ Reads Caddyfile from                     │
│         ▼                                          │
│  ┌──────────────────────────────────────┐         │
│  │  /etc/caddy/Caddyfile                │         │
│  │    (from ConfigMap)                  │         │
│  └──────────────────────────────────────┘         │
│                                                     │
│  ┌──────────────────────────────────────┐         │
│  │  /data/                              │         │
│  │    github_emulator.db (SQLite)       │         │
│  │    (from PersistentVolume)           │         │
│  └──────────────────────────────────────┘         │
└─────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Service            │
│  LoadBalancer       │
│  :443 → :443        │
│  :80  → :80         │
└─────────────────────┘
```

## Files Involved

```
deploy/
├── repos/github-emulator/
│   ├── Dockerfile              # Original (for docker-compose)
│   └── Dockerfile.k3s          # K3s-optimized (no Caddyfile copy)
│
├── k8s/
│   ├── 00-namespace.yaml       # ai-pipeline namespace
│   ├── 01-ca-issuer.yaml       # cert-manager CA issuer
│   ├── 02-certificates.yaml    # Certificate definitions
│   ├── 03-storage.yaml         # PVC for SQLite database
│   ├── 09-github-emulator-config.yaml  # Caddyfile ConfigMap
│   └── 10-github-emulator.yaml # Deployment + Service
│
└── scripts/
    ├── 05-build-images.sh           # Builds all images (optional)
    ├── 05a-build-github-emulator.sh # Builds just github-emulator:k3s (recommended)
    └── 07-deploy-github-emulator.sh # Deploys to k3s
```

## Manual Deployment Steps

If you want to understand what the deployment script does:

```bash
# 1. Build the image
cd /vagrant/deploy/repos/github-emulator
docker build -f Dockerfile.k3s -t github-emulator:k3s .
docker save github-emulator:k3s | sudo k3s ctr images import -

# 2. Create namespace
kubectl apply -f /vagrant/deploy/k8s/00-namespace.yaml

# 3. Set up certificate infrastructure
kubectl apply -f /vagrant/deploy/k8s/01-ca-issuer.yaml
kubectl apply -f /vagrant/deploy/k8s/02-certificates.yaml

# 4. Wait for certificate to be ready
kubectl wait --for=condition=ready certificate/github-emulator-tls -n ai-pipeline --timeout=120s

# 5. Create storage
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml

# 6. Create ConfigMap with Caddyfile
kubectl apply -f /vagrant/deploy/k8s/09-github-emulator-config.yaml

# 7. Deploy the application
kubectl apply -f /vagrant/deploy/k8s/10-github-emulator.yaml

# 8. Check status
kubectl get pods -n ai-pipeline
kubectl get svc -n ai-pipeline github-emulator
```

## Accessing the Service

### From within the cluster

```bash
# Any pod can access via DNS
curl -k https://github-emulator.ai-pipeline.svc.cluster.local

# Or the short name
curl -k https://github-emulator.ai-pipeline
```

### From the VM

```bash
# Get the LoadBalancer IP
kubectl get svc -n ai-pipeline github-emulator

# Use the EXTERNAL-IP (usually 192.168.56.10)
curl -k https://192.168.56.10:443
```

### From your host machine

Add to `/etc/hosts`:
```
192.168.56.10 github.local
```

Then access:
```bash
curl -k https://github.local
```

## Troubleshooting

### Pod won't start

Check events:
```bash
kubectl describe pod -n ai-pipeline -l app=github-emulator
```

Common issues:
- **Image not found**: Run `sudo bash 05-build-images.sh` again
- **PVC pending**: Check storage class `kubectl get pvc -n ai-pipeline`
- **Certificate not ready**: Check `kubectl get certificate -n ai-pipeline`

### Certificate issues

```bash
# Check certificate status
kubectl get certificate -n ai-pipeline github-emulator-tls

# Describe for details
kubectl describe certificate -n ai-pipeline github-emulator-tls

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Check if secret was created
kubectl get secret -n ai-pipeline github-emulator-tls
```

### Caddy configuration issues

Check the mounted Caddyfile:
```bash
kubectl exec -n ai-pipeline deployment/github-emulator -- cat /etc/caddy/Caddyfile
```

Check Caddy logs:
```bash
kubectl logs -n ai-pipeline deployment/github-emulator | grep caddy
```

Update the ConfigMap:
```bash
kubectl edit configmap github-emulator-config -n ai-pipeline
kubectl rollout restart deployment/github-emulator -n ai-pipeline
```

### Database issues

The SQLite database is stored in a PersistentVolume. To inspect:

```bash
# Exec into the pod
kubectl exec -it -n ai-pipeline deployment/github-emulator -- /bin/bash

# Inside the pod
ls -la /data/
sqlite3 /data/github_emulator.db ".tables"
```

### Test the API directly (bypass Caddy)

```bash
# Port forward to uvicorn directly
kubectl port-forward -n ai-pipeline deployment/github-emulator 8000:8000

# In another terminal
curl http://localhost:8000/api/v3
```

## Updating the Deployment

### Update application code

```bash
# Make your changes to the source
# Then rebuild and restart
cd /vagrant/deploy/scripts
sudo bash 05-build-images.sh
kubectl rollout restart deployment/github-emulator -n ai-pipeline
kubectl get pods -n ai-pipeline -w
```

### Update Caddyfile

```bash
# Edit the ConfigMap
kubectl edit configmap github-emulator-config -n ai-pipeline

# Restart to pick up changes
kubectl rollout restart deployment/github-emulator -n ai-pipeline
```

### Update certificates

Cert-manager auto-renews certificates. To force renewal:

```bash
# Delete the secret (cert-manager will recreate)
kubectl delete secret -n ai-pipeline github-emulator-tls

# Wait for it to be recreated
kubectl wait --for=condition=ready certificate/github-emulator-tls -n ai-pipeline
```

## Cleanup

```bash
# Remove just the github-emulator
kubectl delete -f /vagrant/deploy/k8s/10-github-emulator.yaml
kubectl delete -f /vagrant/deploy/k8s/09-github-emulator-config.yaml

# Remove storage (WARNING: deletes database)
kubectl delete -f /vagrant/deploy/k8s/03-storage.yaml

# Remove entire namespace (WARNING: deletes everything)
kubectl delete namespace ai-pipeline
```

## Environment Variables

The deployment sets these environment variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `GITHUB_EMULATOR_DATA_DIR` | `/data` | SQLite database location |
| `GITHUB_EMULATOR_DATABASE_URL` | `sqlite+aiosqlite:////data/github_emulator.db` | Database connection (4 slashes = absolute path) |
| `GITHUB_EMULATOR_PORT` | `8000` | Application port (overrides k8s auto-generated env) |
| `GITHUB_EMULATOR_BASE_URL` | `https://github-emulator.ai-pipeline.svc.cluster.local` | External URL |
| `GITHUB_EMULATOR_HOSTNAME` | `github-emulator.ai-pipeline.svc.cluster.local` | Hostname for Caddy |
| `TLS_CERT_FILE` | `/etc/tls/tls.crt` | Certificate path |
| `TLS_KEY_FILE` | `/etc/tls/tls.key` | Private key path |
| `AUTO_TLS` | `false` | Disable Caddy auto-TLS |
| `PYTHONPATH` | `/app` | Python module path |

These can be overridden by editing the Deployment:
```bash
kubectl edit deployment github-emulator -n ai-pipeline
```

## Next Steps

- Configure GitHub webhooks to point to the emulator
- Set up Ingress for external access (instead of LoadBalancer)
- Add monitoring/metrics collection
- Set up backup for the SQLite database
- Configure OAuth apps in the emulator
