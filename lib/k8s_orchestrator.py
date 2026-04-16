"""Kubernetes orchestrator for pipeline jobs."""

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from pathlib import Path
import os
from datetime import datetime


class PipelineOrchestrator:
    """Manages K8s jobs for pipeline phases."""

    def __init__(self):
        """Initialize K8s client."""
        try:
            # Try in-cluster config first (when running in K8s)
            config.load_incluster_config()
            self.in_cluster = True
        except config.ConfigException:
            # Fallback to kubeconfig (for local testing)
            config.load_kube_config()
            self.in_cluster = False

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
        """Create and submit a K8s Job for a pipeline phase.

        Args:
            phase: Phase name (e.g., "bug-completeness")
            issue_key: Jira issue key (e.g., "RHOAIENG-37036")
            model: Model shorthand ("opus", "sonnet", "haiku")
            args: Additional arguments (force, component, etc.)

        Returns:
            Created K8s Job object
        """
        job = self._create_job_manifest(phase, issue_key, model, args)
        return self.batch_v1.create_namespaced_job(
            namespace=self.namespace,
            body=job
        )

    def list_jobs(self, phase=None, status=None) -> list:
        """List pipeline jobs with optional filters.

        Args:
            phase: Filter by phase name
            status: Filter by status (pending|running|completed|failed)

        Returns:
            List of K8s Job objects
        """
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
        """Get detailed status of a job.

        Args:
            job_name: Name of the job

        Returns:
            Dict with job status details
        """
        try:
            job = self.batch_v1.read_namespaced_job(
                name=job_name,
                namespace=self.namespace
            )
        except ApiException as e:
            if e.status == 404:
                return {"error": "Job not found"}
            raise

        status = self._get_job_status(job)

        return {
            "name": job.metadata.name,
            "status": status,
            "created": job.metadata.creation_timestamp.isoformat() if job.metadata.creation_timestamp else None,
            "started": job.status.start_time.isoformat() if job.status.start_time else None,
            "completed": job.status.completion_time.isoformat() if job.status.completion_time else None,
            "succeeded": job.status.succeeded or 0,
            "failed": job.status.failed or 0,
            "phase": job.metadata.labels.get("phase"),
            "issue": job.metadata.labels.get("issue"),
            "model": job.metadata.labels.get("model")
        }

    def get_job_logs(self, job_name: str) -> str:
        """Get logs from a job's pod.

        Args:
            job_name: Name of the job

        Returns:
            Log output as string, or None if not available
        """
        # Find pod for this job
        try:
            pods = self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"job-name={job_name}"
            )
        except ApiException:
            return None

        if not pods.items:
            return None

        pod_name = pods.items[0].metadata.name

        try:
            return self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace
            )
        except ApiException:
            return None

    def delete_job(self, job_name: str) -> bool:
        """Delete a job and its pods.

        Args:
            job_name: Name of the job to delete

        Returns:
            True if deleted, False if not found
        """
        try:
            self.batch_v1.delete_namespaced_job(
                name=job_name,
                namespace=self.namespace,
                propagation_policy='Background'
            )
            return True
        except ApiException as e:
            if e.status == 404:
                return False
            raise

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
        # Add timestamp to ensure uniqueness
        timestamp = datetime.now().strftime("%m%d-%H%M%S")
        job_name = f"{job_name}-{timestamp}"

        # Build command args - use bash wrapper to install skills and run via Claude CLI
        cmd_args = ["/bin/bash", "/app/scripts/run_skill.sh"]
        cmd_args.extend(["--skill", phase])
        cmd_args.extend(["--issue", issue_key])
        cmd_args.extend(["--model", model])

        if args.get("force"):
            cmd_args.append("--force")

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

                        # Init containers
                        init_containers=[
                            client.V1Container(
                                name="update-ca-trust",
                                image="alpine:3.19",
                                command=["sh", "-c"],
                                args=[
                                    """set -ex

apk add --no-cache ca-certificates

if [ -f /tmp/ca-cert/ca.crt ]; then
  mkdir -p /usr/local/share/ca-certificates
  cp /tmp/ca-cert/ca.crt /usr/local/share/ca-certificates/internal-ca.crt
  update-ca-certificates
  cp /etc/ssl/certs/ca-certificates.crt /shared/ca-certificates.crt
  echo "CA trust store updated successfully"
else
  echo "No CA cert found, skipping"
  cp /etc/ssl/certs/ca-certificates.crt /shared/ca-certificates.crt || touch /shared/ca-certificates.crt
fi
"""
                                ],
                                volume_mounts=[
                                    client.V1VolumeMount(
                                        name="ca-cert",
                                        mount_path="/tmp/ca-cert",
                                        read_only=True
                                    ),
                                    client.V1VolumeMount(
                                        name="shared-ca",
                                        mount_path="/shared"
                                    )
                                ]
                            )
                        ],

                        containers=[
                            client.V1Container(
                                name="agent",
                                image="pipeline-agent:latest",
                                image_pull_policy="Never",  # Use local image
                                command=cmd_args,

                                env=self._build_env_vars(),
                                volume_mounts=self._build_volume_mounts(),

                                resources=client.V1ResourceRequirements(
                                    requests={"memory": "2Gi", "cpu": "500m"},
                                    limits={"memory": "8Gi", "cpu": "2000m"}
                                )
                            )
                        ],

                        volumes=self._build_volumes()
                    )
                )
            )
        )

        return job

    def _build_env_vars(self) -> list:
        """Build environment variables for agent containers."""
        return [
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
            # MCP server URL (optional)
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
                value="/home/pipelineagent/.config/gcloud/credentials.json"
            ),
            # MLflow tracking
            client.V1EnvVar(
                name="MLFLOW_TRACKING_URI",
                value="http://mlflow.ai-pipeline.svc.cluster.local:5000"
            )
        ]

    def _build_volume_mounts(self) -> list:
        """Build volume mounts for agent containers."""
        return [
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
                name="artifacts",
                mount_path="/app/artifacts"
            ),
            client.V1VolumeMount(
                name="context",
                mount_path="/app/.context"
            ),
            client.V1VolumeMount(
                name="gcp-credentials",
                mount_path="/home/pipelineagent/.config/gcloud",
                read_only=True
            ),
            client.V1VolumeMount(
                name="shared-ca",
                mount_path="/shared",
                read_only=True
            )
        ]

    def _build_volumes(self) -> list:
        """Build volumes for agent containers."""
        return [
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
                name="artifacts",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name="pipeline-artifacts"
                )
            ),
            client.V1Volume(
                name="context",
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name="pipeline-context"
                )
            ),
            client.V1Volume(
                name="gcp-credentials",
                secret=client.V1SecretVolumeSource(
                    secret_name="gcp-credentials",
                    optional=False
                )
            ),
            client.V1Volume(
                name="ca-cert",
                config_map=client.V1ConfigMapVolumeSource(
                    name="internal-ca-cert",
                    optional=True
                )
            ),
            client.V1Volume(
                name="shared-ca",
                empty_dir=client.V1EmptyDirVolumeSource()
            )
        ]

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
