"""Phase orchestrators for the bug bash analysis pipeline."""

import html as html_mod
import json
import os
import shutil
import socket
import subprocess
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from jsonschema import validate, ValidationError

from lib.agent_runner import run_agent, format_duration, get_model_id
from lib.prompts import build_phase_prompt
from lib.schemas import PHASE_SCHEMAS
from lib.skill_config import (
    get_skill_name,
    get_allowed_tools,
    get_mcp_servers,
    resolve_cwd,
    should_enable_skills,
)
from lib.paths import (
    BASE_DIR, ISSUES_DIR, WORKSPACE_DIR,
    model_workspace, phase_json, phase_md, phase_log,
    src_dir, patch_diff, test_patch_diff, memory_md, issue_copy,
)
from lib.repo_mapping import (
    get_midstream, get_upstream, clone_midstream_repo,
    normalize_component_name, DOWNSTREAM_ONLY,
)
from lib.validation import (
    load_test_context,
    load_test_context_markdown,
    is_validation_eligible,
    resolve_container_recipes,
    start_validation_container,
    stop_validation_container,
    get_changed_files_from_workspace,
    run_validation_agent,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _cleanup_src(key: str, mid: str) -> None:
    """Remove only the ``src/`` directory under a model workspace to reclaim disk space.

    Results, diffs, and logs are preserved.
    """
    sd = src_dir(key, mid)
    if not sd.exists():
        return
    try:
        shutil.rmtree(sd)
        print(f"  [{key}] fix-attempt: cleaned up src/ in {mid}", file=sys.stderr)
    except Exception as exc:
        print(f"  [{key}] fix-attempt: src/ cleanup failed: {exc}", file=sys.stderr)


def _ensure_issue_copy(key: str, raw_path: Path) -> None:
    """Copy the raw issue JSON to ``workspace/{KEY}/issue.json`` if not already there."""
    dest = issue_copy(key)
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(raw_path, dest)


def _write_patch_diff(key: str, mid: str, diff_text: str) -> None:
    """Write a standalone ``patch.diff`` into the model workspace."""
    if not diff_text:
        return
    out = patch_diff(key, mid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(diff_text)


def _write_memory_md(key: str, mid: str, phase: str, duration: float, prompt_summary: str = "") -> None:
    """Append session metadata to ``MEMORY.md`` in the model workspace."""
    out = memory_md(key, mid)
    out.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = (
        f"## {phase} — {ts}\n\n"
        f"- Model: {mid}\n"
        f"- Duration: {format_duration(duration)}\n"
    )
    if prompt_summary:
        entry += f"- Prompt summary: {prompt_summary}\n"
    entry += "\n"
    with open(out, "a") as f:
        f.write(entry)


def _discover_issues(args) -> list[Path]:
    """Return a sorted list of issue JSON paths, filtered by CLI args."""
    if not ISSUES_DIR.exists():
        print(f"Error: issues directory not found: {ISSUES_DIR}")
        sys.exit(1)

    if args.issue:
        # Explicit issue(s) mode
        targets = []
        for key in args.issue:
            target = ISSUES_DIR / f"{key}.json"
            if not target.exists():
                print(f"Error: issue file not found: {target}")
                sys.exit(1)
            targets.append(target)
        return targets

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


def _parse_issue(path: Path) -> dict | None:
    """Load an issue JSON and return a dict with key fields as plain text.

    Returns None if the file contains invalid JSON.
    """
    with open(path) as f:
        try:
            raw = json.load(f)
        except json.JSONDecodeError:
            print(f"WARNING: skipping {path.name} (invalid JSON)", file=sys.stderr)
            return None

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


def _print_phase_summary(phase_name: str, jobs: list, results: list, model_id: str = "") -> None:
    """Print a standard summary block after a phase completes."""
    successful = [r for r in results if isinstance(r, dict) and r.get("success")]
    failed = [r for r in results if isinstance(r, dict) and not r.get("success")]
    exceptions = [r for r in results if isinstance(r, Exception)]

    print(f"\n{'=' * 60}")
    header = f"{phase_name.upper()} COMPLETE"
    if model_id:
        header += f" [{model_id}]"
    print(header)
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

_RFE_TASKS_DIR = BASE_DIR / "references" / "rfe-creator" / "artifacts" / "rfe-tasks"
_STRAT_TASKS_DIR = BASE_DIR / "references" / "rfe-creator" / "artifacts" / "strat-tasks"
_FRONTMATTER_SCRIPT = BASE_DIR / "references" / "rfe-creator" / "scripts" / "frontmatter.py"
_FRONTMATTER_CWD = str(BASE_DIR / "references" / "rfe-creator")

# Module-level dashboard URL — set by run_all_phases from --dashboard-url arg.
_dashboard_url: str | None = None


def _dashboard_reachable(url: str, timeout: float = 0.5) -> bool:
    """Quick TCP connect check — is anything listening at *url*?"""
    try:
        parsed = urlparse(url)
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except (OSError, TypeError):
        return False

# ---------------------------------------------------------------------------
# Dashboard push — dedicated background thread (keeps asyncio event loop clean)
# ---------------------------------------------------------------------------
import queue as _queue_mod
import threading as _threading

_push_queue: "_queue_mod.Queue[dict | None] | None" = None
_push_thread: "_threading.Thread | None" = None


def _start_push_thread() -> None:
    """Spin up the background thread that drains _push_queue via synchronous HTTP."""
    global _push_queue, _push_thread
    if _push_thread is not None:
        return
    _push_queue = _queue_mod.Queue(maxsize=500)
    _push_thread = _threading.Thread(target=_push_worker, daemon=True)
    _push_thread.start()


def _push_worker() -> None:
    """Background worker — synchronous POSTs, never touches the event loop."""
    import httpx
    client = httpx.Client(timeout=1.0)
    while True:
        try:
            payload = _push_queue.get()  # type: ignore[union-attr]
            if payload is None:
                break  # shutdown sentinel
            client.post(f"{_dashboard_url}/api/events/push", json=payload)
        except Exception:
            pass  # best-effort — silently drop on failure


def _enqueue_push(payload: dict) -> None:
    """Enqueue a payload for the background push thread. Drops if queue is full."""
    if _push_queue is not None:
        try:
            _push_queue.put_nowait(payload)
        except _queue_mod.Full:
            pass  # drop event rather than block the pipeline


def _log_activity(issue_key: str, phase: str, event: str, model: str = "", **extra) -> None:
    """Append a single activity entry to logs/activity.jsonl and push to dashboard."""
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

    # Best-effort push via background thread (never touches the event loop)
    if _dashboard_url:
        _enqueue_push({"type": "event", **entry})


def _inject_model_field(json_path: Path, mid: str) -> None:
    """Inject the ``model`` field into a phase output JSON if not already present."""
    if not json_path.exists():
        return
    try:
        with open(json_path) as f:
            data = json.load(f)
        if "model" not in data:
            data["model"] = mid
            with open(json_path, "w") as f:
                json.dump(data, f, indent=2)
    except (json.JSONDecodeError, OSError):
        pass


async def _run_single_agent(
    key: str,
    phase: str,
    cwd: str,
    prompt: str,
    stale_files: list[Path],
    semaphore: asyncio.Semaphore,
    log_dir: Path,
    model: str,
    mid: str = "",
    allowed_tools: list[str] | None = None,
) -> dict:
    """Acquire semaphore, delete stale files, run one agent, validate output.

    Parameters
    ----------
    model:  shorthand (``"opus"``) passed to the agent runner.
    mid:    full model ID (``"claude-opus-4-6"``), used for workspace paths.

    Returns a result dict with 'name', 'success', 'phase', and optional 'error'.
    """
    if not mid:
        mid = get_model_id(model)

    log_dir.mkdir(parents=True, exist_ok=True)
    _log_activity(key, phase, "started", model=mid)

    # Use per-model log file when workspace paths are in use
    log_file_path = phase_log(key, mid, phase)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)

    async with semaphore:
        # Delete stale outputs just before the agent runs (inside the
        # semaphore) so that a killed orchestrator doesn't leave files
        # deleted-but-never-regenerated.
        for stale_path in stale_files:
            if stale_path.exists():
                stale_path.unlink()

        result = await run_agent(
            key, cwd, prompt, log_dir, model,
            allowed_tools=allowed_tools,
            log_file=log_file_path,
        )

    if isinstance(result, dict):
        _log_activity(
            key, phase,
            "completed" if result.get("success") else "failed",
            model=mid,
            duration_seconds=result.get("duration_seconds"),
            error=result.get("error"),
        )
        result["phase"] = phase

        # Inline schema validation
        schema = PHASE_SCHEMAS.get(phase)
        json_out = phase_json(key, mid, phase)
        if schema and result.get("success"):
            if not json_out.exists():
                print(f"  WARNING: {key} — {phase} JSON output missing: {json_out}")
            else:
                try:
                    with open(json_out) as f:
                        data = json.load(f)
                    validate(instance=data, schema=schema)
                except (json.JSONDecodeError, ValidationError) as exc:
                    invalid_path = json_out.with_suffix(".json.invalid")
                    json_out.rename(invalid_path)
                    print(f"  INVALID: {key} — {phase} — {exc!s:.120}")
                    print(f"           Renamed to {invalid_path.name}")

        # Inject model field into JSON output
        if result.get("success") and json_out.exists():
            _inject_model_field(json_out, mid)

        # Write MEMORY.md entry
        dur = result.get("duration_seconds", 0)
        _write_memory_md(key, mid, phase, dur)

    dur = result.get("duration_seconds", 0) if isinstance(result, dict) else 0
    status = "completed" if isinstance(result, dict) and result.get("success") else "failed"
    print(f"  [{key}] {phase}/{mid} → {status} ({format_duration(dur)})")

    return result


async def _run_phase(phase_name: str, jobs: list, args) -> list:
    """Execute a list of agent jobs with bounded concurrency across all models."""
    log_dir = BASE_DIR / "logs" / phase_name
    log_dir.mkdir(parents=True, exist_ok=True)

    # Determine unique models for the banner
    unique_models = sorted(set(job["model_id"] for job in jobs)) if jobs else []
    models_label = ", ".join(unique_models) if unique_models else "(none)"

    print(f"\n{'=' * 60}")
    print(f"PHASE: {phase_name}  [{models_label}]")
    print(f"{'=' * 60}")
    print(f"Issues to process: {len(jobs)}")
    print(f"Max concurrent agents: {args.max_concurrent}")
    print(f"Models: {models_label}")
    print(f"{'=' * 60}\n")

    if not jobs:
        print("Nothing to do — all issues already have output (use --force to regenerate).")
        return []

    semaphore = asyncio.Semaphore(args.max_concurrent)

    async def run_with_semaphore(job):
        mid = job["model_id"]
        ms = job["model_shorthand"]
        _log_activity(job["name"], phase_name, "started", model=mid)
        log_file_path = phase_log(job["name"], mid, phase_name)
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        async with semaphore:
            for stale_path in job.get("stale_files", []):
                if stale_path.exists():
                    stale_path.unlink()
            result = await run_agent(
                job["name"], job["cwd"], job["prompt"], log_dir, ms,
                log_file=log_file_path,
            )
        if isinstance(result, dict):
            _log_activity(
                job["name"], phase_name,
                "completed" if result.get("success") else "failed",
                model=mid,
                duration_seconds=result.get("duration_seconds"),
                error=result.get("error"),
            )
            # Inject model field
            json_out = phase_json(job["name"], mid, phase_name)
            if result.get("success") and json_out.exists():
                _inject_model_field(json_out, mid)
            result["model_id"] = mid
            result["model_shorthand"] = ms
        return result

    results = await asyncio.gather(
        *(run_with_semaphore(job) for job in jobs),
        return_exceptions=True,
    )

    # Print per-model summaries
    for mid in unique_models:
        model_jobs = [j for j in jobs if j["model_id"] == mid]
        model_results = [r for r, j in zip(results, jobs) if j["model_id"] == mid]
        _print_phase_summary(phase_name, model_jobs, model_results, model_id=mid)

    return list(results)


def _validate_phase_outputs(phase_name: str, results: list, mid: str = "") -> None:
    """Validate JSON outputs from a phase against the schema."""
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
        if mid:
            json_path = phase_json(key, mid, phase_name)
        else:
            json_path = ISSUES_DIR / f"{key}.{phase_name}.json"
        if not json_path.exists():
            print(f"  WARNING: {key} — JSON output missing: {json_path}")
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

    jira_server = os.environ.get("JIRA_SERVER", "").rstrip("/")
    jira_user = os.environ.get("JIRA_USER", "")
    jira_token = os.environ.get("JIRA_TOKEN", "")

    if not jira_server or not jira_token:
        print("Error: JIRA_SERVER and JIRA_TOKEN must be set in .env")
        sys.exit(1)

    ISSUES_DIR.mkdir(exist_ok=True)

    is_cloud = ".atlassian.net" in jira_server.lower()
    session = requests.Session()
    session.headers["Accept"] = "application/json"
    if is_cloud:
        session.auth = (jira_user, jira_token)
    else:
        session.headers["Authorization"] = f"Bearer {jira_token}"

    api_base = f"{jira_server}/rest/api/3" if is_cloud else f"{jira_server}/rest/api/2"
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
    component_filter = getattr(args, "component", None)
    all_jobs: list = []

    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_jobs: list = []

        for path in issue_paths:
            key = _issue_key_from_path(path)
            output_file = phase_json(key, mid, "completeness")
            output_md_file = phase_md(key, mid, "completeness")

            if output_file.exists() and not args.force:
                print(f"  skip {key}/{mid} (output exists)")
                continue

            issue = _parse_issue(path)
            if component_filter:
                if not _issue_matches_component_filter(issue, component_filter):
                    continue

            _ensure_issue_copy(key, path)
            ws = model_workspace(key, mid)
            ws.mkdir(parents=True, exist_ok=True)

            issue_text = _issue_to_text(issue)
            prompt = build_phase_prompt("bug-completeness", key, issue_text, output_dir=ws)

            model_jobs.append({
                "name": key,
                "cwd": str(BASE_DIR),
                "prompt": prompt,
                "stale_files": [output_file, output_md_file],
                "model_shorthand": model_shorthand,
                "model_id": mid,
            })

        if getattr(args, "limit", None):
            model_jobs = model_jobs[: args.limit]
        all_jobs.extend(model_jobs)

    results = await _run_phase("completeness", all_jobs, args)
    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_results = [r for r in results if isinstance(r, dict) and r.get("model_id") == mid]
        _validate_phase_outputs("completeness", model_results, mid=mid)

    return results


# ---------------------------------------------------------------------------
# Phase 3: Context map
# ---------------------------------------------------------------------------

async def run_context_map_phase(args) -> list:
    """Map each bug to available architecture context."""
    issue_paths = _discover_issues(args)
    component_filter = getattr(args, "component", None)
    all_jobs: list = []

    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_jobs: list = []

        for path in issue_paths:
            key = _issue_key_from_path(path)
            output_file = phase_json(key, mid, "context-map")
            output_md_file = phase_md(key, mid, "context-map")

            if output_file.exists() and not args.force:
                print(f"  skip {key}/{mid} (output exists)")
                continue

            issue = _parse_issue(path)
            if component_filter:
                if not _issue_matches_component_filter(issue, component_filter):
                    continue

            _ensure_issue_copy(key, path)
            ws = model_workspace(key, mid)
            ws.mkdir(parents=True, exist_ok=True)

            issue_text = _issue_to_text(issue)
            prompt = build_phase_prompt("bug-context-map", key, issue_text, output_dir=ws)

            model_jobs.append({
                "name": key,
                "cwd": str(BASE_DIR),
                "prompt": prompt,
                "stale_files": [output_file, output_md_file],
                "model_shorthand": model_shorthand,
                "model_id": mid,
            })

        if getattr(args, "limit", None):
            model_jobs = model_jobs[: args.limit]
        all_jobs.extend(model_jobs)

    results = await _run_phase("context-map", all_jobs, args)
    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_results = [r for r in results if isinstance(r, dict) and r.get("model_id") == mid]
        _validate_phase_outputs("context-map", model_results, mid=mid)

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
    """Extract unique, normalized component names from context_entries in a context-map JSON."""
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


def _update_fix_json_validation(json_path: Path, validation_iterations: list[dict]) -> None:
    """Inject the validation results array into the fix-attempt JSON."""
    if not json_path.exists() or not validation_iterations:
        return
    try:
        with open(json_path) as f:
            data = json.load(f)
        data["validation"] = validation_iterations
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, KeyError):
        pass


def _update_fix_json_self_corrections(json_path: Path, self_corrections: list[dict]) -> None:
    """Inject the accumulated self_corrections array into the fix-attempt JSON."""
    if not json_path.exists() or not self_corrections:
        return
    try:
        with open(json_path) as f:
            data = json.load(f)
        data["self_corrections"] = self_corrections
        with open(json_path, "w") as f:
            json.dump(data, f, indent=2)
    except (json.JSONDecodeError, KeyError):
        pass


def _extract_self_corrections(json_path: Path) -> list[dict]:
    """Read self_corrections from a fix-attempt JSON, returning an empty list if absent."""
    if not json_path.exists():
        return []
    try:
        with open(json_path) as f:
            data = json.load(f)
        return data.get("self_corrections", [])
    except (json.JSONDecodeError, KeyError):
        return []


def _reset_workspace(workspace_dir: Path) -> None:
    """Reset all git repos in a workspace to clean state."""
    import subprocess as _sp
    if not workspace_dir.exists():
        return
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


def _load_test_context_for_components(component_names: list[str]) -> str:
    """Load test context markdown for components, returning combined text."""
    sections: list[str] = []
    for comp_name in component_names:
        md = load_test_context_markdown(comp_name)
        if md:
            sections.append(md)
    return "\n\n---\n\n".join(sections) if sections else ""


def _resolve_test_context_md_path(repo_name: str) -> str | None:
    """Return the absolute path to the test context .md file, or None."""
    from lib.validation import TESTS_CONTEXT_DIR
    from lib.repo_mapping import get_midstream

    # Try downstream name first
    md_path = TESTS_CONTEXT_DIR / f"{repo_name}.md"
    if md_path.exists():
        return str(md_path)

    # Try midstream name
    midstream = get_midstream(repo_name)
    if midstream:
        _org, midstream_repo = midstream
        md_path = TESTS_CONTEXT_DIR / f"{midstream_repo}.md"
        if md_path.exists():
            return str(md_path)

    return None


def _format_agent_validation_feedback(result: dict, iteration: int) -> str:
    """Format a validation agent's result dict into markdown for a retry prompt."""
    sections: list[str] = []

    if not result.get("setup_success", True):
        sections.append("**Setup failed** -- container setup commands did not complete successfully.")

    failed_cmds = [
        c for c in result.get("commands_run", [])
        if not c.get("passed", True)
    ]
    for cmd in failed_cmds:
        lines = [
            f"**{cmd.get('category', 'unknown').upper()} FAILED:** `{cmd.get('command', '')}`",
            f"- Exit code: {cmd.get('exit_code', 'unknown')}",
        ]
        summary = cmd.get("output_summary", "")
        if summary:
            lines.append(f"- Output:")
            lines.append(f"```")
            lines.append(summary)
            lines.append(f"```")
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = (
        f"## Validation Feedback (Iteration {iteration})\n\n"
        "The following lint/test commands failed after applying your patch. "
        "Please fix the errors and re-apply your changes.\n\n"
        "**Important:** Include a `self_corrections` entry in your JSON output "
        "describing what you got wrong and what you changed to fix it.\n\n"
    )
    return header + "\n\n".join(sections)


async def _run_validation_loop(
    key: str,
    workspace_dir: Path,
    component_names: list[str],
    cloned_repos: dict[str, Path],
    original_prompt: str,
    agent_cwd: str,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
    model: str,
    mid: str,
    max_iterations: int,
    json_path: Path,
    output_file: Path,
    output_md: Path,
) -> list[dict]:
    """Run validation loop: launch validation agent, retry with feedback on failure."""
    validation_iterations: list[dict] = []
    accumulated_corrections: list[dict] = []

    active_containers: dict[str, str] = {}

    try:
        for iteration in range(1, max_iterations + 1):
            print(f"  [{key}] validation iteration {iteration}/{max_iterations}")

            changed_files_map = get_changed_files_from_workspace(workspace_dir)
            if not changed_files_map:
                print(f"  [{key}] no changed files found, skipping validation")
                break

            iter_results: list[dict] = []

            for repo_dir_name, changed_files in changed_files_map.items():
                repo_path = workspace_dir / repo_dir_name

                if iteration == 1:
                    test_ctx = load_test_context(repo_dir_name)
                    if test_ctx and is_validation_eligible(test_ctx):
                        recipes = resolve_container_recipes(test_ctx, changed_files)
                        if recipes:
                            lang_key, recipe = recipes[0]
                            cn = start_validation_container(
                                f"{repo_dir_name}-{lang_key}", recipe, repo_path,
                            )
                            if cn:
                                active_containers[repo_dir_name] = cn
                            else:
                                print(f"  [{key}] failed to start container for {repo_dir_name}")
                                iter_results.append({
                                    "repo_name": repo_dir_name,
                                    "overall_passed": False,
                                    "setup_success": False,
                                    "skipped": False,
                                    "summary": "Failed to start validation container",
                                })
                                continue
                        else:
                            iter_results.append({
                                "repo_name": repo_dir_name,
                                "overall_passed": False,
                                "skipped": True,
                                "skip_reason": "no matching container recipe",
                            })
                            continue
                    else:
                        readiness = test_ctx.get("agent_readiness", "unknown") if test_ctx else "no test context"
                        iter_results.append({
                            "repo_name": repo_dir_name,
                            "overall_passed": False,
                            "skipped": True,
                            "skip_reason": f"not eligible (readiness: {readiness})",
                        })
                        continue

                container_name = active_containers.get(repo_dir_name)
                if not container_name:
                    iter_results.append({
                        "repo_name": repo_dir_name,
                        "overall_passed": False,
                        "skipped": True,
                        "skip_reason": "no container from initial setup",
                    })
                    continue

                test_context_md_path = _resolve_test_context_md_path(repo_dir_name)
                result_path = log_dir / f"{key}-{repo_dir_name}-val-{iteration}.json"

                print(f"  [{key}]   launching validation agent for {repo_dir_name}")
                val_result = await run_validation_agent(
                    key=key,
                    container_name=container_name,
                    test_context_md_path=test_context_md_path,
                    changed_files=changed_files,
                    result_output_path=result_path,
                    log_dir=log_dir,
                    model=model,
                )

                if val_result:
                    val_result["repo_name"] = repo_dir_name
                    val_result.setdefault("skipped", False)
                    iter_results.append(val_result)
                    status = "PASS" if val_result.get("overall_passed") else "FAIL"
                    print(f"  [{key}]   {repo_dir_name}: {status}")
                else:
                    iter_results.append({
                        "repo_name": repo_dir_name,
                        "overall_passed": False,
                        "skipped": False,
                        "summary": "Validation agent failed to produce results",
                    })
                    print(f"  [{key}]   {repo_dir_name}: AGENT FAILED")

            all_passed = all(
                r.get("overall_passed") or r.get("skipped")
                for r in iter_results
            )

            validation_iterations.append({
                "iteration": iteration,
                "all_passed": all_passed,
                "results": iter_results,
            })

            if all_passed:
                print(f"  [{key}] validation passed on iteration {iteration}")
                break

            if iteration == max_iterations:
                print(f"  [{key}] validation failed after {max_iterations} iterations")
                break

            feedback_parts: list[str] = []
            for r in iter_results:
                if not r.get("overall_passed") and not r.get("skipped"):
                    fb = _format_agent_validation_feedback(r, iteration)
                    if fb:
                        repo = r.get("repo_name", "unknown")
                        feedback_parts.append(f"### {repo}\n\n{fb}")

            if not feedback_parts:
                print(f"  [{key}] no actionable validation feedback, stopping retries")
                break

            retry_prompt = original_prompt + "\n\n" + "\n\n".join(feedback_parts)
            _reset_workspace(workspace_dir)

            print(f"  [{key}] launching retry agent (iteration {iteration + 1})")
            _log_activity(key, "fix-attempt", "validation_retry", iteration=iteration + 1)

            retry_result = await _run_single_agent(
                key, "fix-attempt", agent_cwd, retry_prompt,
                [output_file, output_md], semaphore, log_dir, model, mid=mid,
            )

            if not isinstance(retry_result, dict) or not retry_result.get("success"):
                print(f"  [{key}] retry agent failed, stopping validation loop")
                break

            captured_diff = _capture_git_diffs(workspace_dir)
            if captured_diff:
                _update_fix_json_patch(json_path, captured_diff)

            new_corrections = _extract_self_corrections(json_path)
            if new_corrections:
                accumulated_corrections.extend(new_corrections)

    finally:
        for cn in active_containers.values():
            stop_validation_container(cn)

    if accumulated_corrections:
        _update_fix_json_self_corrections(json_path, accumulated_corrections)

    return validation_iterations


async def run_fix_attempt_phase(args) -> list:
    """Attempt fixes for eligible bugs using midstream repo clones."""
    issue_paths = _discover_issues(args)
    triage_filter = getattr(args, "triage", None)
    component_filter = getattr(args, "component", None)
    recommendation_filter = getattr(args, "recommendation", None)
    all_jobs: list = []
    job_workspaces: dict[tuple[str, str], Path] = {}

    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_jobs: list = []

        skipped_reasons: dict[str, list[str]] = {
            "output_exists": [],
            "active_work": [],
            "triage_mismatch": [],
            "component_mismatch": [],
            "recommendation_mismatch": [],
        }

        for path in issue_paths:
            key = _issue_key_from_path(path)
            output_file = phase_json(key, mid, "fix-attempt")
            output_md_file = phase_md(key, mid, "fix-attempt")

            # When --recommendation is set, filter on existing fix-attempt output
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

            # Filter by triage recommendation if requested (per-model)
            completeness_path = phase_json(key, mid, "completeness")
            if triage_filter:
                triage = _extract_triage_recommendation(completeness_path)
                if triage != triage_filter:
                    skipped_reasons["triage_mismatch"].append(key)
                    continue

            # Filter by component if requested
            if component_filter:
                if not _issue_matches_component_filter(issue, component_filter):
                    skipped_reasons["component_mismatch"].append(key)
                    continue

            # Try to extract components from this model's context-map;
            # if it doesn't exist, try from the raw issue components.
            context_map_path = phase_json(key, mid, "context-map")
            component_names = _extract_components_from_context_map(context_map_path)

            _ensure_issue_copy(key, path)
            ws = model_workspace(key, mid)
            ws.mkdir(parents=True, exist_ok=True)

            # Clone repos into src_dir(key, mid) instead of fix_workspaces_root
            workspace_dir = src_dir(key, mid)

            # Reset cloned repos when --force or --recommendation
            if (args.force or recommendation_filter) and workspace_dir.exists():
                _reset_workspace(workspace_dir)

            cloned_repos: dict[str, Path] = {}
            if component_names:
                for comp_name in component_names:
                    clone_path = clone_midstream_repo(comp_name, workspace_dir)
                    if clone_path is not None:
                        cloned_repos[comp_name] = clone_path

            workspace_info = _build_workspace_info(workspace_dir, cloned_repos, component_names)

            issue_text = _issue_to_text(issue)

            prompt_kwargs: dict[str, str] = dict(workspace_info=workspace_info)

            # Include completeness analysis if available for this model
            if completeness_path.exists():
                prompt_kwargs["completeness_analysis"] = completeness_path.read_text()

            # Include context map if available for this model
            if context_map_path.exists():
                prompt_kwargs["context_map"] = context_map_path.read_text()

            # Load test context markdown for the agent prompt
            test_context_text = _load_test_context_for_components(component_names)
            if test_context_text:
                prompt_kwargs["test_context"] = test_context_text

            prompt = build_phase_prompt(
                "bug-fix-attempt", key, issue_text, output_dir=ws, **prompt_kwargs,
            )

            agent_cwd = str(workspace_dir) if cloned_repos else str(BASE_DIR)

            model_jobs.append({
                "name": key,
                "cwd": agent_cwd,
                "prompt": prompt,
                "stale_files": [output_file, output_md_file],
                "component_names": component_names,
                "cloned_repos": cloned_repos,
                "model_shorthand": model_shorthand,
                "model_id": mid,
            })
            job_workspaces[(key, mid)] = workspace_dir

        # Print skip summary
        for reason, keys_list in skipped_reasons.items():
            if keys_list:
                print(f"  Skipped ({reason}): {len(keys_list)} issues [{mid}]")

        if getattr(args, "limit", None):
            model_jobs = model_jobs[: args.limit]
        all_jobs.extend(model_jobs)

    skip_validation = getattr(args, "skip_validation", False)
    validation_retries = getattr(args, "validation_retries", 2)

    results = await _run_phase("fix-attempt", all_jobs, args)

    # Post-agent: capture git diffs, run validation, and update JSON
    log_dir = BASE_DIR / "logs" / "fix-attempt"
    semaphore = asyncio.Semaphore(getattr(args, "max_concurrent", 5))

    for i, result in enumerate(results):
        if not isinstance(result, dict) or not result.get("success"):
            continue
        key = result["name"]
        mid = result.get("model_id", "")
        model_shorthand = result.get("model_shorthand", "")
        workspace_dir = job_workspaces.get((key, mid))
        if workspace_dir is None:
            continue
        captured_diff = _capture_git_diffs(workspace_dir)
        json_path = phase_json(key, mid, "fix-attempt")
        if captured_diff:
            _update_fix_json_patch(json_path, captured_diff)
            _write_patch_diff(key, mid, captured_diff)
            print(f"  {key}/{mid}: captured git diff ({len(captured_diff)} chars)")

        # Run validation loop if enabled
        if not skip_validation and validation_retries > 0 and captured_diff:
            job = all_jobs[i] if i < len(all_jobs) else None
            if job:
                output_file = phase_json(key, mid, "fix-attempt")
                output_md_file = phase_md(key, mid, "fix-attempt")
                validation_results = await _run_validation_loop(
                    key=key,
                    workspace_dir=workspace_dir,
                    component_names=job.get("component_names", []),
                    cloned_repos=job.get("cloned_repos", {}),
                    original_prompt=job["prompt"],
                    agent_cwd=job["cwd"],
                    semaphore=semaphore,
                    log_dir=log_dir,
                    model=model_shorthand,
                    mid=mid,
                    max_iterations=validation_retries,
                    json_path=json_path,
                    output_file=output_file,
                    output_md=output_md_file,
                )
                if validation_results:
                    _update_fix_json_validation(json_path, validation_results)

        # Clean up src/ only (preserve results, diffs, logs)
        _cleanup_src(key, mid)

    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_results = [r for r in results if isinstance(r, dict) and r.get("model_id") == mid]
        _validate_phase_outputs("fix-attempt", model_results, mid=mid)

    return results


# ---------------------------------------------------------------------------
# Phase 5: Test plan
# ---------------------------------------------------------------------------

async def run_test_plan_phase(args) -> list:
    """Generate ecosystem-aware test plans for all bugs."""
    issue_paths = _discover_issues(args)
    triage_filter = getattr(args, "triage", None)
    component_filter = getattr(args, "component", None)
    recommendation_filter = getattr(args, "recommendation", None)
    all_jobs: list = []

    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_jobs: list = []
        skipped_triage = []
        skipped_component = []
        skipped_recommendation = []

        for path in issue_paths:
            key = _issue_key_from_path(path)
            output_file = phase_json(key, mid, "test-plan")
            output_md_file = phase_md(key, mid, "test-plan")

            # When --recommendation is set, filter on existing fix-attempt recommendation
            fix_attempt_path = phase_json(key, mid, "fix-attempt")
            if recommendation_filter:
                existing_rec = _extract_fix_recommendation(fix_attempt_path)
                if existing_rec != recommendation_filter:
                    skipped_recommendation.append(key)
                    continue
            elif output_file.exists() and not args.force:
                print(f"  skip {key}/{mid} (output exists)")
                continue

            # Filter by triage recommendation if requested
            completeness_path = phase_json(key, mid, "completeness")
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

            _ensure_issue_copy(key, path)
            ws = model_workspace(key, mid)
            ws.mkdir(parents=True, exist_ok=True)

            issue_text = _issue_to_text(issue)
            extra: dict[str, str] = {}

            if completeness_path.exists():
                extra["completeness_analysis"] = completeness_path.read_text()

            context_map_path = phase_json(key, mid, "context-map")
            if context_map_path.exists():
                extra["context_map"] = context_map_path.read_text()

            if fix_attempt_path.exists():
                extra["fix_attempt"] = fix_attempt_path.read_text()

            prompt = build_phase_prompt("bug-test-plan", key, issue_text, output_dir=ws, **extra)

            model_jobs.append({
                "name": key,
                "cwd": str(BASE_DIR),
                "prompt": prompt,
                "stale_files": [output_file, output_md_file],
                "model_shorthand": model_shorthand,
                "model_id": mid,
            })

        if skipped_triage:
            print(f"  Skipped (triage_mismatch): {len(skipped_triage)} issues [{mid}]")
        if skipped_component:
            print(f"  Skipped (component_mismatch): {len(skipped_component)} issues [{mid}]")
        if skipped_recommendation:
            print(f"  Skipped (recommendation_mismatch): {len(skipped_recommendation)} issues [{mid}]")

        if getattr(args, "limit", None):
            model_jobs = model_jobs[: args.limit]
        all_jobs.extend(model_jobs)

    results = await _run_phase("test-plan", all_jobs, args)
    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_results = [r for r in results if isinstance(r, dict) and r.get("model_id") == mid]
        _validate_phase_outputs("test-plan", model_results, mid=mid)

    return results


# ---------------------------------------------------------------------------
# Phase 6: Write test
# ---------------------------------------------------------------------------


def _clone_opendatahub_tests(workspace_dir: Path) -> Path | None:
    """Clone opendatahub-tests into workspace_dir/opendatahub-tests."""
    clone_dir = workspace_dir / "opendatahub-tests"
    if clone_dir.exists():
        return clone_dir
    clone_url = "https://github.com/opendatahub-io/opendatahub-tests.git"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    try:
        import subprocess
        subprocess.run(
            ["git", "clone", "--depth", "1", clone_url, str(clone_dir)],
            check=True, capture_output=True, text=True, timeout=120,
        )
        return clone_dir
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def _capture_test_repo_diff(clone_dir: Path) -> str:
    """Capture all changes (tracked and untracked) in the opendatahub-tests clone.

    ``git diff`` only shows modifications to tracked files.  The write-test
    agent typically creates *new* files which are untracked, so we stage
    everything first with ``git add -A`` and then use ``git diff --cached``
    to produce a complete diff that includes new files.
    """
    import subprocess

    if not clone_dir.exists() or not (clone_dir / ".git").exists():
        return ""
    try:
        # Stage everything (new + modified + deleted) so the diff includes
        # untracked files the agent created.
        subprocess.run(
            ["git", "-C", str(clone_dir), "add", "-A"],
            capture_output=True, text=True, timeout=30,
        )
        result = subprocess.run(
            ["git", "-C", str(clone_dir), "diff", "--cached"],
            capture_output=True, text=True, timeout=30,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ""


def _update_write_test_json_patch(json_path: Path, captured_diff: str) -> None:
    """Replace the ``patch`` field in a write-test JSON with the captured git diff."""
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


def _write_test_patch_diff(key: str, mid: str, diff_text: str) -> None:
    """Write a standalone ``test-patch.diff`` into the model workspace."""
    if not diff_text:
        return
    out = test_patch_diff(key, mid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(diff_text)


async def run_write_test_phase(args) -> list:
    """Write QE tests for opendatahub-tests based on fix attempts and test plans."""
    issue_paths = _discover_issues(args)
    component_filter = getattr(args, "component", None)
    recommendation_filter = getattr(args, "recommendation", None)
    all_jobs: list = []
    job_workspaces: dict[tuple[str, str], Path] = {}

    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_jobs: list = []
        skipped_reasons: dict[str, list[str]] = {
            "output_exists": [],
            "no_fix_attempt": [],
            "not_fixable": [],
            "recommendation_mismatch": [],
            "component_mismatch": [],
        }

        for path in issue_paths:
            key = _issue_key_from_path(path)
            output_file = phase_json(key, mid, "write-test")
            output_md_file = phase_md(key, mid, "write-test")

            # When --recommendation is set, filter on existing fix-attempt recommendation
            fix_attempt_path = phase_json(key, mid, "fix-attempt")
            if recommendation_filter:
                existing_rec = _extract_fix_recommendation(fix_attempt_path)
                if existing_rec != recommendation_filter:
                    skipped_reasons["recommendation_mismatch"].append(key)
                    continue
            elif output_file.exists() and not args.force:
                skipped_reasons["output_exists"].append(key)
                continue

            # Require fix-attempt to exist
            if not fix_attempt_path.exists():
                skipped_reasons["no_fix_attempt"].append(key)
                continue

            # Skip if fix-attempt recommendation is not ai-fixable
            existing_rec = _extract_fix_recommendation(fix_attempt_path)
            if existing_rec != "ai-fixable":
                skipped_reasons["not_fixable"].append(key)
                continue

            issue = _parse_issue(path)

            # Filter by component if requested
            if component_filter:
                if not _issue_matches_component_filter(issue, component_filter):
                    skipped_reasons["component_mismatch"].append(key)
                    continue

            _ensure_issue_copy(key, path)
            ws = model_workspace(key, mid)
            ws.mkdir(parents=True, exist_ok=True)

            # Clone opendatahub-tests into src_dir
            workspace_dir = src_dir(key, mid)
            clone_dir = _clone_opendatahub_tests(workspace_dir)
            if clone_dir is None:
                print(f"  [{key}] write-test: failed to clone opendatahub-tests, skipping")
                continue

            issue_text = _issue_to_text(issue)
            extra: dict[str, str] = {}

            # Load fix-attempt as input context
            extra["fix_attempt"] = fix_attempt_path.read_text()

            # Load test-plan if available
            test_plan_path = phase_json(key, mid, "test-plan")
            if test_plan_path.exists():
                extra["test_plan"] = test_plan_path.read_text()

            # Provide workspace info pointing to the cloned repo
            extra["workspace_info"] = (
                f"Workspace directory: {workspace_dir}\n\n"
                f"Cloned opendatahub-tests repository:\n"
                f"  - {clone_dir}/ (clone of opendatahub-io/opendatahub-tests)\n\n"
                f"Write test files directly into this clone. The orchestrator will\n"
                f"capture your changes as a git diff after the phase completes."
            )

            prompt = build_phase_prompt(
                "bug-write-test", key, issue_text, output_dir=ws, **extra,
            )

            model_jobs.append({
                "name": key,
                "cwd": str(workspace_dir),
                "prompt": prompt,
                "stale_files": [output_file, output_md_file],
                "model_shorthand": model_shorthand,
                "model_id": mid,
            })
            job_workspaces[(key, mid)] = workspace_dir

        # Print skip summary
        for reason, keys_list in skipped_reasons.items():
            if keys_list:
                print(f"  Skipped ({reason}): {len(keys_list)} issues [{mid}]")

        if getattr(args, "limit", None):
            model_jobs = model_jobs[: args.limit]
        all_jobs.extend(model_jobs)

    results = await _run_phase("write-test", all_jobs, args)

    # Post-agent: capture git diffs from opendatahub-tests clone
    for i, result in enumerate(results):
        if not isinstance(result, dict) or not result.get("success"):
            continue
        key = result["name"]
        mid = result.get("model_id", "")
        workspace_dir = job_workspaces.get((key, mid))
        if workspace_dir is None:
            continue
        clone_dir = workspace_dir / "opendatahub-tests"
        captured_diff = _capture_test_repo_diff(clone_dir)
        json_path = phase_json(key, mid, "write-test")
        if captured_diff:
            _update_write_test_json_patch(json_path, captured_diff)
            _write_test_patch_diff(key, mid, captured_diff)
            print(f"  {key}/{mid}: captured test repo diff ({len(captured_diff)} chars)")

        # Clean up cloned repo to save disk space
        _cleanup_src(key, mid)

    for model_shorthand in args.model:
        mid = get_model_id(model_shorthand)
        model_results = [r for r in results if isinstance(r, dict) and r.get("model_id") == mid]
        _validate_phase_outputs("write-test", model_results, mid=mid)

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
    model_shorthand: str,
    mid: str,
) -> dict:
    """Run completeness phase for one issue if needed. Returns result dict."""
    output_file = phase_json(key, mid, "completeness")
    output_md_file = phase_md(key, mid, "completeness")

    if output_file.exists() and not args.force:
        _log_activity(key, "completeness", "skipped", model=mid, reason="output_exists")
        return {"name": key, "phase": "completeness", "skipped": True, "reason": "output_exists"}

    ws = model_workspace(key, mid)
    ws.mkdir(parents=True, exist_ok=True)

    issue_text = _issue_to_text(issue)
    prompt = build_phase_prompt("bug-completeness", key, issue_text, output_dir=ws)

    result = await _run_single_agent(
        key, "completeness", str(BASE_DIR), prompt,
        [output_file, output_md_file], semaphore, log_dir, model_shorthand, mid=mid,
    )
    return result


async def _maybe_run_context_map(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
    model_shorthand: str,
    mid: str,
) -> dict:
    """Run context-map phase for one issue if needed. Returns result dict."""
    output_file = phase_json(key, mid, "context-map")
    output_md_file = phase_md(key, mid, "context-map")

    if output_file.exists() and not args.force:
        _log_activity(key, "context-map", "skipped", model=mid, reason="output_exists")
        return {"name": key, "phase": "context-map", "skipped": True, "reason": "output_exists"}

    ws = model_workspace(key, mid)
    ws.mkdir(parents=True, exist_ok=True)

    issue_text = _issue_to_text(issue)
    prompt = build_phase_prompt("bug-context-map", key, issue_text, output_dir=ws)

    result = await _run_single_agent(
        key, "context-map", str(BASE_DIR), prompt,
        [output_file, output_md_file], semaphore, log_dir, model_shorthand, mid=mid,
    )
    return result


async def _maybe_run_fix_attempt(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
    model_shorthand: str,
    mid: str,
) -> dict:
    """Run fix-attempt phase for one issue. No quality gating."""
    output_file = phase_json(key, mid, "fix-attempt")
    output_md_file = phase_md(key, mid, "fix-attempt")
    recommendation_filter = getattr(args, "recommendation", None)
    triage_filter = getattr(args, "triage", None)

    # When --recommendation is set, filter on existing fix-attempt output
    if recommendation_filter:
        existing_rec = _extract_fix_recommendation(output_file)
        if existing_rec != recommendation_filter:
            _log_activity(key, "fix-attempt", "skipped", model=mid, reason="recommendation_mismatch")
            return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "recommendation_mismatch"}
    elif output_file.exists() and not args.force:
        _log_activity(key, "fix-attempt", "skipped", model=mid, reason="output_exists")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "output_exists"}

    # Skip issues with active work
    if issue["status"] in ("Review", "Testing"):
        _log_activity(key, "fix-attempt", "skipped", model=mid, reason="active_work")
        return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "active_work"}

    # Per-model triage filter
    completeness_path = phase_json(key, mid, "completeness")
    if triage_filter:
        triage = _extract_triage_recommendation(completeness_path)
        if triage != triage_filter:
            _log_activity(key, "fix-attempt", "skipped", model=mid, reason="triage_mismatch")
            return {"name": key, "phase": "fix-attempt", "skipped": True, "reason": "triage_mismatch"}

    # Extract components (if context-map exists for this model)
    context_map_path = phase_json(key, mid, "context-map")
    component_names = _extract_components_from_context_map(context_map_path)

    ws = model_workspace(key, mid)
    ws.mkdir(parents=True, exist_ok=True)

    # Clone repos into src_dir
    workspace_dir = src_dir(key, mid)

    if (args.force or recommendation_filter) and workspace_dir.exists():
        _reset_workspace(workspace_dir)

    cloned_repos: dict[str, Path] = {}
    if component_names:
        for comp_name in component_names:
            clone_path = clone_midstream_repo(comp_name, workspace_dir)
            if clone_path is not None:
                cloned_repos[comp_name] = clone_path

    workspace_info = _build_workspace_info(workspace_dir, cloned_repos, component_names)

    issue_text = _issue_to_text(issue)

    prompt_kwargs: dict[str, str] = dict(workspace_info=workspace_info)

    if completeness_path.exists():
        prompt_kwargs["completeness_analysis"] = completeness_path.read_text()

    if context_map_path.exists():
        prompt_kwargs["context_map"] = context_map_path.read_text()

    test_context_text = _load_test_context_for_components(component_names)
    if test_context_text:
        prompt_kwargs["test_context"] = test_context_text

    prompt = build_phase_prompt(
        "bug-fix-attempt", key, issue_text, output_dir=ws, **prompt_kwargs,
    )

    agent_cwd = str(workspace_dir) if cloned_repos else str(BASE_DIR)

    result = await _run_single_agent(
        key, "fix-attempt", agent_cwd, prompt,
        [output_file, output_md_file], semaphore, log_dir, model_shorthand, mid=mid,
    )

    # Post-agent: capture git diffs and update JSON patch field
    if isinstance(result, dict) and result.get("success"):
        captured_diff = _capture_git_diffs(workspace_dir)
        json_path = phase_json(key, mid, "fix-attempt")
        if captured_diff:
            _update_fix_json_patch(json_path, captured_diff)
            _write_patch_diff(key, mid, captured_diff)
            print(f"  [{key}] fix-attempt: captured git diff ({len(captured_diff)} chars)")

        # Run validation loop if enabled
        skip_validation = getattr(args, "skip_validation", False)
        validation_retries = getattr(args, "validation_retries", 2)

        if not skip_validation and validation_retries > 0 and captured_diff:
            validation_results = await _run_validation_loop(
                key=key,
                workspace_dir=workspace_dir,
                component_names=component_names,
                cloned_repos=cloned_repos,
                original_prompt=prompt,
                agent_cwd=agent_cwd,
                semaphore=semaphore,
                log_dir=log_dir,
                model=model_shorthand,
                mid=mid,
                max_iterations=validation_retries,
                json_path=json_path,
                output_file=output_file,
                output_md=output_md_file,
            )
            if validation_results:
                _update_fix_json_validation(json_path, validation_results)

    # Clean up src/ only
    _cleanup_src(key, mid)

    return result


async def _maybe_run_test_plan(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
    model_shorthand: str,
    mid: str,
) -> dict:
    """Run test-plan phase for one issue if eligible. Returns result dict."""
    output_file = phase_json(key, mid, "test-plan")
    output_md_file = phase_md(key, mid, "test-plan")
    triage_filter = getattr(args, "triage", None)
    recommendation_filter = getattr(args, "recommendation", None)

    fix_attempt_path = phase_json(key, mid, "fix-attempt")
    if recommendation_filter:
        existing_rec = _extract_fix_recommendation(fix_attempt_path)
        if existing_rec != recommendation_filter:
            _log_activity(key, "test-plan", "skipped", model=mid, reason="recommendation_mismatch")
            return {"name": key, "phase": "test-plan", "skipped": True, "reason": "recommendation_mismatch"}
    elif output_file.exists() and not args.force:
        _log_activity(key, "test-plan", "skipped", model=mid, reason="output_exists")
        return {"name": key, "phase": "test-plan", "skipped": True, "reason": "output_exists"}

    completeness_path = phase_json(key, mid, "completeness")
    if triage_filter:
        triage = _extract_triage_recommendation(completeness_path)
        if triage != triage_filter:
            _log_activity(key, "test-plan", "skipped", model=mid, reason="triage_mismatch")
            return {"name": key, "phase": "test-plan", "skipped": True, "reason": "triage_mismatch"}

    ws = model_workspace(key, mid)
    ws.mkdir(parents=True, exist_ok=True)

    issue_text = _issue_to_text(issue)
    extra: dict[str, str] = {}

    if completeness_path.exists():
        extra["completeness_analysis"] = completeness_path.read_text()

    context_map_path = phase_json(key, mid, "context-map")
    if context_map_path.exists():
        extra["context_map"] = context_map_path.read_text()

    if fix_attempt_path.exists():
        extra["fix_attempt"] = fix_attempt_path.read_text()

    prompt = build_phase_prompt("bug-test-plan", key, issue_text, output_dir=ws, **extra)

    result = await _run_single_agent(
        key, "test-plan", str(BASE_DIR), prompt,
        [output_file, output_md_file], semaphore, log_dir, model_shorthand, mid=mid,
    )
    return result


async def _maybe_run_write_test(
    key: str,
    issue: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
    model_shorthand: str,
    mid: str,
) -> dict:
    """Run write-test phase for one issue if eligible. Returns result dict."""
    output_file = phase_json(key, mid, "write-test")
    output_md_file = phase_md(key, mid, "write-test")
    recommendation_filter = getattr(args, "recommendation", None)

    fix_attempt_path = phase_json(key, mid, "fix-attempt")
    if recommendation_filter:
        existing_rec = _extract_fix_recommendation(fix_attempt_path)
        if existing_rec != recommendation_filter:
            _log_activity(key, "write-test", "skipped", model=mid, reason="recommendation_mismatch")
            return {"name": key, "phase": "write-test", "skipped": True, "reason": "recommendation_mismatch"}
    elif output_file.exists() and not args.force:
        _log_activity(key, "write-test", "skipped", model=mid, reason="output_exists")
        return {"name": key, "phase": "write-test", "skipped": True, "reason": "output_exists"}

    # Require fix-attempt with ai-fixable recommendation
    if not fix_attempt_path.exists():
        _log_activity(key, "write-test", "skipped", model=mid, reason="no_fix_attempt")
        return {"name": key, "phase": "write-test", "skipped": True, "reason": "no_fix_attempt"}

    existing_rec = _extract_fix_recommendation(fix_attempt_path)
    if existing_rec != "ai-fixable":
        _log_activity(key, "write-test", "skipped", model=mid, reason="not_fixable")
        return {"name": key, "phase": "write-test", "skipped": True, "reason": "not_fixable"}

    ws = model_workspace(key, mid)
    ws.mkdir(parents=True, exist_ok=True)

    # Clone opendatahub-tests
    workspace_dir = src_dir(key, mid)
    clone_dir = _clone_opendatahub_tests(workspace_dir)
    if clone_dir is None:
        print(f"  [{key}] write-test: failed to clone opendatahub-tests, skipping")
        _log_activity(key, "write-test", "skipped", model=mid, reason="clone_failed")
        return {"name": key, "phase": "write-test", "skipped": True, "reason": "clone_failed"}

    issue_text = _issue_to_text(issue)
    extra: dict[str, str] = {}

    extra["fix_attempt"] = fix_attempt_path.read_text()

    test_plan_path = phase_json(key, mid, "test-plan")
    if test_plan_path.exists():
        extra["test_plan"] = test_plan_path.read_text()

    extra["workspace_info"] = (
        f"Workspace directory: {workspace_dir}\n\n"
        f"Cloned opendatahub-tests repository:\n"
        f"  - {clone_dir}/ (clone of opendatahub-io/opendatahub-tests)\n\n"
        f"Write test files directly into this clone. The orchestrator will\n"
        f"capture your changes as a git diff after the phase completes."
    )

    prompt = build_phase_prompt(
        "bug-write-test", key, issue_text, output_dir=ws, **extra,
    )

    result = await _run_single_agent(
        key, "write-test", str(workspace_dir), prompt,
        [output_file, output_md_file], semaphore, log_dir, model_shorthand, mid=mid,
    )

    # Post-agent: capture git diff from opendatahub-tests clone
    if isinstance(result, dict) and result.get("success"):
        captured_diff = _capture_test_repo_diff(clone_dir)
        json_path = phase_json(key, mid, "write-test")
        if captured_diff:
            _update_write_test_json_patch(json_path, captured_diff)
            _write_test_patch_diff(key, mid, captured_diff)
            print(f"  [{key}] write-test: captured test repo diff ({len(captured_diff)} chars)")

    # Clean up cloned repo
    _cleanup_src(key, mid)

    return result


async def _run_issue_pipeline(
    key: str,
    path: Path,
    args,
    semaphore: asyncio.Semaphore,
    log_dirs: dict[str, Path],
    model_shorthand: str,
    mid: str,
) -> dict:
    """Process one issue through all applicable phases sequentially for one model."""
    issue = _parse_issue(path)
    recommendation_filter = getattr(args, "recommendation", None)
    component_filter = getattr(args, "component", None)

    _log_activity(key, "pipeline", "issue_started", model=mid)
    _ensure_issue_copy(key, path)

    results: dict[str, dict] = {}

    # Early component filter — skip the entire issue
    if component_filter:
        if not _issue_matches_component_filter(issue, component_filter):
            for p in ("completeness", "context-map", "fix-attempt", "test-plan", "write-test"):
                _log_activity(key, p, "skipped", model=mid, reason="component_mismatch")
                results[p] = {"name": key, "phase": p, "skipped": True, "reason": "component_mismatch"}
            _log_activity(key, "pipeline", "issue_completed", model=mid, phases_run=0, phases_failed=0)
            return results

    # --recommendation: skip phases 2+3 (results already exist)
    if recommendation_filter:
        _log_activity(key, "completeness", "skipped", model=mid, reason="recommendation_mode")
        results["completeness"] = {"name": key, "phase": "completeness", "skipped": True, "reason": "recommendation_mode"}
        _log_activity(key, "context-map", "skipped", model=mid, reason="recommendation_mode")
        results["context-map"] = {"name": key, "phase": "context-map", "skipped": True, "reason": "recommendation_mode"}
    else:
        # Phases 2+3 in parallel
        comp_result, ctx_result = await asyncio.gather(
            _maybe_run_completeness(key, issue, args, semaphore, log_dirs["completeness"], model_shorthand, mid),
            _maybe_run_context_map(key, issue, args, semaphore, log_dirs["context-map"], model_shorthand, mid),
        )
        results["completeness"] = comp_result
        results["context-map"] = ctx_result

    # Phase 4 (no quality gating)
    results["fix-attempt"] = await _maybe_run_fix_attempt(
        key, issue, args, semaphore, log_dirs["fix-attempt"], model_shorthand, mid,
    )

    # Phase 5
    results["test-plan"] = await _maybe_run_test_plan(
        key, issue, args, semaphore, log_dirs["test-plan"], model_shorthand, mid,
    )

    # Phase 6
    results["write-test"] = await _maybe_run_write_test(
        key, issue, args, semaphore, log_dirs["write-test"], model_shorthand, mid,
    )

    phases_run = sum(1 for r in results.values() if isinstance(r, dict) and not r.get("skipped"))
    phases_failed = sum(1 for r in results.values() if isinstance(r, dict) and not r.get("skipped") and not r.get("success"))
    _log_activity(key, "pipeline", "issue_completed", model=mid, phases_run=phases_run, phases_failed=phases_failed)

    return results


# ---------------------------------------------------------------------------
# Run all phases
# ---------------------------------------------------------------------------

async def run_all_phases(args) -> None:
    """Run phases 2-6 using a per-issue pipeline model.

    All models run concurrently — the shared semaphore controls total
    concurrent agent count regardless of how many models are in the mix.
    """
    # Configure dashboard push URL (auto-disable if nothing is listening)
    global _dashboard_url
    _dashboard_url = getattr(args, "dashboard_url", None)
    if _dashboard_url and not _dashboard_reachable(_dashboard_url):
        print(f"  [dashboard] {_dashboard_url} not reachable — disabling push")
        _dashboard_url = None
    if _dashboard_url:
        _start_push_thread()

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
    phase_names = ["completeness", "context-map", "fix-attempt", "test-plan", "write-test"]
    log_dirs = {}
    for pn in phase_names:
        d = BASE_DIR / "logs" / pn
        d.mkdir(parents=True, exist_ok=True)
        log_dirs[pn] = d

    recommendation_filter = getattr(args, "recommendation", None)
    triage_filter = getattr(args, "triage", None)
    component_filter = getattr(args, "component", None)

    # Pre-filter issue_paths so the manifest only contains matching issues
    if component_filter:
        issue_paths = [
            p for p in issue_paths
            if _issue_matches_component_filter(_parse_issue(p), component_filter)
        ]

    # Build model list for banner
    model_entries = [(ms, get_model_id(ms)) for ms in args.model]
    models_label = ", ".join(mid for _, mid in model_entries)

    # Startup banner (once, listing all models)
    print(f"\n{'=' * 80}")
    print(f"PIPELINE MODE — per-issue execution [{models_label}]")
    print(f"{'=' * 80}")
    print(f"Issues: {len(issue_paths)}")
    print(f"Models: {len(model_entries)} ({models_label})")
    print(f"Total model×issue jobs: {len(issue_paths) * len(model_entries)}")
    print(f"Max concurrent agents: {args.max_concurrent}")
    print(f"Force: {args.force}")
    if recommendation_filter:
        print(f"Recommendation filter: {recommendation_filter}")
    if triage_filter:
        print(f"Triage filter: {triage_filter}")
    if component_filter:
        print(f"Component filter: {component_filter}")
    print(f"{'=' * 80}\n")

    # Build job manifest and push to dashboard
    issue_keys = [_issue_key_from_path(p) for p in issue_paths]
    manifest = {
        "type": "manifest",
        "total_issues": len(issue_keys),
        "models": [mid for _, mid in model_entries],
        "jobs": [
            {"key": key, "model": mid, "status": "pending"}
            for _, mid in model_entries
            for key in issue_keys
        ],
        "max_concurrent": args.max_concurrent,
        "force": args.force,
    }
    _enqueue_push(manifest)

    for _, mid in model_entries:
        _log_activity(
            "_pipeline", "pipeline", "pipeline_started",
            model=mid,
            total_issues=len(issue_paths),
            max_concurrent=args.max_concurrent,
            force=args.force,
            recommendation_filter=recommendation_filter,
            triage_filter=triage_filter,
            component_filter=component_filter,
        )

    try:
        # Launch per-issue pipelines across all models concurrently
        all_results = await asyncio.gather(
            *(
                _run_issue_pipeline(
                    _issue_key_from_path(path), path, args, semaphore, log_dirs,
                    ms, mid,
                )
                for ms, mid in model_entries
                for path in issue_paths
            ),
            return_exceptions=True,
        )

        # Aggregate summary per model
        # Results are ordered: model_entries[0]×issues, model_entries[1]×issues, ...
        per_model_results: dict[str, list] = {}
        idx = 0
        for ms, mid in model_entries:
            per_model_results[mid] = all_results[idx:idx + len(issue_paths)]
            idx += len(issue_paths)

        for _, mid in model_entries:
            model_results = per_model_results[mid]

            phase_stats: dict[str, dict[str, int]] = {
                pn: {"ran": 0, "success": 0, "failed": 0, "skipped": 0}
                for pn in phase_names
            }
            exceptions: list[Exception] = []

            for entry in model_results:
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
            print(f"PIPELINE COMPLETE [{mid}]")
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
                model=mid,
                total_issues=len(issue_paths),
                phase_stats=phase_stats,
                exceptions=len(exceptions),
            )

    except BaseException as exc:
        for _, mid in model_entries:
            _log_activity(
                "_pipeline", "pipeline", "pipeline_failed",
                model=mid,
                error=str(exc),
            )
        raise


# ---------------------------------------------------------------------------
# Native-skill phase runner (rfe-creator skills)
# ---------------------------------------------------------------------------

_NATIVE_SKILL_PHASES = {
    "rfe-create", "rfe-review", "rfe-split", "rfe-submit",
    "strat-create", "strat-refine", "strat-review", "strat-submit",
    "strat-security-review",
}


async def run_native_skill_phase(args) -> None:
    """Run a phase backed by a native SDK skill.

    Resolves the skill name, working directory, and allowed tools from
    ``pipeline-skills.yaml``, then launches a single agent that invokes
    the skill via the SDK's Skill tool.

    The ``--issue`` flag is passed as the skill argument (e.g. a Jira
    key like ``RHAIRFE-1234``).
    """
    phase = args.command
    skill_name = get_skill_name(phase)
    cwd = str(resolve_cwd(phase))
    allowed_tools = get_allowed_tools(phase)
    enable_skills = should_enable_skills(phase)
    mcp_servers = get_mcp_servers(phase)
    model = args.model if isinstance(args.model, str) else args.model[0]

    print(f"\n{'=' * 60}")
    print(f"PHASE: {phase}  (skill: {skill_name})")
    if mcp_servers:
        print(f"MCP servers: {', '.join(mcp_servers)}")
    print(f"{'=' * 60}\n")

    issue_list = getattr(args, "issue", None) or []
    issue_arg = issue_list[0] if issue_list else ""

    # Build the prompt as a slash-command invocation.  The agent will
    # parse this and call the Skill tool with the correct args.
    skill_args_parts: list[str] = ["--headless"]
    if issue_arg:
        skill_args_parts.append(issue_arg)
    skill_args = " ".join(skill_args_parts)

    prompt = f"/{skill_name} {skill_args}"

    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)

    result = await run_agent(
        name=f"{phase}-{issue_arg or 'batch'}",
        cwd=cwd,
        prompt=prompt,
        log_dir=log_dir,
        model=model,
        allowed_tools=allowed_tools,
        enable_skills=enable_skills,
        mcp_servers=mcp_servers or None,
    )

    if result["success"]:
        print(f"\n{phase} completed successfully.")
    else:
        print(f"\n{phase} failed: {result.get('error', 'unknown error')}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Batch pipeline helpers (strat-all)
# ---------------------------------------------------------------------------


def _read_frontmatter_batch(file_paths: list[str]) -> list[dict]:
    """Call ``frontmatter.py batch-read`` and return parsed JSON array."""
    if not file_paths:
        return []
    result = subprocess.run(
        ["python3", str(_FRONTMATTER_SCRIPT), "batch-read", *file_paths],
        cwd=_FRONTMATTER_CWD,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  [frontmatter] batch-read failed: {result.stderr.strip()}")
        return []
    return json.loads(result.stdout)


_JQL_QUERY_SCRIPT = BASE_DIR / "references" / "rfe-creator" / "scripts" / "jql_query.py"


def _ensure_jira_env() -> bool:
    """Load .env and return True if Jira credentials are available."""
    project_root = BASE_DIR.parent
    load_dotenv(project_root / ".env")
    return bool(os.environ.get("JIRA_SERVER") and os.environ.get("JIRA_TOKEN"))


def _jql_query(jql: str, limit: int | None = None) -> list[str]:
    """Run ``jql_query.py`` and return a list of issue keys.

    The script adds its own compound filters (excludes Done, ignored labels).
    Returns an empty list on failure.
    """
    cmd = ["python3", str(_JQL_QUERY_SCRIPT), jql]
    if limit:
        cmd += ["--limit", str(limit)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [jql_query] failed: {result.stderr.strip()}")
        return []
    keys = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("TOTAL="):
            continue
        if line:
            keys.append(line)
    return keys



def _discover_strats(args) -> list[dict]:
    """Discover strategy keys, preferring Jira over local artifacts.

    If ``--issue`` is given, returns that single key.  Otherwise queries
    Jira for all RHAISTRAT keys.  Falls back to local ``strat-tasks/*.md``
    artifacts only when Jira credentials are not configured.
    """
    issue_filter = getattr(args, "issue", None)
    limit = getattr(args, "limit", None)

    if issue_filter:
        keys = list(issue_filter)
    elif _ensure_jira_env():
        # Prefer Jira as canonical source
        print("  [discover] Querying Jira for RHAISTRAT keys ...")
        keys = _jql_query("project = RHAISTRAT")
        if keys:
            print(f"  [discover] Found {len(keys)} strategies in Jira")
        else:
            print("  [discover] JQL query returned no results.")
            return []
    else:
        # Fallback to local artifacts when Jira is not configured
        strat_files = sorted(_STRAT_TASKS_DIR.glob("*.md"))
        if not strat_files:
            print("  [discover] No local STRAT artifacts and Jira credentials not configured.")
            return []
        keys = [f.stem for f in strat_files]
        print(f"  [discover] Found {len(keys)} local STRAT artifacts (Jira not configured)")

    keys.sort()
    if limit:
        keys = keys[:limit]

    # Enrich with local frontmatter if artifacts exist
    results = []
    for key in keys:
        local_file = _STRAT_TASKS_DIR / f"{key}.md"
        if local_file.exists():
            batch = _read_frontmatter_batch([str(local_file)])
            if batch:
                se = batch[0]
                results.append({
                    "strat_id": se.get("strat_id", key),
                    "strat_file": se.get("_file", str(local_file)),
                    "status": se.get("status", ""),
                    "jira_key": se.get("jira_key", key),
                    "source_rfe": se.get("source_rfe", ""),
                })
                continue
        results.append({
            "strat_id": key,
            "strat_file": "",
            "status": "",
            "jira_key": key,
            "source_rfe": "",
        })

    return results


async def _run_native_skill_for_issue(
    phase: str,
    issue_key: str,
    semaphore: asyncio.Semaphore,
    model: str,
    log_dir: Path,
) -> dict:
    """Run a single native-skill phase for one issue, respecting the semaphore."""
    import time

    skill_name = get_skill_name(phase)
    cwd = str(resolve_cwd(phase))
    allowed_tools = get_allowed_tools(phase)
    enable_skills = should_enable_skills(phase)
    mcp_servers = get_mcp_servers(phase)

    skill_args_parts: list[str] = ["--headless"]
    if issue_key:
        skill_args_parts.append(issue_key)
    skill_args = " ".join(skill_args_parts)

    prompt = f"/{skill_name} {skill_args}"

    _log_activity(issue_key, phase, "started", model=model)
    t0 = time.monotonic()

    try:
        async with semaphore:
            result = await run_agent(
                name=f"{phase}-{issue_key}",
                cwd=cwd,
                prompt=prompt,
                log_dir=log_dir,
                model=model,
                allowed_tools=allowed_tools,
                enable_skills=enable_skills,
                mcp_servers=mcp_servers or None,
            )
    except Exception as exc:
        duration = time.monotonic() - t0
        _log_activity(issue_key, phase, "failed", model=model, error=str(exc))
        print(f"  [{phase}] {issue_key} FAILED ({format_duration(duration)}): {exc}")
        return {
            "phase": phase,
            "key": issue_key,
            "success": False,
            "skipped": False,
            "duration_seconds": round(duration, 1),
            "error": str(exc),
        }

    duration = time.monotonic() - t0
    success = result.get("success", False)
    status = "completed" if success else "failed"
    _log_activity(issue_key, phase, status, model=model, duration=round(duration, 1))
    return {
        "phase": phase,
        "key": issue_key,
        "success": success,
        "skipped": False,
        "duration_seconds": round(duration, 1),
        "error": result.get("error"),
    }


async def _run_strat_pipeline(
    strat_info: dict,
    args,
    semaphore: asyncio.Semaphore,
    log_dir: Path,
) -> dict:
    """Run the strategy pipeline (strat-refine → strat-review → strat-submit → strat-security-review) for one STRAT."""
    strat_id = strat_info["strat_id"]
    model = args.model if isinstance(args.model, str) else args.model[0]
    force = getattr(args, "force", False)

    phases_results: dict[str, dict] = {}
    phases_run = 0
    phases_skipped = 0
    phases_failed = 0

    status = strat_info.get("status", "")

    print(f"\n--- STRAT pipeline: {strat_id} (status={status}) ---")

    # Phase 1: strat-refine (skip if already Refined or Reviewed)
    if not force and status in ("Refined", "Reviewed"):
        print(f"  [strat-refine] {strat_id} SKIPPED (status={status})")
        phases_results["strat-refine"] = {"phase": "strat-refine", "key": strat_id, "skipped": True, "reason": f"status_{status.lower()}"}
        phases_skipped += 1
    else:
        result = await _run_native_skill_for_issue("strat-refine", strat_id, semaphore, model, log_dir)
        phases_results["strat-refine"] = result
        phases_run += 1
        if not result.get("success"):
            phases_failed += 1
            return {"strat_id": strat_id, "phases": phases_results, "phases_run": phases_run, "phases_skipped": phases_skipped, "phases_failed": phases_failed}

    # Phase 2: strat-review
    result = await _run_native_skill_for_issue("strat-review", strat_id, semaphore, model, log_dir)
    phases_results["strat-review"] = result
    phases_run += 1
    if not result.get("success"):
        phases_failed += 1
        return {"strat_id": strat_id, "phases": phases_results, "phases_run": phases_run, "phases_skipped": phases_skipped, "phases_failed": phases_failed}

    # Phase 3: strat-submit
    result = await _run_native_skill_for_issue("strat-submit", strat_id, semaphore, model, log_dir)
    phases_results["strat-submit"] = result
    phases_run += 1
    if not result.get("success"):
        phases_failed += 1
        return {"strat_id": strat_id, "phases": phases_results, "phases_run": phases_run, "phases_skipped": phases_skipped, "phases_failed": phases_failed}

    # Phase 4: strat-security-review
    result = await _run_native_skill_for_issue("strat-security-review", strat_id, semaphore, model, log_dir)
    phases_results["strat-security-review"] = result
    phases_run += 1
    if not result.get("success"):
        phases_failed += 1

    return {"strat_id": strat_id, "phases": phases_results, "phases_run": phases_run, "phases_skipped": phases_skipped, "phases_failed": phases_failed}


async def _gather_with_progress(coros, task_labels, description):
    """Run coroutines concurrently, showing a rich progress bar as each completes."""
    from rich.progress import Progress, BarColumn, MofNCompleteColumn, TimeElapsedColumn, TextColumn

    results = [None] * len(coros)

    with Progress(
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    ) as progress:
        task = progress.add_task(description, total=len(coros))

        async def _run(index, coro):
            result = await coro
            results[index] = result
            # Show which key just finished
            label = task_labels[index]
            success = isinstance(result, dict) and result.get("success")
            status = "OK" if success else "FAILED"
            progress.console.print(f"  {label} {status}")
            progress.advance(task)
            return result

        await asyncio.gather(
            *(_run(i, c) for i, c in enumerate(coros)),
            return_exceptions=True,
        )

    return results


# ---------------------------------------------------------------------------
# Top-level orchestrator for rfe-speedrun / rfe-all
# ---------------------------------------------------------------------------


def _rfe_is_complete(key: str) -> bool:
    """Return True if all expected rfe-speedrun artifacts exist for *key*."""
    base = _RFE_TASKS_DIR.parent  # .../rfe-creator/artifacts
    return all([
        (base / "rfe-tasks" / f"{key}.md").is_file(),
        (base / "rfe-reviews" / f"{key}-review.md").is_file(),
        (base / "rfe-reviews" / f"{key}-feasibility.md").is_file(),
        (base / "rfe-originals" / f"{key}.md").is_file(),
    ])


def _has_unsubmitted_split_children() -> bool:
    """Return True if any RFE-NNN draft children with parent_key exist."""
    base = _RFE_TASKS_DIR.parent  # .../rfe-creator/artifacts
    tasks_dir = base / "rfe-tasks"
    if not tasks_dir.is_dir():
        return False
    for f in tasks_dir.glob("RFE-*.md"):
        if "-comments" in f.stem or "-removed-context" in f.stem:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        # Quick check for parent_key in frontmatter without full parsing
        if "parent_key:" in text:
            return True
    return False


def _discover_rfe_keys(args) -> list[str]:
    """Return a list of RHAIRFE keys to process.

    If ``--issue`` is given, returns that single key.  Otherwise queries
    Jira for all RHAIRFE keys.  Falls back to local ``rfe-tasks/*.md``
    artifacts only when Jira credentials are not configured.
    """
    issue_filter = getattr(args, "issue", None)
    if issue_filter:
        return list(issue_filter)

    # Prefer Jira as canonical source
    if _ensure_jira_env():
        print("  [discover] Querying Jira for RHAIRFE keys ...")
        keys = _jql_query("project = RHAIRFE")
        if keys:
            print(f"  [discover] Found {len(keys)} RFEs in Jira")
        else:
            print("  [discover] JQL query returned no results.")
            return []
    else:
        # Fallback to local artifacts when Jira is not configured
        rfe_files = sorted(
            f for f in _RFE_TASKS_DIR.glob("*.md")
            if not f.name.endswith("-comments.md")
            and not f.name.endswith("-removed-context.md")
        )
        if not rfe_files:
            print("  [discover] No local RFE artifacts and Jira credentials not configured.")
            return []
        keys = [f.stem for f in rfe_files]
        print(f"  [discover] Found {len(keys)} local RFE artifacts (Jira not configured)")

    keys.sort()
    limit = getattr(args, "limit", None)
    if limit:
        keys = keys[:limit]
    return keys


async def run_rfe_speedrun_phases(args) -> None:
    """Discover RFE keys and run ``/rfe.speedrun --headless <key>`` for each."""
    keys = _discover_rfe_keys(args)
    if not keys:
        print("No RFEs found.")
        return

    # Idempotency: skip RFEs whose artifacts are already complete
    force = getattr(args, "force", False)
    if force:
        to_process = keys
        skipped = []
    else:
        to_process = [k for k in keys if not _rfe_is_complete(k)]
        skipped = [k for k in keys if _rfe_is_complete(k)]
        if skipped:
            print(f"Skipping {len(skipped)} already-complete RFEs (use --force to re-run)")
            for k in skipped:
                print(f"  skip {k}")

    model = args.model if isinstance(args.model, str) else args.model[0]
    mid = get_model_id(model)
    max_concurrent = getattr(args, "max_concurrent", 5)
    semaphore = asyncio.Semaphore(max_concurrent)

    log_dir = BASE_DIR / "logs" / "rfe-speedrun"
    log_dir.mkdir(parents=True, exist_ok=True)

    if to_process:
        # Banner
        print(f"\n{'=' * 80}")
        print(f"RFE-SPEEDRUN PIPELINE [{mid}]")
        print(f"{'=' * 80}")
        print(f"RFEs to process: {len(to_process)}  (skipped: {len(skipped)})")
        print(f"Model: {mid}")
        print(f"Max concurrent agents: {max_concurrent}")
        for key in to_process:
            print(f"  {key}")
        print(f"{'=' * 80}\n")

        _log_activity(
            "_pipeline", "rfe-speedrun", "pipeline_started",
            model=mid,
            total_rfes=len(to_process),
            skipped_rfes=len(skipped),
            max_concurrent=max_concurrent,
        )

        coros = [
            _run_native_skill_for_issue(
                "rfe-speedrun", key, semaphore, model, log_dir,
            )
            for key in to_process
        ]
        task_labels = [f"[rfe-speedrun] {key}" for key in to_process]
        all_results = await _gather_with_progress(
            coros, task_labels, "RFE Speedrun",
        )

        # Summary
        success = sum(
            1 for r in all_results
            if isinstance(r, dict) and r.get("success")
        )
        failed = sum(
            1 for r in all_results
            if isinstance(r, dict) and not r.get("success") and not r.get("skipped")
        )
        exceptions = [r for r in all_results if isinstance(r, Exception)]

        print(f"\n{'=' * 80}")
        print(f"RFE-SPEEDRUN PIPELINE COMPLETE [{mid}]")
        print(f"{'=' * 80}")
        print(f"Total: {len(to_process)}  success={success}  failed={failed}  exceptions={len(exceptions)}  skipped={len(skipped)}")
        if exceptions:
            for i, exc in enumerate(exceptions, 1):
                print(f"  {i}. {exc}")
        print(f"{'=' * 80}\n")

        _log_activity(
            "_pipeline", "rfe-speedrun", "pipeline_completed",
            model=mid,
            total_rfes=len(to_process),
            skipped_rfes=len(skipped),
            success=success,
            failed=failed,
            exceptions=len(exceptions),
        )
    else:
        print("All RFEs already processed. Use --force to re-run.")

    # Post-processing: submit any unsubmitted split children
    if _has_unsubmitted_split_children():
        print(f"\n{'=' * 80}")
        print("POST-PROCESSING: Submitting unsubmitted split children")
        print(f"{'=' * 80}\n")
        submit_result = await _run_native_skill_for_issue(
            "rfe-submit", "", semaphore, model, log_dir,
        )
        if submit_result.get("success"):
            print("  Split children submitted successfully.")
        else:
            print(f"  Split child submission failed: {submit_result.get('error')}")


# ---------------------------------------------------------------------------
# Top-level orchestrator for strat-all
# ---------------------------------------------------------------------------


async def run_strat_all_phases(args) -> None:
    """Run the full strategy pipeline (refine → review → submit → security-review) for all discovered strategies."""
    # Dashboard setup
    global _dashboard_url
    _dashboard_url = getattr(args, "dashboard_url", None)
    if _dashboard_url and not _dashboard_reachable(_dashboard_url):
        print(f"  [dashboard] {_dashboard_url} not reachable — disabling push")
        _dashboard_url = None
    if _dashboard_url:
        _start_push_thread()

    # Discover strategies
    strat_jobs = _discover_strats(args)
    if not strat_jobs:
        print("No strategy artifacts found.")
        return

    model = args.model if isinstance(args.model, str) else args.model[0]
    mid = get_model_id(model)
    semaphore = asyncio.Semaphore(args.max_concurrent)

    log_dir = BASE_DIR / "logs" / "strat-all"
    log_dir.mkdir(parents=True, exist_ok=True)

    # Startup banner
    print(f"\n{'=' * 80}")
    print(f"STRAT-ALL PIPELINE [{mid}]")
    print(f"{'=' * 80}")
    print(f"Strategies discovered: {len(strat_jobs)}")
    print(f"Model: {mid}")
    print(f"Max concurrent agents: {args.max_concurrent}")
    print(f"Force: {getattr(args, 'force', False)}")
    for job in strat_jobs:
        print(f"  {job['strat_id']:20s}  status={job['status']:<12s}  source_rfe={job.get('source_rfe', 'n/a')}")
    print(f"{'=' * 80}\n")

    _log_activity(
        "_pipeline", "strat-all", "pipeline_started",
        model=mid,
        total_strats=len(strat_jobs),
        max_concurrent=args.max_concurrent,
        force=getattr(args, "force", False),
    )

    try:
        coros = [
            _run_strat_pipeline(job, args, semaphore, log_dir)
            for job in strat_jobs
        ]
        task_labels = [f"[strat-all] {job['strat_id']}" for job in strat_jobs]
        all_results = await _gather_with_progress(
            coros, task_labels, "Strategy Pipeline",
        )

        # Aggregate stats
        phase_names = ["strat-refine", "strat-review", "strat-submit", "strat-security-review"]
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
            phases = entry.get("phases", {})
            for pn in phase_names:
                r = phases.get(pn)
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
        print(f"STRAT-ALL PIPELINE COMPLETE [{mid}]")
        print(f"{'=' * 80}")
        print(f"Total strategies: {len(strat_jobs)}")
        for pn in phase_names:
            s = phase_stats[pn]
            print(
                f"  {pn:22s}  ran={s['ran']}  success={s['success']}  "
                f"failed={s['failed']}  skipped={s['skipped']}"
            )
        if exceptions:
            print(f"\nExceptions: {len(exceptions)}")
            for i, exc in enumerate(exceptions, 1):
                print(f"  {i}. {exc}")
        print(f"{'=' * 80}\n")

        _log_activity(
            "_pipeline", "strat-all", "pipeline_completed",
            model=mid,
            total_strats=len(strat_jobs),
            phase_stats=phase_stats,
            exceptions=len(exceptions),
        )

    except BaseException as exc:
        _log_activity(
            "_pipeline", "strat-all", "pipeline_failed",
            model=mid,
            error=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

async def run_dashboard_phase(args) -> None:
    """Launch the reporting dashboard web app."""
    from lib.webapp import create_app

    app = create_app()
    app.run(host=args.host, port=args.port, debug=True, threaded=True)


async def main(args) -> None:
    """Main entry point — dispatch to appropriate phase."""
    if args.command == "bug-fetch":
        await run_fetch_phase(args)
    elif args.command == "bug-completeness":
        await run_completeness_phase(args)
    elif args.command == "bug-context-map":
        await run_context_map_phase(args)
    elif args.command == "bug-fix-attempt":
        await run_fix_attempt_phase(args)
    elif args.command == "bug-test-plan":
        await run_test_plan_phase(args)
    elif args.command == "bug-write-test":
        await run_write_test_phase(args)
    elif args.command == "bug-all":
        await run_all_phases(args)
    elif args.command in ("rfe-all", "rfe-speedrun"):
        await run_rfe_speedrun_phases(args)
    elif args.command == "strat-all":
        await run_strat_all_phases(args)
    elif args.command == "dashboard":
        await run_dashboard_phase(args)
    elif args.command in _NATIVE_SKILL_PHASES:
        await run_native_skill_phase(args)
    else:
        print("Error: No command specified. Use --help for usage information.")
        sys.exit(1)
