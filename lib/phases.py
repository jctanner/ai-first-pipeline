"""Phase orchestrators for the bug bash analysis pipeline."""

import html as html_mod
import json
import os
import sys
import asyncio
from pathlib import Path

import requests
from dotenv import load_dotenv
from jsonschema import validate, ValidationError

from lib.agent_runner import run_agent, format_duration
from lib.prompts import build_phase_prompt
from lib.schemas import PHASE_SCHEMAS
from lib.repo_mapping import (
    get_midstream, get_upstream, clone_midstream_repo,
    normalize_component_name, DOWNSTREAM_ONLY,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
ISSUES_DIR = BASE_DIR / "issues"


def _discover_issues(args) -> list[Path]:
    """Return a sorted list of issue JSON paths, filtered by CLI args."""
    if not ISSUES_DIR.exists():
        print(f"Error: issues directory not found: {ISSUES_DIR}")
        sys.exit(1)

    if args.issue:
        # Single issue mode
        target = ISSUES_DIR / f"{args.issue}.json"
        if not target.exists():
            print(f"Error: issue file not found: {target}")
            sys.exit(1)
        return [target]

    # Match only raw issue files (RHOAIENG-NNNNN.json), not phase outputs
    # like RHOAIENG-NNNNN.completeness.json (which have dots in the stem)
    def _numeric_key(p: Path) -> int:
        try:
            return int(p.stem.split("-", 1)[1])
        except (IndexError, ValueError):
            return 0

    paths = sorted(
        (p for p in ISSUES_DIR.glob("RHOAIENG-*.json") if "." not in p.stem),
        key=_numeric_key,
    )
    if not paths:
        print("No issue JSON files found in issues/")
        sys.exit(1)


    return paths


def _issue_key_from_path(path: Path) -> str:
    """Extract 'RHOAIENG-12345' from a file path."""
    return path.stem


def _adf_to_text(node) -> str:
    """Recursively convert an Atlassian Document Format node to plain text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node

    if isinstance(node, list):
        return "".join(_adf_to_text(n) for n in node)

    if not isinstance(node, dict):
        return str(node)

    node_type = node.get("type", "")
    content = node.get("content", [])

    # Leaf text node
    if node_type == "text":
        return node.get("text", "")

    # Inline card (link)
    if node_type == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        return url

    # Media / media-single — just note there's an attachment
    if node_type in ("media", "mediaSingle"):
        return "[attachment]"

    # Mention
    if node_type == "mention":
        return node.get("attrs", {}).get("text", "@someone")

    # Emoji
    if node_type == "emoji":
        return node.get("attrs", {}).get("shortName", "")

    # Block nodes
    text = "".join(_adf_to_text(c) for c in content)

    if node_type == "paragraph":
        return text + "\n\n"
    if node_type == "heading":
        level = node.get("attrs", {}).get("level", 1)
        return "#" * level + " " + text + "\n\n"
    if node_type == "bulletList":
        return text
    if node_type == "orderedList":
        return text
    if node_type == "listItem":
        return "- " + text.strip() + "\n"
    if node_type == "codeBlock":
        lang = node.get("attrs", {}).get("language", "")
        return f"```{lang}\n{text}\n```\n\n"
    if node_type == "blockquote":
        lines = text.strip().split("\n")
        return "\n".join("> " + line for line in lines) + "\n\n"
    if node_type == "rule":
        return "---\n\n"
    if node_type == "table":
        return text + "\n"
    if node_type == "tableRow":
        return "| " + text + "\n"
    if node_type == "tableCell" or node_type == "tableHeader":
        return text.strip() + " | "

    # Default: just return the recursive text
    return text


def _adf_to_html(node) -> str:
    """Recursively convert an Atlassian Document Format node to HTML."""
    if node is None:
        return ""
    if isinstance(node, str):
        return html_mod.escape(node)

    if isinstance(node, list):
        return "".join(_adf_to_html(n) for n in node)

    if not isinstance(node, dict):
        return html_mod.escape(str(node))

    node_type = node.get("type", "")
    content = node.get("content", [])

    # Leaf text node (with optional marks)
    if node_type == "text":
        text = html_mod.escape(node.get("text", ""))
        for mark in node.get("marks", []):
            mark_type = mark.get("type", "")
            if mark_type == "strong":
                text = f"<strong>{text}</strong>"
            elif mark_type == "em":
                text = f"<em>{text}</em>"
            elif mark_type == "code":
                text = f"<code>{text}</code>"
            elif mark_type == "strike":
                text = f"<s>{text}</s>"
            elif mark_type == "underline":
                text = f"<u>{text}</u>"
            elif mark_type == "link":
                href = html_mod.escape(mark.get("attrs", {}).get("href", ""))
                text = f'<a href="{href}" target="_blank" rel="noopener">{text}</a>'
        return text

    # Hard break
    if node_type == "hardBreak":
        return "<br>"

    # Inline card (link)
    if node_type == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        escaped = html_mod.escape(url)
        # Show just the last path segment or issue key as label
        label = url.rsplit("/", 1)[-1] if "/" in url else url
        # Strip fragment
        if "#" in label:
            label = label.split("#")[-1] or label
        return f'<a href="{escaped}" target="_blank" rel="noopener">{html_mod.escape(label)}</a>'

    # Media / media-single
    if node_type in ("media", "mediaSingle"):
        inner = "".join(_adf_to_html(c) for c in content)
        if inner:
            return inner
        return '<span class="badge badge-default">[attachment]</span>'

    # Mention
    if node_type == "mention":
        text = html_mod.escape(node.get("attrs", {}).get("text", "@someone"))
        return f'<strong>{text}</strong>'

    # Emoji
    if node_type == "emoji":
        shortname = node.get("attrs", {}).get("shortName", "")
        return html_mod.escape(shortname)

    # Block nodes — recurse into content
    inner = "".join(_adf_to_html(c) for c in content)

    if node_type == "doc":
        return inner
    if node_type == "paragraph":
        return f"<p>{inner}</p>"
    if node_type == "heading":
        level = node.get("attrs", {}).get("level", 1)
        level = max(1, min(6, level))
        return f"<h{level}>{inner}</h{level}>"
    if node_type == "bulletList":
        return f"<ul>{inner}</ul>"
    if node_type == "orderedList":
        return f"<ol>{inner}</ol>"
    if node_type == "listItem":
        return f"<li>{inner}</li>"
    if node_type == "codeBlock":
        lang = node.get("attrs", {}).get("language", "")
        cls = f' class="language-{html_mod.escape(lang)}"' if lang else ""
        return f"<pre><code{cls}>{inner}</code></pre>"
    if node_type == "blockquote":
        return f"<blockquote>{inner}</blockquote>"
    if node_type == "rule":
        return "<hr>"
    if node_type == "table":
        return f"<table>{inner}</table>"
    if node_type == "tableRow":
        return f"<tr>{inner}</tr>"
    if node_type == "tableHeader":
        return f"<th>{inner}</th>"
    if node_type == "tableCell":
        return f"<td>{inner}</td>"

    # Default: return recursive content
    return inner


def _parse_issue(path: Path) -> dict:
    """Load an issue JSON and return a dict with key fields as plain text."""
    with open(path) as f:
        raw = json.load(f)

    fields = raw.get("fields", {})

    # Basic fields
    key = raw.get("key", _issue_key_from_path(path))
    summary = fields.get("summary", "(no summary)")
    status = fields.get("status", {}).get("name", "Unknown")
    priority = fields.get("priority", {}).get("name", "Unknown")
    issue_type = fields.get("issuetype", {}).get("name", "Unknown")
    components = [c.get("name", "") for c in fields.get("components", [])]
    labels = fields.get("labels", [])
    assignee = fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned"
    reporter = fields.get("reporter", {}).get("displayName", "") if fields.get("reporter") else ""
    created = fields.get("created", "")
    updated = fields.get("updated", "")
    versions = [v.get("name", "") for v in fields.get("versions", [])]
    fix_versions = [v.get("name", "") for v in fields.get("fixVersions", [])]

    # Description (ADF → text + HTML)
    desc_raw = fields.get("description")
    if isinstance(desc_raw, dict):
        description = _adf_to_text(desc_raw).strip()
        description_html = _adf_to_html(desc_raw)
    elif isinstance(desc_raw, str):
        description = desc_raw.strip()
        description_html = f"<p>{html_mod.escape(desc_raw.strip())}</p>"
    else:
        description = "(no description)"
        description_html = "<p><em>(no description)</em></p>"

    # Comments (ADF → text + HTML)
    comment_data = fields.get("comment", {})
    comments_raw = comment_data.get("comments", []) if isinstance(comment_data, dict) else []
    comments = []
    comments_html = []
    for c in comments_raw:
        author = c.get("author", {}).get("displayName", "Unknown")
        c_created = c.get("created", "")
        body_raw = c.get("body")
        if isinstance(body_raw, dict):
            body = _adf_to_text(body_raw).strip()
            body_html = _adf_to_html(body_raw)
        elif isinstance(body_raw, str):
            body = body_raw.strip()
            body_html = f"<p>{html_mod.escape(body_raw.strip())}</p>"
        else:
            body = ""
            body_html = ""
        if body:
            comments.append(f"**{author}** ({c_created}):\n{body}")
            comments_html.append({
                "author": author,
                "created": c_created,
                "body_html": body_html,
            })

    # Attachments
    attachments = []
    for att in fields.get("attachment", []):
        attachments.append(att.get("filename", "unknown"))

    return {
        "key": key,
        "summary": summary,
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "components": components,
        "labels": labels,
        "description": description,
        "description_html": description_html,
        "comments": comments,
        "comments_html": comments_html,
        "attachments": attachments,
        "assignee": assignee,
        "reporter": reporter,
        "created": created,
        "updated": updated,
        "versions": versions,
        "fix_versions": fix_versions,
    }


def _issue_to_text(issue: dict) -> str:
    """Format a parsed issue dict into a readable text block for prompts."""
    lines = [
        f"**Summary:** {issue['summary']}",
        f"**Status:** {issue['status']}",
        f"**Priority:** {issue['priority']}",
        f"**Components:** {', '.join(issue['components']) or '(none)'}",
        f"**Labels:** {', '.join(issue['labels']) or '(none)'}",
        "",
        "### Description",
        "",
        issue["description"],
    ]

    if issue["attachments"]:
        lines += ["", "### Attachments", ""]
        for att in issue["attachments"]:
            lines.append(f"- {att}")

    if issue["comments"]:
        lines += ["", "### Comments", ""]
        for comment in issue["comments"]:
            lines.append(comment)
            lines.append("")

    return "\n".join(lines)


def _print_phase_summary(phase_name: str, jobs: list, results: list) -> None:
    """Print a standard summary block after a phase completes."""
    successful = [r for r in results if isinstance(r, dict) and r.get("success")]
    failed = [r for r in results if isinstance(r, dict) and not r.get("success")]
    exceptions = [r for r in results if isinstance(r, Exception)]

    print(f"\n{'=' * 60}")
    print(f"{phase_name.upper()} COMPLETE")
    print(f"{'=' * 60}")
    print(f"Total issues: {len(jobs)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(failed)}")
    if exceptions:
        print(f"Exceptions: {len(exceptions)}")

    if failed:
        print("\nFailed issues:")
        for r in failed:
            print(f"  x {r['name']}: {r.get('error', 'unknown error')}")
            if r.get("log_file"):
                print(f"    Log: {r['log_file']}")

    if exceptions:
        print("\nExceptions:")
        for i, exc in enumerate(exceptions):
            print(f"  x Exception {i + 1}: {exc}")


ACTIVITY_LOG = BASE_DIR / "logs" / "activity.jsonl"


def _log_activity(issue_key: str, phase: str, event: str, model: str = "", **extra) -> None:
    """Append a single activity entry to logs/activity.jsonl."""
    from datetime import datetime, timezone

    ACTIVITY_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "issue_key": issue_key,
        "phase": phase,
        "event": event,
        "model": model,
        **extra,
    }
    with open(ACTIVITY_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def _run_single_agent(
    key: str,
    phase: str,
    cwd: str,
    prompt: str,
    stale_files: list[Path],
    semaphore: asyncio.Semaphore,
    log_dir: Path,
    model: str,
) -> dict:
    """Acquire semaphore, delete stale files, run one agent, validate output.

    Returns a result dict with 'name', 'success', 'phase', and optional 'error'.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_activity(key, phase, "started", model=model)

    async with semaphore:
        # Delete stale outputs just before the agent runs (inside the
        # semaphore) so that a killed orchestrator doesn't leave files
        # deleted-but-never-regenerated.
        for stale_path in stale_files:
            if stale_path.exists():
                stale_path.unlink()

        result = await run_agent(key, cwd, prompt, log_dir, model)

    if isinstance(result, dict):
        _log_activity(
            key, phase,
            "completed" if result.get("success") else "failed",
            model=model,
            duration_seconds=result.get("duration_seconds"),
            error=result.get("error"),
        )
        result["phase"] = phase

        # Inline schema validation
        schema = PHASE_SCHEMAS.get(phase)
        if schema and result.get("success"):
            json_path = ISSUES_DIR / f"{key}.{phase}.json"
            if not json_path.exists():
                print(f"  WARNING: {key} — {phase} JSON output missing: {json_path.name}")
            else:
                try:
                    with open(json_path) as f:
                        data = json.load(f)
                    validate(instance=data, schema=schema)
                except (json.JSONDecodeError, ValidationError) as exc:
                    invalid_path = json_path.with_suffix(".json.invalid")
                    json_path.rename(invalid_path)
                    print(f"  INVALID: {key} — {phase} — {exc!s:.120}")
                    print(f"           Renamed to {invalid_path.name}")

    dur = result.get("duration_seconds", 0) if isinstance(result, dict) else 0
    status = "completed" if isinstance(result, dict) and result.get("success") else "failed"
    print(f"  [{key}] {phase} → {status} ({format_duration(dur)})")

    return result


async def _run_phase(phase_name: str, jobs: list, args) -> list:
    """Execute a list of agent jobs with bounded concurrency."""
    log_dir = BASE_DIR / "logs" / phase_name
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"PHASE: {phase_name}")
    print(f"{'=' * 60}")
    print(f"Issues to process: {len(jobs)}")
    print(f"Max concurrent agents: {args.max_concurrent}")
    print(f"Model: {args.model}")
    print(f"Logs: {log_dir}")
    print(f"{'=' * 60}\n")

    if not jobs:
        print("Nothing to do — all issues already have output (use --force to regenerate).")
        return []

    semaphore = asyncio.Semaphore(args.max_concurrent)

    async def run_with_semaphore(job):
        _log_activity(job["name"], phase_name, "started", model=args.model)
        async with semaphore:
            # Delete stale outputs just before the agent runs (not during
            # job-building) so that a killed orchestrator doesn't leave
            # hundreds of issues with deleted-but-never-regenerated files.
            for stale_path in job.get("stale_files", []):
                if stale_path.exists():
                    stale_path.unlink()
            result = await run_agent(
                job["name"], job["cwd"], job["prompt"], log_dir, args.model
            )
        if isinstance(result, dict):
            _log_activity(
                job["name"], phase_name,
                "completed" if result.get("success") else "failed",
                model=args.model,
                duration_seconds=result.get("duration_seconds"),
                error=result.get("error"),
            )
        return result

    results = await asyncio.gather(
        *(run_with_semaphore(job) for job in jobs),
        return_exceptions=True,
    )

    _print_phase_summary(phase_name, jobs, results)
    return list(results)


def _validate_phase_outputs(phase_name: str, results: list) -> None:
    """Validate JSON outputs from a phase against the schema.

    For each successful result, load the corresponding JSON file and
    validate it.  Invalid files are renamed to ``*.json.invalid`` so
    they don't block re-runs.
    """
    schema = PHASE_SCHEMAS.get(phase_name)
    if schema is None:
        return

    successful = [r for r in results if isinstance(r, dict) and r.get("success")]
    if not successful:
        return

    valid_count = 0
    invalid_count = 0

    for result in successful:
        key = result["name"]
        json_path = ISSUES_DIR / f"{key}.{phase_name}.json"
        if not json_path.exists():
            print(f"  WARNING: {key} — JSON output missing: {json_path.name}")
            invalid_count += 1
            continue

        try:
            with open(json_path) as f:
                data = json.load(f)
            validate(instance=data, schema=schema)
            valid_count += 1
        except (json.JSONDecodeError, ValidationError) as exc:
            invalid_path = json_path.with_suffix(".json.invalid")
            json_path.rename(invalid_path)
            print(f"  INVALID: {key} — {exc!s:.120}")
            print(f"           Renamed to {invalid_path.name}")
            invalid_count += 1

    print(f"\nSchema validation: {valid_count} valid, {invalid_count} invalid")


# ---------------------------------------------------------------------------
# Phase 1: Fetch
# ---------------------------------------------------------------------------

async def run_fetch_phase(args) -> None:
    """Fetch issues from Jira using the same logic as scripts/fetch_bugs.py."""
    print(f"\n{'=' * 60}")
    print("PHASE 1: Fetching issues from Jira")
    print(f"{'=' * 60}\n")

    # Load Jira credentials from project root .env
    project_root = BASE_DIR.parent
    load_dotenv(project_root / ".env")

    jira_url = os.environ.get("JIRA_URL", "").rstrip("/")
    jira_email = os.environ.get("JIRA_EMAIL", "")
    jira_api_token = os.environ.get("JIRA_API_TOKEN", "")

    if not jira_url or not jira_api_token:
        print("Error: JIRA_URL and JIRA_API_TOKEN must be set in .env")
        sys.exit(1)

    ISSUES_DIR.mkdir(exist_ok=True)

    is_cloud = ".atlassian.net" in jira_url.lower()
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    if is_cloud:
        session.auth = (jira_email, jira_api_token)
    else:
        session.headers["Authorization"] = f"Bearer {jira_api_token}"

    api_base = f"{jira_url}/rest/api/3" if is_cloud else f"{jira_url}/rest/api/2"
    jql = "project = RHOAIENG AND issuetype = Bug AND resolution = Unresolved ORDER BY key ASC"
    page_size = 100

    # Fetch keys
    keys: list[str] = []
    if is_cloud:
        next_page_token = None
        while True:
            body: dict = {"jql": jql, "maxResults": page_size, "fields": ["key"]}
            if next_page_token:
                body["nextPageToken"] = next_page_token
            resp = session.post(f"{api_base}/search/jql", json=body)
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
        start_at = 0
        while True:
            resp = session.get(
                f"{api_base}/search",
                params={"jql": jql, "startAt": start_at, "maxResults": page_size, "fields": "key"},
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

    print(f"\nFound {len(keys)} open bugs\n")

    # Fetch each issue
    for i, key in enumerate(keys, 1):
        dest = ISSUES_DIR / f"{key}.json"
        if dest.exists():
            print(f"[{i}/{len(keys)}] {key} (cached)")
            continue
        print(f"[{i}/{len(keys)}] {key}")
        resp = session.get(f"{api_base}/issue/{key}")
        resp.raise_for_status()
        dest.write_text(json.dumps(resp.json(), indent=2))

    print(f"\nDone. {len(keys)} issues saved to {ISSUES_DIR}")


# ---------------------------------------------------------------------------
# Phase 2: Completeness
# ---------------------------------------------------------------------------

async def run_completeness_phase(args) -> list:
    """Score each bug on the completeness rubric."""
    issue_paths = _discover_issues(args)
    jobs = []
    component_filter = getattr(args, "component", None)

    for path in issue_paths:
        key = _issue_key_from_path(path)
        output_file = ISSUES_DIR / f"{key}.completeness.json"
        output_md = ISSUES_DIR / f"{key}.completeness.md"

        if output_file.exists() and not args.force:
            print(f"  skip {key} (output exists)")
            continue

        issue = _parse_issue(path)

        if component_filter:
            if not _issue_matches_component_filter(issue, component_filter):
                continue

        issue_text = _issue_to_text(issue)
        prompt = build_phase_prompt("bug-completeness", key, issue_text)

        jobs.append({
            "name": key,
            "cwd": str(BASE_DIR),
            "prompt": prompt,
            "stale_files": [output_file, output_md],
        })

    if getattr(args, "limit", None):
        jobs = jobs[: args.limit]

    results = await _run_phase("completeness", jobs, args)
    _validate_phase_outputs("completeness", results)
    return results


# ---------------------------------------------------------------------------
# Phase 3: Context map
# ---------------------------------------------------------------------------

async def run_context_map_phase(args) -> list:
    """Map each bug to available architecture context."""
    issue_paths = _discover_issues(args)
    jobs = []
    component_filter = getattr(args, "component", None)

    for path in issue_paths:
        key = _issue_key_from_path(path)
        output_file = ISSUES_DIR / f"{key}.context-map.json"
        output_md = ISSUES_DIR / f"{key}.context-map.md"

        if output_file.exists() and not args.force:
            print(f"  skip {key} (output exists)")
            continue

        issue = _parse_issue(path)

        if component_filter:
            if not _issue_matches_component_filter(issue, component_filter):
                continue

        issue_text = _issue_to_text(issue)
        prompt = build_phase_prompt("bug-context-map", key, issue_text)

        jobs.append({
            "name": key,
            "cwd": str(BASE_DIR),
            "prompt": prompt,
            "stale_files": [output_file, output_md],
        })

    if getattr(args, "limit", None):
        jobs = jobs[: args.limit]

    results = await _run_phase("context-map", jobs, args)
    _validate_phase_outputs("context-map", results)
    return results


# ---------------------------------------------------------------------------
# Phase 4: Fix attempt
# ---------------------------------------------------------------------------

def _extract_completeness_score(json_path: Path) -> int | None:
    """Extract the overall score from a completeness JSON file."""
    if not json_path.exists():
        return None
    try:
        with open(json_path) as f:
            data = json.load(f)
        return data.get("overall_score")
    except (json.JSONDecodeError, KeyError):
        return None


def _extract_context_rating(json_path: Path) -> str | None:
    """Extract the context rating from a context-map JSON file."""
    if not json_path.exists():
        return None
    try:
        with open(json_path) as f:
            data = json.load(f)
        return data.get("overall_rating")
    except (json.JSONDecodeError, KeyError):
        return None


def _extract_triage_recommendation(json_path: Path) -> str | None:
    """Extract the triage recommendation from a completeness JSON file."""
    if not json_path.exists():
        return None
    try:
        with open(json_path) as f:
            data = json.load(f)
        return data.get("triage_recommendation")
    except (json.JSONDecodeError, KeyError):
        return None


def _extract_fix_recommendation(json_path: Path) -> str | None:
    """Extract the recommendation from a fix-attempt JSON file."""
    if not json_path.exists():
        return None
    try:
        with open(json_path) as f:
            data = json.load(f)
        return data.get("recommendation")
    except (json.JSONDecodeError, KeyError):
        return None


def _issue_matches_component_filter(issue: dict, component_filter: str) -> bool:
    """Check if any Jira component on the issue matches the filter (case-insensitive substring)."""
    needle = component_filter.lower()
    for comp in issue.get("components", []):
        if needle in comp.lower():
            return True
    return False


def _extract_components_from_context_map(json_path: Path) -> list[str]:
    """Extract unique, normalized component names from context_entries in a context-map JSON.

    Raw component names from the context-map agent (e.g. ``kubeflow (odh-notebook-controller)``)
    are normalized to canonical repo names via ``normalize_component_name``.
    """
    if not json_path.exists():
        return []
    try:
        with open(json_path) as f:
            data = json.load(f)
        entries = data.get("context_entries", [])
        seen: set[str] = set()
        components: list[str] = []
        for entry in entries:
            raw = entry.get("component", "")
            name = normalize_component_name(raw)
            if name and name not in seen:
                seen.add(name)
                components.append(name)
        return components
    except (json.JSONDecodeError, KeyError):
        return []


def _build_workspace_info(
    workspace_dir: Path,
    cloned_repos: dict[str, Path],
    component_names: list[str],
) -> str:
    """Build a workspace-info text block for the agent prompt."""
    lines = [f"Workspace directory: {workspace_dir}", ""]
    lines.append("Cloned midstream repositories:")
    for downstream_name, clone_path in cloned_repos.items():
        midstream = get_midstream(downstream_name)
        if midstream:
            org, repo = midstream
            lines.append(f"  - {clone_path.name}/ (clone of {org}/{repo})")

    # Note any downstream-only components
    downstream_only = [c for c in component_names if c in DOWNSTREAM_ONLY]
    if downstream_only:
        lines.append("")
        lines.append("Downstream-only components (no midstream clone available):")
        for name in downstream_only:
            lines.append(f"  - {name}")

    # Note any upstream repos
    upstream_notes = []
    for downstream_name in cloned_repos:
        upstream = get_upstream(downstream_name)
        if upstream:
            upstream_notes.append(f"  - {downstream_name}: upstream is {upstream}")
    if upstream_notes:
        lines.append("")
        lines.append("Known upstream repositories (fix may need to go upstream first):")
        lines.extend(upstream_notes)

    return "\n".join(lines)


def _capture_git_diffs(workspace_dir: Path) -> str:
    """Run ``git diff`` in each repo directory under workspace_dir and return combined output."""
    import subprocess

    diffs = []
    if not workspace_dir.exists():
        return ""

    for child in sorted(workspace_dir.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(child), "diff"],
                capture_output=True, text=True, timeout=30,
            )
            if result.stdout.strip():
                diffs.append(f"# {child.name}\n{result.stdout.strip()}")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass

    return "\n\n".join(diffs)


def _update_fix_json_patch(json_path: Path, captured_diff: str) -> None:
    """Replace the ``patch`` field in a fix-attempt JSON with the captured git diff."""
    if not json_path.exists() or not captured_diff:
        return
    try:
        with open(json_path) as f:
            data = json.load(f)
        data["patch"] = captured_diff
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, KeyError):
        pass


async def run_fix_attempt_phase(args) -> list:
    """Attempt fixes for eligible bugs using midstream repo clones."""
    issue_paths = _discover_issues(args)
    jobs = []
    # Track workspace dirs per job for post-agent diff capture
    job_workspaces: dict[str, Path] = {}

    triage_filter = getattr(args, "triage", None)
    component_filter = getattr(args, "component", None)
    recommendation_filter = getattr(args, "recommendation", None)

    skipped_reasons: dict[str, list[str]] = {
        "output_exists": [],
        "low_completeness": [],
        "no_context": [],
        "no_completeness": [],
        "no_context_map": [],
        "no_components": [],
        "active_work": [],
        "triage_mismatch": [],
        "component_mismatch": [],
        "recommendation_mismatch": [],
    }

    fix_workspaces_root = BASE_DIR / "fix-workspaces"

    for path in issue_paths:
        key = _issue_key_from_path(path)
        output_file = ISSUES_DIR / f"{key}.fix-attempt.json"
        output_md = ISSUES_DIR / f"{key}.fix-attempt.md"

        # When --recommendation is set, filter on existing fix-attempt output
        # (only re-run issues whose previous result matches the given value)
        if recommendation_filter:
            existing_rec = _extract_fix_recommendation(output_file)
            if existing_rec != recommendation_filter:
                skipped_reasons["recommendation_mismatch"].append(key)
                continue
        elif output_file.exists() and not args.force:
            skipped_reasons["output_exists"].append(key)
            continue

        issue = _parse_issue(path)

        # Skip issues with active work
        if issue["status"] in ("Review", "Testing"):
            skipped_reasons["active_work"].append(key)
            continue

        # Check prerequisites
        completeness_path = ISSUES_DIR / f"{key}.completeness.json"
        context_map_path = ISSUES_DIR / f"{key}.context-map.json"

        score = _extract_completeness_score(completeness_path)
        if score is None:
            skipped_reasons["no_completeness"].append(key)
            continue
        if score < 0:
            skipped_reasons["low_completeness"].append(key)
            continue

        # Filter by triage recommendation if requested
        if triage_filter:
            triage = _extract_triage_recommendation(completeness_path)
            if triage != triage_filter:
                skipped_reasons["triage_mismatch"].append(key)
                continue

        rating = _extract_context_rating(context_map_path)
        if rating is None:
            skipped_reasons["no_context_map"].append(key)
            continue
        if rating == "no-context":
            skipped_reasons["no_context"].append(key)
            continue

        # Filter by component if requested
        if component_filter:
            if not _issue_matches_component_filter(issue, component_filter):
                skipped_reasons["component_mismatch"].append(key)
                continue

        # Extract component names from context-map
        component_names = _extract_components_from_context_map(context_map_path)
        if not component_names:
            skipped_reasons["no_components"].append(key)
            continue

        # Create workspace and clone midstream repos
        workspace_dir = fix_workspaces_root / key

        # Reset cloned repos to clean state when --force or --recommendation is used,
        # so the agent starts from unmodified source code.
        if (args.force or recommendation_filter) and workspace_dir.exists():
            import subprocess as _sp
            for child in workspace_dir.iterdir():
                if child.is_dir() and (child / ".git").exists():
                    _sp.run(
                        ["git", "-C", str(child), "checkout", "."],
                        capture_output=True, timeout=30,
                    )
                    _sp.run(
                        ["git", "-C", str(child), "clean", "-fd"],
                        capture_output=True, timeout=30,
                    )

        cloned_repos: dict[str, Path] = {}

        for comp_name in component_names:
            clone_path = clone_midstream_repo(comp_name, workspace_dir)
            if clone_path is not None:
                cloned_repos[comp_name] = clone_path

        # If no repos were cloned (all downstream-only or clone failures),
        # let the agent work read-only with architecture-context
        workspace_info = _build_workspace_info(workspace_dir, cloned_repos, component_names)

        issue_text = _issue_to_text(issue)
        completeness_text = completeness_path.read_text()
        context_map_text = context_map_path.read_text()
        prompt = build_phase_prompt(
            "bug-fix-attempt", key, issue_text,
            completeness_analysis=completeness_text,
            context_map=context_map_text,
            workspace_info=workspace_info,
        )

        # Set agent CWD to workspace if repos were cloned, else project root
        agent_cwd = str(workspace_dir) if cloned_repos else str(BASE_DIR)

        jobs.append({
            "name": key,
            "cwd": agent_cwd,
            "prompt": prompt,
            "stale_files": [output_file, output_md],
        })
        job_workspaces[key] = workspace_dir

    # Print skip summary
    for reason, keys in skipped_reasons.items():
        if keys:
            print(f"  Skipped ({reason}): {len(keys)} issues")

    if getattr(args, "limit", None):
        jobs = jobs[: args.limit]

    results = await _run_phase("fix-attempt", jobs, args)

    # Post-agent: capture git diffs and update JSON patch fields
    for result in results:
        if not isinstance(result, dict) or not result.get("success"):
            continue
        key = result["name"]
        workspace_dir = job_workspaces.get(key)
        if workspace_dir is None:
            continue
        captured_diff = _capture_git_diffs(workspace_dir)
        if captured_diff:
            json_path = ISSUES_DIR / f"{key}.fix-attempt.json"
            _update_fix_json_patch(json_path, captured_diff)
            print(f"  {key}: captured git diff ({len(captured_diff)} chars)")

    _validate_phase_outputs("fix-attempt", results)
    return results


# ---------------------------------------------------------------------------
# Phase 5: Test plan
# ---------------------------------------------------------------------------

async def run_test_plan_phase(args) -> list:
    """Generate ecosystem-aware test plans for all bugs."""
    issue_paths = _discover_issues(args)
    jobs = []
    triage_filter = getattr(args, "triage", None)
    component_filter = getattr(args, "component", None)
    recommendation_filter = getattr(args, "recommendation", None)
    skipped_triage = []
    skipped_component = []
    skipped_recommendation = []

    for path in issue_paths:
        key = _issue_key_from_path(path)
        output_file = ISSUES_DIR / f"{key}.test-plan.json"
        output_md = ISSUES_DIR / f"{key}.test-plan.md"

        # When --recommendation is set, filter on existing fix-attempt recommendation
        fix_attempt_path = ISSUES_DIR / f"{key}.fix-attempt.json"
        if recommendation_filter:
            existing_rec = _extract_fix_recommendation(fix_attempt_path)
            if existing_rec != recommendation_filter:
                skipped_recommendation.append(key)
                continue
        elif output_file.exists() and not args.force:
            print(f"  skip {key} (output exists)")
            continue

        # Filter by triage recommendation if requested
        completeness_path = ISSUES_DIR / f"{key}.completeness.json"
        if triage_filter:
            triage = _extract_triage_recommendation(completeness_path)
            if triage != triage_filter:
                skipped_triage.append(key)
                continue

        issue = _parse_issue(path)

        # Filter by component if requested
        if component_filter:
            if not _issue_matches_component_filter(issue, component_filter):
                skipped_component.append(key)
                continue
        issue_text = _issue_to_text(issue)

        extra: dict[str, str] = {}

        # Include completeness analysis if available
        completeness_path = ISSUES_DIR / f"{key}.completeness.json"
        if completeness_path.exists():
            extra["completeness_analysis"] = completeness_path.read_text()

        # Include context map if available
        context_map_path = ISSUES_DIR / f"{key}.context-map.json"
        if context_map_path.exists():
            extra["context_map"] = context_map_path.read_text()

        # Include fix attempt if available
        fix_path = ISSUES_DIR / f"{key}.fix-attempt.json"
        if fix_path.exists():
            extra["fix_attempt"] = fix_path.read_text()

        prompt = build_phase_prompt("bug-test-plan", key, issue_text, **extra)

        jobs.append({
            "name": key,
            "cwd": str(BASE_DIR),
            "prompt": prompt,
            "stale_files": [output_file, output_md],
        })

    if skipped_triage:
        print(f"  Skipped (triage_mismatch): {len(skipped_triage)} issues")
    if skipped_component:
        print(f"  Skipped (component_mismatch): {len(skipped_component)} issues")
    if skipped_recommendation:
        print(f"  Skipped (recommendation_mismatch): {len(skipped_recommendation)} issues")

    if getattr(args, "limit", None):
        jobs = jobs[: args.limit]

    results = await _run_phase("test-plan", jobs, args)
    _validate_phase_outputs("test-plan", results)
    return results


# ---------------------------------------------------------------------------
# Per-issue pipeline helpers (used by run_all_phases pipeline mode)
# ---------------------------------------------------------------------------


async def _maybe_run_completeness(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
) -> dict:
    """Run completeness phase for one issue if needed. Returns result dict."""
    output_file = ISSUES_DIR / f"{key}.completeness.json"
    output_md = ISSUES_DIR / f"{key}.completeness.md"

    if output_file.exists() and not args.force:
        _log_activity(key, "completeness", "skipped", reason="output_exists")
        return {"name": key, "phase": "completeness", "skipped": True, "reason": "output_exists"}

    issue_text = _issue_to_text(issue)
    prompt = build_phase_prompt("bug-completeness", key, issue_text)

    result = await _run_single_agent(
        key, "completeness", str(BASE_DIR), prompt,
        [output_file, output_md], semaphore, log_dir, args.model,
    )
    return result


async def _maybe_run_context_map(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
) -> dict:
    """Run context-map phase for one issue if needed. Returns result dict."""
    output_file = ISSUES_DIR / f"{key}.context-map.json"
    output_md = ISSUES_DIR / f"{key}.context-map.md"

    if output_file.exists() and not args.force:
        _log_activity(key, "context-map", "skipped", reason="output_exists")
        return {"name": key, "phase": "context-map", "skipped": True, "reason": "output_exists"}

    issue_text = _issue_to_text(issue)
    prompt = build_phase_prompt("bug-context-map", key, issue_text)

    result = await _run_single_agent(
        key, "context-map", str(BASE_DIR), prompt,
        [output_file, output_md], semaphore, log_dir, args.model,
    )
    return result


async def _maybe_run_fix_attempt(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
) -> dict:
    """Run fix-attempt phase for one issue if eligible. Returns result dict."""
    output_file = ISSUES_DIR / f"{key}.fix-attempt.json"
    output_md = ISSUES_DIR / f"{key}.fix-attempt.md"
    recommendation_filter = getattr(args, "recommendation", None)
    triage_filter = getattr(args, "triage", None)

    # When --recommendation is set, filter on existing fix-attempt output
    if recommendation_filter:
        existing_rec = _extract_fix_recommendation(output_file)
        if existing_rec != recommendation_filter:
            _log_activity(key, "fix-attempt", "skipped", reason="recommendation_mismatch")
            return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "recommendation_mismatch"}
    elif output_file.exists() and not args.force:
        _log_activity(key, "fix-attempt", "skipped", reason="output_exists")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "output_exists"}

    # Skip issues with active work
    if issue["status"] in ("Review", "Testing"):
        _log_activity(key, "fix-attempt", "skipped", reason="active_work")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "active_work"}

    # Check prerequisites (read from disk — phases 2+3 already ran or were skipped)
    completeness_path = ISSUES_DIR / f"{key}.completeness.json"
    context_map_path = ISSUES_DIR / f"{key}.context-map.json"

    score = _extract_completeness_score(completeness_path)
    if score is None:
        _log_activity(key, "fix-attempt", "skipped", reason="no_completeness")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "no_completeness"}
    if score < 0:
        _log_activity(key, "fix-attempt", "skipped", reason="low_completeness")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "low_completeness"}

    if triage_filter:
        triage = _extract_triage_recommendation(completeness_path)
        if triage != triage_filter:
            _log_activity(key, "fix-attempt", "skipped", reason="triage_mismatch")
            return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "triage_mismatch"}

    rating = _extract_context_rating(context_map_path)
    if rating is None:
        _log_activity(key, "fix-attempt", "skipped", reason="no_context_map")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "no_context_map"}
    if rating == "no-context":
        _log_activity(key, "fix-attempt", "skipped", reason="no_context")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "no_context"}

    component_names = _extract_components_from_context_map(context_map_path)
    if not component_names:
        _log_activity(key, "fix-attempt", "skipped", reason="no_components")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "no_components"}

    # Create workspace and clone midstream repos
    fix_workspaces_root = BASE_DIR / "fix-workspaces"
    workspace_dir = fix_workspaces_root / key

    if (args.force or recommendation_filter) and workspace_dir.exists():
        import subprocess as _sp
        for child in workspace_dir.iterdir():
            if child.is_dir() and (child / ".git").exists():
                _sp.run(
                    ["git", "-C", str(child), "checkout", "."],
                    capture_output=True, timeout=30,
                )
                _sp.run(
                    ["git", "-C", str(child), "clean", "-fd"],
                    capture_output=True, timeout=30,
                )

    cloned_repos: dict[str, Path] = {}
    for comp_name in component_names:
        clone_path = clone_midstream_repo(comp_name, workspace_dir)
        if clone_path is not None:
            cloned_repos[comp_name] = clone_path

    workspace_info = _build_workspace_info(workspace_dir, cloned_repos, component_names)

    issue_text = _issue_to_text(issue)
    completeness_text = completeness_path.read_text()
    context_map_text = context_map_path.read_text()
    prompt = build_phase_prompt(
        "bug-fix-attempt", key, issue_text,
        completeness_analysis=completeness_text,
        context_map=context_map_text,
        workspace_info=workspace_info,
    )

    agent_cwd = str(workspace_dir) if cloned_repos else str(BASE_DIR)

    result = await _run_single_agent(
        key, "fix-attempt", agent_cwd, prompt,
        [output_file, output_md], semaphore, log_dir, args.model,
    )

    # Post-agent: capture git diffs and update JSON patch field
    if isinstance(result, dict) and result.get("success"):
        captured_diff = _capture_git_diffs(workspace_dir)
        if captured_diff:
            json_path = ISSUES_DIR / f"{key}.fix-attempt.json"
            _update_fix_json_patch(json_path, captured_diff)
            print(f"  [{key}] fix-attempt: captured git diff ({len(captured_diff)} chars)")

    return result


async def _maybe_run_test_plan(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
) -> dict:
    """Run test-plan phase for one issue if eligible. Returns result dict."""
    output_file = ISSUES_DIR / f"{key}.test-plan.json"
    output_md = ISSUES_DIR / f"{key}.test-plan.md"
    triage_filter = getattr(args, "triage", None)
    recommendation_filter = getattr(args, "recommendation", None)

    # When --recommendation is set, filter on existing fix-attempt recommendation
    fix_attempt_path = ISSUES_DIR / f"{key}.fix-attempt.json"
    if recommendation_filter:
        existing_rec = _extract_fix_recommendation(fix_attempt_path)
        if existing_rec != recommendation_filter:
            _log_activity(key, "test-plan", "skipped", reason="recommendation_mismatch")
            return {"name": key, "phase": "test-plan", "skipped": True, "reason": "recommendation_mismatch"}
    elif output_file.exists() and not args.force:
        _log_activity(key, "test-plan", "skipped", reason="output_exists")
        return {"name": key, "phase": "test-plan", "skipped": True, "reason": "output_exists"}

    # Filter by triage recommendation if requested
    completeness_path = ISSUES_DIR / f"{key}.completeness.json"
    if triage_filter:
        triage = _extract_triage_recommendation(completeness_path)
        if triage != triage_filter:
            _log_activity(key, "test-plan", "skipped", reason="triage_mismatch")
            return {"name": key, "phase": "test-plan", "skipped": True, "reason": "triage_mismatch"}

    issue_text = _issue_to_text(issue)
    extra: dict[str, str] = {}

    if completeness_path.exists():
        extra["completeness_analysis"] = completeness_path.read_text()

    context_map_path = ISSUES_DIR / f"{key}.context-map.json"
    if context_map_path.exists():
        extra["context_map"] = context_map_path.read_text()

    if fix_attempt_path.exists():
        extra["fix_attempt"] = fix_attempt_path.read_text()

    prompt = build_phase_prompt("bug-test-plan", key, issue_text, **extra)

    result = await _run_single_agent(
        key, "test-plan", str(BASE_DIR), prompt,
        [output_file, output_md], semaphore, log_dir, args.model,
    )
    return result


async def _run_issue_pipeline(
    key: str,
    path: Path,
    args,
    semaphore: asyncio.Semaphore,
    log_dirs: dict[str, Path],
) -> dict:
    """Process one issue through all applicable phases sequentially.

    Phases 2 (completeness) and 3 (context-map) run concurrently since they
    are independent.  Phase 4 (fix-attempt) waits for both, and phase 5
    (test-plan) waits for phase 4.
    """
    issue = _parse_issue(path)
    recommendation_filter = getattr(args, "recommendation", None)
    component_filter = getattr(args, "component", None)

    _log_activity(key, "pipeline", "issue_started")

    results: dict[str, dict] = {}

    # Early component filter — skip the entire issue
    if component_filter:
        if not _issue_matches_component_filter(issue, component_filter):
            for phase in ("completeness", "context-map", "fix-attempt", "test-plan"):
                _log_activity(key, phase, "skipped", reason="component_mismatch")
                results[phase] = {"name": key, "phase": phase, "skipped": True, "reason": "component_mismatch"}
            _log_activity(key, "pipeline", "issue_completed", phases_run=0, phases_failed=0)
            return results

    # --recommendation: skip phases 2+3 (results already exist)
    if recommendation_filter:
        _log_activity(key, "completeness", "skipped", reason="recommendation_mode")
        results["completeness"] = {"name": key, "phase": "completeness", "skipped": True, "reason": "recommendation_mode"}
        _log_activity(key, "context-map", "skipped", reason="recommendation_mode")
        results["context-map"] = {"name": key, "phase": "context-map", "skipped": True, "reason": "recommendation_mode"}
    else:
        # Phases 2+3 in parallel (both independent — only need raw issue JSON)
        comp_result, ctx_result = await asyncio.gather(
            _maybe_run_completeness(key, issue, args, semaphore, log_dirs["completeness"]),
            _maybe_run_context_map(key, issue, args, semaphore, log_dirs["context-map"]),
        )
        results["completeness"] = comp_result
        results["context-map"] = ctx_result

    # Phase 4 (depends on 2+3)
    results["fix-attempt"] = await _maybe_run_fix_attempt(
        key, issue, args, semaphore, log_dirs["fix-attempt"],
    )

    # Phase 5 (depends on 4)
    results["test-plan"] = await _maybe_run_test_plan(
        key, issue, args, semaphore, log_dirs["test-plan"],
    )

    phases_run = sum(1 for r in results.values() if isinstance(r, dict) and not r.get("skipped"))
    phases_failed = sum(1 for r in results.values() if isinstance(r, dict) and not r.get("skipped") and not r.get("success"))
    _log_activity(key, "pipeline", "issue_completed", phases_run=phases_run, phases_failed=phases_failed)

    return results


# ---------------------------------------------------------------------------
# Run all phases
# ---------------------------------------------------------------------------

async def run_all_phases(args) -> None:
    """Run phases 2-5 using a per-issue pipeline model.

    Each issue flows through all its phases independently, sharing a single
    concurrency pool (semaphore).  This maximises throughput compared to the
    old batch-per-phase approach where every issue had to finish one phase
    before any issue could advance to the next.
    """
    # Phase 1 (optional)
    if getattr(args, "include_fetch", False):
        await run_fetch_phase(args)

    # Discover issues
    issue_paths = _discover_issues(args)
    if getattr(args, "limit", None):
        issue_paths = issue_paths[: args.limit]

    # Shared concurrency control
    semaphore = asyncio.Semaphore(args.max_concurrent)

    # Log directories per phase
    phase_names = ["completeness", "context-map", "fix-attempt", "test-plan"]
    log_dirs = {}
    for pn in phase_names:
        d = BASE_DIR / "logs" / pn
        d.mkdir(parents=True, exist_ok=True)
        log_dirs[pn] = d

    # Startup banner
    print(f"\n{'=' * 80}")
    print("PIPELINE MODE — per-issue execution")
    print(f"{'=' * 80}")
    print(f"Issues: {len(issue_paths)}")
    print(f"Max concurrent agents: {args.max_concurrent}")
    print(f"Model: {args.model}")
    print(f"Force: {args.force}")
    recommendation_filter = getattr(args, "recommendation", None)
    triage_filter = getattr(args, "triage", None)
    component_filter = getattr(args, "component", None)
    if recommendation_filter:
        print(f"Recommendation filter: {recommendation_filter}")
    if triage_filter:
        print(f"Triage filter: {triage_filter}")
    if component_filter:
        print(f"Component filter: {component_filter}")
    print(f"{'=' * 80}\n")

    _log_activity(
        "_pipeline", "pipeline", "pipeline_started",
        model=args.model,
        total_issues=len(issue_paths),
        max_concurrent=args.max_concurrent,
        force=args.force,
        recommendation_filter=recommendation_filter,
        triage_filter=triage_filter,
        component_filter=component_filter,
    )

    try:
        # Launch per-issue pipelines
        all_results = await asyncio.gather(
            *(
                _run_issue_pipeline(
                    _issue_key_from_path(path), path, args, semaphore, log_dirs,
                )
                for path in issue_paths
            ),
            return_exceptions=True,
        )

        # Aggregate summary
        phase_stats: dict[str, dict[str, int]] = {
            pn: {"ran": 0, "success": 0, "failed": 0, "skipped": 0}
            for pn in phase_names
        }
        exceptions: list[Exception] = []

        for entry in all_results:
            if isinstance(entry, Exception):
                exceptions.append(entry)
                continue
            if not isinstance(entry, dict):
                continue
            for pn in phase_names:
                r = entry.get(pn)
                if r is None:
                    continue
                if r.get("skipped"):
                    phase_stats[pn]["skipped"] += 1
                elif r.get("success"):
                    phase_stats[pn]["ran"] += 1
                    phase_stats[pn]["success"] += 1
                else:
                    phase_stats[pn]["ran"] += 1
                    phase_stats[pn]["failed"] += 1

        print(f"\n{'=' * 80}")
        print("PIPELINE COMPLETE")
        print(f"{'=' * 80}")
        print(f"Total issues: {len(issue_paths)}")
        for pn in phase_names:
            s = phase_stats[pn]
            print(
                f"  {pn:16s}  ran={s['ran']}  success={s['success']}  "
                f"failed={s['failed']}  skipped={s['skipped']}"
            )
        if exceptions:
            print(f"\nExceptions: {len(exceptions)}")
            for i, exc in enumerate(exceptions, 1):
                print(f"  {i}. {exc}")
        print(f"{'=' * 80}\n")

        _log_activity(
            "_pipeline", "pipeline", "pipeline_completed",
            total_issues=len(issue_paths),
            phase_stats=phase_stats,
            exceptions=len(exceptions),
        )

    except BaseException as exc:
        _log_activity(
            "_pipeline", "pipeline", "pipeline_failed",
            error=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def run_report_phase(args) -> None:
    """Launch the reporting dashboard web app."""
    from lib.webapp import create_app

    app = create_app()
    app.run(host=args.host, port=args.port, debug=True)


async def main(args) -> None:
    """Main entry point — dispatch to appropriate phase."""
    if args.command == "fetch":
        await run_fetch_phase(args)
    elif args.command == "completeness":
        await run_completeness_phase(args)
    elif args.command == "context-map":
        await run_context_map_phase(args)
    elif args.command == "fix-attempt":
        await run_fix_attempt_phase(args)
    elif args.command == "test-plan":
        await run_test_plan_phase(args)
    elif args.command == "all":
        await run_all_phases(args)
    elif args.command == "report":
        await run_report_phase(args)
    else:
        print("Error: No command specified. Use --help for usage information.")
        sys.exit(1)
