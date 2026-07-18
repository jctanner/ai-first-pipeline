"""Kubernetes orchestrator for pipeline jobs."""

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from pathlib import Path
import json
import re
from datetime import datetime

from src.dashboard.job_names import build_job_name


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
        runner: str = "cli",
        args: dict = None,
        fqn: str | None = None,
        harness: str = "claude-code",
    ) -> client.V1Job:
        """Create and submit a K8s Job for a pipeline phase.

        Args:
            phase: Phase name (e.g., "bug-completeness")
            issue_key: Jira issue key (e.g., "RHOAIENG-37036")
            model: Model shorthand ("opus", "sonnet", "haiku")
            runner: Runner type ("cli" or "sdk")
            args: Additional arguments (force, component, etc.)
            fqn: Optional URI-style FQN (host/owner/repo@ref:skill).
                 When provided, the container clones the repo at runtime
                 instead of using a pre-registered skill.
            harness: Agent harness ("claude-code" or "opencode")

        Returns:
            Created K8s Job object
        """
        if args is None:
            args = {}
        args = dict(args)
        args["extra_env"] = self._normalize_extra_env(args.get("extra_env"))
        job = self._create_job_manifest(phase, issue_key, model, runner, args, fqn=fqn, harness=harness)
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
        label_selector = None
        if phase:
            label_selector = f"phase={phase}"

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
            "category": job.metadata.labels.get("category", ""),
            "issue": job.metadata.labels.get("issue"),
            "model": (job.metadata.annotations or {}).get("model") or job.metadata.labels.get("model"),
            "runner": job.metadata.labels.get("runner", "cli"),
            "harness": job.metadata.labels.get("harness", "claude-code"),
            "force": job.metadata.labels.get("force", "false") == "true",
            "strace": job.metadata.labels.get("strace", "false") == "true",
            "mlflow": job.metadata.labels.get("mlflow", "true") == "true",
            "otel": job.metadata.labels.get("otel", "true") == "true",
            "api_dump": job.metadata.labels.get("api-dump", "true") == "true",
            "extra_kwargs": (job.metadata.annotations or {}).get("extra_kwargs", ""),
            "extra_env": json.loads((job.metadata.annotations or {}).get("extra_env", "{}")),
            "fqn": (job.metadata.annotations or {}).get("fqn", ""),
            "dataset_fqn": (job.metadata.annotations or {}).get("dataset_fqn", ""),
            "context_ref": (job.metadata.annotations or {}).get("context_ref", ""),
            "context_repo": (job.metadata.annotations or {}).get("context_repo", ""),
            "context_mode": (job.metadata.annotations or {}).get("context_mode", ""),
            "baseline": (job.metadata.annotations or {}).get("baseline", ""),
            "eval_harness": (job.metadata.annotations or {}).get("eval_harness", ""),
            "run_id": (job.metadata.annotations or {}).get("run_id", ""),
            "prompt": (job.metadata.annotations or {}).get("prompt", ""),
            "registries": (job.metadata.annotations or {}).get("registries", "[]"),
            "plugins": (job.metadata.annotations or {}).get("plugins", "[]"),
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

    def stop_job(self, job_name: str) -> bool:
        """Stop a running job by deleting it and its pods.

        Args:
            job_name: Name of the job to stop

        Returns:
            True if stopped, False if not found or already finished
        """
        try:
            job = self.batch_v1.read_namespaced_job(
                name=job_name,
                namespace=self.namespace
            )
        except ApiException as e:
            if e.status == 404:
                return False
            raise

        status = self._get_job_status(job)
        if status not in ("running", "pending"):
            return False

        return self.delete_job(job_name)

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

    SCRIPT_MAP = {
        ("claude-code", "cli"): "/app/scripts/run_skill.sh",
        ("claude-code", "sdk"): "/app/scripts/run_skill_sdk.sh",
        ("claude-code", "agentic-ci"): "/app/scripts/run_skill_agentic_ci.sh",
        ("opencode", "cli"): "/app/scripts/run_skill_opencode.sh",
        ("opencode", "sdk"): "/app/scripts/run_skill_opencode_sdk.sh",
        ("opencode", "agentic-ci"): "/app/scripts/run_skill_agentic_ci.sh",
    }

    def _create_job_manifest(
        self,
        phase: str,
        issue_key: str,
        model: str,
        runner: str,
        args: dict,
        fqn: str | None = None,
        harness: str = "claude-code",
    ) -> client.V1Job:
        """Generate a K8s Job manifest for a pipeline phase."""

        # Sanitize model for K8s naming: strip provider prefix and version, replace illegal chars
        model_short = model.split("/")[-1].split("@")[0]  # "google-vertex-anthropic/claude-haiku-4-5@20251001" -> "claude-haiku-4-5"
        model_slug = re.sub(r"[^a-z0-9-]", "-", model_short.lower()).strip("-")[:30]
        model_label = re.sub(r"[^A-Za-z0-9._-]", "_", model)[:63]

        job_name = build_job_name(phase, issue_key, model_slug)

        # Resolve fully-qualified skill name for MLflow experiment
        if fqn:
            skill_fqn = fqn
        else:
            try:
                from src.cli.skill_config import get_skill_fqn
                skill_fqn = get_skill_fqn(phase)
            except Exception:
                skill_fqn = phase

        # OpenCode CLI mode can't flush MLflow plugin traces (process.exit race).
        # Auto-upgrade to SDK runner when MLflow is enabled.
        if harness == "opencode" and runner == "cli" and args.get("mlflow") is not False:
            runner = "sdk"

        # Build command args - choose script based on harness + runner
        script = self.SCRIPT_MAP.get((harness, runner))
        if script is None:
            raise ValueError(f"Unsupported harness+runner: {harness}+{runner}")
        cmd_args = ["/bin/bash", script]

        prompt = args.get("prompt")
        if prompt:
            cmd_args.extend(["--prompt", prompt])
        elif fqn:
            cmd_args.extend(["--fqn", fqn])
        elif skill_fqn and skill_fqn.startswith(("github.com/", "gitlab.com/")):
            cmd_args.extend(["--fqn", skill_fqn])
        else:
            cmd_args.extend(["--skill", phase])
        if issue_key:
            cmd_args.extend(["--issue", issue_key])
        cmd_args.extend(["--model", model])

        if args.get("force"):
            cmd_args.append("--force")

        skill_load_mode = args.get("skill_load_mode", "auto")
        if skill_load_mode and skill_load_mode != "auto":
            cmd_args.extend(["--skill-load-mode", skill_load_mode])

        for kv in (args.get("extra_kwargs") or "").split():
            if "=" in kv:
                cmd_args.extend(["--extra-vars", kv])

        for reg in args.get("registries") or []:
            cmd_args.extend(["--registry", reg])

        for plugin in args.get("plugins") or []:
            cmd_args.extend(["--plugin", plugin])

        if args.get("no_plugin_dir"):
            cmd_args.append("--no-plugin-dir")

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=self.namespace,
                annotations={
                    "extra_kwargs": args.get("extra_kwargs") or "",
                    "extra_env": json.dumps(args.get("extra_env") or {}),
                    "fqn": fqn or "",
                    "model": model,
                    "skill_load_mode": skill_load_mode,
                    "prompt": (prompt or "")[:256],
                    "registries": json.dumps(args.get("registries") or []),
                    "plugins": json.dumps(args.get("plugins") or []),
                },
                labels={
                    "app": "pipeline-agent",
                    "phase": phase,
                    "issue": issue_key.lower() if issue_key else "all",
                    "model": model_label,
                    "runner": runner,
                    "harness": harness,
                    "force": "true" if args.get("force") else "false",
                    "strace": "true" if args.get("strace") else "false",
                    "mlflow": "false" if args.get("mlflow") is False else "true",
                    "otel": "false" if args.get("otel") is False else "true",
                    "api-dump": "false" if args.get("api_dump") is False else "true",
                }
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=86400,  # Clean up after 24hrs
                backoff_limit=0,  # Don't retry failed jobs
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app": "pipeline-agent",
                            "phase": phase,
                            "issue": issue_key.lower() if issue_key else "all"
                        }
                    ),
                    spec=client.V1PodSpec(
                        restart_policy="Never",

                        security_context=client.V1PodSecurityContext(
                            fs_group=1000,
                        ),

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

                                env=self._build_env_vars(args, job_name=job_name, skill_fqn=skill_fqn, harness=harness, model=model, runner=runner),
                                volume_mounts=self._build_volume_mounts(),

                                resources=client.V1ResourceRequirements(
                                    requests={"memory": "2Gi", "cpu": "500m"},
                                    limits={"memory": "8Gi", "cpu": "2000m"}
                                ),
                                security_context=client.V1SecurityContext(
                                    capabilities=client.V1Capabilities(add=["SYS_PTRACE"])
                                ) if args.get("strace") else None
                            )
                        ],

                        volumes=self._build_volumes()
                    )
                )
            )
        )

        return job

    def _build_env_vars(self, args: dict = None, job_name: str = "", skill_fqn: str = "", harness: str = "claude-code", model: str = "", runner: str = "cli") -> list:
        """Build environment variables for agent containers."""
        if args is None:
            args = {}

        env_vars = [
            client.V1EnvVar(name="PIPELINE_JOB_NAME", value=job_name),
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
        ]

        if args.get("mlflow") is not False:
            env_vars.append(client.V1EnvVar(
                name="MLFLOW_TRACKING_URI",
                value="http://mlflow.ai-pipeline.svc.cluster.local:5000"
            ))
            if skill_fqn:
                model_short = model.split("/")[-1].split("@")[0] if model else "unknown"
                experiment = f"{skill_fqn}/{harness}/{model_short}/{runner}"
                env_vars.append(client.V1EnvVar(
                    name="MLFLOW_EXPERIMENT_NAME",
                    value=experiment
                ))

        if args.get("otel") is not False:
            env_vars.append(client.V1EnvVar(
                name="ENABLE_OTEL",
                value="1"
            ))

        if args.get("strace"):
            env_vars.append(client.V1EnvVar(
                name="ENABLE_STRACE",
                value="1"
            ))

        if args.get("api_dump") is not False:
            env_vars.append(client.V1EnvVar(
                name="ANTHROPIC_LOG",
                value=f"/app/artifacts/apibodies/{job_name}"
            ))

        env_vars.append(client.V1EnvVar(
            name="AGENTIC_CI_HARNESS",
            value=harness
        ))

        extra_env = self._normalize_extra_env(args.get("extra_env"))
        for k, v in extra_env.items():
            env_vars.append(client.V1EnvVar(name=k, value=v))

        return env_vars

    @staticmethod
    def _normalize_extra_env(extra_env) -> dict:
        """Accept extra_env as an object or JSON object string (possibly multi-wrapped)."""
        if extra_env in (None, ""):
            return {}
        for _ in range(5):
            if not isinstance(extra_env, str):
                break
            try:
                extra_env = json.loads(extra_env)
            except json.JSONDecodeError as exc:
                raise ValueError("extra_env must be a JSON object string") from exc
        if not isinstance(extra_env, dict):
            raise ValueError("extra_env must be an object")

        normalized = {}
        for key, value in extra_env.items():
            if not isinstance(key, str) or not key:
                raise ValueError("extra_env keys must be non-empty strings")
            normalized[key] = "" if value is None else str(value)
        return normalized

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

    CLEANUP_VOLUME_DEFS = {
        "issues": ("pipeline-issues", "/data/issues", "/data/issues"),
        "workspace": ("pipeline-workspace", "/data/workspace", "/data/workspace"),
        "logs": ("pipeline-logs", "/data/logs", "/data/logs"),
        "artifacts": ("pipeline-artifacts", "/data/artifacts", "/data/artifacts"),
        "context": ("pipeline-context", "/data/context", "/data/context"),
        "job-logs": ("pipeline-artifacts", "/data/artifacts", "/data/artifacts/jobs"),
        "strace": ("pipeline-artifacts", "/data/artifacts", "/data/artifacts/strace"),
        "apibodies": ("pipeline-artifacts", "/data/artifacts", "/data/artifacts/apibodies"),
    }

    def submit_cleanup_job(self, volumes: list[str]) -> client.V1Job:
        """Submit a K8s Job to clear contents of shared data volumes.

        Returns the created K8s Job object.
        """
        pvc_mounts = {}
        clear_paths = []
        unknown = []

        for vol in volumes:
            defn = self.CLEANUP_VOLUME_DEFS.get(vol)
            if not defn:
                unknown.append(vol)
                continue
            pvc_name, mount_path, clear_path = defn
            pvc_mounts[pvc_name] = mount_path
            clear_paths.append(clear_path)

        if unknown:
            raise ValueError(f"Unknown volumes: {', '.join(unknown)}")

        rm_lines = []
        for path in clear_paths:
            rm_lines.append(f'echo "Clearing {path}"')
            rm_lines.append(f'rm -rf {path}/*')
        rm_lines.append('echo "Cleanup complete"')
        script = "\n".join(rm_lines)

        timestamp = datetime.now().strftime("%m%d-%H%M%S")
        job_name = f"cleanup-volumes-{timestamp}"

        volume_mounts = []
        k8s_volumes = []
        for pvc_name, mount_path in pvc_mounts.items():
            vol_name = pvc_name.replace("pipeline-", "")
            volume_mounts.append(client.V1VolumeMount(
                name=vol_name,
                mount_path=mount_path,
            ))
            k8s_volumes.append(client.V1Volume(
                name=vol_name,
                persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                    claim_name=pvc_name,
                ),
            ))

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=self.namespace,
                labels={
                    "app": "pipeline-cleanup",
                    "category": "cleanup",
                },
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=3600,
                backoff_limit=0,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app": "pipeline-cleanup",
                            "category": "cleanup",
                        },
                    ),
                    spec=client.V1PodSpec(
                        restart_policy="Never",
                        affinity=client.V1Affinity(
                            pod_affinity=client.V1PodAffinity(
                                required_during_scheduling_ignored_during_execution=[
                                    client.V1PodAffinityTerm(
                                        label_selector=client.V1LabelSelector(
                                            match_labels={"app": "pipeline-dashboard"}
                                        ),
                                        topology_key="kubernetes.io/hostname",
                                    )
                                ]
                            )
                        ),
                        containers=[
                            client.V1Container(
                                name="cleanup",
                                image="alpine:3.19",
                                command=["sh", "-c", script],
                                volume_mounts=volume_mounts,
                            ),
                        ],
                        volumes=k8s_volumes,
                    ),
                ),
            ),
        )

        return self.batch_v1.create_namespaced_job(
            namespace=self.namespace,
            body=job,
        )

    def submit_eval_job(
        self,
        dataset_fqn: str,
        model: str,
        context_repo: str = "https://github.com/opendatahub-io/architecture-context",
        context_ref: str = "main",
        context_mode: str = "files",
        baseline: str = "",
        eval_harness: str = "https://github.com/opendatahub-io/agent-eval-harness",
        args: dict = None,
    ) -> client.V1Job:
        """Submit a K8s Job for an eval-harness run."""
        if args is None:
            args = {}
        job = self._create_eval_job_manifest(
            dataset_fqn, model, context_repo, context_ref, context_mode, baseline, eval_harness, args
        )
        return self.batch_v1.create_namespaced_job(
            namespace=self.namespace,
            body=job,
        )

    def list_eval_jobs(self) -> list:
        """List eval jobs (category=eval label)."""
        jobs = self.batch_v1.list_namespaced_job(
            namespace=self.namespace,
            label_selector="app=pipeline-agent,category=eval",
        )
        return jobs.items

    def _create_eval_job_manifest(
        self,
        dataset_fqn: str,
        model: str,
        context_repo: str,
        context_ref: str,
        context_mode: str,
        baseline: str,
        eval_harness: str,
        args: dict,
    ) -> client.V1Job:
        """Generate a K8s Job manifest for an eval-harness run."""
        import re

        eval_config = dataset_fqn.rsplit(":", 1)[-1] if ":" in dataset_fqn else "eval"
        model_short = model.split("/")[-1].split("@")[0]
        model_slug = re.sub(r"[^a-z0-9-]", "-", model_short.lower()).strip("-")[:30]
        model_label = re.sub(r"[^A-Za-z0-9._-]", "_", model)[:63]

        timestamp = datetime.now().strftime("%m%d-%H%M%S")
        job_name = f"eval-{eval_config}-{model_slug}-{timestamp}".lower().replace("_", "-")
        run_id = f"{datetime.now().strftime('%Y-%m-%d')}-{model_short}-{timestamp}"

        skill_fqn = dataset_fqn

        cmd_args = [
            "/bin/bash", "/app/scripts/run_eval.sh",
            "--dataset-fqn", dataset_fqn,
            "--model", model,
            "--context-repo", context_repo,
            "--context-ref", context_ref,
            "--context-mode", context_mode,
            "--eval-harness", eval_harness,
            "--run-id", run_id,
        ]
        if baseline:
            cmd_args.extend(["--baseline", baseline])

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=self.namespace,
                annotations={
                    "dataset_fqn": dataset_fqn,
                    "model": model,
                    "context_repo": context_repo,
                    "context_ref": context_ref,
                    "context_mode": context_mode,
                    "baseline": baseline or "",
                    "eval_harness": eval_harness,
                    "run_id": run_id,
                },
                labels={
                    "app": "pipeline-agent",
                    "category": "eval",
                    "eval-config": re.sub(r"[^A-Za-z0-9._-]", "_", eval_config)[:63],
                    "model": model_label,
                    "context-mode": context_mode,
                    "strace": "true" if args.get("strace") else "false",
                    "mlflow": "false" if args.get("mlflow") is False else "true",
                    "otel": "false" if args.get("otel") is False else "true",
                    "api-dump": "false" if args.get("api_dump") is False else "true",
                },
            ),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=86400,
                backoff_limit=0,
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(
                        labels={
                            "app": "pipeline-agent",
                            "category": "eval",
                            "eval-config": re.sub(r"[^A-Za-z0-9._-]", "_", eval_config)[:63],
                        }
                    ),
                    spec=client.V1PodSpec(
                        restart_policy="Never",
                        security_context=client.V1PodSecurityContext(
                            fs_group=1000,
                        ),
                        affinity=client.V1Affinity(
                            pod_affinity=client.V1PodAffinity(
                                required_during_scheduling_ignored_during_execution=[
                                    client.V1PodAffinityTerm(
                                        label_selector=client.V1LabelSelector(
                                            match_labels={"app": "pipeline-dashboard"}
                                        ),
                                        topology_key="kubernetes.io/hostname",
                                    )
                                ]
                            )
                        ),
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
                                        read_only=True,
                                    ),
                                    client.V1VolumeMount(
                                        name="shared-ca",
                                        mount_path="/shared",
                                    ),
                                ],
                            )
                        ],
                        containers=[
                            client.V1Container(
                                name="agent",
                                image="pipeline-agent:latest",
                                image_pull_policy="Never",
                                command=cmd_args,
                                env=self._build_env_vars(
                                    args,
                                    job_name=job_name,
                                    skill_fqn=skill_fqn,
                                    harness="claude-code",
                                    model=model,
                                    runner="cli",
                                ),
                                volume_mounts=self._build_volume_mounts(),
                                resources=client.V1ResourceRequirements(
                                    requests={"memory": "2Gi", "cpu": "500m"},
                                    limits={"memory": "8Gi", "cpu": "2000m"},
                                ),
                                security_context=client.V1SecurityContext(
                                    capabilities=client.V1Capabilities(add=["SYS_PTRACE"])
                                )
                                if args.get("strace")
                                else None,
                            )
                        ],
                        volumes=self._build_volumes(),
                    ),
                ),
            ),
        )

        return job

    _MLFLOW_HARD_DELETE_SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "mlflow_hard_delete.py"

    def exec_mlflow_hard_delete(self) -> dict:
        """Hard-delete all MLflow data by exec-ing a cleanup script into the MLflow pod."""
        from kubernetes.stream import stream as k8s_stream

        pods = self.core_v1.list_namespaced_pod(
            namespace=self.namespace,
            label_selector="app=mlflow",
            field_selector="status.phase=Running",
        )
        running = [p for p in pods.items if p.status.phase == "Running"]
        if not running:
            raise RuntimeError("No running MLflow pod found (label app=mlflow)")
        if len(running) > 1:
            raise RuntimeError(f"Expected 1 MLflow pod, found {len(running)}")

        pod_name = running[0].metadata.name

        script = self._MLFLOW_HARD_DELETE_SCRIPT_PATH.read_text()

        ws = k8s_stream(
            self.core_v1.connect_get_namespaced_pod_exec,
            pod_name,
            self.namespace,
            command=["python3", "-c", script],
            container="mlflow",
            stderr=True,
            stdout=True,
            stdin=False,
            tty=False,
            _preload_content=False,
        )
        ws.run_forever(timeout=60)
        stdout = ws.read_stdout()
        stderr = ws.read_stderr()
        ws.close()

        try:
            result = json.loads(stdout)
        except (json.JSONDecodeError, TypeError):
            raise RuntimeError(
                f"Unexpected output from cleanup script: {stdout}"
                + (f"\nstderr: {stderr}" if stderr else "")
            )

        if result.get("error"):
            raise RuntimeError(result["error"])
        if result.get("db_errors"):
            raise RuntimeError(
                f"DB cleanup failed (rolled back): {'; '.join(result['db_errors'])}"
            )
        if result.get("artifact_errors"):
            result["warning"] = (
                "DB cleanup committed but artifact deletion had errors"
            )

        return result

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
