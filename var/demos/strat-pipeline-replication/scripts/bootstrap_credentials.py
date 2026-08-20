#!/usr/bin/env python3
"""Bootstrap the M2 Jira/GitLab credentials for the strat-pipeline fixture.

Raw tokens exist only in memory and in the target GitLab variable store. The
generated report contains metadata only.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from bootstrap_topology import Api, ApiError


FIXTURE = Path(__file__).resolve().parents[1]
PROJECT_PATH = "redhat/rhel-ai/agentic-ci/strat-pipeline"
DASHBOARD_PROJECT_PATH = "redhat/rhel-ai/agentic-ci/strat-dashboard"
JIRA_USERNAME = "aipcc-agentic-jira-bot"
JIRA_EMAIL = "aipcc-agentic-jira-bot@redhat.com"
JIRA_DISPLAY_NAME = "AIPCC Agentic Jira Bot"
JIRA_TOKEN_NAME = "strat-pipeline-replication"
GITLAB_TOKEN_NAME = "strat-pipeline-replication"


def basic_auth(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


def kubectl_secret_value(secret: str, key: str) -> str | None:
    jsonpath_key = key.replace(".", "\\.")
    result = subprocess.run(
        [
            "kubectl",
            "get",
            "secret",
            secret,
            "-n",
            "ai-pipeline",
            "-o",
            f"jsonpath={{.data.{jsonpath_key}}}",
        ],
        capture_output=True,
        text=True,
    )
    value = result.stdout.strip()
    return value or None


def kubectl_object_exists(kind: str, name: str, namespace: str) -> bool:
    result = subprocess.run(
        ["kubectl", "get", kind, name, "-n", namespace],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def ensure_jira_user(jira_admin: Api, password: str) -> dict:
    path = f"rest/api/2/user?username={quote(JIRA_USERNAME, safe='')}"
    user = jira_admin.get_or_none(path)
    if user is None:
        return jira_admin.request(
            "POST",
            "rest/api/2/user",
            {
                "name": JIRA_USERNAME,
                "password": password,
                "emailAddress": JIRA_EMAIL,
                "displayName": JIRA_DISPLAY_NAME,
            },
        )

    if user.get("emailAddress") != JIRA_EMAIL or user.get("displayName") != JIRA_DISPLAY_NAME:
        user = jira_admin.request(
            "PUT",
            path,
            {"emailAddress": JIRA_EMAIL, "displayName": JIRA_DISPLAY_NAME},
        )
    return user


def validate_jira_token(jira_url: str, token: str) -> bool:
    try:
        user = Api(jira_url, {"Authorization": f"Bearer {token}"}).request(
            "GET", "rest/api/2/myself"
        )
    except (ApiError, RuntimeError):
        return False
    return user.get("key") == JIRA_USERNAME and user.get("emailAddress") == JIRA_EMAIL


def create_jira_token(jira_url: str, jira_admin: Api, password: str) -> str:
    jira_admin.request(
        "PUT",
        f"rest/api/2/user/password?username={quote(JIRA_USERNAME, safe='')}",
        {"password": password},
    )
    jira_bot = Api(jira_url, {"Authorization": basic_auth(JIRA_USERNAME, password)})

    # Revoke fixture-owned tokens before replacement. The list endpoint never
    # returns raw token values.
    for token in jira_bot.request("GET", "rest/pat/latest/tokens"):
        if token.get("name") == JIRA_TOKEN_NAME:
            jira_bot.request("DELETE", f"rest/pat/latest/tokens/{token['id']}")

    created = jira_bot.request(
        "POST",
        "rest/pat/latest/tokens",
        {"name": JIRA_TOKEN_NAME},
    )
    return created["rawToken"]


def validate_gitlab_token(gitlab_api: str, token: str) -> bool:
    try:
        user = Api(gitlab_api, {"PRIVATE-TOKEN": token}).request("GET", "user")
    except (ApiError, RuntimeError):
        return False
    return user.get("login") == "admin"


def create_gitlab_token(gitlab: Api) -> str:
    created = gitlab.request(
        "POST",
        "admin/tokens",
        {
            "login": "admin",
            "name": GITLAB_TOKEN_NAME,
            "scopes": ["api", "read_repository", "write_repository"],
        },
    )
    return created["token"]


def get_variable(gitlab: Api, project_id: int, key: str) -> dict | None:
    try:
        return gitlab.request("GET", f"projects/{project_id}/variables/{quote(key, safe='')}")
    except ApiError as exc:
        if exc.status == 404:
            return None
        raise


def ensure_variable(
    gitlab: Api,
    project_id: int,
    key: str,
    value: str,
    *,
    masked: bool,
    description: str,
) -> None:
    body = {
        "value": value,
        "variable_type": "env_var",
        "masked": masked,
        "hidden": False,
        "protected": False,
        "raw": False,
        "environment_scope": "*",
        "description": description,
    }
    existing = get_variable(gitlab, project_id, key)
    if existing is None:
        gitlab.request("POST", f"projects/{project_id}/variables", {"key": key, **body})
    else:
        gitlab.request("PUT", f"projects/{project_id}/variables/{quote(key, safe='')}", body)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jira-url", default=os.getenv("JIRA_URL", "https://jira.local"))
    parser.add_argument("--jira-admin-user", default=os.getenv("JIRA_ADMIN_USER", "admin"))
    parser.add_argument("--jira-admin-password", default=os.getenv("JIRA_ADMIN_PASSWORD", "admin"))
    parser.add_argument("--jira-runtime-url", default=os.getenv("JIRA_RUNTIME_URL", "https://jira-emulator.ai-pipeline.svc.cluster.local"))
    parser.add_argument("--gitlab-api", default=os.getenv("GITLAB_API_URL", "https://gitlab.local/api/v4"))
    parser.add_argument("--gitlab-admin-user", default=os.getenv("GITLAB_USER", "admin"))
    parser.add_argument("--gitlab-admin-password", default=os.getenv("GITLAB_ADMIN_PASSWORD", "admin"))
    parser.add_argument("--github-runtime-url", default=os.getenv("GITHUB_RUNTIME_URL", "https://github-emulator.ai-pipeline.svc.cluster.local"))
    parser.add_argument("--gitlab-runtime-url", default=os.getenv("GITLAB_RUNTIME_URL", "https://gitlab-emulator.ai-pipeline.svc.cluster.local"))
    parser.add_argument("--gcp-project-id", default=os.getenv("GCP_PROJECT_ID"))
    parser.add_argument("--gcp-service-account-key", default=os.getenv("GCP_SERVICE_ACCOUNT_KEY"))
    args = parser.parse_args()

    jira_admin = Api(args.jira_url, {"Authorization": basic_auth(args.jira_admin_user, args.jira_admin_password)})
    gitlab = Api(args.gitlab_api, {"Authorization": basic_auth(args.gitlab_admin_user, args.gitlab_admin_password)})

    topology_path = FIXTURE / "topology-manifest.json"
    if not topology_path.exists():
        raise SystemExit("M1 topology-manifest.json is missing; run bootstrap_topology.py first")
    topology = json.loads(topology_path.read_text())
    project = next(item for item in topology["gitlab"]["projects"] if item["path"] == PROJECT_PATH)
    project_id = int(project["id"])
    dashboard_project = next(item for item in topology["gitlab"]["projects"] if item["path"] == DASHBOARD_PROJECT_PATH)
    dashboard_project_id = int(dashboard_project["id"])

    jira_user = ensure_jira_user(jira_admin, secrets.token_urlsafe(24))
    existing_jira_var = get_variable(gitlab, project_id, "JIRA_API_TOKEN")
    jira_token = existing_jira_var.get("value") if existing_jira_var else None
    if not jira_token or not validate_jira_token(args.jira_url, jira_token):
        jira_token = create_jira_token(args.jira_url, jira_admin, secrets.token_urlsafe(24))

    existing_gitlab_var = get_variable(gitlab, project_id, "RESULTS_PUSH_TOKEN")
    gitlab_token = existing_gitlab_var.get("value") if existing_gitlab_var else None
    if not gitlab_token or not validate_gitlab_token(args.gitlab_api, gitlab_token):
        gitlab_token = create_gitlab_token(gitlab)

    gcp_project_id = args.gcp_project_id
    if not gcp_project_id:
        encoded_project = kubectl_secret_value("pipeline-secrets", "ANTHROPIC_VERTEX_PROJECT_ID")
        if encoded_project:
            gcp_project_id = base64.b64decode(encoded_project).decode().strip()
    gcp_key = args.gcp_service_account_key or kubectl_secret_value("gcp-credentials", "credentials.json")

    ensure_variable(gitlab, project_id, "JIRA_SERVER", args.jira_runtime_url, masked=False, description="M2 in-cluster Jira emulator endpoint")
    ensure_variable(gitlab, project_id, "JIRA_USER", JIRA_EMAIL, masked=False, description="M2 Jira bot email")
    ensure_variable(gitlab, project_id, "GITHUB_GIT_URL", args.github_runtime_url, masked=False, description="M3 in-cluster GitHub emulator Git endpoint")
    ensure_variable(gitlab, project_id, "GITLAB_GIT_URL", args.gitlab_runtime_url, masked=False, description="M3 in-cluster GitLab emulator Git endpoint")
    ensure_variable(gitlab, project_id, "NO_SSL_VERIFY", "1", masked=False, description="M3 local emulator self-signed TLS compatibility switch")
    ensure_variable(gitlab, project_id, "CAPTURE_API_BODIES", "1", masked=False, description="M3 opt-in Claude API body capture for restricted emulator job artifacts")
    ensure_variable(gitlab, project_id, "JIRA_API_TOKEN", jira_token, masked=True, description="M2 Jira bot PAT")
    ensure_variable(gitlab, project_id, "RESULTS_PUSH_TOKEN", gitlab_token, masked=True, description="M2 GitLab results push PAT")

    ensure_variable(gitlab, dashboard_project_id, "GITHUB_GIT_URL", args.github_runtime_url, masked=False, description="M3 in-cluster GitHub emulator Git endpoint for dashboard")
    ensure_variable(gitlab, dashboard_project_id, "GITLAB_GIT_URL", args.gitlab_runtime_url, masked=False, description="M3 in-cluster GitLab emulator Git endpoint for dashboard data")
    ensure_variable(gitlab, dashboard_project_id, "NO_SSL_VERIFY", "1", masked=False, description="M3 local emulator self-signed TLS compatibility switch for dashboard")
    ensure_variable(gitlab, dashboard_project_id, "DATA_REPO_TOKEN", gitlab_token, masked=True, description="M3 GitLab PAT for dashboard data checkout")

    warnings = []
    if gcp_project_id:
        ensure_variable(gitlab, project_id, "GCP_PROJECT_ID", gcp_project_id, masked=False, description="Vertex project used by strat-pipeline")
    else:
        warnings.append("GCP_PROJECT_ID was not available; provide it before M4")
    if gcp_key:
        ensure_variable(gitlab, project_id, "GCP_SERVICE_ACCOUNT_KEY", gcp_key, masked=True, description="Base64 GCP credential JSON for strat-pipeline")
    else:
        warnings.append("GCP_SERVICE_ACCOUNT_KEY was not available; provide it before M4")

    ca_ready = kubectl_object_exists("configmap", "internal-ca-cert", "ai-pipeline") and kubectl_object_exists("secret", "gitlab-runner-ca", "gitlab-runner")
    if not ca_ready:
        warnings.append("runner CA objects are missing")

    jira_bot_api = Api(args.jira_url, {"Authorization": f"Bearer {jira_token}"})
    myself = jira_bot_api.request("GET", "rest/api/2/myself")
    jira_bot_api.request("POST", "rest/api/2/search", {"jql": "project = RHAIRFE", "maxResults": 1, "fields": ["key"]})
    gitlab_user = Api(args.gitlab_api, {"PRIVATE-TOKEN": gitlab_token}).request("GET", "user")

    report = {
        "version": 1,
        "jira": {"username": jira_user.get("key", JIRA_USERNAME), "email": myself.get("emailAddress"), "display_name": myself.get("displayName"), "token_variable": "JIRA_API_TOKEN", "myself_check": True, "jql_check": True},
        "gitlab": {
            "project": PROJECT_PATH,
            "project_id": project_id,
            "results_token_variable": "RESULTS_PUSH_TOKEN",
            "api_user": gitlab_user.get("login"),
            "dashboard_project": DASHBOARD_PROJECT_PATH,
            "dashboard_project_id": dashboard_project_id,
            "dashboard_data_token_variable": "DATA_REPO_TOKEN",
        },
        "ci_variables": {
            "pipeline_visible": ["JIRA_SERVER", "JIRA_USER", "GITHUB_GIT_URL", "GITLAB_GIT_URL", "NO_SSL_VERIFY", "CAPTURE_API_BODIES"] + (["GCP_PROJECT_ID"] if gcp_project_id else []),
            "pipeline_masked": ["JIRA_API_TOKEN", "RESULTS_PUSH_TOKEN"] + (["GCP_SERVICE_ACCOUNT_KEY"] if gcp_key else []),
            "dashboard_visible": ["GITHUB_GIT_URL", "GITLAB_GIT_URL", "NO_SSL_VERIFY"],
            "dashboard_masked": ["DATA_REPO_TOKEN"],
        },
        "runner_ca_objects": ca_ready,
        "warnings": warnings,
        "notes": ["Raw credentials are not written to this report."],
    }
    (FIXTURE / "credentials-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print("M2 credential bootstrap passed" + (" with warnings" if warnings else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, RuntimeError, KeyError, ValueError) as exc:
        print(f"M2 credential bootstrap failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
