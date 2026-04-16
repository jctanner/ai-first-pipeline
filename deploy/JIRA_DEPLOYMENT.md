# Jira Emulator K3s Deployment Guide

This guide covers deploying the Jira Emulator to k3s with cert-manager managed certificates.

## Quick Start

```bash
# From your host machine
vagrant ssh

# Inside the VM
cd /vagrant/deploy/scripts

# Build the jira-emulator image
sudo bash 05b-build-jira-emulator.sh

# Deploy to k3s
sudo bash 08-deploy-jira-emulator.sh

# Check status
kubectl get pods -n ai-pipeline -l app=jira-emulator
kubectl logs -n ai-pipeline deployment/jira-emulator --tail=20
```

## What's Different for K3s

The Jira Emulator was originally designed for container deployment with direct HTTP access. For k3s deployment, we've made these changes:

### 1. **Dockerfile.k3s**
- Separate Dockerfile optimized for Kubernetes
- Adds Caddy as a reverse proxy for TLS termination
- Uses `supervisord.k3s.conf` that includes Caddy
- Pre-configured environment variables for k8s
- Tagged as `jira-emulator:k3s`

### 2. **Supervisord with Three Services**
The k3s deployment runs three processes under supervisord:
- **Caddy** (ports 443/80) - TLS termination and reverse proxy
- **Jira API** (port 8080) - FastAPI application serving REST API v2 and v3
- **MCP Server** (port 8081) - Model Context Protocol server for Claude integration

### 3. **Caddyfile via ConfigMap**
- Caddyfile is mounted from a ConfigMap (`11-jira-emulator-config.yaml`)
- Configured to use cert-manager certificates from `/etc/tls/`
- Proxies HTTPS requests to Jira API on localhost:8080
- Can be updated without rebuilding the image:
  ```bash
  kubectl edit configmap jira-emulator-config -n ai-pipeline
  kubectl rollout restart deployment/jira-emulator -n ai-pipeline
  ```

### 4. **Certificate Management**
- Uses cert-manager with an internal CA issuer
- Certificate automatically mounted as a Kubernetes Secret
- Certificate paths: `/etc/tls/tls.crt` and `/etc/tls/tls.key`
- Certificate DNS names include:
  - `jira-emulator.ai-pipeline.svc.cluster.local`
  - `jira.local`
  - `192.168.56.10` (IP SAN)

### 5. **Database Configuration**
- SQLite database with absolute path: `sqlite+aiosqlite:////data/jira.db` (4 slashes)
- Persistent storage via PVC (`jira-emulator-data`)
- Includes snapshots directory at `/data/snapshots` for backup/restore functionality

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  Pod: jira-emulator                          │
│                                                              │
│  ┌──────────────┐         ┌──────────────────┐             │
│  │   Caddy      │  ───>   │    Jira API      │             │
│  │   :443/:80   │         │   (FastAPI)      │             │
│  │              │         │   :8080          │             │
│  └──────────────┘         └──────────────────┘             │
│         │                                                    │
│         │ Reads TLS certs from                              │
│         ▼                                                    │
│  ┌──────────────────────────────────────┐                  │
│  │  /etc/tls/                           │                  │
│  │    tls.crt  (from cert-manager)      │                  │
│  │    tls.key  (from cert-manager)      │                  │
│  └──────────────────────────────────────┘                  │
│                                                              │
│  ┌──────────────────┐     ┌──────────────────┐             │
│  │  MCP Server      │────>│  Jira API        │             │
│  │  :8081           │     │  (localhost)     │             │
│  └──────────────────┘     └──────────────────┘             │
│                                                              │
│  ┌──────────────────────────────────────┐                  │
│  │  /data/                              │                  │
│  │    jira.db (SQLite)                  │                  │
│  │    snapshots/ (backups)              │                  │
│  │    attachments/ (file uploads)       │                  │
│  │    (from PersistentVolume)           │                  │
│  └──────────────────────────────────────┘                  │
└──────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Service            │
│  LoadBalancer       │
│  :443 → :443        │
│  :80  → :80         │
│  :8081 → :8081      │
└─────────────────────┘
```

## Files Involved

```
deploy/
├── repos/jira-emulator/
│   ├── Dockerfile              # Original (for standalone)
│   ├── Dockerfile.k3s          # K3s-optimized (with Caddy)
│   ├── supervisord.conf        # Original (jira-api + mcp-server)
│   └── supervisord.k3s.conf    # K3s version (caddy + jira-api + mcp-server)
│
├── k8s/
│   ├── 00-namespace.yaml       # ai-pipeline namespace
│   ├── 01-ca-issuer.yaml       # cert-manager CA issuer
│   ├── 02-certificates.yaml    # Certificate definitions
│   ├── 03-storage.yaml         # PVC for SQLite database
│   ├── 11-jira-emulator-config.yaml  # Caddyfile ConfigMap
│   └── 12-jira-emulator.yaml   # Deployment + Service
│
└── scripts/
    ├── 05-build-images.sh           # Builds all images (optional)
    ├── 05b-build-jira-emulator.sh   # Builds just jira-emulator:k3s (recommended)
    └── 08-deploy-jira-emulator.sh   # Deploys to k3s
```

## Manual Deployment Steps

If you want to understand what the deployment script does:

```bash
# 1. Build the image
cd /vagrant/deploy/repos/jira-emulator
docker build -f Dockerfile.k3s -t jira-emulator:k3s .
docker save jira-emulator:k3s | sudo k3s ctr images import -

# 2. Create namespace
kubectl apply -f /vagrant/deploy/k8s/00-namespace.yaml

# 3. Set up certificate infrastructure
kubectl apply -f /vagrant/deploy/k8s/01-ca-issuer.yaml
kubectl apply -f /vagrant/deploy/k8s/02-certificates.yaml

# 4. Wait for certificate to be ready
kubectl wait --for=condition=ready certificate/jira-emulator-tls -n ai-pipeline --timeout=120s

# 5. Create storage
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml

# 6. Create ConfigMap with Caddyfile
kubectl apply -f /vagrant/deploy/k8s/11-jira-emulator-config.yaml

# 7. Deploy the application
kubectl apply -f /vagrant/deploy/k8s/12-jira-emulator.yaml

# 8. Check status
kubectl get pods -n ai-pipeline -l app=jira-emulator
kubectl get svc -n ai-pipeline jira-emulator
```

## Accessing the Service

### From within the cluster

```bash
# Any pod can access the REST API via DNS
kubectl run test-pod --rm -i --image=curlimages/curl --restart=Never -- \
  curl -k -s https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/2/priority

# Test with authentication
kubectl run test-pod --rm -i --image=curlimages/curl --restart=Never -- \
  curl -k -s -u admin:admin \
  https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/2/myself
```

### From your host machine

Port forward to access from host:

```bash
# REST API (HTTPS)
kubectl port-forward -n ai-pipeline svc/jira-emulator 8443:443

# Then access from host:
curl -k https://localhost:8443/rest/api/2/priority

# MCP Server (for Claude integration)
kubectl port-forward -n ai-pipeline svc/jira-emulator 8081:8081

# MCP endpoint:
curl http://localhost:8081/sse
```

### Web UI

The Jira Emulator includes a web UI:

```bash
# Port forward
kubectl port-forward -n ai-pipeline svc/jira-emulator 8443:443

# Open in browser
open https://localhost:8443
```

## Default Credentials

The jira-emulator comes with default seed data and credentials:

- **Username**: `admin`
- **Password**: `admin`
- **API Token**: `jira-emulator-default-token`

Projects created by seed data:
- **RHOAIENG** - Engineering project
- **RHAIRFE** - RFE project
- **RHAISTRAT** - Strategy project
- **TEST** - Test project

## Testing

### Test REST API v2

```bash
# Get priorities
curl -k -s https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/2/priority

# Get current user (requires auth)
curl -k -s -u admin:admin \
  https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/2/myself

# Search issues with JQL
curl -k -s -u admin:admin \
  'https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/2/search?jql=project=RHOAIENG'
```

### Test REST API v3

```bash
# Get priorities (v3)
curl -k -s https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/3/priority

# Search with pagination token
curl -k -s -u admin:admin \
  'https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/3/search?jql=project=RHOAIENG&maxResults=10'
```

### Test MCP Server

```bash
# Port forward MCP server
kubectl port-forward -n ai-pipeline svc/jira-emulator 8081:8081

# Test SSE endpoint
curl http://localhost:8081/sse
```

## Troubleshooting

### Pod won't start

Check events:
```bash
kubectl describe pod -n ai-pipeline -l app=jira-emulator
```

Common issues:
- **Image not found**: Run `sudo bash 05b-build-jira-emulator.sh` again
- **PVC pending**: Check storage class `kubectl get pvc -n ai-pipeline`
- **Certificate not ready**: Check `kubectl get certificate -n ai-pipeline`

### Check logs for each service

```bash
# All logs
kubectl logs -n ai-pipeline deployment/jira-emulator

# Filter for specific service
kubectl logs -n ai-pipeline deployment/jira-emulator | grep caddy
kubectl logs -n ai-pipeline deployment/jira-emulator | grep jira-api
kubectl logs -n ai-pipeline deployment/jira-emulator | grep mcp-server
```

### Test API directly (bypass Caddy)

```bash
# Port forward to jira-api directly
kubectl port-forward -n ai-pipeline deployment/jira-emulator 8080:8080

# In another terminal
curl http://localhost:8080/rest/api/2/priority
```

### Database issues

The SQLite database is stored in a PersistentVolume. To inspect:

```bash
# Exec into the pod
kubectl exec -it -n ai-pipeline deployment/jira-emulator -- /bin/bash

# Inside the pod
ls -la /data/
# You should see: jira.db, snapshots/, attachments/

# Check database with sqlite3 (if installed)
python -c "import sqlite3; conn = sqlite3.connect('/data/jira.db'); print(conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall())"
```

### Backup and Restore

The jira-emulator supports database snapshots via the admin API:

```bash
# Create a snapshot
curl -k -X POST -u admin:admin \
  https://jira-emulator.ai-pipeline.svc.cluster.local/api/admin/snapshots

# List snapshots
curl -k -u admin:admin \
  https://jira-emulator.ai-pipeline.svc.cluster.local/api/admin/snapshots

# Restore from a snapshot
curl -k -X POST -u admin:admin \
  https://jira-emulator.ai-pipeline.svc.cluster.local/api/admin/snapshots/SNAPSHOT_ID/restore
```

## Updating the Deployment

### Update application code

```bash
# Make your changes to the source
# Then rebuild and restart
cd /vagrant/deploy/scripts
sudo bash 05b-build-jira-emulator.sh
kubectl rollout restart deployment/jira-emulator -n ai-pipeline
kubectl get pods -n ai-pipeline -w
```

### Update Caddyfile

```bash
# Edit the ConfigMap
kubectl edit configmap jira-emulator-config -n ai-pipeline

# Restart to pick up changes
kubectl rollout restart deployment/jira-emulator -n ai-pipeline
```

## Environment Variables

The deployment sets these environment variables:

| Variable | Value | Purpose |
|----------|-------|---------|
| `DATABASE_URL` | `sqlite+aiosqlite:////data/jira.db` | Database connection (4 slashes = absolute path) |
| `PORT` | `8080` | Jira API port |
| `MCP_PORT` | `8081` | MCP server port |
| `JIRA_USER` | `admin` | Default username |
| `JIRA_TOKEN` | `jira-emulator-default-token` | Default API token |
| `SEED_DATA` | `true` | Auto-load sample projects/workflows |
| `IMPORT_ON_STARTUP` | `false` | Auto-import JSON on startup |
| `ATTACHMENT_DIR` | `/data/attachments` | File upload storage |
| `JIRA_EMULATOR_HOSTNAME` | `jira-emulator.ai-pipeline.svc.cluster.local` | Hostname for Caddy |
| `TLS_CERT_FILE` | `/etc/tls/tls.crt` | Certificate path |
| `TLS_KEY_FILE` | `/etc/tls/tls.key` | Private key path |

## Cleanup

```bash
# Remove just the jira-emulator
kubectl delete -f /vagrant/deploy/k8s/12-jira-emulator.yaml
kubectl delete -f /vagrant/deploy/k8s/11-jira-emulator-config.yaml

# Remove storage (WARNING: deletes database)
kubectl delete pvc jira-emulator-data -n ai-pipeline

# Remove entire namespace (WARNING: deletes everything)
kubectl delete namespace ai-pipeline
```

## Integration with Claude

The MCP server exposes Jira functionality to Claude AI:

```bash
# Port forward the MCP server
kubectl port-forward -n ai-pipeline svc/jira-emulator 8081:8081

# Configure in Claude Code settings.json:
{
  "mcpServers": {
    "atlassian-jira": {
      "command": "curl",
      "args": ["-N", "http://localhost:8081/sse"]
    }
  }
}
```

Available MCP tools:
- `jira_search` - Search issues with JQL
- `jira_get_issue` - Get issue details
- `jira_create_issue` - Create new issue
- `jira_update_issue` - Update existing issue
- `jira_add_comment` - Add comment to issue
- `jira_get_projects` - List all projects
- `jira_get_transitions` - Get available transitions for an issue

## Next Steps

- Configure ingress for external access (instead of port-forward)
- Set up monitoring/metrics collection
- Configure backup schedule for database snapshots
- Customize seed data for your use case
- Integrate with CI/CD pipelines
