#!/usr/bin/env python3
"""Jira REST API operations for strat-breakdown skill.

Standalone CLI — no external dependencies beyond Python stdlib.

Environment variables:
    JIRA_SERVER  Jira server URL (e.g. https://mysite.atlassian.net)
    JIRA_USER    Jira username/email
    JIRA_TOKEN   Jira API token

Usage:
    python3 jira_ops.py get-issue RHAISTRAT-1536
    python3 jira_ops.py get-issue RHAISTRAT-1536 --fields summary,description,components
    python3 jira_ops.py get-comments RHAISTRAT-1536
    python3 jira_ops.py create-issue '<JSON payload>'
    python3 jira_ops.py update-issue RHOAIENG-12345 '<JSON payload>'

All output is JSON to stdout. Errors go to stderr with non-zero exit.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request


# ─── Environment ─────────────────────────────────────────────────────────────

def _env():
    server = os.environ.get("JIRA_SERVER", "").rstrip("/")
    user = os.environ.get("JIRA_USER", "")
    token = os.environ.get("JIRA_TOKEN", "")
    if not server:
        print("ERROR: JIRA_SERVER not set", file=sys.stderr)
        sys.exit(1)
    if not token:
        print("ERROR: JIRA_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    return server, user, token


def _is_cloud(url):
    return ".atlassian.net" in url.lower()


# ─── HTTP Layer ──────────────────────────────────────────────────────────────

def _request(url, user, token, server, body=None, method=None):
    if _is_cloud(server):
        credentials = base64.b64encode(f"{user}:{token}".encode()).decode()
        auth_header = f"Basic {credentials}"
    else:
        auth_header = f"Bearer {token}"

    headers = {
        "Authorization": auth_header,
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status == 204:
            return None
        resp_body = resp.read()
        if not resp_body:
            return None
        return json.loads(resp_body)


def _api(server, path, user, token, body=None, method=None, max_retries=3):
    api_version = "3" if _is_cloud(server) else "2"
    url = f"{server}/rest/api/{api_version}{path}"
    last_error = None
    for attempt in range(max_retries):
        try:
            return _request(url, user, token, server, body, method)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = max(int(e.headers.get("Retry-After", 1)), 1)
                print(f"Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                last_error = e
                continue
            if e.code in (502, 503, 504):
                wait = 4 ** attempt
                print(f"HTTP {e.code}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                last_error = e
                continue
            error_body = e.read().decode("utf-8", errors="replace")
            print(f"HTTP {e.code}: {error_body}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            wait = 4 ** attempt
            print(f"Network error: {e.reason}, retrying in {wait}s...",
                  file=sys.stderr)
            time.sleep(wait)
            last_error = e
    print(f"Failed after {max_retries} retries: {last_error}", file=sys.stderr)
    sys.exit(1)


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_get_issue(args):
    """Fetch a Jira issue. Prints JSON to stdout."""
    if not args:
        print("Usage: jira_ops.py get-issue ISSUE-KEY [--fields f1,f2,...]",
              file=sys.stderr)
        sys.exit(1)

    key = args[0]
    fields = None
    if len(args) >= 3 and args[1] == "--fields":
        fields = args[2]

    server, user, token = _env()
    path = f"/issue/{key}"
    if fields:
        path += f"?fields={fields}"

    result = _api(server, path, user, token)
    json.dump(result, sys.stdout, indent=2)
    print()


def cmd_get_comments(args):
    """Fetch all comments for an issue. Prints JSON array to stdout."""
    if not args:
        print("Usage: jira_ops.py get-comments ISSUE-KEY", file=sys.stderr)
        sys.exit(1)

    key = args[0]
    server, user, token = _env()

    comments = []
    start_at = 0
    while True:
        path = f"/issue/{key}/comment?startAt={start_at}&maxResults=100"
        data = _api(server, path, user, token)
        batch = data.get("comments", [])
        comments.extend(batch)
        if start_at + len(batch) >= data.get("total", 0):
            break
        start_at += len(batch)

    json.dump(comments, sys.stdout, indent=2)
    print()


def cmd_create_issue(args):
    """Create a Jira issue. Accepts JSON payload as argument or stdin.

    The payload is sent directly as the request body to POST /issue.
    Returns the created issue JSON (including key).

    Example payload:
    {
      "fields": {
        "project": {"key": "RHOAIENG"},
        "issuetype": {"name": "Epic"},
        "summary": "[Eng RHAISTRAT-1536] Feature title",
        "description": "...",
        "priority": {"name": "Major"},
        "parent": {"key": "RHAISTRAT-1536"},
        "components": [{"name": "Model Serving"}],
        "labels": ["label1"],
        "fixVersions": [{"name": "1.0"}],
        "customfield_10014": "RHOAIENG-58856"
      }
    }
    """
    if args:
        payload = json.loads(args[0])
    else:
        payload = json.loads(sys.stdin.read())

    server, user, token = _env()
    result = _api(server, "/issue", user, token, body=payload)
    json.dump(result, sys.stdout, indent=2)
    print()


def cmd_update_issue(args):
    """Update a Jira issue. Accepts issue key + JSON payload.

    Example:
        jira_ops.py update-issue RHOAIENG-12345 '{"fields": {"summary": "New title"}}'
    """
    if len(args) < 1:
        print("Usage: jira_ops.py update-issue ISSUE-KEY '<JSON>'",
              file=sys.stderr)
        sys.exit(1)

    key = args[0]
    if len(args) >= 2:
        payload = json.loads(args[1])
    else:
        payload = json.loads(sys.stdin.read())

    server, user, token = _env()
    _api(server, f"/issue/{key}", user, token, body=payload, method="PUT")
    print(json.dumps({"status": "updated", "key": key}))


def cmd_search(args):
    """Search issues with JQL. Prints JSON results to stdout.

    Usage: jira_ops.py search 'project = RHOAIENG AND ...' [--fields f1,f2] [--max N]
    """
    if not args:
        print("Usage: jira_ops.py search 'JQL' [--fields f1,f2] [--max N]",
              file=sys.stderr)
        sys.exit(1)

    jql = args[0]
    fields = "*navigable"
    max_results = 50
    i = 1
    while i < len(args):
        if args[i] == "--fields" and i + 1 < len(args):
            fields = args[i + 1]
            i += 2
        elif args[i] == "--max" and i + 1 < len(args):
            max_results = int(args[i + 1])
            i += 2
        else:
            i += 1

    server, user, token = _env()

    issues = []
    start_at = 0
    while True:
        if _is_cloud(server):
            path = "/search/jql"
            body = {
                "jql": jql,
                "fields": fields.split(","),
                "maxResults": min(max_results - len(issues), 100),
                "startAt": start_at,
            }
            data = _api(server, path, user, token, body=body)
        else:
            encoded_jql = urllib.parse.quote(jql)
            path = (f"/search?jql={encoded_jql}&fields={fields}"
                    f"&maxResults={min(max_results - len(issues), 100)}"
                    f"&startAt={start_at}")
            data = _api(server, path, user, token)

        batch = data.get("issues", [])
        issues.extend(batch)
        if len(issues) >= max_results or start_at + len(batch) >= data.get("total", 0):
            break
        start_at += len(batch)

    json.dump(issues, sys.stdout, indent=2)
    print()


COMMANDS = {
    "get-issue": cmd_get_issue,
    "get-comments": cmd_get_comments,
    "create-issue": cmd_create_issue,
    "update-issue": cmd_update_issue,
    "search": cmd_search,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: jira_ops.py <command> [args...]", file=sys.stderr)
        print(f"Commands: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    COMMANDS[cmd](sys.argv[2:])


if __name__ == "__main__":
    main()
