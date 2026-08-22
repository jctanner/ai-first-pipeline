"""Read-only operational dashboard for the local Fullsend stack."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from flask import Flask, jsonify, render_template

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
except ImportError:  # pragma: no cover - exercised only in the tiny local dev image
    client = None
    config = None
    ApiException = Exception


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _pod_status(pod: Any) -> dict[str, Any]:
    statuses = []
    for item in pod.status.container_statuses or []:
        state = item.state
        state_name = "unknown"
        if state and state.running:
            state_name = "running"
        elif state and state.waiting:
            state_name = "waiting"
        elif state and state.terminated:
            state_name = "terminated"
        statuses.append({
            "name": item.name,
            "ready": bool(item.ready),
            "restarts": item.restart_count or 0,
            "state": state_name,
            "reason": (state.waiting.reason if state and state.waiting else None),
        })
    return {
        "name": pod.metadata.name,
        "namespace": pod.metadata.namespace,
        "phase": pod.status.phase,
        "created_at": _iso(pod.metadata.creation_timestamp),
        "labels": pod.metadata.labels or {},
        "containers": statuses,
    }


class FullsendCollector:
    """Collect state from the local GitHub emulator and Kubernetes API."""

    def __init__(self) -> None:
        self.github_api = os.getenv(
            "GITHUB_API_URL",
            "http://github-emulator-backend.ai-pipeline.svc.cluster.local:8000/api/v3",
        ).rstrip("/")
        self.github_ui = os.getenv("GITHUB_UI_URL", "https://github.local").rstrip("/")
        self.github_repos = [
            item.strip()
            for item in os.getenv("GITHUB_REPOS", "fullsend-dev/triage-target").split(",")
            if item.strip()
        ]
        self.github_token = os.getenv("GITHUB_TOKEN", "")
        self.verify_tls = os.getenv("NO_SSL_VERIFY", "0") != "1"
        self.session = requests.Session()
        if self.github_token:
            self.session.headers.update({"Authorization": f"token {self.github_token}"})
        self.session.headers.update({"Accept": "application/vnd.github+json"})
        self.k8s_core = None
        self.k8s_batch = None
        self.k8s_events = None
        self.k8s_error: str | None = None
        if client and config:
            try:
                config.load_incluster_config()
                self.k8s_core = client.CoreV1Api()
                self.k8s_batch = client.BatchV1Api()
                self.k8s_events = client.EventsV1Api()
            except Exception as exc:  # local browser/dev mode may have no cluster
                self.k8s_error = str(exc)

    def _github_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.session.get(
            f"{self.github_api}/{path.lstrip('/')}",
            params=params,
            timeout=8,
            verify=self.verify_tls,
        )
        response.raise_for_status()
        return response.json()

    def github_state(self) -> dict[str, Any]:
        repos: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        errors: list[str] = []
        for repo in self.github_repos:
            try:
                runs_payload = self._github_get(
                    f"repos/{repo}/actions/runs", {"per_page": 20}
                )
                runs = runs_payload.get("workflow_runs", [])
                normalized_runs = []
                for run in runs:
                    jobs: list[dict[str, Any]] = []
                    try:
                        jobs_payload = self._github_get(
                            f"repos/{repo}/actions/runs/{run['id']}/jobs",
                            {"per_page": 100},
                        )
                        for job in jobs_payload.get("jobs", []):
                            normalized_job = {
                                "id": job.get("id"),
                                "name": job.get("name"),
                                "status": job.get("status"),
                                "conclusion": job.get("conclusion"),
                                "runner_name": job.get("runner_name"),
                                "started_at": job.get("started_at"),
                                "completed_at": job.get("completed_at"),
                                "ui_url": f"{self.github_ui}/ui/{repo}/actions/jobs/{job['id']}",
                                "steps": [
                                    {
                                        "name": step.get("name"),
                                        "status": step.get("status"),
                                        "conclusion": step.get("conclusion"),
                                    }
                                    for step in job.get("steps", [])
                                ],
                            }
                            jobs.append(normalized_job)
                            events.append({
                                "kind": "github-job",
                                "time": job.get("completed_at") or job.get("started_at"),
                                "title": job.get("name", "GitHub Actions job"),
                                "detail": f"{job.get('status')} / {job.get('conclusion') or 'active'}",
                                "repo": repo,
                                "run_id": run.get("id"),
                            })
                    except requests.RequestException as exc:
                        errors.append(f"{repo} jobs: {exc}")
                    normalized_runs.append({
                        "id": run.get("id"),
                        "name": run.get("name"),
                        "event": run.get("event"),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "branch": run.get("head_branch"),
                        "sha": run.get("head_sha"),
                        "created_at": run.get("created_at"),
                        "updated_at": run.get("updated_at"),
                        "html_url": run.get("html_url"),
                        "ui_url": f"{self.github_ui}/ui/{repo}/actions/runs/{run['id']}",
                        "jobs": jobs,
                    })
                    events.append({
                        "kind": "github-run",
                        "time": run.get("updated_at") or run.get("created_at"),
                        "title": run.get("name", "GitHub Actions run"),
                        "detail": f"{run.get('status')} / {run.get('conclusion') or 'active'}",
                        "repo": repo,
                        "run_id": run.get("id"),
                    })
                repos.append({"name": repo, "runs": normalized_runs})
            except requests.RequestException as exc:
                errors.append(f"{repo}: {exc}")
        return {"repos": repos, "events": events, "errors": errors}

    def kubernetes_state(self) -> dict[str, Any]:
        if not self.k8s_core:
            return {"pods": [], "jobs": [], "events": [], "errors": [self.k8s_error or "Kubernetes unavailable"]}
        pods: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            pod_list = self.k8s_core.list_pod_for_all_namespaces()
            for pod in pod_list.items:
                name = pod.metadata.name or ""
                namespace = pod.metadata.namespace or ""
                labels = pod.metadata.labels or {}
                if (
                    (name.lower().startswith("agent-") and "controller" not in name.lower())
                    or labels.get("app") == "agent-sandbox"
                ):
                    pods.append(_pod_status(pod))
        except ApiException as exc:
            errors.append(f"pods: {exc}")
        try:
            job_list = self.k8s_batch.list_namespaced_job("ai-pipeline")
            for job in job_list.items:
                name = job.metadata.name or ""
                labels = job.metadata.labels or {}
                if "fullsend" not in name.lower() and "fullsend" not in str(labels).lower():
                    continue
                status = "running"
                if job.status.completion_time:
                    status = "completed" if (job.status.succeeded or 0) else "failed"
                elif (job.status.failed or 0) > 0:
                    status = "failed"
                jobs.append({
                    "name": name,
                    "namespace": "ai-pipeline",
                    "status": status,
                    "created_at": _iso(job.metadata.creation_timestamp),
                    "started_at": _iso(job.status.start_time),
                    "completed_at": _iso(job.status.completion_time),
                    "succeeded": job.status.succeeded or 0,
                    "failed": job.status.failed or 0,
                })
        except ApiException as exc:
            errors.append(f"jobs: {exc}")
        try:
            # The cluster contains legacy events without event_time. The
            # events.k8s.io client model rejects those records during
            # deserialization, so use the core Events API for compatibility.
            event_list = self.k8s_core.list_event_for_all_namespaces()
            for event in event_list.items:
                reference = getattr(event, "involved_object", None)
                name = reference.name if reference else ""
                if not any(token in f"{name} {reference.namespace if reference else ''}".lower() for token in ("agent", "fullsend", "openshell")):
                    continue
                event_time = getattr(event, "last_timestamp", None)
                if not event_time:
                    event_time = getattr(event, "event_time", None)
                if not event_time:
                    event_time = event.metadata.creation_timestamp
                events.append({
                    "kind": "kubernetes",
                    "time": _iso(event_time),
                    "title": event.reason or "Kubernetes event",
                    "detail": getattr(event, "message", None) or getattr(event, "action", None) or "",
                    "object": name,
                    "namespace": reference.namespace if reference else None,
                    "type": event.type,
                })
        except (ApiException, AttributeError) as exc:
            errors.append(f"events: {exc}")
        return {"pods": pods, "jobs": jobs, "events": events, "errors": errors}

    def state(self) -> dict[str, Any]:
        github = self.github_state()
        kubernetes = self.kubernetes_state()
        events = github["events"] + kubernetes["events"]
        events.sort(key=lambda item: item.get("time") or "", reverse=True)
        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "github": {"api": self.github_api, "repos": self.github_repos, "errors": github["errors"]},
                "kubernetes": {"errors": kubernetes["errors"]},
            },
            "github": {"repos": github["repos"]},
            "agents": kubernetes["pods"],
            "jobs": kubernetes["jobs"],
            "events": events[:100],
        }


def create_app(collector: FullsendCollector | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).with_name("templates")))
    collector = collector or FullsendCollector()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/api/state")
    def state():
        return jsonify(collector.state())

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
