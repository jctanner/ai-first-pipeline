#!/usr/bin/env python3
"""Dispatch the mirrored M8 role matrix and verify all matrix jobs complete."""

from __future__ import annotations

import json
import time

from m1_seed import API_URL, ORG, REPO, api_request


WORKFLOW = ".github/workflows/m8-role-events.yml"


def main() -> None:
    status, workflows = api_request("GET", f"/repos/{ORG}/{REPO}/actions/workflows")
    if status != 200:
        raise RuntimeError(f"workflow list failed: HTTP {status}: {workflows}")
    workflow = next((item for item in workflows.get("workflows", []) if item.get("path") == WORKFLOW), None)
    if workflow is None:
        raise RuntimeError(f"mirrored workflow {WORKFLOW} is missing")
    workflow_id = workflow["id"]
    status, payload = api_request("POST", f"/repos/{ORG}/{REPO}/actions/workflows/{workflow_id}/dispatches", {"ref": "main", "inputs": {"role": "triage"}})
    if status != 204:
        raise RuntimeError(f"workflow dispatch failed: HTTP {status}: {payload}")
    deadline = time.time() + 300
    run = None
    while time.time() < deadline:
        status, runs = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs")
        candidates = [item for item in runs.get("workflow_runs", []) if item.get("workflow_id") == workflow_id]
        if candidates:
            run = max(candidates, key=lambda item: int(item["id"]))
            if run.get("status") == "completed":
                break
        time.sleep(2)
    if not run or run.get("status") != "completed":
        raise RuntimeError("M8 role matrix did not complete")
    status, jobs = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs/{run['id']}/jobs")
    items = jobs.get("jobs", []) if status == 200 else []
    if len(items) != 3 or any(item.get("conclusion") != "success" for item in items):
        raise RuntimeError(f"M8 role matrix failed: {items}")
    print(json.dumps({"status": "passed", "workflow_id": workflow_id, "run_id": run["id"], "event": run.get("event"), "jobs": [{"id": item["id"], "name": item["name"], "conclusion": item["conclusion"]} for item in items]}, indent=2))


if __name__ == "__main__":
    main()
