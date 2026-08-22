#!/usr/bin/env python3
"""Development-only Fullsend token mint for the breadboard emulators.

This is intentionally not an OIDC verifier or a GitHub App implementation.
It accepts one opaque development OIDC value and returns pre-created emulator
PATs selected by role.  The role/repository checks preserve the Fullsend API
contract while keeping the local stack deterministic.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROLE_PERMISSIONS = {
    "triage": {"contents": "read", "issues": "write", "metadata": "read"},
    "scribe": {"contents": "read", "issues": "write", "metadata": "read"},
    "coder": {"contents": "write", "issues": "write", "pull_requests": "write", "metadata": "read"},
    "review": {"contents": "read", "issues": "write", "pull_requests": "write", "metadata": "read"},
    "fix": {"contents": "write", "issues": "write", "pull_requests": "write", "metadata": "read"},
    "fullsend": {"contents": "write", "issues": "write", "pull_requests": "write", "metadata": "read"},
}
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _config() -> tuple[str, dict[str, str]]:
    expected = os.environ.get("FULLSEND_DEV_OIDC_TOKEN", "fullsend-dev-oidc")
    try:
        tokens = json.loads(os.environ.get("FULLSEND_ROLE_TOKENS", "{}"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("FULLSEND_ROLE_TOKENS is not valid JSON") from exc
    if not isinstance(tokens, dict):
        raise RuntimeError("FULLSEND_ROLE_TOKENS must be a JSON object")
    return expected, {str(key): str(value) for key, value in tokens.items()}


class Handler(BaseHTTPRequestHandler):
    server_version = "fullsend-mint-dev/1"

    def log_message(self, _format: str, *_args: object) -> None:
        # Never log Authorization headers or token response bodies.
        return

    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send(HTTPStatus.OK, {"status": "ok", "mode": "development-only"})
            return
        if self.path == "/v1/status":
            self._send(HTTPStatus.OK, {"status": "ok", "mode": "development-only", "roles": sorted(ROLE_PERMISSIONS)})
            return
        self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/token":
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return

        expected, tokens = _config()
        authorization = self.headers.get("Authorization", "")
        if authorization != f"Bearer {expected}":
            self._send(HTTPStatus.UNAUTHORIZED, {"error": "development OIDC token rejected"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "request body must be JSON"})
            return

        role = str(body.get("role", ""))
        repos = body.get("repos", [])
        if role not in ROLE_PERMISSIONS:
            self._send(HTTPStatus.BAD_REQUEST, {"error": "unknown role"})
            return
        if not isinstance(repos, list) or not repos or not all(
            isinstance(repo, str) and (REPO_RE.fullmatch(repo) or REPO_NAME_RE.fullmatch(repo))
            for repo in repos
        ):
            self._send(HTTPStatus.BAD_REQUEST, {"error": "repos must contain repository names or owner/name values"})
            return
        default_owner = os.environ.get("FULLSEND_DEV_DEFAULT_OWNER", "fullsend-dev")
        granted_repos = [repo if "/" in repo else f"{default_owner}/{repo}" for repo in repos]

        token = tokens.get(role) or tokens.get("fullsend")
        if not token:
            self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": f"no emulator token configured for role {role}"})
            return

        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        self._send(HTTPStatus.OK, {
            "token": token,
            "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
            "granted_repos": granted_repos,
            "granted_permissions": ROLE_PERMISSIONS[role],
            "repository_selection": "selected",
            "development_only": True,
        })


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    # Fail during startup rather than serving a mint with an empty token map.
    _config()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
