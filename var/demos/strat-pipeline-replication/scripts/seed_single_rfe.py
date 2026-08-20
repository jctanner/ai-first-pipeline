#!/usr/bin/env python3
"""Seed the RHAIRFE issue used by the M4 single-rfe acceptance run.

The issue content and labels mirror the existing strategy-pipeline demos.  The
script is safe to rerun before processing: it reuses an existing issue with
the fixture label instead of creating a duplicate.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


FIXTURE_LABEL = "strat-pipeline-replication-m4"
SUMMARY = "Add rhai-cli diagnose subcommand for RHOAI deployment health checks"
LABELS = [
    FIXTURE_LABEL,
    "rfe-creator-autofix-rubric-pass",
    "rfe-creator-feasibility-pass",
    "rfe-creator-needs-attention",
    "strat-creator-3.6",
]
DESCRIPTION = """h2. Problem Statement

RHOAI administrators troubleshooting deployment issues must manually inspect
multiple OpenShift resources — operator status, CRD conditions, component pod
health, route availability, and certificate expiry. There is no single command
that checks the health of an RHOAI deployment and reports actionable findings.
Administrators end up running ad-hoc `oc get` and `oc describe` commands across
namespaces, which is slow and error-prone.

h2. Desired Outcome

`rhai-cli diagnose` connects to an RHOAI cluster and runs a suite of health
checks: operator deployment status, DSC/DSCI conditions, component readiness
(dashboard, model controller, workbenches, pipelines, and model registry),
route accessibility, certificate validity, and version consistency. Output is a
structured report with pass/fail/warning per check and remediation hints for
failures.

h2. Acceptance Criteria

* The `rhai-cli diagnose` subcommand connects to the active OpenShift cluster context
* Checks operator deployment status (rhods-operator pod health and CSV phase)
* Inspects DataScienceCluster and DSCInitialization custom-resource conditions
* Validates readiness for dashboard, model-controller, workbenches, data-science-pipelines, and model-registry
* Tests route accessibility and TLS certificate validity for exposed endpoints
* Detects version mismatches between operator, DSC, and component images
* Outputs a structured JSON and human-readable report with pass/fail/warning per check
* Provides remediation hints for common failure modes
* Exits non-zero when a critical check fails, making it suitable for CI/CD gating

h2. User Stories

* As an RHOAI administrator, I want one command to check deployment health after an upgrade.
* As a support engineer, I want a structured report I can attach to a support case.
* As a CI/CD operator, I want to gate deployments on health checks before rollout completes.

h2. Technical Notes

Follow the existing `rhai-cli lint` command pattern for registration, flags, and
output formatting. Health checks should be pluggable functions returning a
`CheckResult`, so new checks can be added without changing the dispatcher.
"""


def api_request(base_url: str, username: str, password: str, method: str, path: str, body=None):
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    request = Request(f"{base_url.rstrip('/')}/{path.lstrip('/')}", headers=headers, data=data, method=method)
    try:
        with urlopen(request, context=ssl._create_unverified_context()) as response:
            raw = response.read().decode()
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"Jira API {method} {path} returned {exc.code}: {detail[:500]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jira-url", default=os.getenv("JIRA_URL", "https://jira.local"))
    parser.add_argument("--jira-user", default=os.getenv("JIRA_ADMIN_USER", "admin"))
    parser.add_argument("--jira-password", default=os.getenv("JIRA_ADMIN_PASSWORD", "admin"))
    parser.add_argument("--summary", default=SUMMARY)
    args = parser.parse_args()

    query = quote(f'project = RHAIRFE AND labels = "{FIXTURE_LABEL}"', safe="")
    existing = api_request(
        args.jira_url,
        args.jira_user,
        args.jira_password,
        "GET",
        f"rest/api/2/search?jql={query}&maxResults=1&fields=summary,labels,status",
    )
    issues = (existing or {}).get("issues", [])
    if issues:
        issue = issues[0]
        print(json.dumps({"key": issue["key"], "created": False, "labels": issue.get("fields", {}).get("labels", [])}, indent=2))
        return 0

    issue = api_request(
        args.jira_url,
        args.jira_user,
        args.jira_password,
        "POST",
        "rest/api/2/issue",
        {
            "fields": {
                "project": {"key": "RHAIRFE"},
                "issuetype": {"name": "Feature Request"},
                "summary": args.summary,
                "description": DESCRIPTION,
                "priority": {"name": "Major"},
                "components": [{"name": "CLI"}],
                "labels": LABELS,
            }
        },
    )
    print(json.dumps({"key": issue["key"], "created": True, "labels": LABELS}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
