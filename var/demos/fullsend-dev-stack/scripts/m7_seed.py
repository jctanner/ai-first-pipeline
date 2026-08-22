#!/usr/bin/env python3
"""Seed and dispatch the combined M7 GitHub Actions -> Fullsend scenario."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from m1_seed import (
    API_URL,
    ORG,
    REPO,
    TOKEN,
    api_request,
    ensure_issue,
    ensure_org,
    ensure_repo,
    run_git,
)


ROOT = Path(__file__).resolve().parents[4]
DEMO = ROOT / "var" / "demos" / "fullsend-dev-stack"
POLICY = (DEMO / "policies" / "github-emulator-readonly.yaml").read_text(encoding="utf-8")
WORKFLOW = ".github/workflows/m7-fullsend-actions.yml"

CONFIG = """version: "1"
dispatch:
  platform: github-actions
defaults:
  roles: [triage]
  runtime: claude
agents:
  - name: claude
    source: agents/triage.yaml
repos: {}
"""

HARNESS = """agent: agents/triage.md
role: triage
post_script: scripts/post-triage.sh
image: fullsend-sandbox-dev:k3s
policy: policies/github-emulator.yaml
host_files:
  - src: /var/run/secrets/gcp/credentials.json
    dest: /sandbox/workspace/gcp-credentials.json
    optional: true
env:
  sandbox:
    GH_TOKEN: ${GITHUB_TOKEN}
    GITHUB_API_URL: http://github.local/api/v3
    CLAUDE_CODE_USE_VERTEX: ${CLAUDE_CODE_USE_VERTEX}
    CLOUD_ML_REGION: ${CLOUD_ML_REGION}
    ANTHROPIC_VERTEX_PROJECT_ID: ${ANTHROPIC_VERTEX_PROJECT_ID}
    GOOGLE_APPLICATION_CREDENTIALS: /sandbox/workspace/gcp-credentials.json
"""

AGENT = """# M7 Fullsend triage role

Inspect the target repository and the open issue using read-only API requests.
Write a concise JSON triage result to output/agent-result.json. Do not create
labels, comments, branches, pull requests, or files in the target repository.
Do not use task-management tools. The host-side post-script records the
emulator result after the sandbox exits, so finish after producing the JSON.
"""

POST_SCRIPT = """#!/bin/sh
set -eu
api="${GITHUB_API_URL:-https://github.local/api/v3}"
repo="${FULLSEND_STATUS_REPO:?FULLSEND_STATUS_REPO is required}"
number="${FULLSEND_STATUS_NUMBER:?FULLSEND_STATUS_NUMBER is required}"
token="${GITHUB_TOKEN:?GITHUB_TOKEN is required}"
body="$(printf '%s\\n%s\\nRun: %s' \
  '<!-- fullsend-dev-stack:triage -->' \
  'Fullsend M7 Claude/Vertex triage completed through OpenShell and GitHub Actions.' \
  "${GITHUB_RUN_ID:-unknown}")"
curl_args=""
if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then curl_args="-k"; fi
curl ${curl_args} -fsS -o /dev/null -X POST \
  "${api}/repos/${repo}/issues/${number}/comments" \
  -H "Authorization: token ${token}" \
  -H "Content-Type: application/json" \
  -d "$(jq -nc --arg body "${body}" '{body:$body}')"
echo "Fullsend M7 result comment posted to ${repo}#${number}"
"""

WORKFLOW_CONTENT = r"""name: M7 Fullsend through GitHub Actions

on:
  workflow_dispatch:
    inputs:
      issue_number:
        required: false
        default: "1"
        type: string

jobs:
  fullsend:
    name: Fullsend Claude triage
    runs-on: [self-hosted, linux, fullsend]
    env:
      FULLSEND_STATUS_REPO: fullsend-dev/triage-target
      FULLSEND_STATUS_NUMBER: ${{ inputs.issue_number }}
      FULLSEND_MINT_URL: ""
      GITHUB_API_URL: https://github.local/api/v3
      NO_SSL_VERIFY: "1"
      OPENSHELL_GATEWAY_ENDPOINT: http://openshell.openshell-system.svc.cluster.local:8080
      OPENSHELL_GATEWAY_NAME: openshell
    steps:
      - name: Checkout target repository
        uses: actions/checkout@v4
      - name: Run Fullsend triage through OpenShell
        run: |
          set -eu
          test -x "$(command -v fullsend)"
          test -x "$(command -v openshell)"
          fullsend run claude \
            --fullsend-dir "${GITHUB_WORKSPACE}/.fullsend" \
            --target-repo "${GITHUB_WORKSPACE}" \
            --output-dir "${GITHUB_WORKSPACE}/output" \
            --forge github
      - name: Verify emulator result
        run: |
          set -eu
          comments="$(curl -ksSf \
            -H "Authorization: token ${GITHUB_TOKEN}" \
            "${GITHUB_API_URL}/repos/${FULLSEND_STATUS_REPO}/issues/${FULLSEND_STATUS_NUMBER}/comments")"
          test "$(jq -r 'any(.[]; .body | contains("<!-- fullsend-dev-stack:triage -->"))' <<<"${comments}")" = true
          printf 'M7 Actions-to-emulator result verified\\n'
"""

FILES = {
    WORKFLOW: WORKFLOW_CONTENT,
    ".fullsend/config.yaml": CONFIG,
    ".fullsend/agents/triage.yaml": HARNESS,
    ".fullsend/agents/triage.md": AGENT,
    ".fullsend/policies/github-emulator.yaml": POLICY,
    ".fullsend/scripts/post-triage.sh": POST_SCRIPT,
}


def push_files() -> str:
    remote = f"https://x-access-token:{TOKEN}@github.local/{ORG}/{REPO}.git"
    with __import__("tempfile").TemporaryDirectory(prefix="fullsend-m7-seed-") as temp:
        directory = Path(temp)
        run_git(directory, "init", "--initial-branch=main")
        run_git(directory, "config", "user.name", "Breadboard M7 Seed")
        run_git(directory, "config", "user.email", "breadboard-m7@localhost")
        run_git(directory, "remote", "add", "origin", remote)
        fetched = run_git(directory, "fetch", "origin", "main", check=False)
        if fetched.returncode == 0:
            run_git(directory, "reset", "--hard", "FETCH_HEAD")
        for relative, content in FILES.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        run_git(directory, "add", *FILES)
        if run_git(directory, "diff", "--cached", "--quiet", check=False).returncode != 0:
            run_git(directory, "commit", "-m", "Add M7 Fullsend Actions scenario")
            run_git(directory, "push", "-u", "origin", "main")
        return run_git(directory, "rev-parse", "HEAD").stdout.strip()


def wait_for_run(run_id: int) -> dict:
    deadline = time.time() + 900
    while time.time() < deadline:
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}")
        if status == 200 and isinstance(payload, dict) and payload.get("status") == "completed":
            return payload
        time.sleep(2)
    raise RuntimeError(f"workflow run {run_id} did not complete within 900 seconds")


def main() -> int:
    ensure_org()
    ensure_repo()
    issue_number = ensure_issue()
    status, before = api_request("GET", f"/repos/{ORG}/{REPO}/issues/{issue_number}/comments")
    if status != 200 or not isinstance(before, list):
        raise RuntimeError(f"GET comments failed: HTTP {status}: {before}")
    commit = push_files()

    status, workflows = api_request("GET", f"/repos/{ORG}/{REPO}/actions/workflows")
    if status != 200:
        raise RuntimeError(f"GET workflows failed: HTTP {status}: {workflows}")
    workflow = next(item for item in workflows.get("workflows", []) if item.get("path") == WORKFLOW)
    workflow_id = int(workflow["id"])
    status, payload = api_request(
        "POST",
        f"/repos/{ORG}/{REPO}/actions/workflows/{workflow_id}/dispatches",
        {"ref": "main", "inputs": {"issue_number": str(issue_number)}},
    )
    if status != 204:
        raise RuntimeError(f"POST workflow dispatch failed: HTTP {status}: {payload}")

    status, runs = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs")
    if status != 200:
        raise RuntimeError(f"GET workflow runs failed: HTTP {status}: {runs}")
    candidates = [
        item for item in runs.get("workflow_runs", [])
        if int(item.get("workflow_id", 0)) == workflow_id
        or item.get("path") == WORKFLOW
    ]
    if not candidates:
        raise RuntimeError("workflow dispatch created no M7 run")
    run = max(candidates, key=lambda item: int(item["id"]))
    run_id = int(run["id"])
    result = wait_for_run(run_id)

    status, jobs = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}/jobs")
    if status != 200:
        raise RuntimeError(f"GET workflow jobs failed: HTTP {status}: {jobs}")
    status, after = api_request("GET", f"/repos/{ORG}/{REPO}/issues/{issue_number}/comments")
    if status != 200 or not isinstance(after, list):
        raise RuntimeError(f"GET final comments failed: HTTP {status}: {after}")
    marker_comments = [item for item in after if "fullsend-dev-stack:triage" in str(item.get("body", ""))]
    if len(after) <= len(before) or not marker_comments:
        raise RuntimeError("M7 completed without a new marked emulator comment")

    print(json.dumps({
        "status": "passed" if result.get("conclusion") == "success" else "failed",
        "commit": commit,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "run_status": result.get("status"),
        "run_conclusion": result.get("conclusion"),
        "jobs": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "status": item.get("status"),
                "conclusion": item.get("conclusion"),
                "runner_name": item.get("runner_name"),
            }
            for item in jobs.get("jobs", [])
        ],
        "issue_number": issue_number,
        "comment_count_before": len(before),
        "comment_count_after": len(after),
        "marker_comment_count": len(marker_comments),
    }, indent=2))
    return 0 if result.get("conclusion") == "success" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, StopIteration) as exc:
        print(f"M7 seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
