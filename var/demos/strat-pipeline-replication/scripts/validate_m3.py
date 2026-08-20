#!/usr/bin/env python3
"""Validate the adapted pipeline config in the GitLab emulator."""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
from pathlib import Path
from urllib.request import Request, urlopen

from bootstrap_topology import Api


FIXTURE = Path(__file__).resolve().parents[1]
PROJECT_PATH = "redhat/rhel-ai/agentic-ci/strat-pipeline"
DASHBOARD_PROJECT_PATH = "redhat/rhel-ai/agentic-ci/strat-dashboard"


def basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def fetch_raw(base_url: str, project_path: str, auth: str) -> str:
    request = Request(
        f"{base_url.rstrip('/')}/projects/{project_path}/repository/files/.gitlab-ci.yml/raw?ref=main",
        headers={"Authorization": auth},
    )
    with urlopen(request, context=ssl._create_unverified_context()) as response:
        return response.read().decode()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gitlab-api", default=os.getenv("GITLAB_API_URL", "https://gitlab.local/api/v4"))
    parser.add_argument("--gitlab-user", default=os.getenv("GITLAB_USER", "admin"))
    parser.add_argument("--gitlab-password", default=os.getenv("GITLAB_ADMIN_PASSWORD", "admin"))
    parser.add_argument("--github-api", default=os.getenv("GITHUB_API_URL", "https://github.local/api/v3"))
    parser.add_argument("--github-token", default=os.getenv("GITHUB_API_TOKEN", "<set-me>"))
    args = parser.parse_args()

    auth = basic_auth(args.gitlab_user, args.gitlab_password)
    gitlab = Api(args.gitlab_api, {"Authorization": auth})
    content = fetch_raw(args.gitlab_api, PROJECT_PATH, auth)
    dashboard = gitlab.request("GET", f"projects/{DASHBOARD_PROJECT_PATH}")
    dashboard_content = fetch_raw(args.gitlab_api, DASHBOARD_PROJECT_PATH, auth)
    expected_defaults = [
        'github_git_url="${GITHUB_GIT_URL:-https://github.com}"',
        'export CLAUDE_REPO="${github_git_url}/opendatahub-io/strat-creator.git"',
        'export CLAUDE_PLUGINS="${github_git_url}/opendatahub-io/assess-strat.git"',
        'if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then export GIT_SSL_NO_VERIFY=true; fi',
        'export JIRA_SERVER="${JIRA_SERVER:-https://redhat.atlassian.net}"',
    ]
    missing_defaults = [value for value in expected_defaults if value not in content]
    if missing_defaults:
        raise RuntimeError(f"upstream-safe defaults are missing: {missing_defaults}")
    runtime_defaults = {
        "JIRA_SERVER": "https://jira-emulator.ai-pipeline.svc.cluster.local",
        "GITHUB_GIT_URL": "https://github-emulator.ai-pipeline.svc.cluster.local",
        "GITLAB_GIT_URL": "https://gitlab-emulator.ai-pipeline.svc.cluster.local",
        "NO_SSL_VERIFY": "1",
    }
    missing_overrides = []
    for key, expected in runtime_defaults.items():
        variable = gitlab.request("GET", f"projects/2/variables/{key}")
        if variable.get("value") != expected:
            missing_overrides.append({"key": key, "expected": expected})
    if missing_overrides:
        raise RuntimeError(f"emulator project overrides are missing: {missing_overrides}")

    dashboard_overrides = {
        "GITHUB_GIT_URL": "https://github-emulator.ai-pipeline.svc.cluster.local",
        "GITLAB_GIT_URL": "https://gitlab-emulator.ai-pipeline.svc.cluster.local",
        "NO_SSL_VERIFY": "1",
    }
    missing_dashboard_overrides = []
    for key, expected in dashboard_overrides.items():
        variable = gitlab.request("GET", f"projects/{dashboard['id']}/variables/{key}")
        if variable.get("value") != expected:
            missing_dashboard_overrides.append({"key": key, "expected": expected})
    data_token = gitlab.request("GET", f"projects/{dashboard['id']}/variables/DATA_REPO_TOKEN")
    if not data_token.get("value") or not data_token.get("masked"):
        missing_dashboard_overrides.append({"key": "DATA_REPO_TOKEN", "expected": "masked token"})
    if missing_dashboard_overrides:
        raise RuntimeError(f"dashboard project overrides are missing: {missing_dashboard_overrides}")

    expected_dashboard_wiring = [
        'export CREATOR_REPO="${github_git_url}/opendatahub-io/strat-creator.git"',
        'export DATA_REPO_URL="${data_repo}"',
        'git clone "$DATA_REPO_URL" /tmp/strat-data',
    ]
    missing_dashboard_wiring = [value for value in expected_dashboard_wiring if value not in dashboard_content]
    if missing_dashboard_wiring:
        raise RuntimeError(f"dashboard emulator wiring is missing: {missing_dashboard_wiring}")

    github = Api(args.github_api, {"Authorization": f"token {args.github_token}"})
    jira_utils = github.request(
        "GET",
        "repos/opendatahub-io/strat-creator/contents/scripts/jira_utils.py?ref=main",
    )
    creator_content = base64.b64decode(jira_utils["content"]).decode()
    if (
        "NO_SSL_VERIFY" not in creator_content
        or "_create_unverified_context" not in creator_content
        or "_reachable_attachment_url" not in creator_content
    ):
        raise RuntimeError("strat-creator mirror is missing NO_SSL_VERIFY Jira support")

    lint = gitlab.request(
        "POST",
        f"projects/{PROJECT_PATH}/ci/lint",
        {
            "content": content,
            "ref": "main",
            "include_jobs": True,
            "variables": [
                {"key": "CI_PIPELINE_SOURCE", "value": "schedule"},
                {"key": "CONFIG_FILE", "value": "config/test.yaml"},
                {"key": "RFE_KEY", "value": "RHAIRFE-1"},
                {"key": "STRAT_KEY", "value": "RHAISTRAT-1"},
                *[
                    {"key": key, "value": value}
                    for key, value in runtime_defaults.items()
                ],
            ],
        },
    )
    if not lint.get("valid"):
        raise RuntimeError(f"GitLab CI lint failed: {lint}")
    dashboard_lint = gitlab.request(
        "POST",
        f"projects/{DASHBOARD_PROJECT_PATH}/ci/lint",
        {
            "content": dashboard_content,
            "ref": "main",
            "include_jobs": True,
            "variables": [
                {"key": "CI_PIPELINE_SOURCE", "value": "pipeline"},
                {"key": "CI_COMMIT_BRANCH", "value": "main"},
            ],
        },
    )
    if not dashboard_lint.get("valid"):
        raise RuntimeError(f"dashboard GitLab CI lint failed: {dashboard_lint}")
    jobs = [job["name"] for job in lint.get("jobs", [])]
    expected_manual_jobs = {"batch-config", "single-rfe", "reprocess-strat", "build-dashboard"}
    if set(jobs) != expected_manual_jobs:
        raise RuntimeError(f"unexpected parsed manual jobs: expected {sorted(expected_manual_jobs)}, got {jobs}")
    if "batch-jql:" not in content or 'if: $CI_PIPELINE_SOURCE == "schedule"' not in content:
        raise RuntimeError("scheduled batch-jql job or schedule rule is missing")

    pipeline = gitlab.request(
        "POST",
        "projects/2/pipeline",
        {
            "ref": "main",
            "job": {
                "name": "m3-config-acceptance",
                "image": "alpine:3.20",
                "script": ["echo M3 pipeline configuration accepted"],
            },
        },
    )
    if not pipeline.get("id"):
        raise RuntimeError(f"GitLab pipeline creation failed: {pipeline}")
    canceled = gitlab.request(
        "POST", f"projects/2/pipelines/{pipeline['id']}/cancel"
    )

    report = {
        "version": 1,
        "project": PROJECT_PATH,
        "commit": json.loads((FIXTURE / "pipeline-manifest.json").read_text())["adapted_commit"],
        "ci_lint": {"valid": True, "jobs": sorted(set(jobs)), "warnings": lint.get("warnings", [])},
        "scheduled_job_contract": {"batch-jql": True, "schedule_rule": True},
        "dashboard": {
            "project_id": dashboard["id"],
            "ci_lint": True,
            "pages_job": "pages" in [job["name"] for job in dashboard_lint.get("jobs", [])],
            "runtime_overrides": True,
        },
        "pipeline_create": {
            "id": pipeline["id"],
            "status_at_creation": pipeline.get("status"),
            "cleanup_status": canceled.get("status"),
            "source": pipeline.get("source"),
        },
        "default_and_override_check": {
            "upstream_defaults": True,
            "emulator_overrides": True,
            "strat_creator_jira_support": True,
        },
    }
    (FIXTURE / "m3-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print("M3 pipeline validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
