#!/usr/bin/env python3
"""Attach a file to a Jira issue.

Usage:
    python scripts/attach_to_jira.py RHAISTRAT-1 security-reviews/RHAISTRAT-1-security-review.md

Environment variables:
    JIRA_SERVER  Jira server URL (e.g. https://redhat.atlassian.net)
    JIRA_USER    Jira username/email
    JIRA_TOKEN   Jira API token
"""

import base64
import mimetypes
import os
import sys
import uuid


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <issue-key> <file-path>", file=sys.stderr)
        sys.exit(1)

    issue_key = sys.argv[1]
    file_path = sys.argv[2]

    server = os.environ.get("JIRA_SERVER")
    user = os.environ.get("JIRA_USER")
    token = os.environ.get("JIRA_TOKEN")

    missing = []
    if not server:
        missing.append("JIRA_SERVER")
    if not user:
        missing.append("JIRA_USER")
    if not token:
        missing.append("JIRA_TOKEN")
    if missing:
        print(f"Error: missing env vars: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(file_path):
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    # Build multipart/form-data body manually (no external deps)
    import urllib.request
    import urllib.error

    boundary = uuid.uuid4().hex
    filename = os.path.basename(file_path)
    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    with open(file_path, "rb") as f:
        file_data = f.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n"
        f"\r\n"
    ).encode() + file_data + f"\r\n--{boundary}--\r\n".encode()

    url = f"{server.rstrip('/')}/rest/api/3/issue/{issue_key}/attachments"
    credentials = base64.b64encode(f"{user}:{token}".encode()).decode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("X-Atlassian-Token", "no-check")

    try:
        with urllib.request.urlopen(req) as resp:
            print(f"Attached {filename} to {issue_key} (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"Error attaching to {issue_key}: HTTP {e.code}: {error_body}",
              file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
