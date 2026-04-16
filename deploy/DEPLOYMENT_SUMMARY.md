# AI-First Pipeline K3s Deployment Summary

Both GitHub Emulator and Jira Emulator are now deployed to k3s with cert-manager managed TLS certificates.

## Quick Status Check

```bash
# Check all pods
kubectl get pods -n ai-pipeline

# Check all services
kubectl get svc -n ai-pipeline

# Check certificates
kubectl get certificate -n ai-pipeline
```

## Deployed Services

### 1. GitHub Emulator

**Service**: `github-emulator.ai-pipeline.svc.cluster.local`

**Ports**:
- 443 (HTTPS) → Caddy → Uvicorn (port 8000)
- 80 (HTTP) → Caddy redirect to HTTPS

**Features**:
- GitHub REST API emulation
- Git Smart HTTP protocol
- SSH transport (port 2222)
- Persistent SQLite database

**Documentation**: [GITHUB_DEPLOYMENT.md](GITHUB_DEPLOYMENT.md)

**Test**:
```bash
kubectl run test-pod --rm -i --image=curlimages/curl --restart=Never -- \
  curl -k -s https://github-emulator.ai-pipeline.svc.cluster.local/api/v3
```

### 2. Jira Emulator

**Service**: `jira-emulator.ai-pipeline.svc.cluster.local`

**Ports**:
- 443 (HTTPS) → Caddy → Jira API (port 8080)
- 80 (HTTP) → Caddy redirect to HTTPS
- 8081 (MCP) → MCP Server for Claude integration

**Features**:
- Jira REST API v2 and v3
- JQL search engine
- Model Context Protocol (MCP) server
- Persistent SQLite database
- Database snapshots (backup/restore)
- Seed data (RHOAIENG, RHAIRFE, RHAISTRAT, TEST projects)

**Default Credentials**:
- Username: `admin`
- Password: `admin`
- API Token: `jira-emulator-default-token`

**Documentation**: [JIRA_DEPLOYMENT.md](JIRA_DEPLOYMENT.md)

**Test**:
```bash
kubectl run test-pod --rm -i --image=curlimages/curl --restart=Never -- \
  curl -k -s https://jira-emulator.ai-pipeline.svc.cluster.local/rest/api/2/priority
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     K3s Cluster (ai-pipeline namespace)         │
│                                                                 │
│  ┌──────────────────────────┐    ┌──────────────────────────┐ │
│  │   github-emulator Pod    │    │   jira-emulator Pod      │ │
│  │  ┌────────┐  ┌─────────┐│    │  ┌────────┐  ┌─────────┐ │ │
│  │  │ Caddy  │→ │Uvicorn  ││    │  │ Caddy  │→ │Jira API │ │ │
│  │  │:443/80 │  │:8000    ││    │  │:443/80 │  │:8080    │ │ │
│  │  └────────┘  └─────────┘│    │  └────────┘  └─────────┘ │ │
│  │       ↓                  │    │       ↓         ↓        │ │
│  │  /etc/tls/tls.crt       │    │  /etc/tls/  MCP:8081    │ │
│  │  /etc/tls/tls.key       │    │      tls.crt/key        │ │
│  │       ↓                  │    │       ↓                  │ │
│  │  PVC: github-emu-data   │    │  PVC: jira-emu-data     │ │
│  │  /data/github_emu.db    │    │  /data/jira.db          │ │
│  └──────────────────────────┘    └──────────────────────────┘ │
│           │                                  │                 │
│           ▼                                  ▼                 │
│  ┌──────────────────────┐    ┌──────────────────────────┐    │
│  │ Service              │    │ Service                  │    │
│  │ LoadBalancer         │    │ LoadBalancer             │    │
│  │ :443, :80            │    │ :443, :80, :8081         │    │
│  └──────────────────────┘    └──────────────────────────┘    │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ cert-manager (manages all TLS certificates)              │ │
│  │   - github-emulator-tls                                  │ │
│  │   - jira-emulator-tls                                    │ │
│  │   - internal-ca (root CA)                                │ │
│  └──────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Build Scripts

| Script | Purpose |
|--------|---------|
| `05-build-images.sh` | Build all images (github + jira + pipeline) |
| `05a-build-github-emulator.sh` | Build only github-emulator:k3s |
| `05b-build-jira-emulator.sh` | Build only jira-emulator:k3s |

## Deploy Scripts

| Script | Purpose |
|--------|---------|
| `07-deploy-github-emulator.sh` | Deploy github-emulator to k3s |
| `08-deploy-jira-emulator.sh` | Deploy jira-emulator to k3s |

## Complete Deployment Process

```bash
# From host machine
vagrant up
vagrant ssh

# Inside VM
cd /vagrant/deploy/scripts

# Build images (choose one approach)
# Option 1: Build everything
sudo bash 05-build-images.sh

# Option 2: Build individually (faster for iteration)
sudo bash 05a-build-github-emulator.sh
sudo bash 05b-build-jira-emulator.sh

# Deploy services
sudo bash 07-deploy-github-emulator.sh
sudo bash 08-deploy-jira-emulator.sh

# Verify deployment
kubectl get all -n ai-pipeline
```

## Kubernetes Resources Created

### Namespace
- `ai-pipeline` - Contains all emulator resources

### Certificates (cert-manager)
- `github-emulator-tls` - TLS certificate for GitHub emulator
- `jira-emulator-tls` - TLS certificate for Jira emulator
- `internal-ca` - Self-signed root CA
- `internal-ca-issuer` - Issuer for signing service certificates

### ConfigMaps
- `github-emulator-config` - Caddyfile for GitHub emulator
- `jira-emulator-config` - Caddyfile for Jira emulator
- `internal-ca-cert` - Root CA certificate (optional, for trust)

### PersistentVolumeClaims
- `github-emulator-data` (5Gi) - GitHub emulator database
- `jira-emulator-data` (5Gi) - Jira emulator database + attachments
- `pipeline-data` (20Gi) - Pipeline workspace (not yet used)

### Services (LoadBalancer)
- `github-emulator` - Ports 443, 80
- `jira-emulator` - Ports 443, 80, 8081

### Deployments
- `github-emulator` - 1 replica
- `jira-emulator` - 1 replica

## Access from Host Machine

Both services can be accessed via port-forwarding:

```bash
# GitHub Emulator
kubectl port-forward -n ai-pipeline svc/github-emulator 8443:443
curl -k https://localhost:8443/api/v3

# Jira Emulator (HTTPS)
kubectl port-forward -n ai-pipeline svc/jira-emulator 9443:443
curl -k https://localhost:9443/rest/api/2/priority

# Jira Emulator (MCP Server)
kubectl port-forward -n ai-pipeline svc/jira-emulator 8081:8081
curl http://localhost:8081/sse
```

## Common Operations

### View All Pods
```bash
kubectl get pods -n ai-pipeline
```

### View Logs
```bash
# GitHub emulator
kubectl logs -n ai-pipeline deployment/github-emulator -f

# Jira emulator
kubectl logs -n ai-pipeline deployment/jira-emulator -f
```

### Restart Services
```bash
# Restart github-emulator
kubectl rollout restart deployment/github-emulator -n ai-pipeline

# Restart jira-emulator
kubectl rollout restart deployment/jira-emulator -n ai-pipeline
```

### Rebuild and Redeploy
```bash
# Inside Vagrant VM
cd /vagrant/deploy/scripts

# Rebuild specific emulator
sudo bash 05a-build-github-emulator.sh  # or 05b for jira

# Restart deployment to pick up new image
kubectl rollout restart deployment/github-emulator -n ai-pipeline
# or
kubectl rollout restart deployment/jira-emulator -n ai-pipeline

# Watch rollout
kubectl get pods -n ai-pipeline -w
```

### Database Access
```bash
# GitHub emulator database
kubectl exec -it -n ai-pipeline deployment/github-emulator -- \
  sqlite3 /data/github_emulator.db ".tables"

# Jira emulator database
kubectl exec -it -n ai-pipeline deployment/jira-emulator -- \
  python -c "import sqlite3; conn = sqlite3.connect('/data/jira.db'); print([t[0] for t in conn.execute('SELECT name FROM sqlite_master WHERE type=\"table\"').fetchall()])"
```

## Key Learnings & Fixes Applied

### 1. DATABASE_URL Path Issue
Both emulators needed **4 slashes** for absolute SQLite paths:
- ✅ `sqlite+aiosqlite:////data/database.db` (absolute)
- ❌ `sqlite+aiosqlite:///data/database.db` (relative to /app)

### 2. Kubernetes Environment Variable Collisions
Services named `<name>` automatically create `<NAME>_PORT` env vars that can conflict with app configs. Fixed by explicitly setting app-specific env vars to override.

### 3. Container Port Alignment
Container ports must match what the application actually listens on (Caddy: 443/80, not 3000).

### 4. Supervisord for Multiple Processes
Both emulators use supervisord to run multiple processes:
- GitHub: Caddy + Uvicorn
- Jira: Caddy + Jira API + MCP Server

### 5. ConfigMap for Runtime Configuration
Caddyfile mounted via ConfigMap allows TLS configuration changes without rebuilding images.

## Troubleshooting References

- **GitHub Emulator**: See [GITHUB_DEPLOYMENT.md](GITHUB_DEPLOYMENT.md) and [FIXES_AND_GOTCHAS.md](FIXES_AND_GOTCHAS.md)
- **Jira Emulator**: See [JIRA_DEPLOYMENT.md](JIRA_DEPLOYMENT.md)

## Next Steps

- [ ] Set up Ingress for external access (instead of LoadBalancer)
- [ ] Configure monitoring (Prometheus/Grafana)
- [ ] Set up automated database backups
- [ ] Deploy pipeline dashboard (main application)
- [ ] Configure CI/CD for automated deployments
- [ ] Set up log aggregation (Loki/Elasticsearch)

## Support

For issues or questions:
1. Check deployment logs: `kubectl logs -n ai-pipeline deployment/<name>`
2. Review troubleshooting sections in individual deployment guides
3. Verify certificate status: `kubectl get certificate -n ai-pipeline`
4. Check events: `kubectl get events -n ai-pipeline --sort-by='.lastTimestamp'`
