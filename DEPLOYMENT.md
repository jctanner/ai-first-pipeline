# AI-First Pipeline Kubernetes Deployment

Quick reference for deploying ai-first-pipeline to K3s.

## Prerequisites

1. **Vagrant** with VirtualBox, VMware, or libvirt
2. **At least 10GB free RAM** on your host machine
3. **`.env` file** in project root with credentials (see below)

## .env File Setup

Create a `.env` file in the project root:

```bash
# Vertex AI Configuration (required for pipeline)
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=your-gcp-project-id

# Jira Configuration (required for bug/RFE fetching)
JIRA_SERVER=https://issues.redhat.com
JIRA_USER=your-email@redhat.com
JIRA_TOKEN=your-jira-api-token

# Optional: Atlassian MCP Server
ATLASSIAN_MCP_URL=http://127.0.0.1:8081/sse

# Optional: GCP Service Account (for Vertex AI)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/credentials.json
```

## Quick Start (Automated)

```bash
# 1. Start the VM
vagrant up

# 2. SSH into the VM
vagrant ssh

# 3. Run automated deployment
cd /vagrant/deploy/scripts
sudo bash deploy-all.sh
```

This will:
- Install K3s
- Install cert-manager
- Set up TLS certificates
- Create secrets from your `.env`
- Build container images
- Deploy all applications
- Run validation tests

## Quick Start (Manual)

If you prefer to run steps individually:

```bash
# After "vagrant ssh"
cd /vagrant/deploy/scripts

# 1. Install K3s
sudo bash 01-install-k3s.sh

# 2. Install cert-manager
sudo bash 02-install-cert-manager.sh

# 3. Setup certificates
sudo bash 03-setup-certificates.sh
sudo bash 04-extract-ca-cert.sh

# 4. Create secrets
sudo bash 06-create-secrets.sh

# 5. Build images
sudo bash 05-build-images.sh

# 6. Deploy
kubectl apply -f /vagrant/deploy/k8s/03-storage.yaml
kubectl apply -f /vagrant/deploy/k8s/10-github-emulator.yaml
kubectl apply -f /vagrant/deploy/k8s/20-pipeline-dashboard.yaml

# 7. Validate
cd /vagrant/deploy/validation
bash test-cluster.sh
bash test-certificates.sh
bash test-application.sh
```

## Accessing Services

### From Host Machine

```bash
# Pipeline Dashboard
open http://localhost:5000

# GitHub Emulator
open https://localhost:3000
```

### From Within VM

```bash
# Get service IPs
kubectl get svc -n ai-pipeline

# Access via LoadBalancer IP
curl http://<EXTERNAL-IP>:5000
```

## Running Pipeline Commands

### Option 1: Exec into Dashboard Pod

```bash
kubectl exec -it deployment/pipeline-dashboard -n ai-pipeline -- bash

# Inside pod
uv run python main.py bug-fetch --limit 10
uv run python main.py bug-completeness
uv run python main.py dashboard --port 5000 --host 0.0.0.0
```

### Option 2: Kubernetes Job

```bash
# Copy and edit job template
cp deploy/k8s/30-pipeline-job-template.yaml /tmp/my-job.yaml

# Edit the command in the file
vim /tmp/my-job.yaml

# Run it
kubectl create -f /tmp/my-job.yaml

# Watch progress
kubectl get jobs -n ai-pipeline -w
kubectl logs -f job/<job-name> -n ai-pipeline
```

## Common Operations

```bash
# View logs
kubectl logs -f deployment/pipeline-dashboard -n ai-pipeline
kubectl logs -f deployment/github-emulator -n ai-pipeline

# Restart deployment
kubectl rollout restart deployment/pipeline-dashboard -n ai-pipeline

# Get cluster status
kubectl get all -n ai-pipeline

# Access persistent data
kubectl exec -it deployment/pipeline-dashboard -n ai-pipeline -- ls -la /app/issues
```

## Troubleshooting

See [`deploy/docs/TROUBLESHOOTING.md`](deploy/docs/TROUBLESHOOTING.md) for detailed troubleshooting.

Quick checks:

```bash
# Cluster health
kubectl get nodes
kubectl get pods -A

# Application status
kubectl get all -n ai-pipeline

# Recent events
kubectl get events -n ai-pipeline --sort-by='.lastTimestamp' | tail -20

# Verification
cd /vagrant/deploy/scripts
bash 99-verify-cluster.sh
```

## Project Structure

```
.
├── Vagrantfile                  # VM definition
├── DEPLOYMENT.md                # This file
├── .env                         # Credentials (create this)
└── deploy/
    ├── README.md                # Detailed deployment docs
    ├── scripts/                 # Setup scripts
    ├── k8s/                     # Kubernetes manifests
    ├── validation/              # Validation scripts
    └── docs/                    # Additional documentation
```

## Cleanup

```bash
# Delete deployments
kubectl delete namespace ai-pipeline

# Destroy VM (from host)
vagrant destroy -f
```

## Complete Documentation

For comprehensive documentation, see:

- **Deployment Details**: [`deploy/README.md`](deploy/README.md)
- **Troubleshooting**: [`deploy/docs/TROUBLESHOOTING.md`](deploy/docs/TROUBLESHOOTING.md)
- **Project Overview**: [`CLAUDE.md`](CLAUDE.md)

## Architecture Summary

- **VM**: Ubuntu 22.04, 8GB RAM, 4 CPUs
- **K3s**: Single-node Kubernetes cluster
- **Networking**: Private network at `192.168.56.10`
- **Certificates**: Self-signed CA via cert-manager
- **Storage**: Local-path provisioner with persistent volumes
- **Components**:
  - Pipeline Dashboard (Flask app on port 5000)
  - GitHub Emulator (API server on port 3000)
  - Pipeline Jobs (on-demand Kubernetes Jobs)

## Getting Help

1. Check the troubleshooting guide
2. Review logs: `kubectl logs <pod-name> -n ai-pipeline`
3. Verify status: `cd deploy/scripts && bash 99-verify-cluster.sh`
4. Collect diagnostics and create an issue
