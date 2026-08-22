#!/usr/bin/env python3
"""Seed the minimal GitHub emulator repository used by the M1 runner smoke test.

This intentionally uses the Git transport for the workflow commit. The
emulator's Contents API creates a commit, but workflow runs currently start
from the emulator's post-receive push hook.
"""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


BASE_URL = os.environ.get("GITHUB_EMULATOR_URL", "https://github.local").rstrip("/")
API_URL = f"{BASE_URL}/api/v3"
TOKEN = os.environ.get("GITHUB_EMULATOR_TOKEN", "ghp_admin_default_token")
ORG = "fullsend-dev"
REPO = "triage-target"
ISSUE_TITLE = "Fullsend M1 runner smoke issue"
WORKFLOW = ".github/workflows/m1-runner-smoke.yml"

WORKFLOW_CONTENT = """name: M1 runner smoke

on:
  push:
    branches: [main]

jobs:
  smoke:
    runs-on: [self-hosted, linux, fullsend]
    steps:
      - name: Write M1 marker
        run: |
          test -n \"${GITHUB_REPOSITORY:-}\"
          test -n \"${GITHUB_RUN_ID:-}\"
          printf 'm1-runner-ok\\n' > m1-runner-marker
"""


def api_request(method: str, path: str, body: dict | None = None) -> tuple[int, dict | list | None]:
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"token {TOKEN}",
        "User-Agent": "breadboard-fullsend-m1-seed",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"{API_URL}{path}", data=data, headers=headers, method=method,
    )
    context = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(request, context=context) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            decoded = json.loads(payload) if payload else None
        except json.JSONDecodeError:
            decoded = payload.decode(errors="replace")
        return exc.code, decoded


def ensure_org() -> None:
    status, _ = api_request("GET", f"/orgs/{ORG}")
    if status == 200:
        return
    if status != 404:
        raise RuntimeError(f"GET organization failed: HTTP {status}")
    status, payload = api_request("POST", "/orgs", {"login": ORG, "name": ORG})
    if status not in (201, 422):
        raise RuntimeError(f"POST organization failed: HTTP {status}: {payload}")


def ensure_repo() -> None:
    status, _ = api_request("GET", f"/repos/{ORG}/{REPO}")
    if status == 200:
        return
    if status != 404:
        raise RuntimeError(f"GET repository failed: HTTP {status}")
    status, payload = api_request(
        "POST", f"/orgs/{ORG}/repos",
        {"name": REPO, "description": "Minimal Fullsend development target", "private": False},
    )
    if status not in (201, 422):
        raise RuntimeError(f"POST repository failed: HTTP {status}: {payload}")


def ensure_issue() -> int:
    status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/issues?state=all")
    if status != 200 or not isinstance(payload, list):
        raise RuntimeError(f"GET issues failed: HTTP {status}: {payload}")
    for issue in payload:
        if issue.get("title") == ISSUE_TITLE:
            return int(issue["number"])
    status, payload = api_request(
        "POST", f"/repos/{ORG}/{REPO}/issues",
        {"title": ISSUE_TITLE, "body": "Created by the repeatable M1 smoke harness."},
    )
    if status != 201:
        raise RuntimeError(f"POST issue failed: HTTP {status}: {payload}")
    return int(payload["number"])


def git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_SSL_NO_VERIFY"] = "true"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def run_git(directory: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=directory, env=git_env(), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
    )


def push_workflow(
    workflow: str = WORKFLOW,
    workflow_content: str = WORKFLOW_CONTENT,
    message: str = "Add M1 runner smoke workflow",
) -> str:
    remote = f"https://x-access-token:{TOKEN}@github.local/{ORG}/{REPO}.git"
    with tempfile.TemporaryDirectory(prefix="fullsend-m1-seed-") as temp:
        directory = Path(temp)
        run_git(directory, "init", "--initial-branch=main")
        run_git(directory, "config", "user.name", "Breadboard M1 Seed")
        run_git(directory, "config", "user.email", "breadboard-m1@localhost")
        run_git(directory, "remote", "add", "origin", remote)
        fetched = run_git(directory, "fetch", "origin", "main", check=False)
        if fetched.returncode == 0:
            run_git(directory, "reset", "--hard", "FETCH_HEAD")

        workflow_path = directory / workflow
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text(workflow_content)
        run_git(directory, "add", workflow)
        committed = run_git(directory, "commit", "-m", message, check=False)
        if committed.returncode != 0 and "nothing to commit" not in committed.stdout + committed.stderr:
            raise RuntimeError(committed.stderr)
        if committed.returncode == 0:
            pushed = run_git(directory, "push", "-u", "origin", "main", check=False)
            if pushed.returncode != 0:
                raise RuntimeError(pushed.stderr)
        return run_git(directory, "rev-parse", "HEAD").stdout.strip()


def main() -> None:
    ensure_org()
    ensure_repo()
    issue_number = ensure_issue()
    commit = push_workflow()
    print(json.dumps({
        "status": "seeded",
        "repository": f"{ORG}/{REPO}",
        "issue_number": issue_number,
        "workflow": WORKFLOW,
        "commit": commit,
    }, indent=2))


if __name__ == "__main__":
    main()
