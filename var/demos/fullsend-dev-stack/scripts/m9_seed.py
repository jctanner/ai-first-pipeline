#!/usr/bin/env python3
"""Seed and dispatch the real pinned Fullsend triage harness.

This is intentionally separate from m7_seed.py. M7 remains a small plumbing
fixture; M9 copies the actual triage agent, scripts, skills, policy, and output
schema from the pinned fullsend-ai/agents checkout.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from m1_seed import API_URL, ORG, REPO, TOKEN, api_request, ensure_issue, ensure_org, ensure_repo, run_git


ROOT = Path(__file__).resolve().parents[4]
AGENTS = ROOT / "checkouts" / "fullsend-agents"
FULLSEND = ROOT / "checkouts.tmp" / "fullsend"
WORKFLOW = ".github/workflows/m9-fullsend-triage.yml"
APP_ACTION = ".github/actions/mint-token/action.yml"


WORKFLOW_CONTENT = r'''name: M9 Fullsend real triage

on:
  workflow_dispatch:
    inputs:
      issue_number:
        required: false
        default: "1"
        type: string

jobs:
  triage:
    name: Fullsend upstream triage
    runs-on: [self-hosted, linux, fullsend]
    permissions:
      contents: read
      id-token: write
      issues: write
    env:
      # Keep the issue URL in GitHub's documented shape because the upstream
      # triage scripts validate it. GH_HOST routes gh CLI requests locally.
      GITHUB_ISSUE_URL: https://github.com/fullsend-dev/triage-target/issues/${{ inputs.issue_number }}
      GITHUB_API_URL: https://github.local/api/v3
      GITHUB_SERVER_URL: https://github.local
      GH_HOST: github.local
      FULLSEND_FORGE: github
      FULLSEND_MINT_URL: http://fullsend-mint-dev.ai-pipeline.svc.cluster.local:8080
      NO_SSL_VERIFY: "1"
      CLAUDE_CODE_USE_VERTEX: "1"
      CLOUD_ML_REGION: global
      GOOGLE_APPLICATION_CREDENTIALS: /var/run/secrets/gcp/credentials.json
      OPENSHELL_GATEWAY_ENDPOINT: http://openshell.openshell-system.svc.cluster.local:8080
      OPENSHELL_GATEWAY_NAME: openshell
    steps:
      - name: Checkout target repository
        uses: actions/checkout@v4
      - name: Mint triage token through the real Fullsend action
        id: app-token
        uses: ./.github/actions/mint-token
        with:
          role: triage
          repos: fullsend-dev/triage-target
          mint_url: http://fullsend-mint-dev.ai-pipeline.svc.cluster.local:8080
      - name: Refresh local Vertex profile
        run: |
          set -eu
          openshell sandbox list | awk '$1 ~ /^agent-triage-/ {print $1}' | while read -r sandbox; do
            openshell sandbox delete "${sandbox}" 2>/dev/null || true
          done
          openshell provider profile delete fullsend-vertex-ai 2>/dev/null || true
          openshell provider profile import \
            --file "${GITHUB_WORKSPACE}/.fullsend/profiles/fullsend-vertex-ai.yaml"
      - name: Run the real Fullsend triage agent
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
          REPO_FULL_NAME: fullsend-dev/triage-target
          MINT_REPOS: triage-target
        run: |
          set -eu
          fullsend run triage \
            --fullsend-dir "${GITHUB_WORKSPACE}/.fullsend" \
            --target-repo "${GITHUB_WORKSPACE}" \
            --output-dir "${GITHUB_WORKSPACE}/output" \
            --debug=api \
            --forge github
      - name: Verify agent-owned emulator result
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
        run: |
          set -eu
          comments="$(curl -kfsS -H "Authorization: token ${GH_TOKEN}" \
            "${GITHUB_API_URL}/repos/fullsend-dev/triage-target/issues/${{ inputs.issue_number }}/comments")"
          test "$(jq -r 'length > 0' <<<"${comments}")" = true
          printf 'M9 real Fullsend triage API result is visible\n'
'''


def _copy(relative: str) -> str:
    source = AGENTS / relative
    if not source.is_file():
        raise RuntimeError(f"pinned Fullsend agent file is missing: {source}")
    return source.read_text(encoding="utf-8")


def _vertex_profile() -> str:
    content = _copy("profiles/fullsend-vertex-ai.yaml")
    explicit_endpoints = """endpoints:
  - host: oauth2.googleapis.com
    port: 443
    protocol: rest
    access: read-write
    enforcement: enforce
  - host: aiplatform.googleapis.com
    port: 443
    protocol: rest
    access: read-write
    enforcement: enforce
  - host: \"*.aiplatform.googleapis.com\"
    port: 443
    protocol: rest
    access: read-write
    enforcement: enforce
"""
    content = content.replace("endpoints:\n", explicit_endpoints, 1)
    explicit_binaries = """binaries:
  - /usr/bin/node
  - /usr/local/bin/node
  - /usr/local/lib/node_modules/@anthropic-ai/claude-code/**
"""
    return content.replace(
        'binaries:\n  - "**/claude"\n  - "**/node"\n',
        explicit_binaries,
        1,
    )


def _triage_harness() -> str:
    content = _copy("harness/triage.yaml")
    content = content.replace(
        "image: ghcr.io/fullsend-ai/fullsend-sandbox@sha256:eaf365ad038d762954d8fd5f41618cd6766a8a6a6f76d944aaf160819666734d",
        "image: fullsend-sandbox-dev:k3s",
    )
    content = content.replace(
        "        FULLSEND_FORGE: github\n",
        "        FULLSEND_FORGE: github\n        GH_HOST: github.local\n        GITHUB_API_URL: https://github.local/api/v3\n        NO_SSL_VERIFY: \"1\"\n",
    )
    content = content.replace(
        "        GH_TOKEN: ${GH_TOKEN}\n",
        "        GH_TOKEN: ${GH_TOKEN}\n        GH_ENTERPRISE_TOKEN: ${GH_TOKEN}\n",
    )
    content = content.replace(
        '        GH_TOKEN: \"${GH_TOKEN}\"\n',
        '        GH_TOKEN: \"${GH_TOKEN}\"\n        GH_ENTERPRISE_TOKEN: \"${GH_TOKEN}\"\n',
    )
    return content


def _triage_env() -> str:
    return (
        'export ISSUE_URL="${GITHUB_ISSUE_URL}"\n'
        'export GH_TOKEN="${GH_TOKEN}"\n'
        'export GH_HOST="${GH_HOST:-github.local}"\n'
    )


def files_to_push() -> dict[str, str]:
    files: dict[str, str] = {
        WORKFLOW: WORKFLOW_CONTENT,
        ".fullsend/config.yaml": """version: \"1\"\nruntime: claude\nroles: [triage]\nagents:\n  - source: agents/triage.yaml\n""",
        ".fullsend/agents/triage.yaml": _triage_harness(),
        ".fullsend/agents/triage.md": _copy("agents/triage.md"),
        ".fullsend/docs/triage.md": _copy("docs/triage.md"),
        ".fullsend/scripts/pre-triage.sh": _copy("scripts/pre-triage.sh"),
        ".fullsend/scripts/post-triage.sh": _copy("scripts/post-triage.sh"),
        ".fullsend/scripts/prepare-sandbox-credentials.sh": _copy("scripts/prepare-sandbox-credentials.sh"),
        ".fullsend/scripts/validate-output-schema.sh": _copy("scripts/validate-output-schema.sh"),
        ".fullsend/schemas/triage-result.schema.json": _copy("schemas/triage-result.schema.json"),
        ".fullsend/env/github/triage.env": _triage_env(),
        ".fullsend/env/gcp-vertex.env": _copy("env/gcp-vertex.env"),
        ".fullsend/policies/base.yaml": _copy("policies/base.yaml"),
        ".fullsend/profiles/fullsend-vertex-ai.yaml": _vertex_profile(),
        ".fullsend/providers/vertex-ai.yaml": _copy("providers/vertex-ai.yaml"),
        ".fullsend/providers/github-ro.yaml": _copy("providers/github-ro.yaml"),
        ".fullsend/.github/actions/mint-token/action.yml": (FULLSEND / ".github/actions/mint-token/action.yml").read_text(encoding="utf-8"),
        APP_ACTION: (FULLSEND / ".github/actions/mint-token/action.yml").read_text(encoding="utf-8"),
    }
    profile = _copy("profiles/fullsend-github-ro.yaml").replace("api.github.com", "github.local").replace("github.com", "github.local")
    files[".fullsend/profiles/fullsend-github-ro.yaml"] = profile
    for relative in ("skills/github-forge/SKILL.md", "skills/issue-labels/github/SKILL.md"):
        files[f".fullsend/{relative}"] = _copy(relative)
    return files


def push_files() -> str:
    remote = f"https://x-access-token:{TOKEN}@github.local/{ORG}/{REPO}.git"
    files = files_to_push()
    with tempfile.TemporaryDirectory(prefix="fullsend-m9-seed-") as temp:
        directory = Path(temp)
        run_git(directory, "init", "--initial-branch=main")
        run_git(directory, "config", "user.name", "Breadboard M9 Seed")
        run_git(directory, "config", "user.email", "breadboard-m9@localhost")
        run_git(directory, "remote", "add", "origin", remote)
        fetched = run_git(directory, "fetch", "origin", "main", check=False)
        if fetched.returncode == 0:
            run_git(directory, "reset", "--hard", "FETCH_HEAD")
        for relative, content in files.items():
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        run_git(directory, "add", *files)
        if run_git(directory, "diff", "--cached", "--quiet", check=False).returncode != 0:
            run_git(directory, "commit", "-m", "Run the pinned Fullsend triage agent")
            pushed = run_git(directory, "push", "-u", "origin", "main", check=False)
            if pushed.returncode != 0:
                raise RuntimeError(f"git push failed ({pushed.returncode}): {pushed.stderr or pushed.stdout}")
        return run_git(directory, "rev-parse", "HEAD").stdout.strip()


def wait_for_run(run_id: int) -> dict:
    deadline = time.time() + 1200
    while time.time() < deadline:
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}")
        if status == 200 and isinstance(payload, dict) and payload.get("status") == "completed":
            return payload
        time.sleep(3)
    raise RuntimeError(f"workflow run {run_id} did not complete within 1200 seconds")


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
    candidates = []
    for _ in range(30):
        status, runs = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs")
        if status != 200:
            raise RuntimeError(f"GET workflow runs failed: HTTP {status}: {runs}")
        candidates = [
            item for item in runs.get("workflow_runs", [])
            if int(item.get("workflow_id", 0)) == workflow_id or item.get("path") == WORKFLOW
        ]
        if candidates:
            break
        time.sleep(1)
    if not candidates:
        raise RuntimeError("workflow dispatch created no M9 run")
    run_id = int(max(candidates, key=lambda item: int(item["id"]))["id"])
    result = wait_for_run(run_id)
    status, jobs = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}/jobs")
    if status != 200:
        raise RuntimeError(f"GET workflow jobs failed: HTTP {status}: {jobs}")
    status, after = api_request("GET", f"/repos/{ORG}/{REPO}/issues/{issue_number}/comments")
    if status != 200 or not isinstance(after, list):
        raise RuntimeError(f"GET final comments failed: HTTP {status}: {after}")
    before_ids = {item.get("id") for item in before}
    new_comments = [item for item in after if item.get("id") not in before_ids]
    marker_comments = [item for item in new_comments if "fullsend:triage-agent" in str(item.get("body", ""))]
    if not new_comments:
        raise RuntimeError("M9 completed without a new agent-owned triage comment")
    print(json.dumps({
        "status": "passed" if result.get("conclusion") == "success" else "failed",
        "commit": commit,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "run_status": result.get("status"),
        "run_conclusion": result.get("conclusion"),
        "jobs": [{"id": item.get("id"), "name": item.get("name"), "status": item.get("status"), "conclusion": item.get("conclusion")} for item in jobs.get("jobs", [])],
        "issue_number": issue_number,
        "comment_count_before": len(before),
        "comment_count_after": len(after),
        "agent_comment_count": len(new_comments),
        "agent_marker_comment_count": len(marker_comments),
    }, indent=2))
    return 0 if result.get("conclusion") == "success" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, StopIteration) as exc:
        print(f"M9 seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
