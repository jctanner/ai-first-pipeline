#!/usr/bin/env python3
"""Seed and verify a workflow executed by the upstream actions/runner binary."""

from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.request

from m1_seed import API_URL, ORG, REPO, TOKEN, api_request, ensure_org, ensure_repo, push_workflow


WORKFLOW = ".github/workflows/m8-upstream-runner.yml"
WORKFLOW_CONTENT = r'''name: M8 upstream actions runner

on:
  workflow_dispatch:

jobs:
  protocol:
    name: Upstream runner protocol smoke
    runs-on: [self-hosted, linux, fullsend-real]
    steps:
      - name: Verify runner environment
        run: |
          set -eu
          test -n "${GITHUB_RUN_ID}"
          test -n "${GITHUB_JOB}"
          test -n "${GITHUB_WORKSPACE}"
          printf 'm8-upstream-runner-ok run=%s job=%s\n' "${GITHUB_RUN_ID}" "${GITHUB_JOB}"
'''


def raw_api_request(path: str) -> tuple[int, str]:
    request = urllib.request.Request(
        f"{API_URL}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"token {TOKEN}",
            "User-Agent": "breadboard-fullsend-m8-seed",
        },
    )
    context = ssl._create_unverified_context()
    with urllib.request.urlopen(request, context=context) as response:
        return response.status, response.read().decode(errors="replace")


def dispatch(workflow_id: int) -> int:
    status, payload = api_request(
        "POST",
        f"/repos/{ORG}/{REPO}/actions/workflows/{workflow_id}/dispatches",
        {"ref": "main", "inputs": {}},
    )
    if status != 204:
        raise RuntimeError(f"dispatch failed: HTTP {status}: {payload}")
    deadline = time.time() + 30
    while time.time() < deadline:
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs")
        if status == 200:
            for run in payload.get("workflow_runs", []):
                if run.get("workflow_id") == workflow_id:
                    return int(run["id"])
        time.sleep(1)
    raise RuntimeError("dispatch did not create a workflow run")


def wait_for_run(run_id: int) -> dict:
    deadline = time.time() + 180
    while time.time() < deadline:
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}")
        if status == 200 and payload.get("status") == "completed":
            return payload
        time.sleep(2)
    raise RuntimeError(f"run {run_id} did not complete")


def main() -> int:
    ensure_org()
    ensure_repo()
    commit = push_workflow(WORKFLOW, WORKFLOW_CONTENT, "Add M8 upstream runner smoke")
    workflow = None
    for _ in range(30):
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/workflows")
        if status != 200:
            raise RuntimeError(f"workflow listing failed: HTTP {status}: {payload}")
        workflow = next((item for item in payload.get("workflows", []) if item.get("path") == WORKFLOW), None)
        if workflow is not None:
            break
        time.sleep(1)
    if workflow is None:
        raise RuntimeError(f"workflow was not indexed: {WORKFLOW}")
    run_id = dispatch(int(workflow["id"]))
    run = wait_for_run(run_id)
    status, jobs_payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run_id}/jobs")
    if status != 200:
        raise RuntimeError(f"job listing failed: HTTP {status}: {jobs_payload}")
    jobs = []
    for job in jobs_payload.get("jobs", []):
        job_status, logs = raw_api_request(f"/repos/{ORG}/{REPO}/actions/jobs/{job['id']}/logs")
        jobs.append({
            "id": job.get("id"),
            "name": job.get("name"),
            "status": job.get("status"),
            "conclusion": job.get("conclusion"),
            "runner_name": job.get("runner_name"),
            "logs_status": job_status,
            "marker": "m8-upstream-runner-ok" in (logs if isinstance(logs, str) else ""),
        })
    if run.get("conclusion") != "success" or not jobs or not all(item["marker"] for item in jobs):
        raise RuntimeError(json.dumps({"run": run, "jobs": jobs}, indent=2))
    print(json.dumps({
        "status": "passed",
        "commit": commit,
        "workflow_id": workflow["id"],
        "run_id": run_id,
        "run_conclusion": run.get("conclusion"),
        "jobs": jobs,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
