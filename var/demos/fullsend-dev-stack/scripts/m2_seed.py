#!/usr/bin/env python3
"""Seed and dispatch the reduced Fullsend-shaped M2 workflow."""

from __future__ import annotations

import json
import sys
import time

from m1_seed import (
    API_URL,
    ORG,
    REPO,
    api_request,
    ensure_issue,
    ensure_org,
    ensure_repo,
    push_workflow,
)


WORKFLOW = ".github/workflows/m2-fullsend-shaped.yml"
WORKFLOW_CONTENT = """name: M2 Fullsend-shaped smoke

on:
  workflow_dispatch:
    inputs:
      agent:
        required: true
        type: string
      message:
        required: false
        default: "M2 default message"
        type: string

jobs:
  fullsend:
    name: Reduced Fullsend run
    runs-on: [self-hosted, linux, fullsend]
    env:
      FULLSEND_AGENT: ${{ inputs.agent }}
      FULLSEND_MESSAGE: ${{ inputs.message }}
      FULLSEND_M2_MARKER: ${{ vars.FULLSEND_M2_MARKER }}
    steps:
      - name: Checkout target repository
        uses: actions/checkout@v4
      - name: Run reduced Fullsend step
        id: fullsend
        run: |
          set -eu
          test -f .github/workflows/m1-runner-smoke.yml
          test "${FULLSEND_AGENT}" = "triage"
          test "${FULLSEND_M2_MARKER}" = "m2-ready"
          printf 'fullsend run reached for %s: %s\\n' "${FULLSEND_AGENT}" "${FULLSEND_MESSAGE}"
          printf 'result=fullsend-run-reached\\n' >> "${GITHUB_OUTPUT}"
          printf 'FULLSEND_RESULT=fullsend-run-reached\\n' >> "${GITHUB_ENV}"
      - name: Verify command files
        run: test "${FULLSEND_RESULT}" = "fullsend-run-reached"
"""


def ensure_variable() -> None:
    status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/variables")
    if status != 200:
        raise RuntimeError(f"GET variables failed: HTTP {status}: {payload}")
    if any(item.get("name") == "FULLSEND_M2_MARKER" for item in payload.get("variables", [])):
        return
    status, payload = api_request(
        "POST", f"/repos/{ORG}/{REPO}/actions/variables",
        {"name": "FULLSEND_M2_MARKER", "value": "m2-ready"},
    )
    if status not in (201, 422):
        raise RuntimeError(f"POST variable failed: HTTP {status}: {payload}")


def dispatch() -> tuple[int, int]:
    workflow = None
    for _ in range(30):
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/workflows")
        if status != 200:
            raise RuntimeError(f"GET workflows failed: HTTP {status}: {payload}")
        workflow = next(
            (item for item in payload["workflows"] if item["path"] == WORKFLOW),
            None,
        )
        if workflow is not None:
            break
        time.sleep(1)
    if workflow is None:
        raise RuntimeError(f"Workflow was not indexed: {WORKFLOW}")
    status, payload = api_request(
        "POST", f"/repos/{ORG}/{REPO}/actions/workflows/{workflow['id']}/dispatches",
        {"ref": "main", "inputs": {"agent": "triage", "message": "M2 dispatch smoke"}},
    )
    if status != 204:
        raise RuntimeError(f"POST dispatch failed: HTTP {status}: {payload}")

    for _ in range(30):
        status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs")
        if status == 200:
            for run in payload.get("workflow_runs", []):
                if run.get("workflow_id") == workflow["id"]:
                    return workflow["id"], run["id"]
        time.sleep(1)
    raise RuntimeError("Dispatch did not create a workflow run")


def main() -> None:
    ensure_org()
    ensure_repo()
    ensure_issue()
    ensure_variable()
    commit = push_workflow(WORKFLOW, WORKFLOW_CONTENT, "Add M2 Fullsend-shaped smoke workflow")
    workflow_id, run_id = dispatch()
    print(json.dumps({
        "status": "dispatched",
        "repository": f"{ORG}/{REPO}",
        "workflow": WORKFLOW,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "seed_commit": commit,
    }, indent=2))


if __name__ == "__main__":
    main()
