# Pipeline Agent Container

Container image for running AI-first-pipeline agents as Kubernetes Jobs.

## Contents

- **Dockerfile** - Container image definition
- **build-and-deploy.sh** - Build script that creates image and imports to K3s

## What's Inside

The container includes:
- Python 3.13
- Claude Code CLI (`@anthropic-ai/claude-code` npm package)
- All pipeline dependencies (via `uv sync`)
- Complete pipeline codebase (`main.py`, `lib/`, `.claude/skills/`)
- Git, curl, Node.js

## Building

```bash
./build-and-deploy.sh
```

This will:
1. Build the Docker image inside Vagrant VM
2. Import it into K3s using `k3s ctr images import`
3. Verify the image is available

## Image Details

- **Name:** `pipeline-agent:latest`
- **Size:** ~509 MB
- **User:** `pipelineagent` (non-root)
- **Workdir:** `/app`
- **Python:** 3.13 with uv-managed virtualenv

## Testing

```bash
# Quick test
kubectl run test-agent \
  --image=pipeline-agent:latest \
  --image-pull-policy=Never \
  --restart=Never \
  --rm -it \
  -n ai-pipeline \
  -- python main.py --help

# Test with mounted volumes
kubectl apply -f - <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: test-agent
  namespace: ai-pipeline
spec:
  restartPolicy: Never
  containers:
  - name: agent
    image: pipeline-agent:latest
    imagePullPolicy: Never
    command: ["python", "main.py", "bug-fetch", "--help"]
    volumeMounts:
    - name: issues
      mountPath: /app/issues
    env:
    - name: JIRA_SERVER
      value: "https://jira-emulator.ai-pipeline.svc.cluster.local"
  volumes:
  - name: issues
    persistentVolumeClaim:
      claimName: pipeline-issues
EOF

kubectl logs test-agent -n ai-pipeline -f
kubectl delete pod test-agent -n ai-pipeline
```

## Usage in Jobs

When creating Kubernetes Jobs, use:

```yaml
spec:
  template:
    spec:
      containers:
      - name: agent
        image: pipeline-agent:latest
        imagePullPolicy: Never  # Important! Use local image
        command: ["python", "main.py", "bug-completeness", "--issue", "RHOAIENG-12345"]
```

**Important:** Always set `imagePullPolicy: Never` since this is a locally-built image not in a registry.

## Rebuilding

After making changes to the pipeline code:

```bash
./build-and-deploy.sh
```

This rebuilds the image with the latest code. Running jobs will continue using the old image until they restart.

## Next Steps

See `deploy/docs/ARCHITECTURE-V2.md` for:
- How to create K8s Jobs with this image
- Environment variables needed (GCP credentials, Jira config)
- Volume mounts for shared storage
- Dashboard integration for job submission
