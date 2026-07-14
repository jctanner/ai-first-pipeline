#!/usr/bin/env python3
"""Index all forensic evidence sources for a given issue key.

Emits a JSON manifest of pointers (file paths, job names, trace IDs, API URLs)
— does NOT read or dump the actual content. The agent decides what to fetch.

Usage: python gather-evidence.py RHAISTRAT-1
"""

import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

ISSUE_KEY = sys.argv[1] if len(sys.argv) > 1 else None
if not ISSUE_KEY:
    print("Usage: gather-evidence.py <ISSUE_KEY>", file=sys.stderr)
    sys.exit(1)

ISSUE_LOWER = ISSUE_KEY.lower()
ARTIFACTS_DIR = "/app/artifacts" if os.path.isdir("/app/artifacts") else "./artifacts"
OBSERVATORY_URL = os.environ.get("OBSERVATORY_URL", "http://observatory.ai-pipeline.svc.cluster.local:8000")
MLFLOW_URL = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow.ai-pipeline.svc.cluster.local:5000")


def find_k8s_jobs():
    """List K8s jobs matching the issue key with log availability."""
    try:
        result = subprocess.run(
            ["kubectl", "get", "jobs", "-n", "ai-pipeline", "--no-headers",
             "-o", "custom-columns="
             "NAME:.metadata.name,"
             "CREATED:.metadata.creationTimestamp,"
             "STATUS:.status.conditions[0].type"],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    jobs = []
    for line in result.stdout.strip().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name = parts[0]
        if ISSUE_LOWER not in name.lower():
            continue

        has_logs = False
        try:
            log_check = subprocess.run(
                ["kubectl", "logs", f"job/{name}", "-n", "ai-pipeline",
                 "--tail=1"],
                capture_output=True, text=True, timeout=10,
            )
            has_logs = log_check.returncode == 0 and len(log_check.stdout.strip()) > 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        log_file = os.path.join(ARTIFACTS_DIR, "jobs", f"{name}.log")
        has_log_file = os.path.isfile(log_file)

        jobs.append({
            "name": name,
            "created": parts[1],
            "status": parts[2] if len(parts) > 2 else "Unknown",
            "has_logs": has_logs,
            "log_cmd": f"kubectl logs job/{name} -n ai-pipeline --tail=5000",
            "log_file": log_file if has_log_file else None,
        })

    # Also discover log files for jobs already GC'd from K8s
    known_names = {j["name"] for j in jobs}
    jobs_dir = os.path.join(ARTIFACTS_DIR, "jobs")
    if os.path.isdir(jobs_dir):
        for f in sorted(os.listdir(jobs_dir)):
            if not f.endswith(".log") or ISSUE_LOWER not in f.lower():
                continue
            name = f[:-4]  # strip .log
            if name not in known_names:
                jobs.append({
                    "name": name,
                    "created": None,
                    "status": "GC'd",
                    "has_logs": False,
                    "log_cmd": None,
                    "log_file": os.path.join(jobs_dir, f),
                })

    return jobs


def find_mlflow_traces():
    """Find MLflow traces matching the issue key."""
    traces = []

    # Get experiments
    try:
        req = urllib.request.Request(
            f"{MLFLOW_URL}/api/2.0/mlflow/experiments/search",
            data=json.dumps({"max_results": 100}).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=10)
        experiments = json.loads(resp.read()).get("experiments", [])
    except Exception:
        return traces

    exp_map = {e["experiment_id"]: e["name"] for e in experiments}

    # Query each experiment individually (MLflow rejects comma-separated IDs)
    for exp_id in exp_map:
        try:
            url = f"{MLFLOW_URL}/api/2.0/mlflow/traces?experiment_ids={exp_id}&max_results=100"
            resp = urllib.request.urlopen(url, timeout=10)
            data = json.loads(resp.read())
        except Exception:
            continue

        for t in data.get("traces", []):
            meta = {m["key"]: m["value"] for m in t.get("request_metadata", [])}
            tags = {tg["key"]: tg["value"] for tg in t.get("tags", [])}

            combined = meta.get("mlflow.traceInputs", "") + meta.get("mlflow.traceOutputs", "")
            if ISSUE_KEY.upper() not in combined.upper():
                continue

            def _parse(s):
                try:
                    return json.loads(s)
                except Exception:
                    return {}

            cost = _parse(meta.get("mlflow.trace.cost", ""))
            tokens = _parse(meta.get("mlflow.trace.tokenUsage", ""))
            size = _parse(meta.get("mlflow.trace.sizeStats", ""))

            traces.append({
                "trace_id": t["request_id"],
                "experiment_name": exp_map.get(t["experiment_id"], ""),
                "status": t["status"],
                "timestamp_ms": t.get("timestamp_ms"),
                "duration_ms": t.get("execution_time_ms", 0),
                "cost_usd": round(cost.get("total_cost", 0), 4),
                "input_tokens": tokens.get("input_tokens", 0),
                "output_tokens": tokens.get("output_tokens", 0),
                "num_spans": size.get("num_spans", 0),
                "model": tags.get("mlflow.traceModel", ""),
                "ui_url": f"{MLFLOW_URL}/#/experiments/{t['experiment_id']}/traces/{t['request_id']}",
                "api_url": f"{MLFLOW_URL}/api/2.0/mlflow/traces/{t['request_id']}",
            })

    return traces


def find_strace_dirs():
    """Find strace output directories for matching jobs."""
    strace_base = os.path.join(ARTIFACTS_DIR, "strace")
    if not os.path.isdir(strace_base):
        return []

    entries = []
    for d in sorted(os.listdir(strace_base)):
        if ISSUE_LOWER not in d.lower():
            continue
        full = os.path.join(strace_base, d)
        if not os.path.isdir(full):
            continue
        files = os.listdir(full)
        total_bytes = sum(
            os.path.getsize(os.path.join(full, f))
            for f in files if os.path.isfile(os.path.join(full, f))
        )
        entries.append({
            "job_name": d,
            "directory": full,
            "file_count": len(files),
            "total_mb": round(total_bytes / (1024 * 1024), 1),
        })

    return entries


def find_artifacts(claim_ids=None):
    """Find source artifact files related to the issue."""
    found = []
    claim_ids = {str(value) for value in (claim_ids or []) if value is not None}

    def report_matches(path):
        if path.stem in claim_ids or any(part in claim_ids for part in path.parts):
            return True
        try:
            text = path.read_text(errors="ignore")
            if ISSUE_KEY.upper() in text.upper():
                return True
            if path.suffix == ".json":
                payload = json.loads(text)
                occurrence_id = payload.get("claim_occurrence_id")
                return str(occurrence_id) in claim_ids
            return False
        except OSError:
            return False
        except (TypeError, json.JSONDecodeError):
            return False

    # Pipeline outputs across RFE, strategy, epic, investigation, and codegen
    # directories. Exclude outputs produced by the claim-analysis stages.
    artifacts_root = Path(ARTIFACTS_DIR)
    derived_dirs = {"claims", "verification", "explanations"}
    if artifacts_root.is_dir():
        for path in sorted(artifacts_root.rglob("*.md")):
            relative = path.relative_to(artifacts_root)
            if any(part.startswith(".") or part in derived_dirs for part in relative.parts):
                continue
            if ISSUE_KEY.upper() not in relative.as_posix().upper():
                continue
            found.append({
                "type": "pipeline_output",
                "path": str(path),
            })

    # Claims JSON
    claims_dir = os.path.join(ARTIFACTS_DIR, "claims")
    if os.path.isdir(claims_dir):
        for root, _, files in os.walk(claims_dir):
            for f in sorted(files):
                if ISSUE_KEY.upper() in f.upper() and f.endswith(".claims.json"):
                    found.append({
                        "type": "claims_json",
                        "path": os.path.join(root, f),
                    })

    # Verification logs and immutable structured runs. Structured runs live one
    # directory below the occurrence ID, so a top-level os.listdir() silently
    # misses the evidence that explanation must bind to.
    verif_dir = Path(ARTIFACTS_DIR) / "verification"
    if verif_dir.is_dir():
        for path in sorted(verif_dir.rglob("*.md")):
            if report_matches(path):
                found.append({
                    "type": "verification_log",
                    "path": str(path),
                })
        for path in sorted(verif_dir.rglob("*.verification.json")):
            if report_matches(path):
                found.append({
                    "type": "verification_run",
                    "path": str(path),
                })

    # Existing explanations include both the legacy markdown projection and
    # immutable structured runs nested under verification-run IDs.
    explain_dir = Path(ARTIFACTS_DIR) / "explanations"
    if explain_dir.is_dir():
        for pattern in ("*.md", "*.explanation.json"):
            for path in sorted(explain_dir.rglob(pattern)):
                if report_matches(path):
                    found.append({
                        "type": "existing_explanation",
                        "path": str(path),
                    })

    return found


def find_otel_logs():
    """Find OTel log events from Observatory matching the issue key."""
    try:
        url = f"{OBSERVATORY_URL}/api/otel/logs?search={ISSUE_KEY}&limit=200"
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
    except Exception:
        return {"reachable": False, "total": 0, "logs": []}

    logs = []
    for log in data.get("logs", []):
        raw_attrs = log.get("attributes", "{}")
        try:
            attrs = json.loads(raw_attrs) if isinstance(raw_attrs, str) else raw_attrs
        except (TypeError, json.JSONDecodeError):
            attrs = {}
        logs.append({
            "id": log.get("id"),
            "event_name": attrs.get("event.name"),
            "timestamp": log.get("observed_at") or log.get("timestamp"),
            "trace_id": log.get("trace_id"),
            "severity": log.get("severity_text"),
            "tool_name": attrs.get("tool_name"),
            "model": attrs.get("model"),
            "cost_usd": attrs.get("cost_usd"),
            "url": f"{OBSERVATORY_URL}/api/otel/logs/{log.get('id')}",
        })

    return {
        "reachable": True,
        "total": data.get("total", len(logs)),
        "api_url": url,
        "logs": logs,
    }


def find_api_bodies():
    """Find raw API request/response body files matching the issue key."""
    apibodies_base = os.path.join(ARTIFACTS_DIR, "apibodies")
    if not os.path.isdir(apibodies_base):
        return []

    entries = []
    for d in sorted(os.listdir(apibodies_base)):
        if ISSUE_LOWER not in d.lower():
            continue
        full = os.path.join(apibodies_base, d)
        if not os.path.isdir(full):
            continue
        files = os.listdir(full)
        request_files = [f for f in files if f.endswith(".request.json")]
        response_files = [f for f in files if f.endswith(".response.json")]
        total_bytes = sum(
            os.path.getsize(os.path.join(full, f))
            for f in files if os.path.isfile(os.path.join(full, f))
        )
        entries.append({
            "job_name": d,
            "directory": full,
            "request_files": len(request_files),
            "response_files": len(response_files),
            "total_mb": round(total_bytes / (1024 * 1024), 1),
        })

    return entries


def find_observatory_claims():
    """Get v2 occurrences and immutable verification histories."""
    try:
        url = (
            f"{OBSERVATORY_URL}/api/v2/claims/occurrences"
            f"?jira_key={ISSUE_KEY}&pending_only=false&limit=1000"
        )
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read())
    except Exception:
        try:
            url = f"{OBSERVATORY_URL}/api/hallucinations/claims?jira_key={ISSUE_KEY}&limit=1000"
            resp = urllib.request.urlopen(url, timeout=10)
            data = json.loads(resp.read())
        except Exception:
            return {"reachable": False, "total": 0, "claims": []}
        return {
            "reachable": True,
            "legacy_fallback": True,
            "total": data.get("total", 0),
            "api_url": url,
            "claims": data.get("claims", []),
            "overflow": len(data.get("claims", [])) == 1000,
        }

    occurrences = data.get("occurrences", [])
    if len(occurrences) == 1000:
        return {
            "reachable": True,
            "legacy_fallback": False,
            "total": data.get("total", len(occurrences)),
            "api_url": url,
            "claims": [],
            "overflow": True,
            "error": (
                "Observatory returned exactly 1000 occurrences; the result may "
                "be truncated, so explanation selection must stop."
            ),
        }

    if not occurrences:
        try:
            legacy_url = (
                f"{OBSERVATORY_URL}/api/hallucinations/claims"
                f"?jira_key={ISSUE_KEY}&limit=1000"
            )
            legacy = json.loads(urllib.request.urlopen(legacy_url, timeout=10).read())
            if legacy.get("total", 0):
                return {
                    "reachable": True,
                    "legacy_fallback": True,
                    "total": legacy["total"],
                    "api_url": legacy_url,
                    "claims": legacy.get("claims", []),
                    "overflow": len(legacy.get("claims", [])) == 1000,
                }
        except Exception:
            pass

    claims = []
    for c in data.get("occurrences", []):
        history = {}
        try:
            history_url = (
                f"{OBSERVATORY_URL}/api/v2/claims/occurrences/{c.get('id')}/history"
            )
            history = json.loads(urllib.request.urlopen(history_url, timeout=10).read())
        except Exception:
            pass
        runs = history.get("verification_runs", [])
        latest = max(runs, key=lambda run: run.get("id", -1)) if runs else {}
        claims.append({
            "id": c.get("id"),
            "claim_text": c.get("claim_text", ""),
            "claim_type": c.get("claim_type"),
            "verdict": latest.get("verdict"),
            "confidence": latest.get("confidence"),
            "verification_run_id": latest.get("id"),
            "verification_history": runs,
            "source_file": c.get("source_file"),
            "source_locator": c.get("source_locator"),
            "url": f"{OBSERVATORY_URL}/api/v2/claims/occurrences/{c.get('id')}/history",
        })

    return {
        "reachable": True,
        "legacy_fallback": False,
        "total": data.get("total", len(claims)),
        "api_url": url,
        "claims": claims,
        "overflow": False,
    }


if __name__ == "__main__":
    print(f"Indexing evidence for {ISSUE_KEY}...", file=sys.stderr)

    jobs = find_k8s_jobs()
    print(f"  K8s jobs: {len(jobs)} ({sum(1 for j in jobs if j['has_logs'])} with logs)", file=sys.stderr)

    traces = find_mlflow_traces()
    print(f"  MLflow traces: {len(traces)}", file=sys.stderr)

    strace = find_strace_dirs()
    print(f"  Strace dirs: {len(strace)}", file=sys.stderr)

    observatory = find_observatory_claims()
    print(f"  Observatory claims: {observatory['total']} (reachable={observatory['reachable']})", file=sys.stderr)

    artifacts = find_artifacts(c.get("id") for c in observatory["claims"])
    by_type = {}
    for a in artifacts:
        by_type.setdefault(a["type"], []).append(a)
    for t, items in sorted(by_type.items()):
        print(f"  {t}: {len(items)}", file=sys.stderr)

    otel_logs = find_otel_logs()
    print(f"  OTel logs: {otel_logs['total']} (reachable={otel_logs['reachable']})", file=sys.stderr)

    api_bodies = find_api_bodies()
    print(f"  API body dirs: {len(api_bodies)} ({sum(e['request_files'] for e in api_bodies)} requests)", file=sys.stderr)

    manifest = {
        "issue_key": ISSUE_KEY,
        "evidence_sources": {
            "k8s_jobs": jobs,
            "mlflow_traces": traces,
            "strace": strace,
            "otel_logs": otel_logs,
            "api_bodies": api_bodies,
            "artifacts": artifacts,
            "observatory": observatory,
        },
        "summary": {
            "k8s_jobs": len(jobs),
            "k8s_jobs_with_logs": sum(1 for j in jobs if j["has_logs"]),
            "mlflow_traces": len(traces),
            "strace_dirs": len(strace),
            "otel_logs": otel_logs["total"],
            "api_body_dirs": len(api_bodies),
            "pipeline_outputs": len(by_type.get("pipeline_output", [])),
            "claims_json_files": len(by_type.get("claims_json", [])),
            "verification_logs": len(by_type.get("verification_log", [])),
            "existing_explanations": len(by_type.get("existing_explanation", [])),
            "observatory_claims": observatory["total"],
        },
    }

    json.dump(manifest, sys.stdout, indent=2)
    print(file=sys.stdout)
