# Running Claude Agents on K3s with Vertex AI

This document explains how to run Claude Code agents in Kubernetes pods with proper Google Cloud Platform (Vertex AI) authentication, based on patterns from the company-simulator project.

## Overview

The company-simulator project uses containerized agents running Claude Code CLI with Vertex AI. We've adapted this design for our K3s cluster with the following architecture:

```
┌─────────────────────────────────────────────────┐
│ K8s Pod (Agent Container)                       │
│                                                  │
│  ┌───────────────────────────────────────────┐  │
│  │ Claude Code CLI (@anthropic-ai/claude-code)│  │
│  │ - Installed via npm                        │  │
│  │ - Runs as non-root user                    │  │
│  └───────────────────────────────────────────┘  │
│                                                  │
│  Environment Variables:                         │
│  ├─ CLAUDE_CODE_USE_VERTEX=1                   │
│  ├─ CLOUD_ML_REGION=us-east5                   │
│  ├─ ANTHROPIC_VERTEX_PROJECT_ID=<project>      │
│  └─ GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp/credentials.json
│                                                  │
│  Volume Mounts:                                 │
│  └─ /secrets/gcp/credentials.json (from Secret)│
│                                                  │
└─────────────────────────────────────────────────┘
                      │
                      ▼
         Google Cloud Vertex AI API
         (Claude models: opus, sonnet, haiku)
```

## Credentials Flow

### 1. Local Development Setup

On your development machine:
```bash
# Authenticate with GCP
gcloud auth application-default login

# This creates: ~/.config/gcloud/application_default_credentials.json
```

### 2. Transfer to Kubernetes

The deployment script (`06-create-secrets.sh`) reads your local credentials and creates a Kubernetes Secret:

```bash
# From .env or environment
export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json

# Script creates secret
kubectl create secret generic gcp-credentials \
  -n ai-pipeline \
  --from-file=credentials.json="$GOOGLE_APPLICATION_CREDENTIALS"
```

### 3. Mount in Pod

The deployment YAML mounts the secret as a file:

```yaml
env:
- name: GOOGLE_APPLICATION_CREDENTIALS
  value: /secrets/gcp/credentials.json

volumeMounts:
- name: gcp-credentials
  mountPath: /secrets/gcp
  readOnly: true

volumes:
- name: gcp-credentials
  secret:
    secretName: gcp-credentials
    optional: true  # Don't fail if secret doesn't exist
```

### 4. Claude SDK Uses Credentials

When the Claude Agent SDK initializes, it:
1. Reads `GOOGLE_APPLICATION_CREDENTIALS` env var
2. Loads the JSON file at that path
3. Uses it to authenticate with Vertex AI
4. Makes API calls to Claude models

## Container Design Pattern

Based on `company-simulator/Dockerfile.agent`, here's the pattern for Claude agent containers:

```dockerfile
FROM python:3.13-slim

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl nodejs npm git \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -s /bin/bash agent

# Create credentials directory (file mounted at runtime)
RUN mkdir -p /home/agent/.config/gcloud
RUN chown -R agent:agent /home/agent/.config

# Set environment variables
ENV HOME=/home/agent \
    GOOGLE_APPLICATION_CREDENTIALS=/home/agent/.config/gcloud/credentials.json

USER agent
WORKDIR /home/agent/workspace

# Keep container alive for exec-based execution
CMD ["sleep", "infinity"]
```

## Kubernetes Deployment Pattern

### Basic Agent Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: claude-agent
  namespace: ai-pipeline
spec:
  replicas: 1
  selector:
    matchLabels:
      app: claude-agent
  template:
    metadata:
      labels:
        app: claude-agent
    spec:
      containers:
      - name: agent
        image: claude-agent:latest
        imagePullPolicy: IfNotPresent

        env:
        # Vertex AI configuration
        - name: CLAUDE_CODE_USE_VERTEX
          valueFrom:
            secretKeyRef:
              name: pipeline-secrets
              key: CLAUDE_CODE_USE_VERTEX
        - name: CLOUD_ML_REGION
          valueFrom:
            secretKeyRef:
              name: pipeline-secrets
              key: CLOUD_ML_REGION
        - name: ANTHROPIC_VERTEX_PROJECT_ID
          valueFrom:
            secretKeyRef:
              name: pipeline-secrets
              key: ANTHROPIC_VERTEX_PROJECT_ID
        # GCP credentials path
        - name: GOOGLE_APPLICATION_CREDENTIALS
          value: /secrets/gcp/credentials.json

        volumeMounts:
        # Mount GCP credentials
        - name: gcp-credentials
          mountPath: /secrets/gcp
          readOnly: true
        # Mount workspace for agent operations
        - name: workspace
          mountPath: /home/agent/workspace

        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"

      volumes:
      - name: gcp-credentials
        secret:
          secretName: gcp-credentials
          optional: true
      - name: workspace
        emptyDir: {}
```

## Existing Infrastructure

Our K3s cluster **already has** the following set up:

### ✅ Secret Management

- **Script**: `deploy/scripts/06-create-secrets.sh`
- **Secret**: `pipeline-secrets` (Vertex AI env vars)
- **Secret**: `gcp-credentials` (GCP credentials JSON)
- **Location**: `ai-pipeline` namespace

### ✅ Pipeline Dashboard

The pipeline dashboard (`deploy/k8s/20-pipeline-dashboard.yaml`) already implements this pattern:

```yaml
env:
- name: CLAUDE_CODE_USE_VERTEX
  valueFrom:
    secretKeyRef:
      name: pipeline-secrets
      key: CLAUDE_CODE_USE_VERTEX
# ... other Vertex AI vars ...
- name: GOOGLE_APPLICATION_CREDENTIALS
  value: /secrets/gcp/credentials.json

volumeMounts:
- name: gcp-credentials
  mountPath: /secrets/gcp
  readOnly: true

volumes:
- name: gcp-credentials
  secret:
    secretName: gcp-credentials
    optional: true
```

This means **any new service** can copy this pattern to get Vertex AI access.

## Usage Patterns

### Pattern 1: Long-Running Agent (company-simulator style)

Container stays alive, execute commands via `kubectl exec`:

```bash
# Deploy agent pod
kubectl apply -f claude-agent-deployment.yaml

# Execute Claude Code commands
kubectl exec -n ai-pipeline deployment/claude-agent -- \
  claude -p "Review the code in /workspace/src"

# Or interactive shell
kubectl exec -it -n ai-pipeline deployment/claude-agent -- bash
```

### Pattern 2: Job-Based Execution

Run agent as a Kubernetes Job for one-time tasks:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: claude-analysis-job
  namespace: ai-pipeline
spec:
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: agent
        image: claude-agent:latest
        command: ["claude"]
        args: ["-p", "Analyze the codebase and generate a report"]
        env:
        # Same env vars as above
        volumeMounts:
        # Same mounts as above
      volumes:
      # Same volumes as above
```

### Pattern 3: CronJob for Scheduled Tasks

Run agent on a schedule:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: daily-code-review
  namespace: ai-pipeline
spec:
  schedule: "0 9 * * *"  # Daily at 9 AM
  jobTemplate:
    spec:
      template:
        spec:
          # Same as Job pattern above
```

## Security Considerations

### ✅ Best Practices We Follow

1. **Non-root user**: Agents run as `agent` user, not root
2. **Read-only credentials**: GCP credentials mounted read-only
3. **Secret separation**: Credentials in Secrets, not ConfigMaps
4. **Optional secrets**: Using `optional: true` prevents pod failures
5. **Namespace isolation**: All resources in `ai-pipeline` namespace

### ⚠️ Security Notes

- **Credentials are sensitive**: The GCP credentials JSON grants access to Vertex AI
- **Cost implications**: Claude API calls on Vertex AI incur charges
- **Audit trail**: All API calls logged in GCP Cloud Logging
- **No credential sharing**: Each pod gets its own mount of the same secret

## Comparison: Podman vs Kubernetes

| Aspect | Company-Simulator (Podman) | Our K3s Cluster |
|--------|---------------------------|-----------------|
| **Credentials** | Volume mount from host `~/.config/gcloud` | Kubernetes Secret mount |
| **Networking** | `host.containers.internal` for MCP | Kubernetes Services + DNS |
| **Orchestration** | Python script manages containers | Kubernetes manages pods |
| **Scaling** | Manual container management | `replicas:` field |
| **Persistence** | Host volume mounts | PersistentVolumeClaims |
| **Discovery** | Environment variables | Service DNS names |

## Adaptation Example: Multi-Agent System

To adapt company-simulator's multi-agent design to K3s:

```yaml
---
# MCP Server (provides tools to agents)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server
  namespace: ai-pipeline
spec:
  replicas: 1
  template:
    spec:
      containers:
      - name: mcp-server
        image: company-simulator:latest
        command: ["python", "main.py", "mcp-server"]
        ports:
        - containerPort: 5001
---
apiVersion: v1
kind: Service
metadata:
  name: mcp-server
  namespace: ai-pipeline
spec:
  selector:
    app: mcp-server
  ports:
  - port: 5001
---
# Agent Deployment (multiple replicas)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: claude-agents
  namespace: ai-pipeline
spec:
  replicas: 3  # Multiple agents
  template:
    spec:
      containers:
      - name: agent
        image: claude-agent:latest
        env:
        # Vertex AI vars (as shown above)
        - name: MCP_SERVER_URL
          value: "http://mcp-server.ai-pipeline.svc.cluster.local:5001"
        - name: AGENT_PERSONA_KEY
          valueFrom:
            fieldRef:
              fieldPath: metadata.name  # Each pod gets unique name
        volumeMounts:
        # GCP credentials (as shown above)
```

Agents discover MCP server via Kubernetes DNS: `mcp-server.ai-pipeline.svc.cluster.local`

## Testing the Setup

### 1. Verify Secrets Exist

```bash
kubectl get secrets -n ai-pipeline
# Should show: pipeline-secrets, gcp-credentials
```

### 2. Check Secret Contents

```bash
# Check if credentials.json exists in secret
kubectl get secret gcp-credentials -n ai-pipeline -o jsonpath='{.data.credentials\.json}' | base64 -d | jq .type
# Should output: "authorized_user" or "service_account"
```

### 3. Test from Pod

```bash
# Create test pod
kubectl run test-claude -n ai-pipeline --image=python:3.13-slim \
  --env="GOOGLE_APPLICATION_CREDENTIALS=/secrets/gcp/credentials.json" \
  --overrides='
{
  "spec": {
    "volumes": [
      {
        "name": "gcp-credentials",
        "secret": {"secretName": "gcp-credentials"}
      }
    ],
    "containers": [
      {
        "name": "test-claude",
        "image": "python:3.13-slim",
        "command": ["sleep", "infinity"],
        "volumeMounts": [
          {
            "name": "gcp-credentials",
            "mountPath": "/secrets/gcp"
          }
        ]
      }
    ]
  }
}' -- sleep infinity

# Exec into pod and check
kubectl exec -it test-claude -n ai-pipeline -- bash
ls -la /secrets/gcp/
cat /secrets/gcp/credentials.json
```

## Next Steps

1. **Build agent image**: Create Dockerfile following the pattern above
2. **Deploy agent**: Use deployment YAML with credential mounts
3. **Connect to MCP**: If using company-simulator pattern, deploy MCP server
4. **Test execution**: Run `kubectl exec` to execute Claude commands
5. **Monitor usage**: Check GCP console for Vertex AI API calls

## References

- Company-simulator Dockerfile: `deploy/repos/company-simulator/Dockerfile.agent`
- Company-simulator CLAUDE.md: `deploy/repos/company-simulator/CLAUDE.md`
- Pipeline dashboard deployment: `deploy/k8s/20-pipeline-dashboard.yaml`
- Secrets creation script: `deploy/scripts/06-create-secrets.sh`
- Vertex AI docs: https://cloud.google.com/vertex-ai/docs
- Claude Agent SDK: https://github.com/anthropics/anthropic-sdk-python
