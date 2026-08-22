#!/usr/bin/env python3
"""Seed and dispatch the pinned Fullsend review agent against a local PR."""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

from m1_seed import API_URL, ORG, REPO, TOKEN, api_request, ensure_org, ensure_repo, run_git


ROOT = Path(__file__).resolve().parents[4]
AGENTS = ROOT / "checkouts" / "fullsend-agents"
FULLSEND = ROOT / "checkouts.tmp" / "fullsend"
WORKFLOW = ".github/workflows/m10-fullsend-review.yml"
APP_ACTION = ".github/actions/mint-token/action.yml"
BRANCH = "m10-review-fixture"
FIXTURE_FILE = "src/review_fixture.py"


WORKFLOW_CONTENT = r'''name: M10 Fullsend review

on:
  workflow_dispatch:
    inputs:
      pr_number:
        required: true
        type: string

jobs:
  review:
    name: Fullsend upstream review
    runs-on: [self-hosted, linux, fullsend]
    permissions:
      contents: read
      id-token: write
      pull-requests: write
      issues: write
    env:
      GITHUB_PR_URL: https://github.com/fullsend-dev/triage-target/pull/${{ inputs.pr_number }}
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
      REPO_FULL_NAME: fullsend-dev/triage-target
      PR_NUMBER: ${{ inputs.pr_number }}
      GITHUB_PR_NUMBER: ${{ inputs.pr_number }}
      PRIOR_REVIEW_SHA: ""
      PRIOR_REVIEW_PROVENANCE: none
      REVIEW_SKIP_AUTHORS: ""
    steps:
      - name: Checkout target repository
        uses: actions/checkout@v4
      - name: Mint review token through the real Fullsend action
        id: app-token
        uses: ./.github/actions/mint-token
        with:
          role: review
          repos: fullsend-dev/triage-target
          mint_url: http://fullsend-mint-dev.ai-pipeline.svc.cluster.local:8080
      - name: Refresh local Vertex profile
        run: |
          set -eu
          openshell sandbox list | awk '$1 ~ /^agent-review-/ {print $1}' | while read -r sandbox; do
            openshell sandbox delete "${sandbox}" 2>/dev/null || true
          done
          openshell provider profile delete fullsend-vertex-ai 2>/dev/null || true
          openshell provider profile import \
            --file "${GITHUB_WORKSPACE}/.fullsend/profiles/fullsend-vertex-ai.yaml"
      - name: Run the real Fullsend review agent
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
          REPO_FULL_NAME: fullsend-dev/triage-target
          PR_NUMBER: ${{ inputs.pr_number }}
          MINT_REPOS: triage-target
        run: |
          set -eu
          fullsend run review \
            --fullsend-dir "${GITHUB_WORKSPACE}/.fullsend" \
            --target-repo "${GITHUB_WORKSPACE}" \
            --output-dir "${GITHUB_WORKSPACE}/output" \
            --debug=api \
            --forge github
      - name: Verify review is visible in the emulator
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
        run: |
          set -eu
          reviews="$(curl -kfsS -H "Authorization: token ${GH_TOKEN:-${GITHUB_TOKEN:-}}" \
            "${GITHUB_API_URL}/repos/fullsend-dev/triage-target/pulls/${{ inputs.pr_number }}/reviews")"
          comments="$(curl -kfsS -H "Authorization: token ${GH_TOKEN:-${GITHUB_TOKEN:-}}" \
            "${GITHUB_API_URL}/repos/fullsend-dev/triage-target/issues/${{ inputs.pr_number }}/comments")"
          test "$(jq -r 'length > 0' <<<"${reviews}")" = true || \
            test "$(jq -r 'length > 0' <<<"${comments}")" = true
          printf 'M10 review API result is visible\n'
'''


def _copy(relative: str) -> str:
    source = AGENTS / relative
    if not source.is_file():
        raise RuntimeError(f"pinned Fullsend review file is missing: {source}")
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
  - host: "*.aiplatform.googleapis.com"
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


def _review_harness() -> str:
    content = _copy("harness/review.yaml")
    content = content.replace(
        "image: ghcr.io/fullsend-ai/fullsend-code@sha256:de3ecbd7719a1927c983142ada96475f3314d2505d0f258bcf19c31411856eb6",
        "image: fullsend-sandbox-dev:k3s",
    )
    content = content.replace(
        "        FULLSEND_FORGE: github\n",
        "        FULLSEND_FORGE: github\n        GH_HOST: github.local\n        GITHUB_API_URL: https://github.local/api/v3\n        NO_SSL_VERIFY: \"1\"\n",
    )
    content = content.replace(
        '        GH_TOKEN: "${GH_TOKEN}"\n',
        '        GH_TOKEN: "${GH_TOKEN}"\n        GH_ENTERPRISE_TOKEN: "${REVIEW_TOKEN}"\n',
    )
    return content


def _review_env() -> str:
    return (
        'export PR_URL="${GITHUB_PR_URL}"\n'
        'export GH_TOKEN="${GH_TOKEN}"\n'
        'export GH_ENTERPRISE_TOKEN="${REVIEW_TOKEN:-${GH_TOKEN}}"\n'
        'export PR_NUMBER="${PR_NUMBER}"\n'
        'export REPO_FULL_NAME="${REPO_FULL_NAME}"\n'
        'export PRIOR_REVIEW_SHA="${PRIOR_REVIEW_SHA:-}"\n'
        'export PRIOR_REVIEW_PROVENANCE="${PRIOR_REVIEW_PROVENANCE:-none}"\n'
        'export REVIEW_FINDING_SEVERITY_THRESHOLD="${REVIEW_FINDING_SEVERITY_THRESHOLD}"\n'
        'export REVIEW_SKIP_AUTHORS="${REVIEW_SKIP_AUTHORS:-}"\n'
    )


def _post_review_script() -> str:
    """Use the GitHub REST files endpoint instead of gh's GraphQL files field.

    The GitHub emulator intentionally implements changed files through the
    standard REST endpoint.  The upstream ``gh pr view --json files`` query
    currently asks for a GraphQL connection that is not implemented there.
    REST is also supported by GitHub.com and GitHub Enterprise, so this keeps
    the local adaptation suitable for an upstream compatibility patch.
    """
    content = _copy("scripts/post-review.sh")
    old = '''forge_get_pr_files() {
  GH_TOKEN="${REVIEW_TOKEN}" gh pr view "${PR_NUMBER}" \\
    --repo "${REPO}" --json files --jq '.files[].path'
}'''
    new = '''forge_get_pr_files() {
  GH_TOKEN="${REVIEW_TOKEN}" gh api \\
    "repos/${REPO}/pulls/${PR_NUMBER}/files" \\
    --paginate --jq '.[].filename'
}'''
    if old not in content:
        raise RuntimeError("pinned post-review.sh changed: REST compatibility patch no longer applies")
    return content.replace(old, new, 1)


def files_to_push() -> dict[str, str]:
    files: dict[str, str] = {
        WORKFLOW: WORKFLOW_CONTENT,
        ".fullsend/config.yaml": 'version: "1"\nruntime: claude\nroles: [review]\nagents:\n  - source: agents/review.yaml\n',
        ".fullsend/agents/review.yaml": _review_harness(),
        ".fullsend/agents/review.md": _copy("agents/review.md"),
        ".fullsend/docs/review.md": _copy("docs/review.md"),
        ".fullsend/scripts/pre-review.sh": _copy("scripts/pre-review.sh"),
        ".fullsend/scripts/post-review.sh": _post_review_script(),
        ".fullsend/scripts/validate-output-schema.sh": _copy("scripts/validate-output-schema.sh"),
        ".fullsend/schemas/review-result.schema.json": _copy("schemas/review-result.schema.json"),
        ".fullsend/env/github/review.env": _review_env(),
        ".fullsend/env/gcp-vertex.env": _copy("env/gcp-vertex.env"),
        ".fullsend/policies/base.yaml": _copy("policies/base.yaml"),
        ".fullsend/policies/github/review.yaml": _copy("policies/github/review.yaml"),
        ".fullsend/profiles/fullsend-vertex-ai.yaml": _vertex_profile(),
        ".fullsend/profiles/fullsend-github-ro.yaml": _copy("profiles/fullsend-github-ro.yaml").replace("api.github.com", "github.local").replace("github.com", "github.local"),
        ".fullsend/providers/vertex-ai.yaml": _copy("providers/vertex-ai.yaml"),
        ".fullsend/providers/github-ro.yaml": _copy("providers/github-ro.yaml"),
        ".fullsend/.github/actions/mint-token/action.yml": (FULLSEND / ".github/actions/mint-token/action.yml").read_text(encoding="utf-8"),
        APP_ACTION: (FULLSEND / ".github/actions/mint-token/action.yml").read_text(encoding="utf-8"),
    }
    for relative in (
        "skills/pr-review/SKILL.md",
        "skills/pr-review/meta-prompt.md",
        "skills/code-review/SKILL.md",
        "skills/docs-review/SKILL.md",
        "skills/pr-review/github/SKILL.md",
        "skills/github-forge/SKILL.md",
        "skills/issue-labels/github/SKILL.md",
    ):
        files[f".fullsend/{relative}"] = _copy(relative)
    for subagent in (AGENTS / "skills/pr-review/sub-agents").glob("*.md"):
        relative = subagent.relative_to(AGENTS)
        files[f".fullsend/{relative}"] = subagent.read_text(encoding="utf-8")
    return files


def push_main_files() -> str:
    remote = f"https://x-access-token:{TOKEN}@github.local/{ORG}/{REPO}.git"
    files = files_to_push()
    with tempfile.TemporaryDirectory(prefix="fullsend-m10-seed-") as temp:
        directory = Path(temp)
        run_git(directory, "init", "--initial-branch=main")
        run_git(directory, "config", "user.name", "Breadboard M10 Seed")
        run_git(directory, "config", "user.email", "breadboard-m10@localhost")
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
            run_git(directory, "commit", "-m", "Run the pinned Fullsend review agent")
            pushed = run_git(directory, "push", "-u", "origin", "main", check=False)
            if pushed.returncode != 0:
                raise RuntimeError(f"git push failed ({pushed.returncode}): {pushed.stderr or pushed.stdout}")
        return run_git(directory, "rev-parse", "HEAD").stdout.strip()


def ensure_review_branch() -> None:
    remote = f"https://x-access-token:{TOKEN}@github.local/{ORG}/{REPO}.git"
    with tempfile.TemporaryDirectory(prefix="fullsend-m10-pr-") as temp:
        directory = Path(temp)
        run_git(directory, "init", "--initial-branch=main")
        run_git(directory, "config", "user.name", "Breadboard M10 Fixture")
        run_git(directory, "config", "user.email", "breadboard-m10-fixture@localhost")
        run_git(directory, "remote", "add", "origin", remote)
        run_git(directory, "fetch", "origin", "main")
        run_git(directory, "fetch", "origin", BRANCH, check=False)
        branch_exists = run_git(directory, "show-ref", "--verify", f"refs/remotes/origin/{BRANCH}", check=False).returncode == 0
        if branch_exists:
            run_git(directory, "checkout", "-B", BRANCH, f"origin/{BRANCH}")
        else:
            run_git(directory, "checkout", "-B", BRANCH, "origin/main")
        fixture = directory / FIXTURE_FILE
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(
            '"""Small non-protected change used by the M10 review fixture."""\n\n\ndef greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
            encoding="utf-8",
        )
        run_git(directory, "add", FIXTURE_FILE)
        if run_git(directory, "diff", "--cached", "--quiet", check=False).returncode != 0:
            run_git(directory, "commit", "-m", "Add review fixture")
            pushed = run_git(directory, "push", "-u", "origin", BRANCH, check=False)
            if pushed.returncode != 0:
                raise RuntimeError(f"review fixture push failed ({pushed.returncode}): {pushed.stderr or pushed.stdout}")


def ensure_pull_request() -> int:
    status, pulls = api_request("GET", f"/repos/{ORG}/{REPO}/pulls?state=open")
    if status != 200 or not isinstance(pulls, list):
        raise RuntimeError(f"GET open pulls failed: HTTP {status}: {pulls}")
    for pull in pulls:
        if (pull.get("head") or {}).get("ref") == BRANCH:
            return int(pull["number"])
    status, pull = api_request(
        "POST",
        f"/repos/{ORG}/{REPO}/pulls",
        {
            "title": "M10 review fixture",
            "body": "Small non-protected change for the repeatable Fullsend review-agent scenario.",
            "head": BRANCH,
            "base": "main",
        },
    )
    if status not in (200, 201) or not isinstance(pull, dict):
        raise RuntimeError(f"POST pull request failed: HTTP {status}: {pull}")
    return int(pull["number"])


def wait_for_run(run_id: int) -> dict:
    deadline = time.time() + 1500
    while time.time() < deadline:
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}")
        if status == 200 and isinstance(payload, dict) and payload.get("status") == "completed":
            return payload
        time.sleep(3)
    raise RuntimeError(f"workflow run {run_id} did not complete within 1500 seconds")


def main() -> int:
    ensure_org()
    ensure_repo()
    commit = push_main_files()
    ensure_review_branch()
    pr_number = ensure_pull_request()
    status, before_reviews = api_request("GET", f"/repos/{ORG}/{REPO}/pulls/{pr_number}/reviews")
    if status != 200 or not isinstance(before_reviews, list):
        raise RuntimeError(f"GET initial reviews failed: HTTP {status}: {before_reviews}")
    status, before_comments = api_request("GET", f"/repos/{ORG}/{REPO}/issues/{pr_number}/comments")
    if status != 200 or not isinstance(before_comments, list):
        raise RuntimeError(f"GET initial comments failed: HTTP {status}: {before_comments}")
    status, workflows = api_request("GET", f"/repos/{ORG}/{REPO}/actions/workflows")
    if status != 200:
        raise RuntimeError(f"GET workflows failed: HTTP {status}: {workflows}")
    workflow = next(item for item in workflows.get("workflows", []) if item.get("path") == WORKFLOW)
    workflow_id = int(workflow["id"])
    status, payload = api_request(
        "POST",
        f"/repos/{ORG}/{REPO}/actions/workflows/{workflow_id}/dispatches",
        {"ref": "main", "inputs": {"pr_number": str(pr_number)}},
    )
    if status != 204:
        raise RuntimeError(f"POST workflow dispatch failed: HTTP {status}: {payload}")
    candidates: list[dict] = []
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
        raise RuntimeError("workflow dispatch created no M10 run")
    run_id = int(max(candidates, key=lambda item: int(item["id"]))["id"])
    result = wait_for_run(run_id)
    status, jobs = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}/jobs")
    if status != 200:
        raise RuntimeError(f"GET workflow jobs failed: HTTP {status}: {jobs}")
    status, after_reviews = api_request("GET", f"/repos/{ORG}/{REPO}/pulls/{pr_number}/reviews")
    if status != 200 or not isinstance(after_reviews, list):
        raise RuntimeError(f"GET final reviews failed: HTTP {status}: {after_reviews}")
    status, after_comments = api_request("GET", f"/repos/{ORG}/{REPO}/issues/{pr_number}/comments")
    if status != 200 or not isinstance(after_comments, list):
        raise RuntimeError(f"GET final comments failed: HTTP {status}: {after_comments}")
    before_review_ids = {item.get("id") for item in before_reviews}
    before_comment_ids = {item.get("id") for item in before_comments}
    new_reviews = [item for item in after_reviews if item.get("id") not in before_review_ids]
    new_comments = [item for item in after_comments if item.get("id") not in before_comment_ids]
    if not new_reviews and not new_comments:
        raise RuntimeError("M10 completed without a new review or review comment")
    print(json.dumps({
        "status": "passed" if result.get("conclusion") == "success" else "failed",
        "commit": commit,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "run_status": result.get("status"),
        "run_conclusion": result.get("conclusion"),
        "pull_request": pr_number,
        "branch": BRANCH,
        "jobs": [{"id": item.get("id"), "name": item.get("name"), "status": item.get("status"), "conclusion": item.get("conclusion")} for item in jobs.get("jobs", [])],
        "new_review_count": len(new_reviews),
        "new_comment_count": len(new_comments),
        "review_states": [item.get("state") for item in new_reviews],
    }, indent=2))
    return 0 if result.get("conclusion") == "success" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, StopIteration) as exc:
        print(f"M10 seed failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
