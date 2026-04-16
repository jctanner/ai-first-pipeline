# Deployment Scripts

Automated deployment scripts for setting up the AI-First Pipeline on K3s.

## Quick Start

From inside the Vagrant VM (after `vagrant up` and `vagrant ssh`):

```bash
cd /vagrant/deploy/scripts
sudo bash deploy-all.sh
```

This runs all deployment steps in order.

## Individual Scripts

Run these scripts in order for manual deployment:

### 1. Core Infrastructure

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `01-install-k3s.sh` | Install K3s Kubernetes distribution | None |
| `02-install-cert-manager.sh` | Install cert-manager for TLS certificates | K3s running |
| `03-setup-certificates.sh` | Create internal CA and service certificates | cert-manager installed |
| `04-extract-ca-cert.sh` | Extract CA certificate to ConfigMap | Certificates created |

### 2. Secrets and Configuration

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `06-create-secrets.sh` | Create Kubernetes secrets from .env file | K3s running, .env exists |

### 3. Build Images

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `05-build-images.sh` | Build all container images | Docker installed |
| `05a-build-github-emulator.sh` | Build GitHub emulator image only | GitHub emulator repo cloned |
| `05b-build-jira-emulator.sh` | Build Jira emulator image only | Jira emulator repo cloned |

### 4. Deploy Services

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `07-deploy-github-emulator.sh` | Deploy GitHub emulator | Images built, ConfigMap applied |
| `08-deploy-jira-emulator.sh` | Deploy Jira emulator | Images built, ConfigMap applied |
| `10-deploy-mlflow.sh` | Deploy MLflow tracking server | Storage provisioned |
| `09-deploy-ingress-proxy.sh` | Deploy Go reverse proxy (ingress) | All services deployed |

### 5. Utilities

| Script | Description | Dependencies |
|--------|-------------|--------------|
| `redeploy-dashboard.sh` | Rebuild and redeploy dashboard | Dashboard already deployed |
| `access-emulators.sh` | Set up port forwarding to emulators | Services running |
| `99-verify-cluster.sh` | Verify cluster health | Cluster deployed |

## Complete Deployment Flow

The `deploy-all.sh` script runs the following steps:

1. **Install K3s** - Lightweight Kubernetes distribution
2. **Install cert-manager** - Certificate management
3. **Setup certificates** - Internal CA and service certs
4. **Extract CA cert** - Make CA available to pods
5. **Create secrets** - Load credentials from .env
6. **Build images** - Dashboard, GitHub, Jira emulators
7. **Deploy storage** - PersistentVolumeClaims
8. **Deploy ConfigMaps** - Emulator configurations
9. **Deploy GitHub emulator** - GitHub API emulator
10. **Deploy Jira emulator** - Jira API emulator
11. **Deploy dashboard** - Pipeline web UI
12. **Deploy MLflow** - ML tracking server
13. **Deploy ingress proxy** - Go reverse proxy for unified access

## Environment Requirements

### Required Files

- `/vagrant/.env` - Environment variables with credentials
- `/vagrant/deploy/repos/github-emulator/` - GitHub emulator source
- `/vagrant/deploy/repos/jira-emulator/` - Jira emulator source

### .env File Format

```bash
# Vertex AI Configuration
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project

# Jira Emulator (in-cluster)
JIRA_SERVER=https://jira-emulator.ai-pipeline.svc.cluster.local
JIRA_USER=admin
JIRA_TOKEN=admin

# MCP Server
ATLASSIAN_MCP_URL=http://jira-emulator.ai-pipeline.svc.cluster.local:8081/sse

# GitHub Emulator
GITHUB_EMULATOR_URL=https://github-emulator.ai-pipeline.svc.cluster.local
```

## Access Information

After successful deployment:

### Via Ingress Proxy (Recommended)

All services accessible via single LoadBalancer IP:

```bash
# Get the LoadBalancer IP
INGRESS_IP=$(kubectl get svc -n ai-pipeline ingress-proxy -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# Access services
curl -H 'Host: dashboard.local' http://$INGRESS_IP/
curl -H 'Host: jira.local' http://$INGRESS_IP/
curl -H 'Host: github.local' http://$INGRESS_IP/
curl -H 'Host: mlflow.local' http://$INGRESS_IP/
```

### Internal (Pod-to-Pod)

From within the cluster:

- **Dashboard**: `http://pipeline-dashboard.ai-pipeline.svc.cluster.local:5000`
- **GitHub**: `https://github-emulator.ai-pipeline.svc.cluster.local:443`
- **Jira**: `https://jira-emulator.ai-pipeline.svc.cluster.local:443`
- **MLflow**: `http://mlflow.ai-pipeline.svc.cluster.local:5000`

### From Host Machine

Port forwards configured in Vagrantfile:
- **Dashboard**: `http://localhost:5000`

For other services, use `access-emulators.sh` script.

## Troubleshooting

### Check Deployment Status

```bash
kubectl get all -n ai-pipeline
kubectl get pvc -n ai-pipeline
kubectl get certificates -n ai-pipeline
```

### View Logs

```bash
# Dashboard
kubectl logs -f deployment/pipeline-dashboard -n ai-pipeline

# GitHub Emulator
kubectl logs -f deployment/github-emulator -n ai-pipeline

# Jira Emulator
kubectl logs -f deployment/jira-emulator -n ai-pipeline

# Ingress Proxy
kubectl logs -f deployment/ingress-proxy -n ai-pipeline

# MLflow
kubectl logs -f deployment/mlflow -n ai-pipeline
```

### Common Issues

**Pods pending/not starting:**
```bash
kubectl describe pod <pod-name> -n ai-pipeline
kubectl get events -n ai-pipeline --sort-by='.lastTimestamp'
```

**Certificates not ready:**
```bash
kubectl get certificate -n ai-pipeline
kubectl describe certificate <cert-name> -n ai-pipeline
```

**Images not found:**
```bash
sudo k3s ctr images ls | grep -E 'ai-first-pipeline|github-emulator|jira-emulator|ingress-proxy'
```

## Redeploy Specific Components

### Dashboard Only
```bash
./redeploy-dashboard.sh
```

### Ingress Proxy Only
```bash
./09-deploy-ingress-proxy.sh
```

### Rebuild All Images
```bash
sudo bash 05-build-images.sh
```

## Clean Up

To remove all deployed resources:

```bash
kubectl delete namespace ai-pipeline
kubectl delete clusterissuer internal-ca-issuer
kubectl delete secret internal-ca-secret -n cert-manager
```

To completely reset (including K3s):

```bash
/usr/local/bin/k3s-uninstall.sh
```

Then re-run `deploy-all.sh` to start fresh.
