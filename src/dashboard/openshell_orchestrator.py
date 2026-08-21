"""OpenShell-backed execution for dashboard pipeline jobs.

This module deliberately keeps OpenShell optional. Kubernetes Jobs remain the
default backend, while this class provides the first dashboard integration
path for comparing a sandboxed run with the existing direct-Kubernetes path.
"""

from __future__ import annotations

import json
import os
import shlex
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.protobuf.struct_pb2 import Struct
import grpc

from src.dashboard.k8s_orchestrator import PipelineOrchestrator

try:
    from openshell import SandboxClient, WorkspaceClient
    from openshell._proto import openshell_pb2, sandbox_pb2

    OPEN_SHELL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by local installs without SDK
    SandboxClient = None
    WorkspaceClient = None
    openshell_pb2 = None
    sandbox_pb2 = None
    OPEN_SHELL_AVAILABLE = False


class OpenShellOrchestrator:
    """Submit and monitor pipeline commands in OpenShell sandboxes."""

    WORKSPACE = os.environ.get("OPENSHELL_WORKSPACE", "breadboard")
    ENDPOINT = os.environ.get(
        "OPENSHELL_GATEWAY_ENDPOINT",
        "openshell.openshell-system.svc.cluster.local:8080",
    )
    ARTIFACTS_ROOT = Path(os.environ.get("PIPELINE_ARTIFACTS_DIR", "/app/artifacts"))
    _executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="openshell-job")
    _lock = threading.Lock()
    _jobs: dict[str, dict[str, Any]] = {}

    def __init__(self) -> None:
        if not OPEN_SHELL_AVAILABLE:
            raise RuntimeError("OpenShell Python SDK is not available")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _job_name() -> str:
        return f"bb-os-{uuid.uuid4().hex[:10]}"

    @staticmethod
    def _model_short(model: str) -> str:
        return model.split("/")[-1].split("@")[0]

    def _skill_fqn(self, phase: str, fqn: str | None) -> str:
        if fqn:
            return fqn
        try:
            from src.cli.skill_config import get_skill_fqn

            return get_skill_fqn(phase)
        except Exception:
            return phase

    def _command(
        self,
        phase: str,
        issue_key: str,
        model: str,
        runner: str,
        args: dict,
        fqn: str | None,
        harness: str,
    ) -> tuple[list[str], str]:
        if harness == "opencode" and runner == "cli" and args.get("mlflow") is not False:
            runner = "sdk"
        script = PipelineOrchestrator.SCRIPT_MAP.get((harness, runner))
        if script is None:
            raise ValueError(f"Unsupported harness+runner: {harness}+{runner}")

        skill_fqn = self._skill_fqn(phase, fqn)
        command = ["/bin/bash", script]
        prompt = args.get("prompt")
        if prompt:
            command.extend(["--prompt", prompt])
        elif fqn:
            command.extend(["--fqn", fqn])
        elif skill_fqn.startswith(("github.com/", "gitlab.com/")):
            command.extend(["--fqn", skill_fqn])
        else:
            command.extend(["--skill", phase])
        if issue_key:
            command.extend(["--issue", issue_key])
        command.extend(["--model", model])
        if args.get("force"):
            command.append("--force")
        skill_load_mode = args.get("skill_load_mode", "auto")
        if skill_load_mode and skill_load_mode != "auto":
            command.extend(["--skill-load-mode", skill_load_mode])
        for item in (args.get("extra_kwargs") or "").split():
            if "=" in item:
                command.extend(["--extra-vars", item])
        for registry in args.get("registries") or []:
            command.extend(["--registry", registry])
        for plugin in args.get("plugins") or []:
            command.extend(["--plugin", plugin])
        if args.get("no_plugin_dir"):
            command.append("--no-plugin-dir")
        if args.get("swap_enabled_order"):
            command.append("--swap-enabled-order")
        if args.get("swap_installed_order"):
            command.append("--swap-installed-order")
        return command, skill_fqn

    def _environment(
        self,
        args: dict,
        job_name: str,
        skill_fqn: str,
        model: str,
        runner: str,
        harness: str,
    ) -> dict[str, str]:
        names = (
            "CLAUDE_CODE_USE_VERTEX",
            "CLOUD_ML_REGION",
            "ANTHROPIC_VERTEX_PROJECT_ID",
            "JIRA_SERVER",
            "JIRA_USER",
            "JIRA_TOKEN",
            "ATLASSIAN_MCP_URL",
        )
        environment = {name: os.environ[name] for name in names if os.environ.get(name) is not None}
        environment.update(
            {
                # OpenShell runs the command inside its /sandbox workspace.
                # Set these explicitly instead of relying on the sandbox
                # launcher to synthesize a home directory; Claude and the
                # Google SDK both persist configuration under these paths.
                "HOME": "/sandbox",
                "USER": "pipelineagent",
                "LOGNAME": "pipelineagent",
                "XDG_CONFIG_HOME": "/sandbox/.config",
                "PIPELINE_JOB_NAME": job_name,
                # Keep the wrapper log inside the sandbox; the dashboard
                # collects the command result into the shared job log after
                # execution. This avoids cross-UID writes to that file.
                "PIPELINE_LOG_FILE": f"/tmp/{job_name}.log",
                "GOOGLE_APPLICATION_CREDENTIALS": "/sandbox/.config/gcloud/credentials.json",
                "AGENTIC_CI_HARNESS": harness,
                # OpenShell supplies a minimal PATH; retain the pipeline
                # virtualenv so wrapper scripts resolve PyYAML and friends.
                "PATH": "/app/.venv/bin:/usr/local/bin:/usr/bin:/bin",
            }
        )
        if args.get("mlflow") is not False:
            environment["MLFLOW_CLAUDE_HOME"] = "/sandbox"
            environment["MLFLOW_TRACKING_URI"] = "http://mlflow.ai-pipeline.svc.cluster.local:5000"
            environment["MLFLOW_EXPERIMENT_NAME"] = (
                f"{skill_fqn}/{harness}/{self._model_short(model)}/{runner}"
            )
        if args.get("otel") is not False:
            environment["ENABLE_OTEL"] = "1"
        else:
            # The wrappers default telemetry on when the variable is absent.
            environment["ENABLE_OTEL"] = "0"
        if args.get("strace"):
            environment["ENABLE_STRACE"] = "1"
        if args.get("api_dump") is not False:
            environment["ANTHROPIC_LOG"] = f"/app/artifacts/apibodies/{job_name}"
        environment.update(PipelineOrchestrator._normalize_extra_env(args.get("extra_env")))
        return environment

    @staticmethod
    def _driver_config() -> Struct:
        """Mount the existing pipeline PVCs in the sandbox agent container."""
        config = Struct()
        config.update(
            {
                "kubernetes": {
                    "volumes": [
                        {
                            "name": name,
                            "persistent_volume_claim": {
                                "claim_name": claim,
                                "read_only": False,
                            },
                        }
                        for name, claim in (
                            ("bb-issues", "pipeline-issues"),
                            ("bb-workspace", "pipeline-workspace"),
                            ("bb-logs", "pipeline-logs"),
                            ("bb-artifacts", "pipeline-artifacts"),
                            ("bb-context", "pipeline-context"),
                        )
                    ],
                    "containers": {
                        "agent": {
                            "volume_mounts": [
                                {
                                    "name": name,
                                    "mount_path": mount,
                                    "read_only": False,
                                }
                                for name, mount in (
                                    ("bb-issues", "/app/issues"),
                                    ("bb-workspace", "/app/workspace"),
                                    ("bb-logs", "/app/logs"),
                                    ("bb-artifacts", "/app/artifacts"),
                                    ("bb-context", "/app/.context"),
                                )
                            ]
                        }
                    },
                }
            }
        )
        return config

    def _spec(self, environment: dict[str, str]) -> Any:
        template = openshell_pb2.SandboxTemplate(
            image="pipeline-agent:latest",
            driver_config=self._driver_config(),
        )
        policy = sandbox_pb2.SandboxPolicy(
            version=1,
            filesystem=sandbox_pb2.FilesystemPolicy(
                include_workdir=True,
                read_only=["/usr", "/lib", "/proc", "/dev/urandom", "/app", "/etc", "/var/log"],
                read_write=["/sandbox", "/tmp", "/dev/null"],
            ),
            landlock=sandbox_pb2.LandlockPolicy(compatibility="best_effort"),
        )

        # OpenShell starts with deny-by-default egress. These are the only
        # destinations required by the pipeline-agent job: Google OAuth and
        # Vertex for Claude, plus the isolated in-cluster services used by
        # skills and telemetry. Keep the policy host-scoped and port-scoped;
        # all other destinations remain denied.
        google_endpoints = (
            "oauth2.googleapis.com",
            "aiplatform.googleapis.com",
            "us-east5-aiplatform.googleapis.com",
        )
        internal_endpoints = ("**.ai-pipeline.svc.cluster.local",)
        network_binaries = (
            "/usr/local/bin/claude",
            "/usr/bin/node",
            "/usr/local/bin/python3",
            "/usr/local/bin/python",
            "/usr/bin/curl",
            "/usr/bin/git",
            "/usr/lib/git-core/git-remote-https",
        )
        for policy_name, hosts, ports in (
            ("google-ai", google_endpoints, (443,)),
            ("pipeline-services", internal_endpoints, (80, 443, 5000, 8000, 8080, 8081)),
        ):
            rule = policy.network_policies[policy_name]
            rule.name = policy_name
            for path in network_binaries:
                rule.binaries.add(path=path)
            for host in hosts:
                endpoint = rule.endpoints.add(
                    host=host,
                    protocol="rest",
                    enforcement="enforce",
                    access="full",
                )
                endpoint.ports.extend(ports)

        return openshell_pb2.SandboxSpec(
            environment=environment,
            template=template,
            policy=policy,
        )

    def _metadata_path(self, name: str) -> Path:
        return self.ARTIFACTS_ROOT / "jobs" / f"{name}.json"

    def _write_metadata(self, metadata: dict[str, Any]) -> None:
        path = self._metadata_path(metadata["name"])
        path.parent.mkdir(parents=True, exist_ok=True)
        # The in-memory record also carries the command and environment sent
        # to the sandbox. Never persist those: the environment includes Jira,
        # Vertex, and other credentials.
        public = {
            key: value
            for key, value in metadata.items()
            if key not in {"command", "environment"}
        }
        path.write_text(json.dumps(public, indent=2) + "\n")

    def submit_phase_job(
        self,
        phase: str,
        issue_key: str,
        model: str,
        runner: str = "cli",
        args: dict | None = None,
        fqn: str | None = None,
        harness: str = "claude-code",
    ) -> dict[str, Any]:
        args = dict(args or {})
        args["extra_env"] = PipelineOrchestrator._normalize_extra_env(args.get("extra_env"))
        # OpenShell intentionally starts with a restricted network policy. Do
        # not make every sandbox clone the public default marketplace unless
        # the caller explicitly opts back in.
        args.setdefault("no_plugin_dir", True)
        name = self._job_name()
        command, skill_fqn = self._command(phase, issue_key, model, runner, args, fqn, harness)
        environment = self._environment(args, name, skill_fqn, model, runner, harness)
        metadata = {
            "name": name,
            "phase": phase,
            "issue": issue_key.lower() if issue_key else "all",
            "model": model,
            "runner": runner,
            "harness": harness,
            "status": "pending",
            "created": self._now(),
            "started": None,
            "completed": None,
            "exit_code": None,
            "force": bool(args.get("force")),
            "strace": bool(args.get("strace")),
            "mlflow": args.get("mlflow") is not False,
            "otel": args.get("otel") is not False,
            "api_dump": args.get("api_dump") is not False,
            "extra_kwargs": args.get("extra_kwargs") or "",
            "extra_env": args["extra_env"],
            "fqn": fqn or "",
            "prompt": args.get("prompt", ""),
            "registries": args.get("registries") or [],
            "plugins": args.get("plugins") or [],
        }
        with self._lock:
            self._jobs[name] = {**metadata, "command": command, "environment": environment}
        self._write_metadata(metadata)
        self._executor.submit(self._run, name, command, environment)
        return metadata

    def _run(self, name: str, command: list[str], environment: dict[str, str]) -> None:
        # The dashboard and sandbox processes use different UIDs while
        # sharing these PVCs. Ensure per-run artifact roots are writable by
        # both before the sandbox starts.
        for directory in (
            self.ARTIFACTS_ROOT / "jobs",
            self.ARTIFACTS_ROOT / "apibodies",
            self.ARTIFACTS_ROOT / "strace",
        ):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o777)
        with self._lock:
            metadata = self._jobs[name]
            metadata["status"] = "running"
            metadata["started"] = self._now()
            self._write_metadata(metadata)
        client = SandboxClient(self.ENDPOINT, tls=None, timeout=30.0)
        try:
            workspace_client = WorkspaceClient.from_sandbox_client(client)
            try:
                workspace_client.get(self.WORKSPACE)
            except grpc.RpcError as exc:
                # A fresh emulator/cluster has no workspaces. Create the
                # dashboard-owned one lazily on the first submitted job.
                if exc.code() != grpc.StatusCode.NOT_FOUND:
                    raise
                workspace_client.create(
                    self.WORKSPACE,
                    labels={"breadboard.io/managed": "true"},
                )
            labels = {"breadboard.io/managed": "true", "breadboard.io/job": name}
            sandbox = client.create(
                workspace=self.WORKSPACE,
                spec=self._spec(environment),
                name=name,
                labels=labels,
            )
            with self._lock:
                self._jobs[name]["sandbox_id"] = sandbox.id
                self._write_metadata(self._jobs[name])
            client.wait_ready(name, workspace=self.WORKSPACE, timeout_seconds=300)

            credentials_path = os.environ.get(
                "GOOGLE_APPLICATION_CREDENTIALS",
                "/home/pipelineagent/.config/gcloud/credentials.json",
            )
            if Path(credentials_path).is_file():
                sandbox_credentials = environment["GOOGLE_APPLICATION_CREDENTIALS"]
                copy_result = client.exec(
                    sandbox.id,
                    [
                        "/bin/bash",
                        "-lc",
                        "mkdir -p {directory} && cat > {path} && chmod 600 {path}".format(
                            directory=shlex.quote(str(Path(sandbox_credentials).parent)),
                            path=shlex.quote(sandbox_credentials),
                        ),
                    ],
                    stdin=Path(credentials_path).read_bytes(),
                    timeout_seconds=30,
                )
                if copy_result.exit_code != 0:
                    raise RuntimeError(
                        "OpenShell could not copy the Vertex credential into the sandbox: "
                        f"{copy_result.stderr or copy_result.stdout}"
                    )
                verify_result = client.exec(
                    sandbox.id,
                    ["/bin/bash", "-lc", f"test -s {shlex.quote(sandbox_credentials)}"],
                    timeout_seconds=30,
                )
                if verify_result.exit_code != 0:
                    raise RuntimeError(
                        "OpenShell credential copy completed without a readable credential file "
                        f"at {sandbox_credentials}"
                    )
            elif environment.get("CLAUDE_CODE_USE_VERTEX") == "1":
                raise RuntimeError(
                    "Vertex is enabled but the dashboard credential file is unavailable: "
                    f"{credentials_path}"
                )

            log_path = self.ARTIFACTS_ROOT / "jobs" / f"{name}.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("wb") as log_file:
                result = client.exec(
                    sandbox.id,
                    command,
                    stream_output=False,
                    timeout_seconds=24 * 60 * 60,
                )
                log_file.write(result.stdout.encode())
                if result.stderr:
                    log_file.write(result.stderr.encode())
            with self._lock:
                metadata = self._jobs[name]
                metadata["status"] = "completed" if result.exit_code == 0 else "failed"
                metadata["exit_code"] = result.exit_code
                metadata["completed"] = self._now()
                self._write_metadata(metadata)
        except Exception as exc:
            with self._lock:
                metadata = self._jobs[name]
                metadata["status"] = "failed"
                metadata["error"] = str(exc)
                metadata["completed"] = self._now()
                self._write_metadata(metadata)
        finally:
            client.close()

    def _metadata(self, name: str) -> dict[str, Any] | None:
        with self._lock:
            item = self._jobs.get(name)
            if item:
                return dict(item)
        path = self._metadata_path(name)
        if path.is_file():
            return json.loads(path.read_text())
        return None

    def list_jobs(self, phase: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        jobs = []
        for path in (self.ARTIFACTS_ROOT / "jobs").glob("bb-os-*.json"):
            try:
                job = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if phase and job.get("phase") != phase:
                continue
            if status and job.get("status") != status:
                continue
            jobs.append(job)
        return jobs

    def get_job_status(self, name: str) -> dict[str, Any]:
        job = self._metadata(name)
        if not job:
            return {"error": "Job not found"}
        return job

    def get_job_logs(self, name: str) -> str | None:
        path = self.ARTIFACTS_ROOT / "jobs" / f"{name}.log"
        if not path.is_file():
            return None
        return path.read_text(errors="replace")

    def stop_job(self, name: str) -> bool:
        job = self._metadata(name)
        if not job or job.get("status") not in ("pending", "running"):
            return False
        client = SandboxClient(self.ENDPOINT, tls=None, timeout=30.0)
        try:
            deleted = client.delete(name, workspace=self.WORKSPACE)
        finally:
            client.close()
        if deleted:
            with self._lock:
                job = self._jobs.get(name, job)
                job["status"] = "failed"
                job["error"] = "stopped by operator"
                job["completed"] = self._now()
                self._write_metadata(job)
        return deleted

    def delete_job(self, name: str) -> bool:
        job = self._metadata(name)
        if not job:
            return False
        client = SandboxClient(self.ENDPOINT, tls=None, timeout=30.0)
        try:
            deleted = client.delete(name, workspace=self.WORKSPACE)
        finally:
            client.close()
        with self._lock:
            self._jobs.pop(name, None)
        return deleted or True
