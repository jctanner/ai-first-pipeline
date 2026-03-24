"""Data loading layer for the reporting dashboard.

Scans the issues/ directory, loads raw issue JSON and phase output JSONs,
and returns structured dicts for the webapp to render.
"""

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from lib.phases import _parse_issue, ISSUES_DIR

PHASE_SUFFIXES = ["completeness", "context-map", "fix-attempt", "test-plan"]


def _load_phase_json(key: str, phase: str) -> dict | None:
    """Load a phase output JSON for an issue, or return None if missing."""
    path = ISSUES_DIR / f"{key}.{phase}.json"
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _latest_phase_mtime(key: str) -> str:
    """Return the most recent mtime across all phase output files, as an ISO string."""
    latest = 0.0
    for suffix in PHASE_SUFFIXES:
        p = ISSUES_DIR / f"{key}.{suffix}.json"
        if p.exists():
            mt = p.stat().st_mtime
            if mt > latest:
                latest = mt
    if latest == 0.0:
        return ""
    return datetime.fromtimestamp(latest, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _enrich_issue(path: Path) -> dict | None:
    """Load a raw issue and attach all phase outputs."""
    issue = _parse_issue(path)
    if issue is None:
        return None
    key = issue["key"]
    issue["completeness"] = _load_phase_json(key, "completeness")
    issue["context_map"] = _load_phase_json(key, "context-map")
    issue["fix_attempt"] = _load_phase_json(key, "fix-attempt")
    issue["test_plan"] = _load_phase_json(key, "test-plan")
    issue["last_processed"] = _latest_phase_mtime(key)
    return issue


def load_all_issues() -> list[dict]:
    """Return a list of enriched issue dicts for every raw issue JSON."""
    if not ISSUES_DIR.exists():
        return []

    def _numeric_key(p: Path) -> int:
        """Extract the numeric suffix from RHOAIENG-NNNNN for sorting."""
        try:
            return int(p.stem.split("-", 1)[1])
        except (IndexError, ValueError):
            return 0

    paths = sorted(
        (p for p in ISSUES_DIR.glob("RHOAIENG-*.json") if "." not in p.stem),
        key=_numeric_key,
    )
    return [issue for p in paths if (issue := _enrich_issue(p)) is not None]


def load_single_issue(key: str) -> dict | None:
    """Return an enriched issue dict for a single issue key, or None."""
    path = ISSUES_DIR / f"{key}.json"
    if not path.exists():
        return None
    return _enrich_issue(path)


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------

ACTIVITY_LOG = ISSUES_DIR.parent / "logs" / "activity.jsonl"


_STALE_THRESHOLD_SECONDS = 2 * 60 * 60  # 2 hours


def load_activity(limit: int = 200) -> tuple[list[dict], list[dict]]:
    """Load activity log and return (in_progress, history).

    ``in_progress`` contains entries with event ``started`` that have no
    matching ``completed`` or ``failed`` entry after them and are less
    than 2 hours old.  Older unfinished entries are treated as orphaned
    (the orchestrator was likely killed) and appear in ``history`` with
    event ``orphaned``.

    ``history`` contains the most recent *limit* terminal entries
    (completed/failed/orphaned), newest first.
    """
    if not ACTIVITY_LOG.exists():
        return [], []

    entries: list[dict] = []
    try:
        with open(ACTIVITY_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return [], []

    now = datetime.now(timezone.utc)

    # Filter out _pipeline sentinel entries from issue-level processing
    entries = [e for e in entries if e.get("issue_key") != "_pipeline"]

    # Build set of (issue_key, phase) pairs that have finished.
    # We track per-timestamp so a re-run of the same issue/phase
    # doesn't mask an earlier orphan.
    finished: set[tuple[str, str]] = set()
    for e in entries:
        if e.get("event") in ("completed", "failed", "skipped"):
            finished.add((e["issue_key"], e["phase"]))

    # Walk backwards to find latest started-but-not-finished
    in_progress: list[dict] = []
    orphaned: list[dict] = []
    seen_started: set[tuple[str, str]] = set()
    for e in reversed(entries):
        pair = (e["issue_key"], e["phase"])
        if e.get("event") == "started" and pair not in finished and pair not in seen_started:
            seen_started.add(pair)
            # Check staleness
            try:
                started_at = datetime.fromisoformat(e["timestamp"])
                age = (now - started_at).total_seconds()
            except (KeyError, ValueError):
                age = _STALE_THRESHOLD_SECONDS + 1  # treat unparseable as stale

            if age < _STALE_THRESHOLD_SECONDS:
                in_progress.append(e)
            else:
                entry = {**e, "event": "orphaned"}
                orphaned.append(entry)

    # History: terminal events + orphaned, newest first
    terminal = [e for e in reversed(entries) if e.get("event") in ("completed", "failed", "skipped")]
    history = sorted(terminal + orphaned, key=lambda e: e.get("timestamp", ""), reverse=True)
    history = history[:limit]

    return in_progress, history


# ---------------------------------------------------------------------------
# File tailing for SSE
# ---------------------------------------------------------------------------

def tail_activity_log(poll_interval: float = 1.0) -> Generator[str, None, None]:
    """Yield new lines from activity.jsonl as they are appended.

    Starts from the current end of file and polls for new data.
    Handles file-not-yet-existing (waits) and file truncation (re-seeks).
    """
    # Wait for the file to exist
    while not ACTIVITY_LOG.exists():
        time.sleep(poll_interval)

    with open(ACTIVITY_LOG) as f:
        # Seek to end
        f.seek(0, 2)
        file_size = f.tell()

        while True:
            line = f.readline()
            if line:
                line = line.strip()
                if line:
                    yield line
            else:
                # Check for truncation (file got smaller)
                try:
                    current_size = ACTIVITY_LOG.stat().st_size
                except OSError:
                    current_size = 0
                if current_size < file_size:
                    # File was truncated — re-seek to beginning
                    f.seek(0)
                file_size = current_size
                time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Pipeline status snapshot
# ---------------------------------------------------------------------------

def load_pipeline_status() -> dict:
    """Build a snapshot of the current pipeline status from activity.jsonl.

    Returns a dict with:
    - pipeline_running: bool
    - pipeline_info: dict or None (config from pipeline_started event)
    - active_issues: list of dicts (issue_key, current_phase, started_at)
    - summary: dict with counts
    """
    result = {
        "pipeline_running": False,
        "pipeline_info": None,
        "active_issues": [],
        "summary": {},
    }

    if not ACTIVITY_LOG.exists():
        return result

    entries: list[dict] = []
    try:
        with open(ACTIVITY_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return result

    # Find the most recent pipeline_started event
    last_pipeline_started_idx = None
    for i, e in enumerate(entries):
        if e.get("issue_key") == "_pipeline" and e.get("event") == "pipeline_started":
            last_pipeline_started_idx = i

    if last_pipeline_started_idx is None:
        return result

    pipeline_start_entry = entries[last_pipeline_started_idx]

    # Check if there's a pipeline_completed or pipeline_failed after it
    pipeline_running = True
    for e in entries[last_pipeline_started_idx + 1:]:
        if e.get("issue_key") == "_pipeline" and e.get("event") in ("pipeline_completed", "pipeline_failed"):
            pipeline_running = False
            break

    result["pipeline_running"] = pipeline_running
    result["pipeline_info"] = {
        "started_at": pipeline_start_entry.get("timestamp", ""),
        "model": pipeline_start_entry.get("model", ""),
        "total_issues": pipeline_start_entry.get("total_issues", 0),
        "max_concurrent": pipeline_start_entry.get("max_concurrent", 0),
    }

    if not pipeline_running:
        return result

    # Find active issues: issue_started after last pipeline_started with no issue_completed
    entries_since = entries[last_pipeline_started_idx + 1:]
    started_issues: dict[str, str] = {}  # key -> timestamp
    completed_issues: set[str] = set()

    for e in entries_since:
        ik = e.get("issue_key", "")
        if ik == "_pipeline":
            continue
        event = e.get("event", "")
        if event == "issue_started":
            started_issues[ik] = e.get("timestamp", "")
        elif event == "issue_completed":
            completed_issues.add(ik)

    active_keys = set(started_issues.keys()) - completed_issues

    # For each active issue, find the most recent phase event
    active_issues = []
    for key in sorted(active_keys):
        current_phase = "starting"
        for e in reversed(entries_since):
            if e.get("issue_key") == key and e.get("phase") != "pipeline":
                current_phase = e.get("phase", "unknown")
                break
        active_issues.append({
            "issue_key": key,
            "current_phase": current_phase,
            "started_at": started_issues[key],
        })

    result["active_issues"] = active_issues
    result["summary"] = {
        "total_started": len(started_issues),
        "completed": len(completed_issues),
        "active": len(active_keys),
    }

    return result


# ---------------------------------------------------------------------------
# Summary statistics for narrative pages
# ---------------------------------------------------------------------------

def compute_summary_stats() -> dict:
    """Compute aggregate statistics for narrative summary pages.

    Scans phase output JSONs directly (no numpy/scipy dependency) and
    returns a dict of counts, distributions, and breakdowns suitable
    for rendering the executive / developer / statistician summaries.
    """
    if not ISSUES_DIR.exists():
        return {"total": 0}

    keys = sorted(
        set(
            p.stem
            for p in ISSUES_DIR.glob("RHOAIENG-*.json")
            if "." not in p.stem
        )
    )

    recs: Counter = Counter()
    triages: Counter = Counter()
    ctx_ratings: Counter = Counter()
    confidences: Counter = Counter()
    efforts: Counter = Counter()
    comp_scores: list[int | float] = []
    ctx_scores: list[int | float] = []
    cov_scores: list[int | float] = []
    depth_scores: list[int | float] = []
    fresh_scores: list[int | float] = []
    n_comp = n_ctx = n_fix = n_tp = 0
    component_fix_counts: dict[str, Counter] = {}  # component -> rec counter

    for key in keys:
        comp = _load_phase_json(key, "completeness")
        ctx = _load_phase_json(key, "context-map")
        fix = _load_phase_json(key, "fix-attempt")
        tp = _load_phase_json(key, "test-plan")

        # --- raw issue for component breakdown ---
        raw_path = ISSUES_DIR / f"{key}.json"
        raw = None
        if raw_path.exists():
            try:
                with open(raw_path) as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        if comp:
            n_comp += 1
            s = comp.get("overall_score")
            if s is not None:
                comp_scores.append(s)
            t = comp.get("triage_recommendation", "")
            if t:
                triages[t] += 1

        if ctx:
            n_ctx += 1
            r = ctx.get("overall_rating", "")
            if r:
                ctx_ratings[r] += 1
            ch = ctx.get("context_helpfulness") or {}
            cs = ch.get("overall_score")
            if cs is not None:
                ctx_scores.append(cs)
            for dim, bucket in [
                ("coverage", cov_scores),
                ("depth", depth_scores),
                ("freshness", fresh_scores),
            ]:
                ds = (ch.get(dim) or {}).get("score")
                if ds is not None:
                    bucket.append(ds)

        rec = ""
        if fix:
            n_fix += 1
            rec = fix.get("recommendation", "")
            if rec:
                recs[rec] += 1
            c = fix.get("confidence", "")
            if c:
                confidences[c] += 1

        if tp:
            n_tp += 1
            e = tp.get("effort_estimate", "")
            if e:
                efforts[e] += 1

        # Per-component fix breakdown
        if raw and rec:
            components = []
            for c in raw.get("fields", {}).get("components", []):
                name = c.get("name", "") if isinstance(c, dict) else str(c)
                if name:
                    components.append(name)
            if not components:
                components = ["(none)"]
            for c in components:
                if c not in component_fix_counts:
                    component_fix_counts[c] = Counter()
                component_fix_counts[c][rec] += 1

    def _percentile(arr: list, pct: float):
        if not arr:
            return 0
        s = sorted(arr)
        idx = int(len(s) * pct / 100)
        return s[min(idx, len(s) - 1)]

    def _dist(arr: list) -> dict:
        if not arr:
            return {"n": 0, "avg": 0, "median": 0, "p25": 0, "p75": 0,
                    "min": 0, "max": 0}
        s = sorted(arr)
        return {
            "n": len(s),
            "avg": round(sum(s) / len(s), 1),
            "median": _percentile(arr, 50),
            "p25": _percentile(arr, 25),
            "p75": _percentile(arr, 75),
            "min": s[0],
            "max": s[-1],
        }

    # Top components by volume
    comp_summary = []
    for comp_name in sorted(
        component_fix_counts, key=lambda c: sum(component_fix_counts[c].values()), reverse=True
    )[:15]:
        counts = component_fix_counts[comp_name]
        total = sum(counts.values())
        fixable = counts.get("ai-fixable", 0)
        comp_summary.append({
            "name": comp_name,
            "total": total,
            "ai_fixable": fixable,
            "fix_rate": round(100 * fixable / total, 1) if total else 0,
            "not_fixable": counts.get("ai-could-not-fix", 0),
        })

    n_fixable = recs.get("ai-fixable", 0)

    return {
        "total": len(keys),
        "with_completeness": n_comp,
        "with_context_map": n_ctx,
        "with_fix_attempt": n_fix,
        "with_test_plan": n_tp,
        "fix_recommendations": dict(recs.most_common()),
        "triage_recommendations": dict(triages.most_common()),
        "context_ratings": dict(ctx_ratings.most_common()),
        "confidences": dict(confidences.most_common()),
        "efforts": dict(efforts.most_common()),
        "comp_dist": _dist(comp_scores),
        "ctx_dist": _dist(ctx_scores),
        "cov_dist": _dist(cov_scores),
        "depth_dist": _dist(depth_scores),
        "fresh_dist": _dist(fresh_scores),
        "component_breakdown": comp_summary,
        "n_fixable": n_fixable,
        "fix_rate_of_analyzed": round(100 * n_fixable / n_fix, 1) if n_fix else 0,
        "fix_rate_of_total": round(100 * n_fixable / len(keys), 1) if keys else 0,
        "coverage_pct": {
            "full": round(100 * ctx_ratings.get("full-context", 0) / len(keys), 1) if keys else 0,
            "partial": round(100 * ctx_ratings.get("partial-context", 0) / len(keys), 1) if keys else 0,
            "none": round(100 * ctx_ratings.get("no-context", 0) / len(keys), 1) if keys else 0,
            "cross": round(100 * ctx_ratings.get("cross-component", 0) / len(keys), 1) if keys else 0,
        },
    }


# ---------------------------------------------------------------------------
# Agent Ready scores (snapshot from 2026-03-17 report)
# ---------------------------------------------------------------------------

AGENT_READY_SCORES: dict[str, int] = {
    "notebooks": 88, "odh-dashboard": 87, "openclaw": 84,
    "pipelines-components": 83, "litellm": 82, "feast": 79,
    "opendatahub-operator": 78, "eval-hub": 78,
    "data-science-pipelines-operator": 77, "workload-variant-autoscaler": 77,
    "modelmesh-serving": 76, "model-registry": 74, "kuberay": 74,
    "data-science-pipelines": 73, "opendatahub-tests": 73,
    "spark-operator": 73, "NeMo-Guardrails": 73, "kube-auth-proxy": 73,
    "kserve": 73, "argo-workflows": 72, "llm-d-inference-scheduler": 72,
    "rhoai-mcp": 72, "training-operator": 71, "mlflow-operator": 70,
    "mod-arch-library": 70, "semantic-router": 69, "trainer": 69,
    "llama-stack-k8s-operator": 68, "rhaii-cluster-validation": 68,
    "trainer-sdk": 68, "kubeflow-sdk": 68, "model-registry-bf4-kf": 68,
    "odh-model-controller": 67, "mlflow": 67,
    "model-metadata-collection": 66, "odh-cli": 65,
    "codeflare-operator": 65, "codeflare-operator-poc": 65,
    "llm-d-kv-cache": 64, "training-notebooks": 64,
    "modelmesh-runtime-adapter": 64, "kube-rbac-proxy": 63,
    "MLServer": 62, "model-registry-operator": 62, "langfuse": 62,
    "openrag": 62, "llama-stack": 62, "base-containers": 61,
    "kube-authkit": 61, "caikit-nlp": 60, "elyra": 60,
    "trustyai-explainability": 60, "models-as-a-service": 59,
    "mcp-server-operator": 59, "rest-proxy": 59,
    "trustyai-service-operator": 58, "kubeflow": 58,
    "caikit-nlp-client": 58, "kueue": 57,
    "elyra-pipeline-editor": 55, "mlflow-go": 55,
    "odh-ide-extensions": 53, "vllm-tgis-adapter": 53,
    "batch-gateway": 53, "fms-guardrails-orchestrator": 52,
    "openvino": 52, "llama-stack-provider-ragas": 50,
    "openvino.genai": 48, "distributed-workloads": 47, "modelmesh": 46,
    "guardrails-detectors": 46, "llama-stack-client-python": 46,
    "openvino_model_server": 44, "llama-stack-distribution": 44,
    "lm-evaluation-harness": 44, "vllm-gaudi": 42,
    "gpt-researcher": 40, "data-processing": 40,
    "llama-stack-provider-trustyai-garak": 39, "perf_analyzer": 38,
    "elyra-examples": 38, "rhaii-on-xks": 37, "openvino_contrib": 37,
    "llama-stack-provider-kfp-trainer": 34, "modelcar-base-image": 33,
    "caikit-tgis-serving": 31, "openvino_tokenizers": 29,
    "fips-compliance-checker-claude-code-plugin": 28, "rag": 27,
    "llama-stack-demos": 26, "client": 24, "ai-helpers": 21,
    "ml-metadata": 19, "ai-gateway-payload-processing": 19,
    "odh-s2i-project-cds": 19, "vllm-orchestrator-gateway": 17,
    "llama-stack-provider-kft": 15, "architecture-context": 14,
    "llama-stack-provider-instructlab-train": 14,
    "odh-s2i-project-cookiecutter": 13, "agents": 12, "odh-gitops": 10,
    "opendatahub.io": 9, "opendatahub-documentation": 9,
    "llm-d-playbooks": 4, "model-runtimes-agent": 4,
    "odh-s2i-project-simple": 4, "odh-build-metadata": 4,
    "dsp-dev-tools": 4,
}


def compute_component_readiness() -> list[dict]:
    """Compute per-component readiness data combining pipeline results and Agent Ready scores.

    For each Jira component, aggregates pipeline phase results and maps
    identified repos to their Agent Ready scores for side-by-side comparison.
    """
    if not ISSUES_DIR.exists():
        return []

    keys = sorted(
        set(p.stem for p in ISSUES_DIR.glob("RHOAIENG-*.json") if "." not in p.stem)
    )

    # Collect per-component data
    comp_data: dict[str, dict] = {}

    for key in keys:
        raw_path = ISSUES_DIR / f"{key}.json"
        raw = None
        if raw_path.exists():
            try:
                with open(raw_path) as f:
                    raw = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        comp = _load_phase_json(key, "completeness")
        ctx = _load_phase_json(key, "context-map")
        fix = _load_phase_json(key, "fix-attempt")
        tp = _load_phase_json(key, "test-plan")

        if not raw:
            continue

        components: list[str] = []
        for c in raw.get("fields", {}).get("components", []):
            name = c.get("name", "") if isinstance(c, dict) else str(c)
            if name:
                components.append(name)
        if not components:
            components = ["(none)"]

        # Repos identified by context-map for this issue
        identified_repos: list[str] = []
        if ctx:
            for ic in ctx.get("identified_components", []):
                if isinstance(ic, dict):
                    rname = ic.get("name", "")
                elif isinstance(ic, str):
                    rname = ic
                else:
                    continue
                if rname:
                    identified_repos.append(rname)

        for cname in components:
            if cname not in comp_data:
                comp_data[cname] = {
                    "total": 0,
                    "with_fix": 0,
                    "fix_recs": Counter(),
                    "confidences": Counter(),
                    "ctx_ratings": Counter(),
                    "ctx_scores": [],
                    "comp_scores": [],
                    "efforts": Counter(),
                    "cov_scores": [],
                    "depth_scores": [],
                    "fresh_scores": [],
                    "repo_counts": Counter(),
                }

            d = comp_data[cname]
            d["total"] += 1

            for rname in identified_repos:
                d["repo_counts"][rname] += 1

            if comp:
                s = comp.get("overall_score")
                if s is not None:
                    d["comp_scores"].append(s)

            if ctx:
                r = ctx.get("overall_rating", "")
                if r:
                    d["ctx_ratings"][r] += 1
                ch = ctx.get("context_helpfulness") or {}
                cs = ch.get("overall_score")
                if cs is not None:
                    d["ctx_scores"].append(cs)
                for dim, bucket_key in [
                    ("coverage", "cov_scores"),
                    ("depth", "depth_scores"),
                    ("freshness", "fresh_scores"),
                ]:
                    ds = (ch.get(dim) or {}).get("score")
                    if ds is not None:
                        d[bucket_key].append(ds)

            if fix:
                d["with_fix"] += 1
                rec = fix.get("recommendation", "")
                if rec:
                    d["fix_recs"][rec] += 1
                conf = fix.get("confidence", "")
                if conf:
                    d["confidences"][conf] += 1

            if tp:
                eff = tp.get("effort_estimate", "")
                if eff:
                    d["efforts"][eff] += 1

    # Build result list
    def _avg(arr: list) -> float:
        return round(sum(arr) / len(arr), 1) if arr else 0

    results = []
    for cname in sorted(comp_data, key=lambda c: comp_data[c]["total"], reverse=True):
        d = comp_data[cname]
        fixable = d["fix_recs"].get("ai-fixable", 0)
        fix_rate = round(100 * fixable / d["with_fix"], 1) if d["with_fix"] else 0

        # Top repos for this component (by frequency, max 5)
        top_repos = []
        for rname, count in d["repo_counts"].most_common(5):
            ar_score = AGENT_READY_SCORES.get(rname)
            # Also try common name variations
            if ar_score is None:
                ar_score = AGENT_READY_SCORES.get(
                    rname.split(" ")[0].split("(")[0].strip()
                )
            top_repos.append({
                "name": rname,
                "issues": count,
                "agent_ready_score": ar_score,
            })

        # Pipeline readiness score: weighted combination of fix rate, context, completeness
        ctx_avg = _avg(d["ctx_scores"])
        comp_avg = _avg(d["comp_scores"])
        # Weight: 50% fix rate, 30% context helpfulness, 20% completeness
        pipeline_score = round(
            0.5 * fix_rate + 0.3 * ctx_avg + 0.2 * comp_avg
        ) if d["with_fix"] else round(0.3 * ctx_avg + 0.2 * comp_avg)

        # Best Agent Ready score among top repos
        ar_scores = [r["agent_ready_score"] for r in top_repos if r["agent_ready_score"] is not None]
        best_ar = max(ar_scores) if ar_scores else None
        avg_ar = round(sum(ar_scores) / len(ar_scores)) if ar_scores else None

        results.append({
            "name": cname,
            "total": d["total"],
            "with_fix": d["with_fix"],
            "fixable": fixable,
            "not_fixable": d["fix_recs"].get("ai-could-not-fix", 0),
            "fix_rate": fix_rate,
            "comp_avg": comp_avg,
            "ctx_avg": ctx_avg,
            "cov_avg": _avg(d["cov_scores"]),
            "depth_avg": _avg(d["depth_scores"]),
            "fresh_avg": _avg(d["fresh_scores"]),
            "ctx_ratings": dict(d["ctx_ratings"].most_common()),
            "confidences": dict(d["confidences"].most_common()),
            "efforts": dict(d["efforts"].most_common()),
            "top_repos": top_repos,
            "pipeline_score": pipeline_score,
            "agent_ready_best": best_ar,
            "agent_ready_avg": avg_ar,
        })

    return results
