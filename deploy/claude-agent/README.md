# Claude Agent Container for K3s

This directory contains everything needed to run Claude Code agents in Kubernetes pods with Vertex AI authentication.

## Architecture

Based on the company-simulator agent design, adapted for K3s:

```
┌────────────────────────────────────┐
│ Claude Agent Pod                   │
│                                    │
│ ┌────────────────────────────────┐ │
│ │ Claude Code CLI                │ │
│ │ (@anthropic-ai/claude-code)    │ │
│ └────────────────────────────────┘ │
│                                    │
│ Env: GOOGLE_APPLICATION_CREDENTIALS│
│      /home/agent/.config/gcloud/   │
│      credentials.json              │
│                                    │
│ Volume: gcp-credentials (Secret)   │
└────────────────────────────────────┘
           │
           ▼
    Vertex AI API
```

## Quick Start

### 1. Ensure Prerequisites

Make sure the cluster has the required secrets:

```bash
vagrant ssh -c "kubectl get secrets -n ai-pipeline | grep -E 'pipeline-secrets|gcp-credentials'"
```

You should see both secrets. If not, run:

```bash
vagrant ssh
cd /vagrant/deploy/scripts
sudo bash 06-create-secrets.sh
```

### 2. Build and Deploy

```bash
cd deploy/claude-agent
./build-and-deploy.sh
```

This will:
1. Build the Docker image
2. Import to k3s
3. Deploy to the cluster
4. Wait for pod to be ready
5. Show usage examples

### 3. Use the Agent

Execute Claude Code commands:

```bash
# Get pod name
POD=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent -o jsonpath='{.items[0].metadata.name}'")

# Run a Claude prompt
vagrant ssh -c "kubectl exec -n ai-pipeline $POD -- claude -p 'Explain the project structure'"

# Interactive mode
vagrant ssh -c "kubectl exec -it -n ai-pipeline $POD -- bash"
# Inside container:
claude -p "What files are in this directory?"
```

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | Container image definition |
| `deployment.yaml` | Kubernetes deployment manifest |
| `build-and-deploy.sh` | Automated build and deployment |
| `README.md` | This file |

## Container Details

### Base Image
- `python:3.13-slim`

### Installed Software
- **Node.js & npm** - For Claude Code CLI
- **Claude Code CLI** - `@anthropic-ai/claude-code` (latest)
- **Git** - For repository operations
- **curl** - For HTTP operations

### User Configuration
- **User**: `agent` (non-root)
- **Home**: `/home/agent`
- **Workspace**: `/home/agent/workspace`
- **Data**: `/home/agent/data` (persistent)

### Environment Variables

Automatically configured from Kubernetes Secrets:

| Variable | Source | Value |
|----------|--------|-------|
| `CLAUDE_CODE_USE_VERTEX` | `pipeline-secrets` | `1` |
| `CLOUD_ML_REGION` | `pipeline-secrets` | `us-east5` |
| `ANTHROPIC_VERTEX_PROJECT_ID` | `pipeline-secrets` | Your GCP project |
| `GOOGLE_APPLICATION_CREDENTIALS` | Hardcoded | `/home/agent/.config/gcloud/credentials.json` |
| `AGENT_NAME` | Pod metadata | Pod name (unique per replica) |

### Volume Mounts

| Mount Point | Source | Purpose |
|-------------|--------|---------|
| `/home/agent/.config/gcloud/` | Secret: `gcp-credentials` | GCP authentication |
| `/home/agent/workspace/` | EmptyDir | Ephemeral work area |
| `/home/agent/data/` | PVC: `agent-data` | Persistent storage |

## Usage Patterns

### Pattern 1: One-Shot Commands

Execute a single Claude command and exit:

```bash
kubectl exec -n ai-pipeline deployment/claude-agent -- \
  claude -p "Analyze the code quality"
```

### Pattern 2: Interactive Session

Start an interactive bash session:

```bash
kubectl exec -it -n ai-pipeline deployment/claude-agent -- bash

# Inside container
cd /home/agent/workspace
git clone https://github.com/example/repo
cd repo
claude -p "Review this codebase"
```

### Pattern 3: Multiple Agents (Scaling)

Deploy multiple agent replicas:

```bash
vagrant ssh -c "kubectl scale deployment claude-agent -n ai-pipeline --replicas=3"
```

Each pod gets a unique name via `AGENT_NAME` env var.

### Pattern 4: Job-Based Execution

Create a one-time job:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: code-review-job
  namespace: ai-pipeline
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: agent
        image: claude-agent:latest
        command: ["claude"]
        args: ["-p", "Review the codebase and generate a report"]
        env:
        # Copy env vars from deployment.yaml
        volumeMounts:
        # Copy mounts from deployment.yaml
      volumes:
      # Copy volumes from deployment.yaml
```

## Debugging

### Check Pod Status

```bash
vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent"
```

### View Logs

```bash
vagrant ssh -c "kubectl logs -f deployment/claude-agent -n ai-pipeline"
```

### Describe Pod

```bash
vagrant ssh -c "kubectl describe pod -n ai-pipeline -l app=claude-agent"
```

### Verify Credentials

```bash
POD=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent -o jsonpath='{.items[0].metadata.name}'")

# Check file exists
vagrant ssh -c "kubectl exec -n ai-pipeline $POD -- ls -la /home/agent/.config/gcloud/"

# Check file contents (should show JSON structure)
vagrant ssh -c "kubectl exec -n ai-pipeline $POD -- cat /home/agent/.config/gcloud/credentials.json | head -5"
```

### Test Vertex AI Connection

```bash
POD=$(vagrant ssh -c "kubectl get pods -n ai-pipeline -l app=claude-agent -o jsonpath='{.items[0].metadata.name}'")

vagrant ssh -c "kubectl exec -n ai-pipeline $POD -- claude -p 'Say hello'"
```

If this works, Vertex AI authentication is correct.

## Customization

### Change Claude Model

By default, Claude Code uses the best available model. To specify:

```bash
kubectl exec -n ai-pipeline deployment/claude-agent -- \
  claude --model opus -p "Complex analysis task"

kubectl exec -n ai-pipeline deployment/claude-agent -- \
  claude --model sonnet -p "Balanced task"

kubectl exec -n ai-pipeline deployment/claude-agent -- \
  claude --model haiku -p "Quick task"
```

### Add Custom Tools

Mount additional tools or scripts:

```yaml
# In deployment.yaml, add:
volumeMounts:
- name: custom-tools
  mountPath: /home/agent/tools

volumes:
- name: custom-tools
  configMap:
    name: agent-tools
    defaultMode: 0755
```

### Persistent Workspace

To keep workspace across restarts:

```yaml
# Change from emptyDir to PVC
- name: workspace
  persistentVolumeClaim:
    claimName: agent-workspace
```

## Integration with Company-Simulator Pattern

This agent can be integrated with an MCP server for tool access:

```yaml
env:
- name: MCP_SERVER_URL
  value: "http://mcp-server.ai-pipeline.svc.cluster.local:5001"
```

See `deploy/docs/CLAUDE-AGENTS-ON-K3S.md` for full multi-agent setup.

## Resource Requirements

### Minimum
- **Memory**: 512Mi request, 2Gi limit
- **CPU**: 250m request, 1000m limit
- **Storage**: 5Gi PVC for persistent data

### Recommended for Production
- **Memory**: 1Gi request, 4Gi limit
- **CPU**: 500m request, 2000m limit
- **Storage**: 20Gi PVC

## Cost Considerations

Each Claude Code execution makes API calls to Vertex AI:
- **Opus**: Highest cost, best quality
- **Sonnet**: Balanced cost/performance
- **Haiku**: Lowest cost, fast responses

Monitor usage in GCP Console → Vertex AI → Usage

## Security Notes

- ✅ Runs as non-root user (`agent`)
- ✅ Credentials mounted read-only
- ✅ Secrets not in environment variables (mounted files)
- ✅ No privilege escalation
- ⚠️ GCP credentials grant full Vertex AI access
- ⚠️ Consider using Workload Identity for production

## Cleanup

Remove the deployment:

```bash
vagrant ssh -c "kubectl delete -f /vagrant/deploy/claude-agent/deployment.yaml"
```

Remove the image:

```bash
vagrant ssh -c "sudo k3s ctr images rm docker.io/library/claude-agent:latest"
```

## References

- Design doc: `deploy/docs/CLAUDE-AGENTS-ON-K3S.md`
- Company-simulator: `deploy/repos/company-simulator/`
- Pipeline dashboard (reference implementation): `deploy/k8s/20-pipeline-dashboard.yaml`
- Secrets setup: `deploy/scripts/06-create-secrets.sh`
