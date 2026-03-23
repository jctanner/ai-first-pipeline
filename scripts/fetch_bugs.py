#!/usr/bin/env python3
"""Fetch every open Bug from the RHOAIENG JIRA project and save raw JSON per issue."""

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from the project root (two levels up from bug-bash/scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

JIRA_URL = os.environ.get("JIRA_URL", "").rstrip("/")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")

if not JIRA_URL or not JIRA_API_TOKEN:
    sys.exit("Error: JIRA_URL and JIRA_API_TOKEN must be set in .env")

ISSUES_DIR = Path(__file__).resolve().parent.parent / "issues"
ISSUES_DIR.mkdir(exist_ok=True)

JQL = 'project = RHOAIENG AND issuetype = Bug AND resolution = Unresolved ORDER BY key ASC'
PAGE_SIZE = 100


def _is_cloud(url: str) -> bool:
    return ".atlassian.net" in url.lower()


def _session() -> requests.Session:
    """Build an authenticated requests session matching the MCP server's auth logic."""
    s = requests.Session()
    s.headers["Accept"] = "application/json"
    if _is_cloud(JIRA_URL):
        s.auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    else:
        s.headers["Authorization"] = f"Bearer {JIRA_API_TOKEN}"
    return s


def _api_base() -> str:
    """Return the appropriate API base path for Cloud vs Server."""
    return f"{JIRA_URL}/rest/api/3" if _is_cloud(JIRA_URL) else f"{JIRA_URL}/rest/api/2"


def fetch_issue_keys(session: requests.Session) -> list[str]:
    """Page through the search endpoint to collect every matching issue key."""
    keys: list[str] = []
    api = _api_base()

    if _is_cloud(JIRA_URL):
        # Cloud: use POST /rest/api/3/search/jql with nextPageToken pagination
        next_page_token = None
        while True:
            body: dict = {"jql": JQL, "maxResults": PAGE_SIZE, "fields": ["key"]}
            if next_page_token:
                body["nextPageToken"] = next_page_token
            resp = session.post(f"{api}/search/jql", json=body)
            if not resp.ok:
                sys.exit(f"Search failed ({resp.status_code}): {resp.text}")
            data = resp.json()
            batch = [issue["key"] for issue in data.get("issues", [])]
            keys.extend(batch)
            total = data.get("total", len(keys))
            print(f"  search: fetched {len(keys)}/{total} keys")
            next_page_token = data.get("nextPageToken")
            if not next_page_token or not batch:
                break
    else:
        # Server/DC: GET /rest/api/2/search with startAt pagination
        start_at = 0
        while True:
            resp = session.get(
                f"{api}/search",
                params={"jql": JQL, "startAt": start_at, "maxResults": PAGE_SIZE, "fields": "key"},
            )
            if not resp.ok:
                sys.exit(f"Search failed ({resp.status_code}): {resp.text}")
            data = resp.json()
            batch = [issue["key"] for issue in data["issues"]]
            keys.extend(batch)
            print(f"  search: fetched {len(keys)}/{data['total']} keys")
            if start_at + len(batch) >= data["total"]:
                break
            start_at += len(batch)

    return keys


def fetch_and_save(session: requests.Session, key: str) -> None:
    """GET the full raw JSON for a single issue and write it to disk."""
    api = _api_base()
    resp = session.get(f"{api}/issue/{key}")
    resp.raise_for_status()
    dest = ISSUES_DIR / f"{key}.json"
    dest.write_text(json.dumps(resp.json(), indent=2))


def main() -> None:
    session = _session()

    print(f"Searching: {JQL}")
    keys = fetch_issue_keys(session)
    print(f"Found {len(keys)} open bugs in RHOAIENG\n")

    for i, key in enumerate(keys, 1):
        print(f"[{i}/{len(keys)}] {key}")
        fetch_and_save(session, key)

    print(f"\nDone. {len(keys)} issues saved to {ISSUES_DIR}")


if __name__ == "__main__":
    main()
