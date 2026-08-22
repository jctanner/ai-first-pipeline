#!/usr/bin/env python3
"""Seed and dispatch the M3 Fullsend mint/Vertex configuration smoke."""

from __future__ import annotations

import json
from pathlib import Path

from m1_seed import (
    ORG,
    REPO,
    api_request,
    ensure_org,
    ensure_repo,
    push_workflow,
)


WORKFLOW = ".github/workflows/m3-fullsend-mint-vertex.yml"
MINT_ACTION = ".github/actions/mint-token/action.yml"
FULLSEND_ROOT = Path(__file__).resolve().parents[4] / "checkouts.tmp" / "fullsend"

WORKFLOW_CONTENT = r'''name: M3 Fullsend mint and Vertex smoke

on:
  workflow_dispatch:

jobs:
  fullsend:
    name: Fullsend mint and Vertex configuration
    runs-on: [self-hosted, linux, fullsend]
    permissions:
      id-token: write
    steps:
      - name: Checkout target repository
        uses: actions/checkout@v4
      - name: Mint triage token through Fullsend action
        id: app-token
        uses: ./.github/actions/mint-token
        with:
          role: triage
          repos: fullsend-dev/triage-target
          mint_url: ${{ vars.FULLSEND_MINT_URL }}
      - name: Verify emulator authentication
        env:
          MINTED_TOKEN: ${{ steps.app-token.outputs.token }}
        run: |
          set -eu
          test -n "${MINTED_TOKEN}"
          test "$(curl -skSf -H "Authorization: token ${MINTED_TOKEN}" "${GITHUB_API_URL}/user" | jq -r .login)" = admin
          test "$(curl -skSf -H "Authorization: token ${MINTED_TOKEN}" "${GITHUB_API_URL}/repos/fullsend-dev/triage-target" | jq -r .full_name)" = fullsend-dev/triage-target
          printf 'fullsend mint authenticated to the emulator\n'
      - name: Initialize development Vertex backend configuration
        run: |
          set -eu
          test "${CLAUDE_CODE_USE_VERTEX}" = 1
          test -n "${CLOUD_ML_REGION}"
          test -n "${ANTHROPIC_VERTEX_PROJECT_ID}"
          test -s "${GOOGLE_APPLICATION_CREDENTIALS}"
          python - <<'PY'
          import json
          import os
          with open(os.environ["GOOGLE_APPLICATION_CREDENTIALS"], encoding="utf-8") as handle:
              credentials = json.load(handle)
          assert credentials.get("type") in {"authorized_user", "service_account"}
          print("Vertex credential file loaded; backend configuration is ready")
          PY
'''


def ensure_variable() -> None:
    status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/variables")
    if status != 200:
        raise RuntimeError(f"GET variables failed: HTTP {status}: {payload}")
    if any(item.get("name") == "FULLSEND_MINT_URL" for item in payload.get("variables", [])):
        return
    status, payload = api_request(
        "POST", f"/repos/{ORG}/{REPO}/actions/variables",
        {"name": "FULLSEND_MINT_URL", "value": "http://fullsend-mint-dev.ai-pipeline.svc.cluster.local:8080"},
    )
    if status not in (201, 422):
        raise RuntimeError(f"POST variable failed: HTTP {status}: {payload}")


def dispatch(workflow_id: int) -> int:
    status, payload = api_request(
        "POST", f"/repos/{ORG}/{REPO}/actions/workflows/{workflow_id}/dispatches",
        {"ref": "main", "inputs": {}},
    )
    if status != 204:
        raise RuntimeError(f"POST dispatch failed: HTTP {status}: {payload}")
    status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/runs")
    if status != 200:
        raise RuntimeError(f"GET runs failed: HTTP {status}: {payload}")
    for run in payload.get("workflow_runs", []):
        if run.get("path") == WORKFLOW or run.get("workflow_id") == workflow_id:
            return int(run["id"])
    raise RuntimeError("Dispatch did not create a workflow run")


def main() -> None:
    action_path = FULLSEND_ROOT / MINT_ACTION
    if not action_path.is_file():
        raise RuntimeError(f"Fullsend checkout is missing {MINT_ACTION}: {action_path}")
    ensure_org()
    ensure_repo()
    ensure_variable()
    push_workflow(WORKFLOW, WORKFLOW_CONTENT, "Add M3 Fullsend mint and Vertex smoke")
    action_commit = push_workflow(MINT_ACTION, action_path.read_text(), "Vendor Fullsend mint action for M3 smoke")

    status, payload = api_request("GET", f"/repos/{ORG}/{REPO}/actions/workflows")
    if status != 200:
        raise RuntimeError(f"GET workflows failed: HTTP {status}: {payload}")
    workflow = next((item for item in payload["workflows"] if item["path"] == WORKFLOW), None)
    if workflow is None:
        raise RuntimeError(f"Workflow was not indexed: {WORKFLOW}")
    run_id = dispatch(int(workflow["id"]))
    print(json.dumps({
        "status": "dispatched",
        "repository": f"{ORG}/{REPO}",
        "workflow": WORKFLOW,
        "workflow_id": workflow["id"],
        "run_id": run_id,
        "mint_action_commit": action_commit,
    }, indent=2))


if __name__ == "__main__":
    main()
