# AI-First Pipeline K3s Deployment

Complete Kubernetes deployment for the ai-first-pipeline project on K3s with proper TLS certificate infrastructure.

## Quick Start

```bash
# 1. Start the VM
vagrant up

# 2. SSH into the VM
vagrant ssh

# 3. Run setup scripts in order
cd /vagrant/deploy/scripts
sudo bash 01-install-k3s.sh
sudo bash 02-install-cert-manager.sh
sudo bash 03-setup-certificates.sh
sudo bash 04-extract-ca-cert.sh

# 4. Create secrets from your .env file
sudo bash 06-create-secrets.sh

# 5. Build and load container images
sudo bash 05-build-images.sh

# 6. Deploy storage
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml

# 7. Deploy applications
kubectl apply -f /vagrant/deploy/k8s/10-github-emulator.yaml
kubectl apply -f /vagrant/deploy/k8s/20-pipeline-dashboard.yaml

# 8. Validate everything works
cd /vagrant/deploy/validation
bash test-cluster.sh
bash test-certificates.sh
bash test-application.sh
```

## Architecture Overview

### Components

1. **K3s Cluster**: Single-node Kubernetes cluster running in a VM
2. **cert-manager**: Automated certificate management
3. **GitHub Emulator**: Local GitHub API emulator for testing
4. **Pipeline Dashboard**: Web UI for monitoring pipeline activity
5. **Pipeline Jobs**: Kubernetes Jobs for running pipeline phases

### Infrastructure

- **VM**: Ubuntu 22.04, 8GB RAM, 4 CPUs
- **Network**: Private network at `192.168.56.10` with port forwarding
- **Storage**: Local-path provisioner with persistent volumes
- **Certificates**: Internal CA managed by cert-manager
- **Secrets**: Kubernetes Secrets for credentials and configuration

### Networking

```
Host Machine
    ↓
192.168.56.10:5000 → Pipeline Dashboard (LoadBalancer)
192.168.56.10:3000 → GitHub Emulator (LoadBalancer)
    ↓
K3s Cluster
    ↓
pipeline-dashboard.ai-pipeline.svc.cluster.local:5000
github-emulator.ai-pipeline.svc.cluster.local:443
```

## Prerequisites

- Vagrant (with VirtualBox, VMware, or libvirt)
- ~10GB free RAM
- ~30GB free disk space
- Internet connection for package downloads
- `.env` file with required credentials (see Configuration section)

## Project Structure

```
deploy/
├── scripts/                          # Setup and management scripts
│   ├── 01-install-k3s.sh            # Install K3s
│   ├── 02-install-cert-manager.sh   # Install cert-manager
│   ├── 03-setup-certificates.sh     # Create certificates
│   ├── 04-extract-ca-cert.sh        # Extract CA for trust distribution
│   ├── 05-build-images.sh           # Build container images
│   ├── 06-create-secrets.sh         # Create Kubernetes secrets
│   └── 99-verify-cluster.sh         # Verify cluster health
├── k8s/                              # Kubernetes manifests
│   ├── 00-namespace.yaml            # Namespace definition
│   ├── 01-ca-issuer.yaml            # Certificate authority setup
│   ├── 02-certificates.yaml         # Service certificates
│   ├── 03-storage.yaml              # Persistent volume claims
│   ├── 10-github-emulator.yaml      # GitHub emulator deployment
│   ├── 20-pipeline-dashboard.yaml   # Dashboard deployment
│   └── 30-pipeline-job-template.yaml # Template for pipeline jobs
├── validation/                       # Validation scripts
│   ├── test-cluster.sh              # Validate cluster health
│   ├── test-certificates.sh         # Validate certificates
│   └── test-application.sh          # Validate application deployment
├── docs/                             # Documentation
│   └── TROUBLESHOOTING.md           # Troubleshooting guide
└── README.md                         # This file
```

## Configuration

### .env File

Create a `.env` file in the project root with the following variables:

```bash
# Vertex AI Configuration
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project-id

# Jira Configuration
JIRA_SERVER=https://issues.redhat.com
JIRA_USER=your-email@redhat.com
JIRA_TOKEN=your-jira-api-token

# Optional: Atlassian MCP Server
ATLASSIAN_MCP_URL=http://127.0.0.1:8081/sse

# Optional: GCP Service Account Credentials
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

### GCP Credentials

If you need Vertex AI access, ensure you have a GCP service account JSON file:

1. Create a service account with Vertex AI permissions
2. Download the JSON key file
3. Set `GOOGLE_APPLICATION_CREDENTIALS` in `.env` to the path
4. The deployment script will automatically create a Kubernetes secret from it

## Deployment Steps

### 1. VM Setup

```bash
# Start the VM (from project root)
vagrant up

# SSH into the VM
vagrant ssh
```

### 2. K3s Installation

```bash
# Install K3s
cd /vagrant/deploy/scripts
sudo bash 01-install-k3s.sh

# Verify installation
kubectl get nodes
```

### 3. Certificate Infrastructure

```bash
# Install cert-manager
sudo bash 02-install-cert-manager.sh

# Set up certificates
sudo bash 03-setup-certificates.sh

# Extract CA cert for trust distribution
sudo bash 04-extract-ca-cert.sh

# Verify certificates
kubectl get certificate -n ai-pipeline
```

### 4. Secrets and Configuration

```bash
# Create secrets from .env file
# Make sure /vagrant/.env exists first!
sudo bash 06-create-secrets.sh

# Verify secrets
kubectl get secrets -n ai-pipeline
```

### 5. Build Container Images

```bash
# Build and import images
sudo bash 05-build-images.sh

# Verify images are loaded
sudo k3s ctr images ls | grep -E 'ai-first-pipeline|github-emulator'
```

### 6. Deploy Applications

```bash
# Deploy storage
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml

# Deploy GitHub emulator
kubectl apply -f /vagrant/deploy/k8s/10-github-emulator.yaml

# Deploy pipeline dashboard
kubectl apply -f /vagrant/deploy/k8s/20-pipeline-dashboard.yaml

# Watch pods come up
kubectl get pods -n ai-pipeline -w
```

### 7. Validation

```bash
# Run validation scripts
cd /vagrant/deploy/validation
bash test-cluster.sh
bash test-certificates.sh
bash test-application.sh
```

## Accessing Services

### From Host Machine

Once deployed, services are accessible from your host machine:

**Pipeline Dashboard:**
```bash
# Via port forwarding (if configured)
open http://localhost:5000

# Or via LoadBalancer IP
kubectl get svc -n ai-pipeline pipeline-dashboard
# Note the EXTERNAL-IP and access via http://<EXTERNAL-IP>:5000
```

**GitHub Emulator:**
```bash
# Via port forwarding (if configured)
open http://localhost:3000

# Or via LoadBalancer IP
kubectl get svc -n ai-pipeline github-emulator
```

### From Within Cluster

Services are accessible via their DNS names:

```bash
# Dashboard
curl http://pipeline-dashboard.ai-pipeline.svc.cluster.local:5000

# GitHub Emulator (HTTPS)
curl https://github-emulator.ai-pipeline.svc.cluster.local
```

### Add to /etc/hosts (Optional)

For easier access from your host machine:

```bash
# Get the VM IP (192.168.56.10)
echo "192.168.56.10 dashboard.local github.local" | sudo tee -a /etc/hosts
```

Then access via:
- http://dashboard.local:5000
- https://github.local:3000

## Running Pipeline Phases

Pipeline phases can be run as Kubernetes Jobs or directly in a pod.

### Option 1: Kubernetes Job (Recommended)

```bash
# Copy and customize the job template
cp /vagrant/deploy/k8s/30-pipeline-job-template.yaml /tmp/my-job.yaml

# Edit the command to run your desired phase
vim /tmp/my-job.yaml

# Run the job
kubectl create -f /tmp/my-job.yaml

# Watch the job
kubectl get jobs -n ai-pipeline -w

# View logs
kubectl logs -n ai-pipeline job/pipeline-bug-fetch

# Clean up when done
kubectl delete job pipeline-bug-fetch -n ai-pipeline
```

### Option 2: Interactive Pod

```bash
# Exec into the dashboard pod
kubectl exec -it -n ai-pipeline deployment/pipeline-dashboard -- /bin/bash

# Run pipeline commands
uv run python main.py bug-fetch --limit 10
uv run python main.py bug-completeness --limit 5
```

## Common Operations

### View Logs

```bash
# Dashboard logs
kubectl logs -n ai-pipeline deployment/pipeline-dashboard -f

# GitHub emulator logs
kubectl logs -n ai-pipeline deployment/github-emulator -f

# Job logs
kubectl logs -n ai-pipeline job/<job-name>
```

### Update Configuration

```bash
# Update secrets
kubectl edit secret pipeline-secrets -n ai-pipeline

# Or recreate from updated .env
cd /vagrant/deploy/scripts
sudo bash 06-create-secrets.sh
```

### Restart Deployments

```bash
# Restart dashboard
kubectl rollout restart deployment/pipeline-dashboard -n ai-pipeline

# Restart emulator
kubectl rollout restart deployment/github-emulator -n ai-pipeline
```

### Access Persistent Data

```bash
# Exec into a pod with the volume mounted
kubectl exec -it -n ai-pipeline deployment/pipeline-dashboard -- /bin/bash

# Navigate to data directories
ls -la /app/issues
ls -la /app/workspace
ls -la /app/logs
ls -la /app/artifacts
```

### Scale Resources

```bash
# Edit deployment resources
kubectl edit deployment pipeline-dashboard -n ai-pipeline

# Or use kubectl set
kubectl set resources deployment/pipeline-dashboard -n ai-pipeline \
  --limits=cpu=2000m,memory=4Gi \
  --requests=cpu=500m,memory=1Gi
```

## Troubleshooting

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for detailed troubleshooting steps.

### Quick Checks

```bash
# Is K3s running?
sudo systemctl status k3s

# Are all pods healthy?
kubectl get pods -A

# Are certificates ready?
kubectl get certificate -A

# Can DNS resolve?
kubectl run -it --rm debug --image=alpine --restart=Never -- \
  nslookup pipeline-dashboard.ai-pipeline.svc.cluster.local
```

### Common Issues

**Pods stuck in Pending:**
- Check PVC status: `kubectl get pvc -n ai-pipeline`
- Check node resources: `kubectl describe nodes`

**Certificate not ready:**
- Check cert-manager logs: `kubectl logs -n cert-manager deployment/cert-manager`
- Describe certificate: `kubectl describe certificate -n ai-pipeline`

**Image pull errors:**
- Verify image exists: `sudo k3s ctr images ls`
- Rebuild and import: `cd /vagrant/deploy/scripts && sudo bash 05-build-images.sh`

**Secrets not found:**
- Check if secrets exist: `kubectl get secrets -n ai-pipeline`
- Recreate secrets: `cd /vagrant/deploy/scripts && sudo bash 06-create-secrets.sh`

## Cleanup

### Remove Deployments

```bash
# Delete all resources in namespace
kubectl delete namespace ai-pipeline

# Or delete specific resources
kubectl delete -f /vagrant/deploy/k8s/20-pipeline-dashboard.yaml
kubectl delete -f /vagrant/deploy/k8s/10-github-emulator.yaml
kubectl delete -f /vagrant/deploy/k8s/03-storage.yaml
```

### Destroy VM

```bash
# From host machine (project root)
vagrant destroy -f

# Remove Vagrant box (optional)
vagrant box remove ubuntu/jammy64
```

### Reset and Redeploy

```bash
# From within VM
cd /vagrant/deploy/scripts

# Delete namespace and certificates
kubectl delete namespace ai-pipeline
kubectl delete clusterissuer --all

# Reinstall cert-manager
kubectl delete -f https://github.com/cert-manager/cert-manager/releases/download/v1.14.4/cert-manager.yaml
sleep 30
sudo bash 02-install-cert-manager.sh

# Recreate everything
sudo bash 03-setup-certificates.sh
sudo bash 04-extract-ca-cert.sh
sudo bash 06-create-secrets.sh

# Redeploy applications
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml
kubectl apply -f /vagrant/deploy/k8s/10-github-emulator.yaml
kubectl apply -f /vagrant/deploy/k8s/20-pipeline-dashboard.yaml
```

## Development Workflow

### Iterating on Code

```bash
# 1. Make code changes on host machine
# 2. Rebuild image in VM
vagrant ssh
cd /vagrant/deploy/scripts
sudo bash 05-build-images.sh

# 3. Restart deployment to pick up new image
kubectl rollout restart deployment/pipeline-dashboard -n ai-pipeline

# 4. Watch it redeploy
kubectl get pods -n ai-pipeline -w
```

### Testing Changes

```bash
# Run a one-off job with your changes
kubectl create -f /vagrant/deploy/k8s/30-pipeline-job-template.yaml

# Or exec into running pod
kubectl exec -it -n ai-pipeline deployment/pipeline-dashboard -- /bin/bash
```

### Viewing Pipeline Data

Since the project directory is synced to `/vagrant`, and persistent data is stored in PVCs, you can:

1. **View from host**: Some data may be visible in the project directory
2. **View from VM**: Access via pod exec or kubectl cp
3. **Copy from pod**:
   ```bash
   kubectl cp ai-pipeline/pipeline-dashboard-<pod-id>:/app/logs ./local-logs
   ```

## Advanced Configuration

### Custom VM Resources

Edit `Vagrantfile` in project root:

```ruby
vb.memory = "16384"  # 16GB RAM
vb.cpus = 8          # 8 CPUs
```

### Custom IP Address

Edit `Vagrantfile`:

```ruby
config.vm.network "private_network", ip: "192.168.56.20"
```

Then update K3s TLS SAN in `deploy/scripts/01-install-k3s.sh`:

```bash
--tls-san 192.168.56.20
```

### Additional Port Forwarding

Edit `Vagrantfile`:

```ruby
config.vm.network "forwarded_port", guest: 8080, host: 8080, host_ip: "127.0.0.1"
```

### External LoadBalancer Access

By default, K3s servicelb assigns LoadBalancer IPs from the node IP range. To customize:

```bash
# Edit the service to use a specific IP
kubectl edit service pipeline-dashboard -n ai-pipeline

# Add under spec:
spec:
  loadBalancerIP: 192.168.56.100
```

## Security Considerations

This deployment is designed for **local development and testing only**. For production use:

1. **Use real certificates**: Replace self-signed CA with Let's Encrypt or corporate CA
2. **Secure secrets**: Use external secret management (Vault, SOPS, etc.)
3. **Network policies**: Implement NetworkPolicy resources
4. **RBAC**: Configure proper role-based access control
5. **Image scanning**: Scan images for vulnerabilities
6. **Resource limits**: Enforce ResourceQuotas and LimitRanges
7. **Audit logging**: Enable Kubernetes audit logging
8. **Encrypted storage**: Use encrypted persistent volumes

## License

This deployment configuration is part of the ai-first-pipeline project.
