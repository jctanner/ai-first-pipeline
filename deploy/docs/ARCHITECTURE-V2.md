# K3s Architecture Plan for AI-First Pipeline

**Version 2.0 - Kubernetes-Native Architecture**

## Overview

This document describes the architecture for running the ai-first-pipeline entirely within K3s, transforming it from a local Python application into a cloud-native, distributed system using Kubernetes Jobs for agent execution and a centralized dashboard for orchestration and monitoring.

## Current Architecture Summary

The pipeline currently runs as a **local Python application**:
- Entry point: `main.py` → `lib/phases.py` → `lib/agent_runner.py`
- Each phase discovers issues, builds job lists, runs agents concurrently with asyncio semaphore
- Agents execute via Claude Agent SDK (CLI or SDK mode) with Vertex AI
- Skills are either "templated" (prompt injection) or "native" (SDK discovery)
- Dashboard is a Flask app showing results with SSE for live activity
- Storage: `issues/`, `workspace/`, `logs/` directories on local filesystem

**Limitations:**
- Single machine resource constraints
- Manual execution required
- No built-in job queuing or prioritization
- Limited observability
- Workspace cleanup requires manual intervention

## Proposed K3s Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    User (Browser)                           │
└────────────┬───────────────────────────┬────────────────────┘
             │                           │
             │ Dashboard UI              │ MLflow UI
             ▼                           ▼
┌──────────────────────────┐   ┌────────────────────────────┐
│ Pipeline Dashboard (Pod) │   │ MLflow Server (Pod)        │
│ - Job submission API     │   │ - Trace storage            │
│ - Job monitoring         │   │ - Metrics aggregation      │
│ - SSE activity feed      │◄──┤ - Cost tracking            │
│ - K8s orchestrator       │   │ - Quality evaluation       │
└──┬───────────────────┬───┘   └────────────▲───────────────┘
   │                   │                    │
   │ creates           │ monitors           │ logs traces
   ▼                   ▼                    │
┌────────────┐  ┌──────────────┐           │
│ K8s Jobs   │  │ Job Status   │           │
│ (Agents)   │──┤ (K8s API)    │           │
└──────┬─────┘  └──────────────┘           │
       │                                    │
       │ writes                             │
       ▼                                    │
┌─────────────────┐                        │
│ Shared Storage  │                        │
│ (PVCs)          │                        │
│ - issues/       │                        │
│ - workspace/    │                        │
│ - logs/         ├────────────────────────┘
│ - .context/     │ (activity.jsonl)
└─────────────────┘
```

### Key Benefits

✅ **Scalability** - K8s manages resource allocation and scheduling  
✅ **Reliability** - Failed jobs can be retried automatically  
✅ **Observability** - Built-in logging and metrics via K8s + MLflow  
✅ **Job Queuing** - Natural queue management via pending Jobs  
✅ **Resource Isolation** - Each agent runs in its own container  
✅ **Workspace Management** - PVCs provide durable, shared storage  
✅ **Full Telemetry** - MLflow tracks every execution with prompts, responses, tokens, costs, and quality metrics  
✅ **Cost Transparency** - Real-time cost tracking per issue, phase, and model  
✅ **Quality Monitoring** - LLM-as-a-judge evaluation integrated into traces  

## Components

### 1. Shared Storage (PVCs)

Create persistent volumes for shared data across all pipeline components:

```yaml
# deploy/k8s/14-pipeline-storage.yaml
---
# Raw Jira issue JSON
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pipeline-issues
  namespace: ai-pipeline
spec:
  accessModes:
    - ReadWriteOnce  # Single node (K3s local-path limitation)
  resources:
    requests:
      storage: 5Gi
  storageClassName: local-path
---
# Cloned repos and phase outputs per issue
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pipeline-workspace
  namespace: ai-pipeline
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 50Gi  # Large - holds cloned repos
  storageClassName: local-path
---
# Activity logs and phase logs
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pipeline-logs
  namespace: ai-pipeline
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: local-path
---
# Architecture context and test recipes (read-only reference data)
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pipeline-context
  namespace: ai-pipeline
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi  # .context/ directory
  storageClassName: local-path
---
# RFE/strategy skills from external repo
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pipeline-remote-skills
  namespace: ai-pipeline
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: local-path
```

**Note:** K3s local-path provisioner only supports `ReadWriteOnce`. All pods must be scheduled on the same node, or we need to deploy an NFS provisioner for `ReadWriteMany`.

**Pod Affinity Strategy:**
```yaml
# Add to all pipeline pods
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
    - labelSelector:
        matchLabels:
          app: pipeline-dashboard
      topologyKey: kubernetes.io/hostname
```

### 2. Agent Container Image

Build a container with the pipeline code, dependencies, and Claude CLI:

```dockerfile
# deploy/pipeline-agent/Dockerfile
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    nodejs \
    npm \
    ca-certificates \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (uv for speed)
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy pipeline code
COPY . /app/

# Create non-root user
RUN useradd -m -s /bin/bash pipelineagent \
    && chown -R pipelineagent:pipelineagent /app

USER pipelineagent

# Set up Python path
ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:${PATH}"

# Entry point will be overridden by Job spec
CMD ["python", "main.py", "--help"]
```

**Build and deploy script:**
```bash
#!/bin/bash
# deploy/pipeline-agent/build-and-deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Building Pipeline Agent Container ==="

# Build from project root (to include all source)
cd "$PROJECT_ROOT"
vagrant ssh -c "cd /vagrant && sudo docker build -f deploy/pipeline-agent/Dockerfile -t pipeline-agent:latest ."

# Import to K3s
echo "=== Importing to K3s ==="
vagrant ssh -c "sudo docker save pipeline-agent:latest | sudo k3s ctr images import -"

echo "✓ Pipeline agent image ready"
vagrant ssh -c "sudo k3s ctr images ls | grep pipeline-agent"
```

### 3. Dashboard Enhancements

The dashboard evolves from a read-only viewer into an **orchestration control plane**.

#### New API Endpoints

Add to `lib/webapp.py`:

```python
from lib.k8s_orchestrator import PipelineOrchestrator

orchestrator = PipelineOrchestrator()

@app.route("/api/jobs/submit", methods=["POST"])
def submit_job():
    """Submit a new pipeline job to K8s.
    
    POST body:
    {
      "command": "bug-completeness",
      "args": {
        "issue": "RHOAIENG-37036",
        "model": "opus",
        "force": true
      }
    }
    
    Returns:
    {
      "job_name": "bug-completeness-rhoaieng-37036-opus-abc123",
      "status": "pending"
    }
    """
    data = request.get_json()
    job = orchestrator.submit_phase_job(
        phase=data['command'],
        issue_key=data['args']['issue'],
        model=data['args'].get('model', 'opus'),
        args=data['args']
    )
    return jsonify({
        "job_name": job.metadata.name,
        "status": "pending"
    })

@app.route("/api/jobs/batch", methods=["POST"])
def submit_batch_jobs():
    """Submit multiple jobs with concurrency control.
    
    POST body:
    {
      "command": "bug-all",
      "args": {
        "limit": 10,
        "model": ["opus", "sonnet"],
        "max_concurrent": 5
      }
    }
    """
    data = request.get_json()
    jobs = orchestrator.submit_batch(
        phase=data['command'],
        args=data['args']
    )
    return jsonify({
        "submitted": len(jobs),
        "job_names": [j.metadata.name for j in jobs]
    })

@app.route("/api/jobs/<job_name>")
def get_job_status(job_name):
    """Get status of a K8s job."""
    status = orchestrator.get_job_status(job_name)
    return jsonify(status)

@app.route("/api/jobs")
def list_jobs():
    """List all pipeline jobs with optional filters."""
    phase = request.args.get('phase')
    status = request.args.get('status')  # pending|running|completed|failed
    jobs = orchestrator.list_jobs(phase=phase, status=status)
    return jsonify([{
        "name": j.metadata.name,
        "phase": j.metadata.labels.get('phase'),
        "issue": j.metadata.labels.get('issue'),
        "model": j.metadata.labels.get('model'),
        "status": _job_status(j),
        "created": j.metadata.creation_timestamp.isoformat(),
        "duration": _job_duration(j)
    } for j in jobs])

@app.route("/api/jobs/<job_name>/logs")
def get_job_logs(job_name):
    """Stream logs from a job's pod."""
    logs = orchestrator.get_job_logs(job_name)
    return Response(logs, mimetype='text/plain')
```

### 4. Kubernetes Orchestrator

New module to manage K8s Jobs:

```python
# lib/k8s_orchestrator.py
from kubernetes import client, config
from pathlib import Path
import os

class PipelineOrchestrator:
    """Manages K8s jobs for pipeline phases."""
    
    def __init__(self):
        try:
            # Try in-cluster config first (when running in K8s)
            config.load_incluster_config()
        except config.ConfigException:
            # Fallback to kubeconfig (for local testing)
            config.load_kube_config()
        
        self.batch_v1 = client.BatchV1Api()
        self.core_v1 = client.CoreV1Api()
        self.namespace = "ai-pipeline"
        
    def submit_phase_job(
        self, 
        phase: str,
        issue_key: str,
        model: str,
        args: dict
    ) -> client.V1Job:
        """Create and submit a K8s Job for a pipeline phase."""
        job = self._create_job_manifest(phase, issue_key, model, args)
        return self.batch_v1.create_namespaced_job(
            namespace=self.namespace,
            body=job
        )
    
    def submit_batch(self, phase: str, args: dict) -> list:
        """Submit multiple jobs with concurrency management.
        
        This implements dashboard-side queuing to respect max_concurrent.
        Jobs are created but K8s will schedule them based on resources.
        """
        # Discover issues based on args (reuse _discover_issues logic)
        issue_keys = args.get('issue', [])
        if not issue_keys:
            # Would need to list from issues/ PVC
            issue_keys = self._list_issues_from_pvc()
        
        models = args.get('model', ['opus'])
        if isinstance(models, str):
            models = [models]
        
        limit = args.get('limit')
        if limit:
            issue_keys = issue_keys[:limit]
        
        jobs = []
        for issue in issue_keys:
            for model in models:
                job = self.submit_phase_job(phase, issue, model, args)
                jobs.append(job)
        
        return jobs
    
    def list_jobs(self, phase=None, status=None) -> list:
        """List pipeline jobs with optional filters."""
        label_selector = "app=pipeline-agent"
        if phase:
            label_selector += f",phase={phase}"
        
        jobs = self.batch_v1.list_namespaced_job(
            namespace=self.namespace,
            label_selector=label_selector
        )
        
        if status:
            jobs.items = [j for j in jobs.items if self._get_job_status(j) == status]
        
        return jobs.items
    
    def get_job_status(self, job_name: str) -> dict:
        """Get detailed status of a job."""
        job = self.batch_v1.read_namespaced_job(
            name=job_name,
            namespace=self.namespace
        )
        
        status = self._get_job_status(job)
        
        # Get pod logs if running or failed
        logs = None
        if status in ['running', 'failed', 'completed']:
            logs = self.get_job_logs(job_name)
        
        return {
            "name": job.metadata.name,
            "status": status,
            "created": job.metadata.creation_timestamp.isoformat(),
            "started": job.status.start_time.isoformat() if job.status.start_time else None,
            "completed": job.status.completion_time.isoformat() if job.status.completion_time else None,
            "succeeded": job.status.succeeded or 0,
            "failed": job.status.failed or 0,
            "logs_available": logs is not None
        }
    
    def get_job_logs(self, job_name: str) -> str:
        """Get logs from a job's pod."""
        # Find pod for this job
        pods = self.core_v1.list_namespaced_pod(
            namespace=self.namespace,
            label_selector=f"job-name={job_name}"
        )
        
        if not pods.items:
            return None
        
        pod_name = pods.items[0].metadata.name
        
        try:
            return self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace
            )
        except client.ApiException:
            return None
    
    def _create_job_manifest(
        self,
        phase: str,
        issue_key: str,
        model: str,
        args: dict
    ) -> client.V1Job:
        """Generate a K8s Job manifest for a pipeline phase."""
        
        # Sanitize for K8s naming (lowercase, no underscores)
        job_name = f"{phase}-{issue_key}-{model}".lower().replace("_", "-")
        
        # Build command args
        cmd_args = ["python", "main.py", phase]
        cmd_args.extend(["--issue", issue_key])
        cmd_args.extend(["--model", model])
        
        if args.get("force"):
            cmd_args.append("--force")
        if args.get("component"):
            cmd_args.extend(["--component", args["component"]])
        if args.get("triage"):
            cmd_args.extend(["--triage", args["triage"]])
        if args.get("recommendation"):
            cmd_args.extend(["--recommendation", args["recommendation"]])
        if args.get("validation_retries") is not None:
            cmd_args.extend(["--validation-retries", str(args["validation_retries"])])
        if args.get("skip_validation"):
            cmd_args.append("--skip-validation")
        
        # Set max-concurrent to 1 for single-job execution
        cmd_args.extend(["--max-concurrent", "1"])
        
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=self.namespace,
                labels={
                    "app": "pipeline-agent",
                    "phase": phase,
                    "issue": issue_key.lower(),
                    "model": model
                }
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=3600,  # Clean up after 1hr
                backoff_limit=0,  # Don't retry failed jobs
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app": "pipeline-agent",
                            "phase": phase,
                            "issue": issue_key.lower()
                        }
                    ),
                    spec=client.V1PodSpec(
                        restart_policy="Never",
                        
                        # Pod affinity: schedule on same node as dashboard
                        affinity=client.V1Affinity(
                            pod_affinity=client.V1PodAffinity(
                                required_during_scheduling_ignored_during_execution=[
                                    client.V1PodAffinityTerm(
                                        label_selector=client.V1LabelSelector(
                                            match_labels={"app": "pipeline-dashboard"}
                                        ),
                                        topology_key="kubernetes.io/hostname"
                                    )
                                ]
                            )
                        ),
                        
                        containers=[
                            client.V1Container(
                                name="agent",
                                image="pipeline-agent:latest",
                                image_pull_policy="IfNotPresent",
                                command=cmd_args,
                                
                                env=[
                                    # Vertex AI config
                                    client.V1EnvVar(
                                        name="CLAUDE_CODE_USE_VERTEX",
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name="pipeline-secrets",
                                                key="CLAUDE_CODE_USE_VERTEX"
                                            )
                                        )
                                    ),
                                    client.V1EnvVar(
                                        name="CLOUD_ML_REGION",
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name="pipeline-secrets",
                                                key="CLOUD_ML_REGION"
                                            )
                                        )
                                    ),
                                    client.V1EnvVar(
                                        name="ANTHROPIC_VERTEX_PROJECT_ID",
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name="pipeline-secrets",
                                                key="ANTHROPIC_VERTEX_PROJECT_ID"
                                            )
                                        )
                                    ),
                                    # Jira config
                                    client.V1EnvVar(
                                        name="JIRA_SERVER",
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name="pipeline-secrets",
                                                key="JIRA_SERVER"
                                            )
                                        )
                                    ),
                                    client.V1EnvVar(
                                        name="JIRA_USER",
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name="pipeline-secrets",
                                                key="JIRA_USER"
                                            )
                                        )
                                    ),
                                    client.V1EnvVar(
                                        name="JIRA_TOKEN",
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name="pipeline-secrets",
                                                key="JIRA_TOKEN"
                                            )
                                        )
                                    ),
                                    # MCP server URL
                                    client.V1EnvVar(
                                        name="ATLASSIAN_MCP_URL",
                                        value_from=client.V1EnvVarSource(
                                            secret_key_ref=client.V1SecretKeySelector(
                                                name="pipeline-secrets",
                                                key="ATLASSIAN_MCP_URL",
                                                optional=True
                                            )
                                        )
                                    ),
                                    # GCP credentials path
                                    client.V1EnvVar(
                                        name="GOOGLE_APPLICATION_CREDENTIALS",
                                        value="/app/.gcloud/credentials.json"
                                    ),
                                    # MLflow tracking
                                    client.V1EnvVar(
                                        name="MLFLOW_TRACKING_URI",
                                        value="http://mlflow.ai-pipeline.svc.cluster.local:5000"
                                    )
                                ],
                                
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name="issues",
                                        mount_path="/app/issues"
                                    ),
                                    client.V1VolumeMount(
                                        name="workspace",
                                        mount_path="/app/workspace"
                                    ),
                                    client.V1VolumeMount(
                                        name="logs",
                                        mount_path="/app/logs"
                                    ),
                                    client.V1VolumeMount(
                                        name="context",
                                        mount_path="/app/.context",
                                        read_only=True
                                    ),
                                    client.V1VolumeMount(
                                        name="remote-skills",
                                        mount_path="/app/remote_skills",
                                        read_only=True
                                    ),
                                    client.V1VolumeMount(
                                        name="gcp-credentials",
                                        mount_path="/app/.gcloud",
                                        read_only=True
                                    )
                                ],
                                
                                resources=client.V1ResourceRequirements(
                                    requests={"memory": "2Gi", "cpu": "500m"},
                                    limits={"memory": "8Gi", "cpu": "2000m"}
                                )
                            )
                        ],
                        
                        volumes=[
                            client.V1Volume(
                                name="issues",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name="pipeline-issues"
                                )
                            ),
                            client.V1Volume(
                                name="workspace",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name="pipeline-workspace"
                                )
                            ),
                            client.V1Volume(
                                name="logs",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name="pipeline-logs"
                                )
                            ),
                            client.V1Volume(
                                name="context",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name="pipeline-context"
                                )
                            ),
                            client.V1Volume(
                                name="remote-skills",
                                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                    claim_name="pipeline-remote-skills"
                                )
                            ),
                            client.V1Volume(
                                name="gcp-credentials",
                                secret=client.V1SecretVolumeSource(
                                    secret_name="gcp-credentials",
                                    optional=False
                                )
                            )
                        ]
                    )
                )
            )
        )
        
        return job
    
    def _get_job_status(self, job: client.V1Job) -> str:
        """Determine job status from K8s Job object."""
        if job.status.succeeded:
            return "completed"
        elif job.status.failed:
            return "failed"
        elif job.status.active:
            return "running"
        else:
            return "pending"
    
    def _list_issues_from_pvc(self) -> list:
        """List issue keys from issues/ PVC.
        
        This would require mounting the PVC to the dashboard pod.
        For now, return empty list.
        """
        # TODO: Scan issues/ directory
        return []
```

### 5. RBAC Configuration

Dashboard pod needs permissions to create and monitor Jobs:

```yaml
# deploy/k8s/16-pipeline-rbac.yaml
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: pipeline-dashboard
  namespace: ai-pipeline
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pipeline-orchestrator
  namespace: ai-pipeline
rules:
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["get", "list", "watch", "create", "delete"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: pipeline-orchestrator-binding
  namespace: ai-pipeline
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: pipeline-orchestrator
subjects:
- kind: ServiceAccount
  name: pipeline-dashboard
  namespace: ai-pipeline
```

### 6. Updated Dashboard Deployment

```yaml
# deploy/k8s/15-pipeline-dashboard.yaml (updated)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pipeline-dashboard
  namespace: ai-pipeline
spec:
  replicas: 1
  selector:
    matchLabels:
      app: pipeline-dashboard
  template:
    metadata:
      labels:
        app: pipeline-dashboard
    spec:
      serviceAccountName: pipeline-dashboard  # NEW: for K8s API access
      
      containers:
      - name: dashboard
        image: pipeline-agent:latest  # Same image, different command
        imagePullPolicy: IfNotPresent
        
        command: ["python", "main.py", "dashboard", "--host", "0.0.0.0", "--port", "5000"]
        
        ports:
        - name: http
          containerPort: 5000
        
        env:
        - name: KUBERNETES_SERVICE_HOST
          value: kubernetes.default.svc
        # ... (copy env vars from agent job spec)
        
        volumeMounts:
        - name: issues
          mountPath: /app/issues
        - name: workspace
          mountPath: /app/workspace
        - name: logs
          mountPath: /app/logs
        - name: context
          mountPath: /app/.context
          readOnly: true
        - name: remote-skills
          mountPath: /app/remote_skills
          readOnly: true
        - name: gcp-credentials
          mountPath: /app/.gcloud
          readOnly: true
        
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
      
      volumes:
      - name: issues
        persistentVolumeClaim:
          claimName: pipeline-issues
      - name: workspace
        persistentVolumeClaim:
          claimName: pipeline-workspace
      - name: logs
        persistentVolumeClaim:
          claimName: pipeline-logs
      - name: context
        persistentVolumeClaim:
          claimName: pipeline-context
      - name: remote-skills
        persistentVolumeClaim:
          claimName: pipeline-remote-skills
      - name: gcp-credentials
        secret:
          secretName: gcp-credentials
```

### 7. Dashboard UI - Jobs Page

Add a new "Jobs" page to the dashboard:

```python
# Add to lib/webapp.py templates

JOBS_PAGE = """
{% extends "layout.html" %}
{% block title %}Pipeline Jobs{% endblock %}
{% block content %}
<div class="container">
  <h2>Pipeline Jobs</h2>
  
  <section>
    <h3>Submit New Job</h3>
    <form id="job-submit-form">
      <label>
        Phase:
        <select name="phase" required>
          <option value="bug-completeness">Bug Completeness</option>
          <option value="bug-context-map">Bug Context Map</option>
          <option value="bug-fix-attempt">Bug Fix Attempt</option>
          <option value="bug-test-plan">Bug Test Plan</option>
          <option value="bug-write-test">Bug Write Test</option>
          <option value="rfe-create">RFE Create</option>
          <option value="rfe-review">RFE Review</option>
          <option value="strat-review">Strategy Review</option>
        </select>
      </label>
      
      <label>
        Issue Key:
        <input type="text" name="issue" placeholder="RHOAIENG-37036" required>
      </label>
      
      <label>
        Model:
        <select name="model">
          <option value="opus">Opus (Best Quality)</option>
          <option value="sonnet">Sonnet (Balanced)</option>
          <option value="haiku">Haiku (Fast)</option>
        </select>
      </label>
      
      <label>
        <input type="checkbox" name="force"> Force regenerate
      </label>
      
      <button type="submit">Submit Job</button>
    </form>
  </section>
  
  <section>
    <h3>Active Jobs</h3>
    <div style="margin-bottom: 1rem;">
      <button onclick="refreshJobs()">🔄 Refresh</button>
      <span style="margin-left: 1rem;">Auto-refresh: <span id="refresh-timer">5</span>s</span>
    </div>
    
    <table id="jobs-table">
      <thead>
        <tr>
          <th>Job Name</th>
          <th>Phase</th>
          <th>Issue</th>
          <th>Model</th>
          <th>Status</th>
          <th>Started</th>
          <th>Duration</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr><td colspan="8" style="text-align: center;">Loading...</td></tr>
      </tbody>
    </table>
  </section>
  
  <section>
    <h3>Batch Operations</h3>
    <form id="batch-submit-form">
      <label>
        Pipeline:
        <select name="pipeline" required>
          <option value="bug-all">Bug Analysis (All Phases)</option>
          <option value="rfe-all">RFE Pipeline</option>
          <option value="strat-all">Strategy Pipeline</option>
        </select>
      </label>
      
      <label>
        Limit (optional):
        <input type="number" name="limit" placeholder="10" min="1">
      </label>
      
      <label>
        Max Concurrent:
        <input type="number" name="max_concurrent" value="5" min="1" max="20">
      </label>
      
      <button type="submit">Run Batch</button>
    </form>
  </section>
</div>

<script>
let refreshInterval;
let secondsUntilRefresh = 5;

function formatDuration(seconds) {
  if (!seconds) return '-';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h > 0 ? `${h}h ${m}m` : m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatTimestamp(iso) {
  if (!iso) return '-';
  const date = new Date(iso);
  return date.toLocaleString();
}

function getStatusBadge(status) {
  const colors = {
    pending: 'background: #888; color: white;',
    running: 'background: #0074d9; color: white;',
    completed: 'background: #2ecc40; color: white;',
    failed: 'background: #ff4136; color: white;'
  };
  const style = colors[status] || 'background: #ddd;';
  return `<span style="padding: 2px 8px; border-radius: 3px; ${style}">${status}</span>`;
}

async function refreshJobs() {
  try {
    const response = await fetch('/api/jobs');
    const jobs = await response.json();
    
    const tbody = document.querySelector('#jobs-table tbody');
    if (jobs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="text-align: center;">No jobs found</td></tr>';
      return;
    }
    
    tbody.innerHTML = jobs.map(job => {
      const duration = job.duration ? Math.floor(job.duration) : null;
      return `
        <tr>
          <td><code>${job.name}</code></td>
          <td>${job.phase}</td>
          <td>${job.issue}</td>
          <td>${job.model}</td>
          <td>${getStatusBadge(job.status)}</td>
          <td><small>${formatTimestamp(job.created)}</small></td>
          <td>${formatDuration(duration)}</td>
          <td>
            <a href="/api/jobs/${job.name}/logs" target="_blank">📋 Logs</a>
          </td>
        </tr>
      `;
    }).join('');
    
    secondsUntilRefresh = 5;
  } catch (error) {
    console.error('Failed to refresh jobs:', error);
  }
}

function startAutoRefresh() {
  refreshInterval = setInterval(() => {
    secondsUntilRefresh--;
    document.getElementById('refresh-timer').textContent = secondsUntilRefresh;
    
    if (secondsUntilRefresh <= 0) {
      refreshJobs();
      secondsUntilRefresh = 5;
    }
  }, 1000);
}

// Initial load
refreshJobs();
startAutoRefresh();

// Handle single job submission
document.getElementById('job-submit-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  const payload = {
    command: formData.get('phase'),
    args: {
      issue: formData.get('issue'),
      model: formData.get('model'),
      force: formData.get('force') === 'on'
    }
  };
  
  try {
    const response = await fetch('/api/jobs/submit', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    
    if (response.ok) {
      const result = await response.json();
      alert(`Job submitted: ${result.job_name}`);
      refreshJobs();
      e.target.reset();
    } else {
      const error = await response.text();
      alert(`Failed to submit job: ${error}`);
    }
  } catch (error) {
    alert(`Error: ${error.message}`);
  }
});

// Handle batch submission
document.getElementById('batch-submit-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const formData = new FormData(e.target);
  const payload = {
    command: formData.get('pipeline'),
    args: {
      limit: formData.get('limit') ? parseInt(formData.get('limit')) : null,
      max_concurrent: parseInt(formData.get('max_concurrent')),
      force: false
    }
  };
  
  try {
    const response = await fetch('/api/jobs/batch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    
    if (response.ok) {
      const result = await response.json();
      alert(`Batch submitted: ${result.submitted} jobs created`);
      refreshJobs();
    } else {
      const error = await response.text();
      alert(`Failed to submit batch: ${error}`);
    }
  } catch (error) {
    alert(`Error: ${error.message}`);
  }
});

// Clean up interval on page unload
window.addEventListener('beforeunload', () => {
  clearInterval(refreshInterval);
});
</script>
{% endblock %}
"""

# Add route
@app.route("/jobs")
def jobs_page():
    return render_template_string(JOBS_PAGE)

# Add to nav in LAYOUT template
# <a href="/jobs">Jobs</a>
```

## Migration Strategy

### Phase 1: Storage Setup ⚙️

**Objective:** Create and populate shared storage

```bash
# 1. Create PVCs
kubectl apply -f deploy/k8s/14-pipeline-storage.yaml

# 2. Create a helper pod to populate .context/ and remote_skills/
kubectl run -it --rm populate-context \
  --image=alpine:latest \
  --overrides='{"spec":{"volumes":[
    {"name":"context","persistentVolumeClaim":{"claimName":"pipeline-context"}},
    {"name":"remote-skills","persistentVolumeClaim":{"claimName":"pipeline-remote-skills"}}
  ],"containers":[{
    "name":"populate",
    "image":"alpine:latest",
    "command":["sh"],
    "volumeMounts":[
      {"name":"context","mountPath":"/context"},
      {"name":"remote-skills","mountPath":"/remote-skills"}
    ]
  }]}}'

# Inside pod:
apk add git
git clone <architecture-context-repo> /context/architecture-context
git clone <odh-tests-context-repo> /context/odh-tests-context
git clone <rfe-creator-repo> /remote-skills/rfe-creator
exit

# 3. Verify
kubectl run -it --rm verify \
  --image=alpine:latest \
  --overrides='<same volumes>' \
  -- ls -la /context /remote-skills
```

### Phase 2: Container Image 🐳

**Objective:** Build and test agent container

```bash
# 1. Build image
cd deploy/pipeline-agent
./build-and-deploy.sh

# 2. Test single job manually
kubectl run test-agent \
  --image=pipeline-agent:latest \
  --restart=Never \
  --rm -it \
  -- python main.py bug-fetch --help

# 3. Test with full volume mounts
kubectl apply -f deploy/k8s/test-agent-job.yaml
kubectl logs job/test-agent -f
```

### Phase 3: Dashboard Updates 📊

**Objective:** Add K8s orchestration to dashboard

```bash
# 1. Install kubernetes Python package
uv add kubernetes

# 2. Create new modules
# - lib/k8s_orchestrator.py
# - Add API routes to lib/webapp.py
# - Add JOBS_PAGE template

# 3. Apply RBAC
kubectl apply -f deploy/k8s/16-pipeline-rbac.yaml

# 4. Update dashboard deployment
kubectl apply -f deploy/k8s/15-pipeline-dashboard.yaml

# 5. Test job submission
curl -X POST http://dashboard.local/api/jobs/submit \
  -H 'Content-Type: application/json' \
  -d '{"command":"bug-completeness","args":{"issue":"RHOAIENG-37036","model":"haiku"}}'
```

### Phase 4: Integration Testing 🧪

**Objective:** End-to-end validation

```bash
# 1. Submit a single job via API
# 2. Monitor job status via dashboard
# 3. Verify outputs appear in workspace/ PVC
# 4. Check logs in logs/ PVC
# 5. View results in dashboard UI
# 6. Verify MLflow traces are created
```

### Phase 5: Batch Operations 📦

**Objective:** Multi-job orchestration

```bash
# 1. Test bug-all with limit=3
# 2. Monitor concurrency (should respect max_concurrent)
# 3. Verify all jobs complete successfully
# 4. Check aggregate statistics
```

### Phase 6: Production Hardening 🔒

**Objective:** Security, monitoring, cleanup

- Add resource quotas
- Configure pod security policies
- Set up job cleanup CronJob
- Add Prometheus metrics
- Configure log aggregation
- Implement job retries for transient failures

## Key Design Decisions

### 1. Storage Model

**Decision:** ReadWriteOnce PVCs with pod affinity

**Rationale:**
- K3s local-path doesn't support ReadWriteMany
- Pod affinity ensures all pods on same node can access PVCs
- Simpler than deploying NFS provisioner
- Good enough for single-node dev/test cluster

**Future:** For multi-node production, migrate to NFS or Ceph

### 2. Job Concurrency Control

**Decision:** Dashboard-managed queue (submit jobs, let K8s schedule)

**Rationale:**
- Better visibility into queue state
- Easier to implement job prioritization
- Can pause/resume queue without K8s changes
- Dashboard becomes central control plane

**Alternative:** K8s native parallelism with Job `spec.parallelism` would work but less flexible

### 3. Code Distribution

**Decision:** Bake code into container image

**Rationale:**
- Simpler deployment model
- Version control via image tags
- No risk of code/dependency drift between jobs
- Faster startup (no git clone)

**Trade-off:** Requires rebuilding image for code changes

### 4. Event System

**Decision:** Keep existing file-based activity log

**Rationale:**
- No code changes required
- Jobs write to shared `logs/activity.jsonl`
- Dashboard reads and streams via SSE
- Already implemented and tested

**Alternative:** HTTP POST to dashboard would work but requires network reliability

### 5. Credentials Management

**Decision:** Reuse existing K8s Secrets

**Rationale:**
- `gcp-credentials` secret already set up ✅
- `pipeline-secrets` has Jira + Vertex config ✅
- Mount as volumes (GCP creds) or env vars (Jira)
- Secure and K8s-native

## File Structure

```
deploy/
├── pipeline-agent/
│   ├── Dockerfile                    # Agent container image
│   ├── build-and-deploy.sh           # Build and import script
│   └── README.md                     # Agent container docs
├── k8s/
│   ├── 14-pipeline-storage.yaml      # PVCs for shared data
│   ├── 15-pipeline-dashboard.yaml    # Updated dashboard deployment
│   └── 16-pipeline-rbac.yaml         # ServiceAccount + Role + RoleBinding
├── scripts/
│   └── populate-storage.sh           # Helper to populate .context/ PVC
└── docs/
    └── ARCHITECTURE-V2.md            # This document

lib/
├── k8s_orchestrator.py               # NEW: K8s job management
├── webapp.py                         # UPDATED: Add job APIs and Jobs page
└── phases.py                         # Mostly unchanged (CLI still works)

pyproject.toml                        # UPDATED: Add kubernetes package
```

## Benefits of K8s Architecture

### Scalability
- **Before:** Limited by single machine resources
- **After:** K8s schedules jobs across cluster capacity
- **Example:** Run 50 fix-attempt jobs in parallel if cluster has capacity

### Reliability
- **Before:** Process crash loses all in-flight work
- **After:** Jobs are isolated; failures don't affect other jobs
- **Example:** One bad bug that crashes agent doesn't stop other analyses

### Observability
- **Before:** Single log file, manual log parsing
- **After:** Per-job logs, K8s events, Prometheus metrics
- **Example:** Track job success rate, duration distribution, resource usage

### Cost Efficiency
- **Before:** Machine idles when no jobs running
- **After:** Cluster can auto-scale (with GKE/EKS)
- **Example:** Scale down to zero when pipeline inactive

### Developer Experience
- **Before:** Run `python main.py bug-all` and wait
- **After:** Click "Run Batch" in UI, monitor progress, continue other work
- **Example:** Submit overnight batch, check results in morning

## Integration with Existing Components

### MLflow - Comprehensive Telemetry

MLflow provides the **observability layer** for the entire pipeline, tracking every agent execution with rich telemetry.

#### Architecture

```
┌─────────────────┐
│  Agent Job      │
│  (K8s Pod)      │
└────────┬────────┘
         │
         │ logs traces
         ▼
┌─────────────────────────────────────┐
│  MLflow Tracking Server             │
│  (mlflow.ai-pipeline.svc:5000)      │
│                                     │
│  - Traces (prompts + responses)     │
│  - Metrics (tokens, duration, cost) │
│  - Parameters (phase, model, args)  │
│  - Artifacts (patches, reports)     │
└────────┬────────────────────────────┘
         │
         │ stores
         ▼
┌─────────────────┐
│  MLflow PVC     │
│  - mlflow.db    │
│  - artifacts/   │
└─────────────────┘
```

#### Telemetry Data Model

Every agent execution creates an MLflow **trace** with:

**1. Trace Metadata**
```python
{
  "trace_id": "tr-abc123...",
  "request_id": "RHOAIENG-37036-bug-completeness-opus",
  "timestamp_ms": 1713254400000,
  "execution_time_ms": 45230,
  "status": "OK"  # or "ERROR"
}
```

**2. Inputs (Prompt)**
```python
{
  "issue_key": "RHOAIENG-37036",
  "phase": "bug-completeness",
  "model": "claude-opus-4-6",
  "skill": "bug-completeness",
  "prompt_length": 15420,
  "issue_summary": "Dashboard crashes when...",
  "issue_component": "Dashboard"
}
```

**3. Outputs (Response)**
```python
{
  "completeness_score": 85,
  "recommendation": "ai-fixable",
  "response_length": 3240,
  "structured_output": {...},  # Full JSON result
  "success": true
}
```

**4. Attributes (Metrics)**
```python
{
  "input_tokens": 15234,
  "output_tokens": 3421,
  "total_tokens": 18655,
  "cost_usd": 0.0456,  # Calculated from tokens
  "duration_seconds": 45.23,
  "model_id": "claude-opus-4-6@20250929",
  "validation_attempts": 0,  # For fix-attempt phase
  "validation_passed": null
}
```

**5. Events (Span Timeline)**
```python
[
  {"timestamp": 0,     "name": "start",           "type": "info"},
  {"timestamp": 1200,  "name": "prompt_built",    "type": "info"},
  {"timestamp": 1500,  "name": "agent_started",   "type": "info"},
  {"timestamp": 45000, "name": "agent_completed", "type": "info"},
  {"timestamp": 45200, "name": "output_validated", "type": "info"}
]
```

#### Implementation in Agent Jobs

Add MLflow tracing to `lib/agent_runner.py`:

```python
# lib/agent_runner.py (additions)
import mlflow
from anthropic import AnthropicVertex

async def run_agent(
    name: str,
    cwd: str,
    prompt: str,
    log_dir: Path,
    model_shorthand: str,
    log_file: Path | None = None,
    runner: str = "sdk",
) -> dict:
    """Run agent with MLflow tracing."""
    
    # Extract issue key and phase from name
    issue_key = name
    phase = log_dir.name  # From log_dir path
    
    # Start MLflow span
    with mlflow.start_span(name=f"{phase}_{issue_key}_{model_shorthand}") as span:
        # Set inputs
        span.set_inputs({
            "issue_key": issue_key,
            "phase": phase,
            "model": model_shorthand,
            "prompt_length": len(prompt),
            "cwd": cwd
        })
        
        # Set attributes (metadata)
        span.set_attributes({
            "runner": runner,
            "model_id": get_model_id(model_shorthand),
            "job_name": os.getenv("HOSTNAME", "local")  # K8s pod name
        })
        
        start_time = time.time()
        
        try:
            # Run agent (existing code)
            if runner == "cli":
                result = await _run_agent_cli(...)
            else:
                result = await _run_agent_sdk(...)
            
            duration = time.time() - start_time
            
            # Calculate cost
            model_id = get_model_id(model_shorthand)
            input_tokens = result.get("input_tokens", 0)
            output_tokens = result.get("output_tokens", 0)
            cost_usd = calculate_cost(model_id, input_tokens, output_tokens)
            
            # Set outputs
            span.set_outputs({
                "success": result.get("success", False),
                "output_file": str(result.get("output_file", "")),
                "error": result.get("error")
            })
            
            # Set metrics
            span.set_attributes({
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cost_usd": cost_usd,
                "duration_seconds": duration,
                "exit_code": result.get("exit_code", 0)
            })
            
            # For fix-attempt phase, add validation metrics
            if phase == "fix-attempt" and "validation_results" in result:
                span.set_attributes({
                    "validation_attempts": len(result["validation_results"]),
                    "validation_passed": result["validation_results"][-1]["passed"],
                    "total_validation_time": sum(
                        v["duration"] for v in result["validation_results"]
                    )
                })
            
            return result
            
        except Exception as e:
            span.set_attribute("error", str(e))
            span.set_attribute("status", "ERROR")
            raise

def calculate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD based on model pricing."""
    # Pricing as of 2026 (update as needed)
    pricing = {
        "claude-opus-4-6": {"input": 0.000015, "output": 0.000075},      # $15/$75 per 1M tokens
        "claude-sonnet-4-6": {"input": 0.000003, "output": 0.000015},    # $3/$15 per 1M tokens
        "claude-haiku-4-5": {"input": 0.00000025, "output": 0.00000125}  # $0.25/$1.25 per 1M tokens
    }
    
    model_pricing = pricing.get(model_id, pricing["claude-sonnet-4-6"])
    
    input_cost = (input_tokens / 1_000_000) * model_pricing["input"]
    output_cost = (output_tokens / 1_000_000) * model_pricing["output"]
    
    return round(input_cost + output_cost, 6)
```

#### Experiment Organization

Group traces by pipeline run:

```python
# lib/phases.py - when starting a batch
async def run_completeness_phase(args):
    # Create MLflow experiment for this batch
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    experiment_name = f"bug-completeness-{timestamp}"
    
    mlflow.set_experiment(experiment_name)
    
    # Run jobs (each job logs to this experiment)
    results = await _run_phase("completeness", all_jobs, args)
    
    # Log aggregate metrics
    with mlflow.start_run(run_name=f"batch-summary"):
        total_issues = len(results)
        successful = sum(1 for r in results if r.get("success"))
        total_cost = sum(
            calculate_cost(r["model_id"], r["input_tokens"], r["output_tokens"])
            for r in results if r.get("success")
        )
        
        mlflow.log_metrics({
            "total_issues": total_issues,
            "successful_runs": successful,
            "success_rate": successful / total_issues if total_issues > 0 else 0,
            "total_cost_usd": total_cost,
            "avg_cost_per_issue": total_cost / total_issues if total_issues > 0 else 0
        })
```

#### Cost Tracking Dashboard

Add cost analytics to the pipeline dashboard:

```python
# lib/webapp.py - new endpoint
@app.route("/api/costs")
def get_costs():
    """Get cost analytics from MLflow traces."""
    
    # Query MLflow for all traces in past 30 days
    traces = mlflow.search_traces(
        filter_string=f"timestamp_ms > {thirty_days_ago_ms}"
    )
    
    # Calculate costs
    costs_by_phase = defaultdict(float)
    costs_by_model = defaultdict(float)
    costs_by_day = defaultdict(float)
    
    for trace in traces.itertuples():
        cost = trace.attributes.get("cost_usd", 0)
        phase = trace.inputs.get("phase", "unknown")
        model = trace.inputs.get("model", "unknown")
        day = datetime.fromtimestamp(trace.timestamp_ms / 1000).strftime("%Y-%m-%d")
        
        costs_by_phase[phase] += cost
        costs_by_model[model] += cost
        costs_by_day[day] += cost
    
    return jsonify({
        "total_cost": sum(costs_by_phase.values()),
        "by_phase": dict(costs_by_phase),
        "by_model": dict(costs_by_model),
        "by_day": dict(costs_by_day),
        "total_traces": len(traces)
    })

# Add cost visualization to dashboard
COST_DASHBOARD = """
{% extends "layout.html" %}
{% block title %}Cost Analytics{% endblock %}
{% block content %}
<div class="container">
  <h2>Cost Analytics</h2>
  
  <section>
    <h3>Summary (Last 30 Days)</h3>
    <div class="grid">
      <div>
        <strong>Total Cost:</strong>
        <p style="font-size: 2rem; color: #0074d9;">${{ "%.2f"|format(costs.total_cost) }}</p>
      </div>
      <div>
        <strong>Total Traces:</strong>
        <p style="font-size: 2rem;">{{ costs.total_traces }}</p>
      </div>
      <div>
        <strong>Avg Cost/Trace:</strong>
        <p style="font-size: 2rem;">${{ "%.4f"|format(costs.total_cost / costs.total_traces if costs.total_traces > 0 else 0) }}</p>
      </div>
    </div>
  </section>
  
  <section>
    <h3>Cost by Phase</h3>
    <table>
      <thead>
        <tr><th>Phase</th><th>Cost (USD)</th><th>% of Total</th></tr>
      </thead>
      <tbody>
        {% for phase, cost in costs.by_phase.items() %}
        <tr>
          <td>{{ phase }}</td>
          <td>${{ "%.2f"|format(cost) }}</td>
          <td>{{ "%.1f"|format(100 * cost / costs.total_cost) }}%</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </section>
  
  <section>
    <h3>Cost by Model</h3>
    <table>
      <thead>
        <tr><th>Model</th><th>Cost (USD)</th><th>Avg Tokens</th></tr>
      </thead>
      <tbody>
        {% for model, cost in costs.by_model.items() %}
        <tr>
          <td>{{ model }}</td>
          <td>${{ "%.2f"|format(cost) }}</td>
          <td>{{ avg_tokens[model] }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </section>
</div>
{% endblock %}
"""
```

#### LLM-as-a-Judge Integration

Use MLflow to evaluate pipeline outputs:

```python
# scripts/evaluate_pipeline_quality.py
import mlflow
from lib.claude_scorer import create_claude_relevance_scorer

# Load traces from a pipeline run
experiment = mlflow.get_experiment_by_name("bug-completeness-20260416")
traces_df = mlflow.search_traces(experiment_ids=[experiment.experiment_id])

# Create evaluator
scorer = create_claude_relevance_scorer(model="claude-sonnet-4-6")

# Evaluate
result = mlflow.genai.evaluate(
    data=traces_df,
    scorers=[scorer]
)

# Results show quality scores for each trace
print(f"Average quality score: {result.metrics['claude_relevance/mean']}")
print(f"Quality scores: {result.result_df[['trace_id', 'claude_relevance']]}")
```

#### Metrics & Monitoring

Key metrics to track in MLflow:

**Performance Metrics:**
- `duration_seconds` - Agent execution time
- `input_tokens`, `output_tokens` - Token usage
- `cost_usd` - Cost per execution

**Quality Metrics:**
- `success_rate` - Percentage of successful completions
- `validation_pass_rate` - For fix-attempt phase
- `completeness_score` - Avg bug report quality
- `llm_judge_score` - Quality rating from evaluator

**Operational Metrics:**
- `job_queue_depth` - Number of pending K8s jobs
- `concurrent_jobs` - Active job count
- `workspace_disk_usage` - PVC utilization
- `error_rate` - Failed jobs / total jobs

**Cost Metrics:**
- `cost_per_issue` - Total cost divided by issues processed
- `cost_by_model` - Breakdown by model tier
- `cost_trend` - Daily/weekly spending

#### Dashboard Integration

Link pipeline dashboard to MLflow UI:

```python
# lib/webapp.py - issue detail page
@app.route("/issue/<key>")
def issue_detail(key):
    # ... existing code ...
    
    # Get MLflow traces for this issue
    traces = mlflow.search_traces(
        filter_string=f"inputs.issue_key = '{key}'"
    )
    
    mlflow_links = []
    for trace in traces.itertuples():
        phase = trace.inputs.get("phase")
        model = trace.inputs.get("model")
        trace_url = f"http://mlflow.local/#/traces/{trace.request_id}"
        
        mlflow_links.append({
            "phase": phase,
            "model": model,
            "url": trace_url,
            "cost": trace.attributes.get("cost_usd", 0),
            "duration": trace.attributes.get("duration_seconds", 0),
            "tokens": trace.attributes.get("total_tokens", 0)
        })
    
    return render_template_string(
        ISSUE_DETAIL,
        issue=issue_data,
        mlflow_traces=mlflow_links
    )
```

Add to issue detail template:

```html
<section>
  <h3>MLflow Traces</h3>
  <table>
    <thead>
      <tr>
        <th>Phase</th>
        <th>Model</th>
        <th>Tokens</th>
        <th>Cost</th>
        <th>Duration</th>
        <th>Link</th>
      </tr>
    </thead>
    <tbody>
      {% for trace in mlflow_traces %}
      <tr>
        <td>{{ trace.phase }}</td>
        <td>{{ trace.model }}</td>
        <td>{{ trace.tokens }}</td>
        <td>${{ "%.4f"|format(trace.cost) }}</td>
        <td>{{ trace.duration|round(1) }}s</td>
        <td><a href="{{ trace.url }}" target="_blank">View in MLflow →</a></td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

#### Benefits

✅ **Complete observability** - Every agent execution tracked  
✅ **Cost transparency** - Real-time cost tracking and forecasting  
✅ **Quality metrics** - Automated quality scoring via LLM judges  
✅ **Performance optimization** - Identify slow phases and optimize  
✅ **Debugging** - Full trace replay for failed jobs  
✅ **Compliance** - Audit trail of all AI interactions  
✅ **Experiment comparison** - A/B test different models/prompts  

#### Configuration

Jobs automatically log to MLflow via `MLFLOW_TRACKING_URI` environment variable (already configured in agent job spec):

```yaml
env:
- name: MLFLOW_TRACKING_URI
  value: http://mlflow.ai-pipeline.svc.cluster.local:5000
```

No additional configuration needed - just use MLflow's tracing APIs in `lib/agent_runner.py`.

### Jira Emulator
- Jobs can hit `jira-emulator.ai-pipeline.svc.cluster.local`
- Testing without production Jira access
- MCP server for enhanced Jira operations

### GitHub Emulator
- Jobs can clone from `github-emulator.ai-pipeline.svc.cluster.local`
- Test repo operations in isolated environment

## Next Steps

### Immediate (Week 1)
1. ✅ Write architecture document
2. ⏳ Create PVCs and populate storage
3. ⏳ Build agent container image
4. ⏳ Test single job execution
5. ⏳ Add MLflow tracing to `lib/agent_runner.py`
6. ⏳ Test trace logging with single job

### Short-term (Week 2-3)
1. Add K8s orchestrator to dashboard
2. Implement job submission APIs
3. Create Jobs UI page
4. Test batch operations
5. Add cost calculation function
6. Implement cost analytics endpoint
7. Create Cost Dashboard page
8. Link issue detail pages to MLflow traces

### Medium-term (Month 1)
1. Add job cleanup CronJob
2. Implement job prioritization
3. Add resource quotas
4. Set up monitoring dashboards (Grafana + MLflow metrics)
5. Implement experiment-based batch tracking
6. Add aggregate metrics logging
7. Create LLM-as-a-judge evaluation scripts
8. Set up quality scoring pipelines

### Long-term (Month 2+)
1. Multi-node cluster support (NFS)
2. Auto-scaling configuration
3. Advanced job scheduling (time-based, resource-aware)
4. Integration with CI/CD pipelines
5. Automated cost alerts and budgeting
6. Quality regression detection
7. A/B testing framework for model comparison
8. Prometheus metrics export from MLflow

## Conclusion

This architecture transforms the ai-first-pipeline from a local script into a **cloud-native, distributed system** with **comprehensive telemetry** while preserving the existing codebase and workflows. The dashboard becomes a central control plane for job orchestration, monitoring, and results visualization, while MLflow provides complete observability into every AI interaction.

Key advantages:
- **Incremental migration** - Can run local and K8s modes side-by-side
- **Minimal code changes** - Most logic in `lib/phases.py` unchanged
- **Reuse existing infrastructure** - Leverages K8s primitives (Jobs, PVCs, Secrets)
- **Operational improvements** - Better observability, reliability, and scalability
- **Complete telemetry** - Every agent execution tracked with prompts, responses, tokens, costs
- **Cost transparency** - Real-time tracking and forecasting of AI spending
- **Quality assurance** - Automated quality scoring and regression detection via LLM judges
- **Data-driven optimization** - Rich metrics enable continuous improvement of pipeline performance

The migration path is clear, with well-defined phases and testable milestones. We can validate each component independently before full integration. MLflow integration provides immediate value even before full K8s migration, as it can be added to the existing local setup.
