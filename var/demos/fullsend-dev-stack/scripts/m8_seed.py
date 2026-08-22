#!/usr/bin/env python3
"""Idempotently seed the M8 GitHub App installation fixture."""

from __future__ import annotations

import json
import time

from m1_seed import API_URL, ORG, REPO, TOKEN, api_request, ensure_org, ensure_repo


APP_ID = "1001"
APP_SLUG = "fullsend-triage"


def main() -> None:
    for _ in range(30):
        status, _ = api_request("GET", "")
        if status == 200:
            break
        time.sleep(1)
    else:
        raise RuntimeError("GitHub emulator did not become reachable")
    ensure_org()
    ensure_repo()
    status, app = api_request("POST", "/admin/apps", {
        "app_id": APP_ID,
        "name": "Fullsend Triage",
        "slug": APP_SLUG,
        "permissions": {"contents": "read", "issues": "write", "metadata": "read"},
    })
    if status == 409:
        status, app = api_request("GET", f"/admin/apps/{APP_ID}")
    if status not in (200, 201) or not isinstance(app, dict):
        raise RuntimeError(f"GitHub App bootstrap failed: HTTP {status}: {app}")

    status, installation = api_request("POST", f"/admin/apps/{APP_ID}/installations", {
        "account_login": ORG,
        "account_type": "Organization",
        "repositories": [f"{ORG}/{REPO}"],
        "permissions": {"contents": "read", "issues": "write", "metadata": "read"},
    })
    if status not in (200, 201) or not isinstance(installation, dict):
        raise RuntimeError(f"GitHub App installation bootstrap failed: HTTP {status}: {installation}")

    print(json.dumps({
        "status": "seeded",
        "app_id": app["id"],
        "app_slug": app["slug"],
        "installation_id": installation["id"],
        "repository": f"{ORG}/{REPO}",
        "oidc_configuration": f"{API_URL.removesuffix('/api/v3')}/.well-known/openid-configuration",
        "private_key_returned": bool(app.get("private_key")),
    }, indent=2))


if __name__ == "__main__":
    main()
