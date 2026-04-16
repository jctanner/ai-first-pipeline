# Deployment Files Reference

Complete list of all deployment files and their purposes.

## Project Root Files

```
Vagrantfile              # VM definition (Ubuntu 22.04, 8GB RAM, 4 CPUs)
DEPLOYMENT.md            # Quick start deployment guide
.env                     # Credentials (YOU MUST CREATE THIS)
```

## Deploy Directory Structure

```
deploy/
├── README.md                              # Comprehensive deployment documentation
├── FILELIST.md                            # This file
│
├── scripts/                               # Setup and automation scripts
│   ├── 01-install-k3s.sh                 # Install K3s cluster
│   ├── 02-install-cert-manager.sh        # Install cert-manager
│   ├── 03-setup-certificates.sh          # Create CA and service certificates
│   ├── 04-extract-ca-cert.sh             # Extract CA cert for trust distribution
│   ├── 05-build-images.sh                # Build and import container images
│   ├── 06-create-secrets.sh              # Create Kubernetes secrets from .env
│   ├── 99-verify-cluster.sh              # Verify cluster health
│   └── deploy-all.sh                     # Automated end-to-end deployment
│
├── k8s/                                   # Kubernetes manifests
│   ├── 00-namespace.yaml                 # ai-pipeline namespace
│   ├── 01-ca-issuer.yaml                 # Self-signed CA and ClusterIssuer
│   ├── 02-certificates.yaml              # Service certificates (emulator + dashboard)
│   ├── 03-storage.yaml                   # PersistentVolumeClaims (20Gi + 5Gi)
│   ├── 10-github-emulator.yaml           # GitHub emulator deployment + service
│   ├── 20-pipeline-dashboard.yaml        # Pipeline dashboard deployment + service
│   └── 30-pipeline-job-template.yaml     # Template for running pipeline Jobs
│
├── validation/                            # Validation scripts
│   ├── test-cluster.sh                   # Validate K3s and core components
│   ├── test-certificates.sh              # Validate cert-manager and certificates
│   └── test-application.sh               # Validate application deployments
│
└── docs/                                  # Additional documentation
    └── TROUBLESHOOTING.md                # Comprehensive troubleshooting guide
```

## File Purposes

### Root Files

**Vagrantfile**
- Defines Ubuntu 22.04 VM with 8GB RAM, 4 CPUs (configurable to 8 CPUs)
- Configures private network at 192.168.56.10
- Port forwarding: 5000 (dashboard), 3000 (emulator)
- Syncs project directory to /vagrant
- Provisions system packages and uv

**DEPLOYMENT.md**
- Quick start guide for deployment
- Common operations reference
- Links to detailed documentation

**.env** (you create this)
- Vertex AI credentials (ANTHROPIC_VERTEX_PROJECT_ID, etc.)
- Jira credentials (JIRA_SERVER, JIRA_USER, JIRA_TOKEN)
- Optional: GCP service account path

### Setup Scripts

**01-install-k3s.sh**
- Installs K3s with Traefik disabled
- Configures kubectl access for vagrant user
- Sets up kubeconfig

**02-install-cert-manager.sh**
- Installs cert-manager v1.14.4
- Waits for all cert-manager components to be ready

**03-setup-certificates.sh**
- Creates ai-pipeline namespace
- Applies CA issuer
- Creates service certificates
- Waits for certificates to be issued

**04-extract-ca-cert.sh**
- Extracts CA certificate from issued certificate
- Creates ConfigMap for trust distribution
- Used by pods to trust internal services

**05-build-images.sh**
- Creates default Dockerfile if missing
- Builds ai-first-pipeline:latest image
- Imports image into k3s
- Optionally builds github-emulator if repo exists

**06-create-secrets.sh**
- Sources .env file
- Creates pipeline-secrets with credentials
- Creates github-token placeholder
- Optionally creates gcp-credentials from JSON file

**99-verify-cluster.sh**
- Shows cluster health overview
- Lists all pods, certificates, and resources
- Quick status check

**deploy-all.sh**
- Runs all setup scripts in order
- Deploys all Kubernetes resources
- Runs validation tests
- Displays access information
- Complete automation from fresh VM to running cluster

### Kubernetes Manifests

**00-namespace.yaml**
- Creates ai-pipeline namespace
- All resources deploy here

**01-ca-issuer.yaml**
- Self-signed ClusterIssuer (bootstrap)
- Internal CA Certificate (10 year validity)
- CA-based ClusterIssuer (for signing service certs)

**02-certificates.yaml**
- github-emulator-tls certificate
  - DNS: github-emulator.ai-pipeline.svc.cluster.local
  - IP SAN: 192.168.56.10
- pipeline-dashboard-tls certificate
  - DNS: pipeline-dashboard.ai-pipeline.svc.cluster.local
  - IP SAN: 192.168.56.10

**03-storage.yaml**
- pipeline-data PVC (20Gi)
  - Mounts: issues, workspace, logs, artifacts
- github-emulator-data PVC (5Gi)
  - Mount: /data

**10-github-emulator.yaml**
- LoadBalancer Service (ports 80, 443)
- Deployment with TLS certificate mounting
- Init container for CA trust setup
- Resource limits: 512Mi RAM, 500m CPU

**20-pipeline-dashboard.yaml**
- LoadBalancer Service (port 5000)
- Deployment with environment variables from secrets
- Init container for CA trust setup
- Persistent volume mounts for pipeline data
- Resource limits: 2Gi RAM, 1 CPU

**30-pipeline-job-template.yaml**
- Template for running pipeline phases as Jobs
- Customizable command section
- Same secrets and volume mounts as dashboard
- TTL: 24 hours after completion

### Validation Scripts

**test-cluster.sh**
- Checks node status
- Verifies CoreDNS
- Verifies local-path-provisioner
- Checks cert-manager pods

**test-certificates.sh**
- Validates ClusterIssuers are ready
- Checks all certificates are issued
- Verifies certificate Secrets exist
- Validates certificate SANs
- Checks CA ConfigMap

**test-application.sh**
- Checks deployment availability
- Validates services exist
- Verifies PVCs are bound
- Tests DNS resolution
- Checks secrets exist

### Documentation

**deploy/README.md**
- Complete deployment documentation
- Architecture overview
- Step-by-step instructions
- Common operations
- Troubleshooting quick reference

**deploy/docs/TROUBLESHOOTING.md**
- Detailed troubleshooting for all components
- Diagnostic commands
- Common issues and solutions
- Debug workflows
- Reset procedures

## Quick Reference

### Deployment Order

1. `vagrant up && vagrant ssh`
2. `cd /vagrant/deploy/scripts`
3. `sudo bash deploy-all.sh` (automated)
   OR run 01-06 scripts individually

### Validation Order

1. `cd /vagrant/deploy/validation`
2. `bash test-cluster.sh`
3. `bash test-certificates.sh`
4. `bash test-application.sh`

### File Modifications

**To customize VM resources**: Edit `Vagrantfile`
**To change namespaces**: Edit all `k8s/*.yaml` files
**To add environment vars**: Edit `.env`, then re-run `06-create-secrets.sh`
**To modify deployments**: Edit `k8s/10-*.yaml` and `k8s/20-*.yaml`
**To change certificate SANs**: Edit `k8s/02-certificates.yaml`

## Generated Files (not in git)

During deployment, these are created:
- `internal-ca-secret` (Kubernetes Secret with CA key/cert)
- `github-emulator-tls` (Kubernetes Secret with service cert)
- `pipeline-dashboard-tls` (Kubernetes Secret with service cert)
- `internal-ca-cert` (ConfigMap with CA cert for trust)
- `pipeline-secrets` (Kubernetes Secret from .env)
- `github-token` (Kubernetes Secret with placeholder)
- `gcp-credentials` (Kubernetes Secret from JSON file, optional)

## All Scripts at a Glance

| Script | Purpose | Runtime |
|--------|---------|---------|
| 01-install-k3s.sh | K3s installation | ~2 min |
| 02-install-cert-manager.sh | cert-manager installation | ~2 min |
| 03-setup-certificates.sh | Certificate creation | ~30 sec |
| 04-extract-ca-cert.sh | CA trust setup | ~5 sec |
| 05-build-images.sh | Container image build | ~5 min |
| 06-create-secrets.sh | Kubernetes secrets | ~5 sec |
| 99-verify-cluster.sh | Health check | ~5 sec |
| deploy-all.sh | Full automation | ~10 min |
| test-cluster.sh | Cluster validation | ~10 sec |
| test-certificates.sh | Certificate validation | ~10 sec |
| test-application.sh | App validation | ~30 sec |

## Size Summary

- Total manifest size: ~15KB
- Total script size: ~30KB
- Total documentation: ~100KB
- Container images: ~2GB (depends on dependencies)
- Persistent storage: 25Gi allocated
