"""Query MLflow traces and runs, correlating them with Jira issue keys."""

import json
import os
import re
from datetime import datetime, timezone

import requests

MLFLOW_TRACKING_URI = os.getenv(
    "MLFLOW_TRACKING_URI", "http://mlflow:5000"
)

_ISSUE_KEY_RE = re.compile(r"(?:RHOAIENG|RHAIRFE|RHAISTRAT)-\d+")

# run_name format: {phase}-{ISSUE_KEY}-{runner}
_RUN_NAME_RE = re.compile(
    r"^(?P<phase>.+)-(?P<issue_key>[A-Z]+-\d+)-(?P<runner>[a-z]+)$"
)


def _parse_run_name(run_name: str) -> dict | None:
    m = _RUN_NAME_RE.match(run_name)
    if not m:
        return None
    return {
        "phase": m.group("phase"),
        "issue_key": m.group("issue_key"),
        "runner": m.group("runner"),
    }


def _ts_to_iso(ms: int | None) -> str | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _extract_issue_keys(text: str) -> list[str]:
    return list(dict.fromkeys(_ISSUE_KEY_RE.findall(text)))


def _parse_json_field(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


# ---- Traces API (Claude Code's built-in MLflow tracing) ----

def fetch_all_traces(experiment_ids: list[str] | None = None) -> list[dict]:
    """Fetch all MLflow traces with extracted issue keys and cost data."""
    if experiment_ids is None:
        experiment_ids = ["0"]

    base_url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/traces"
    all_traces = []
    page_token = None

    while True:
        params = {
            "experiment_ids": ",".join(experiment_ids),
            "max_results": "100",
        }
        if page_token:
            params["page_token"] = page_token

        resp = requests.get(base_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        for t in data.get("traces", []):
            meta = {
                m["key"]: m["value"]
                for m in t.get("request_metadata", [])
            }
            tags = {
                tg["key"]: tg["value"]
                for tg in t.get("tags", [])
            }

            inputs_raw = meta.get("mlflow.traceInputs", "")
            outputs_raw = meta.get("mlflow.traceOutputs", "")
            issue_keys = _extract_issue_keys(inputs_raw + outputs_raw)

            cost_data = _parse_json_field(meta.get("mlflow.trace.cost", ""))
            token_data = _parse_json_field(
                meta.get("mlflow.trace.tokenUsage", "")
            )
            size_data = _parse_json_field(
                meta.get("mlflow.trace.sizeStats", "")
            )

            entry = {
                "trace_id": t["request_id"],
                "status": t["status"],
                "start_time": _ts_to_iso(t.get("timestamp_ms")),
                "duration_s": round(
                    t.get("execution_time_ms", 0) / 1000, 1
                ),
                "issue_keys": issue_keys,
                "session_id": meta.get("mlflow.trace.session", ""),
                "cost_usd": round(
                    cost_data.get("total_cost", 0), 4
                ) if cost_data else 0,
                "input_tokens": (
                    token_data.get("input_tokens", 0) if token_data else 0
                ),
                "output_tokens": (
                    token_data.get("output_tokens", 0) if token_data else 0
                ),
                "num_spans": (
                    size_data.get("num_spans", 0) if size_data else 0
                ),
                "user": meta.get("mlflow.user", ""),
            }
            all_traces.append(entry)

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return all_traces


def traces_by_issue(
    traces: list[dict] | None = None,
) -> dict[str, list[dict]]:
    """Group traces by Jira issue key."""
    if traces is None:
        traces = fetch_all_traces()
    grouped: dict[str, list[dict]] = {}
    for trace in traces:
        for key in trace.get("issue_keys", []):
            grouped.setdefault(key, []).append(trace)
    for key in grouped:
        grouped[key].sort(key=lambda t: t["start_time"] or "")
    return grouped


def traces_for_issue(
    issue_key: str, traces: list[dict] | None = None
) -> list[dict]:
    """Return all MLflow traces for a specific Jira issue key."""
    if traces is None:
        traces = fetch_all_traces()
    return sorted(
        [t for t in traces if issue_key in t.get("issue_keys", [])],
        key=lambda t: t["start_time"] or "",
    )


# ---- Runs API (ambient-runner explicit runs) ----

def fetch_all_runs(experiment_ids: list[str] | None = None) -> list[dict]:
    """Fetch all MLflow runs, returning parsed + enriched dicts."""
    if experiment_ids is None:
        experiment_ids = ["0"]

    url = f"{MLFLOW_TRACKING_URI}/api/2.0/mlflow/runs/search"
    all_runs = []
    page_token = None

    while True:
        body: dict = {
            "experiment_ids": experiment_ids,
            "max_results": 100,
        }
        if page_token:
            body["page_token"] = page_token

        resp = requests.post(url, json=body, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        for run in data.get("runs", []):
            info = run["info"]
            metrics = {
                m["key"]: m["value"]
                for m in run.get("data", {}).get("metrics", [])
            }
            tags = {
                t["key"]: t["value"]
                for t in run.get("data", {}).get("tags", [])
            }

            run_name = info.get("run_name", "")
            parsed = _parse_run_name(run_name)

            entry = {
                "run_id": info["run_id"],
                "run_name": run_name,
                "status": info["status"],
                "start_time": _ts_to_iso(info.get("start_time")),
                "end_time": _ts_to_iso(info.get("end_time")),
                "issue_key": parsed["issue_key"] if parsed else None,
                "phase": parsed["phase"] if parsed else None,
                "runner": parsed["runner"] if parsed else None,
                "duration_s": round(
                    metrics.get("duration_ms", 0) / 1000, 1
                ),
                "cost_usd": round(metrics.get("cost_usd", 0), 4),
                "num_turns": int(metrics.get("num_turns", 0)),
                "tool_use_count": int(metrics.get("tool_use_count", 0)),
                "is_error": bool(metrics.get("is_error", 0)),
                "user": tags.get("mlflow.user", ""),
            }
            all_runs.append(entry)

        page_token = data.get("next_page_token")
        if not page_token:
            break

    return all_runs


def runs_by_issue(runs: list[dict] | None = None) -> dict[str, list[dict]]:
    """Group runs by Jira issue key."""
    if runs is None:
        runs = fetch_all_runs()
    grouped: dict[str, list[dict]] = {}
    for run in runs:
        key = run.get("issue_key")
        if key:
            grouped.setdefault(key, []).append(run)
    for key in grouped:
        grouped[key].sort(key=lambda r: r["start_time"] or "")
    return grouped
