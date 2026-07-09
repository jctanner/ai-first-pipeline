"""Flask web application for the bug bash reporting dashboard."""

import json
import os
import queue
import shutil
import stat
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, render_template, jsonify, abort, Response, request
from jinja2 import FileSystemLoader

from src.dashboard.report_data import (
    load_all_issues, load_single_issue,
    load_pipeline_status,
)
from src.cli.paths import discover_models, model_workspace
from src.dashboard.rfe_data import load_rfe_issues, load_single_rfe, load_strat_issues, load_single_strat, load_epic_issues

# K8s orchestration (imported lazily to avoid requiring K8s client when not needed)
try:
    from src.dashboard.k8s_orchestrator import PipelineOrchestrator
    _orchestrator = None
    def get_orchestrator():
        global _orchestrator
        if _orchestrator is None:
            _orchestrator = PipelineOrchestrator()
        return _orchestrator
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    def get_orchestrator():
        return None

# ---------------------------------------------------------------------------
# In-memory pipeline state (single-process Flask dev server)
# ---------------------------------------------------------------------------

_pipeline_state = {
    "running": False,
    "manifest": None,       # full manifest from controller
    "jobs": {},             # (issue_key, model) -> {status, phase, started_at, ...}
    "events": [],           # recent events for SSE replay (capped)
    "sse_subscribers": [],  # list of queue.Queue for SSE push
}
_state_lock = threading.Lock()
_MAX_EVENTS = 5000


def _broadcast_sse(data: dict) -> None:
    """Push a JSON event to all SSE subscriber queues."""
    msg = json.dumps(data)
    with _state_lock:
        dead = []
        for i, q in enumerate(_pipeline_state["sse_subscribers"]):
            try:
                q.put_nowait(msg)
            except queue.Full:
                dead.append(i)
        # Remove dead/full queues in reverse order
        for i in reversed(dead):
            _pipeline_state["sse_subscribers"].pop(i)


def _handle_manifest(payload: dict) -> None:
    """Process a manifest message — resets all prior state."""
    with _state_lock:
        _pipeline_state["running"] = True
        _pipeline_state["manifest"] = payload
        _pipeline_state["events"] = []
        _pipeline_state["jobs"] = {}
        for job in payload.get("jobs", []):
            jk = (job["key"], job["model"])
            _pipeline_state["jobs"][jk] = {
                "key": job["key"],
                "model": job["model"],
                "status": "pending",
                "phase": None,
                "started_at": None,
                "completed_at": None,
                "error": None,
            }
    _broadcast_sse(payload)


def _handle_event(payload: dict) -> None:
    """Process an individual event — updates job state in place."""
    issue_key = payload.get("issue_key", "")
    model = payload.get("model", "")
    event = payload.get("event", "")
    phase = payload.get("phase", "")
    timestamp = payload.get("timestamp", "")

    with _state_lock:
        # Append to recent events (capped)
        _pipeline_state["events"].append(payload)
        if len(_pipeline_state["events"]) > _MAX_EVENTS:
            _pipeline_state["events"] = _pipeline_state["events"][-_MAX_EVENTS:]

        jk = (issue_key, model)
        job = _pipeline_state["jobs"].get(jk)

        if event == "pipeline_completed" or event == "pipeline_failed":
            _pipeline_state["running"] = False
        elif event == "issue_started":
            if job:
                job["status"] = "running"
                job["started_at"] = timestamp
        elif event == "started":
            if job:
                job["status"] = "running"
                job["phase"] = phase
        elif event == "completed":
            if job:
                job["phase"] = phase
                # Only mark completed if this is the issue_completed event
                # Individual phase completions just update the phase
        elif event == "failed":
            if job:
                job["phase"] = phase
                job["error"] = payload.get("error")
        elif event == "issue_completed":
            if job:
                job["status"] = "completed"
                job["completed_at"] = timestamp
        elif event == "skipped":
            if job:
                job["phase"] = phase

    _broadcast_sse(payload)


def _get_queue_snapshot() -> dict:
    """Return a snapshot of the full queue state from memory."""
    with _state_lock:
        manifest = _pipeline_state["manifest"]
        jobs_list = sorted(
            _pipeline_state["jobs"].values(),
            key=lambda j: (j["key"], j["model"]),
        )
        counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        for j in jobs_list:
            s = j["status"]
            if s in counts:
                counts[s] += 1

        # Per-model breakdown
        model_counts: dict[str, dict[str, int]] = {}
        for j in jobs_list:
            m = j["model"]
            if m not in model_counts:
                model_counts[m] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
            s = j["status"]
            if s in model_counts[m]:
                model_counts[m][s] += 1

        return {
            "running": _pipeline_state["running"],
            "manifest": manifest,
            "total_jobs": len(jobs_list),
            "counts": counts,
            "model_counts": model_counts,
            "jobs": jobs_list,
        }

# ---------------------------------------------------------------------------
# Flask app factory
# ---------------------------------------------------------------------------

def create_app() -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    app.jinja_loader = FileSystemLoader(
        os.path.join(os.path.dirname(__file__), "templates")
    )

    @app.route("/healthz")
    def healthz():
        return "ok", 200

    @app.route("/")
    def dashboard():
        issues = load_all_issues()

        # Flatten issues into one row per model
        rows = []
        for issue in issues:
            models = issue.get("models", {})
            if models:
                for mid, mdata in models.items():
                    row = {**issue}
                    row["model"] = mid
                    row["completeness"] = mdata.get("completeness")
                    row["context_map"] = mdata.get("context_map")
                    row["fix_attempt"] = mdata.get("fix_attempt")
                    row["test_plan"] = mdata.get("test_plan")
                    row["write_test"] = mdata.get("write_test")
                    rows.append(row)
            else:
                row = {**issue, "model": ""}
                rows.append(row)

        # Extract test-context helpfulness rating from last validation iteration
        _rank = {"none": 0, "low": 1, "medium": 2, "high": 3}
        for row in rows:
            fa = row.get("fix_attempt")
            if fa and fa.get("validation"):
                last_iter = fa["validation"][-1]
                ratings = [
                    vr["test_context_helpfulness"]["rating"]
                    for vr in last_iter.get("results", [])
                    if vr.get("test_context_helpfulness", {}).get("rating")
                ]
                # Use the worst (lowest) rating across repos
                row["test_context_rating"] = (
                    min(ratings, key=lambda r: _rank.get(r, -1)) if ratings else ""
                )
            else:
                row["test_context_rating"] = ""

        # Summarise per-component arch-doc and source-checkout availability
        for row in rows:
            cm = row.get("context_map")
            entries = cm.get("context_entries", []) if cm else []
            if entries:
                has_arch = [e.get("architecture_doc", "not found") != "not found" for e in entries]
                has_src = [e.get("source_checkout", "not found") != "not found" for e in entries]
                row["arch_docs"] = "all" if all(has_arch) else ("partial" if any(has_arch) else "none")
                row["src_code"] = "all" if all(has_src) else ("partial" if any(has_src) else "none")
            else:
                row["arch_docs"] = ""
                row["src_code"] = ""

        model_names = sorted({r["model"] for r in rows if r["model"]})

        # Collect unique filter values
        statuses = sorted({r["status"] for r in rows})
        triages = sorted({
            r["completeness"]["triage_recommendation"]
            for r in rows if r.get("completeness") and "triage_recommendation" in r["completeness"]
        })
        issue_types = sorted({
            r["completeness"]["issue_type_assessment"]["classified_type"]
            for r in rows
            if r.get("completeness") and r["completeness"].get("issue_type_assessment")
        })
        context_ratings = sorted({
            r["context_map"]["overall_rating"]
            for r in rows if r.get("context_map") and "overall_rating" in r["context_map"]
        })
        components = sorted({
            c for r in rows for c in r.get("components", []) if c
        })
        fix_recommendations = sorted({
            r["fix_attempt"]["recommendation"]
            for r in rows if r.get("fix_attempt") and r["fix_attempt"].get("recommendation")
        })
        test_context_ratings = sorted({
            r["test_context_rating"]
            for r in rows if r["test_context_rating"]
        })
        arch_docs_values = sorted({r["arch_docs"] for r in rows if r["arch_docs"]})
        src_code_values = sorted({r["src_code"] for r in rows if r["src_code"]})
        write_test_decisions = sorted({
            r["write_test"]["decision"]
            for r in rows if r.get("write_test") and r["write_test"].get("decision")
        })

        # --- RFE data ---
        rfe_issues = load_rfe_issues()
        rfe_statuses = sorted({r.get("status", "") for r in rfe_issues if r.get("status")})
        rfe_priorities = sorted({r.get("priority", "") for r in rfe_issues if r.get("priority")})
        rfe_recommendations = sorted({
            r["review"]["recommendation"]
            for r in rfe_issues if r.get("review") and r["review"].get("recommendation")
        })

        # --- Strategy data ---
        strat_issues = load_strat_issues()
        strat_statuses = sorted({s.get("status", "") for s in strat_issues if s.get("status")})
        strat_priorities = sorted({s.get("priority", "") for s in strat_issues if s.get("priority")})
        strat_recommendations = sorted({
            s["review"]["recommendation"]
            for s in strat_issues if s.get("review") and s["review"].get("recommendation")
        })

        # --- Epic data ---
        epic_issues = load_epic_issues()
        epic_types = sorted({e.get("type", "") for e in epic_issues if e.get("type")})
        epic_strat_keys = sorted({e.get("strat_key", "") for e in epic_issues if e.get("strat_key")})

        # --- Build unified all-issues list ---
        all_issues = []

        # Bugs: deduplicate by issue key (one row per issue, not per model)
        seen_bug_keys = set()
        for row in rows:
            k = row["key"]
            if k in seen_bug_keys:
                continue
            seen_bug_keys.add(k)
            comp = row.get("completeness")
            score = comp.get("overall_score", -1) if comp else -1
            rec = ""
            fa = row.get("fix_attempt")
            if fa:
                rec = fa.get("recommendation", "")
            all_issues.append({
                "type": "bug",
                "key": k,
                "title": row.get("summary", ""),
                "status": row.get("status", ""),
                "priority": row.get("priority", ""),
                "quality_score": score,
                "quality_display": str(score) if score >= 0 else "\u2014",
                "quality_class": (
                    "score-red" if score < 40 else ("score-yellow" if score < 80 else "score-green")
                ) if score >= 0 else "",
                "recommendation": rec,
                "security_verdict": "",
                "attention": bool(comp and comp.get("triage_recommendation")),
                "detail_url": f"/issue/{k}",
            })

        # RFEs
        for rfe in rfe_issues:
            rev = rfe.get("review")
            score = rev.get("score", -1) if rev else -1
            all_issues.append({
                "type": "rfe",
                "key": rfe["key"],
                "title": rfe.get("title", ""),
                "status": rfe.get("status", ""),
                "priority": rfe.get("priority", ""),
                "quality_score": score,
                "quality_display": f"{score}/10" if score >= 0 else "\u2014",
                "quality_class": (
                    "score-red" if score < 5 else ("score-yellow" if score < 8 else "score-green")
                ) if score >= 0 else "",
                "recommendation": rev.get("recommendation", "") if rev else "",
                "security_verdict": "",
                "attention": bool(rev and rev.get("needs_attention")),
                "detail_url": f"/rfe/{rfe['key']}",
            })

        # Strategies
        for st in strat_issues:
            rev = st.get("review")
            sec = st.get("security")
            verdict = sec.get("verdict", "") if sec else ""
            # Attention if any reviewer says reject OR security verdict is CONCERNS or FAIL
            attention = False
            if rev and rev.get("reviewers"):
                attention = any(v == "reject" for v in rev["reviewers"].values())
            if verdict.upper() in ("CONCERNS", "FAIL", "CONCERNS_CRITICAL"):
                attention = True
            all_issues.append({
                "type": "strategy",
                "key": st["key"],
                "title": st.get("title", ""),
                "status": st.get("status", ""),
                "priority": st.get("priority", ""),
                "quality_score": -1,
                "quality_display": rev.get("recommendation", "\u2014") if rev else "\u2014",
                "quality_class": "",
                "recommendation": rev.get("recommendation", "") if rev else "",
                "security_verdict": verdict.upper() if verdict else "",
                "attention": attention,
                "detail_url": f"/strat/{st['key']}",
            })

        all_statuses = sorted({i["status"] for i in all_issues if i["status"]})
        all_priorities = sorted({i["priority"] for i in all_issues if i["priority"]})

        return render_template(
            "dashboard.html",
            rows=rows,
            model_names=model_names,
            statuses=statuses,
            triages=triages,
            issue_types=issue_types,
            context_ratings=context_ratings,
            components=components,
            fix_recommendations=fix_recommendations,
            test_context_ratings=test_context_ratings,
            arch_docs_values=arch_docs_values,
            src_code_values=src_code_values,
            write_test_decisions=write_test_decisions,
            rfe_issues=rfe_issues,
            rfe_statuses=rfe_statuses,
            rfe_priorities=rfe_priorities,
            rfe_recommendations=rfe_recommendations,
            strat_issues=strat_issues,
            strat_statuses=strat_statuses,
            strat_priorities=strat_priorities,
            strat_recommendations=strat_recommendations,
            epic_issues=epic_issues,
            epic_types=epic_types,
            epic_strat_keys=epic_strat_keys,
            all_issues=all_issues,
            all_statuses=all_statuses,
            all_priorities=all_priorities,
        )

    @app.route("/issue/<key>")
    def issue_detail(key):
        issue = load_single_issue(key)
        if issue is None:
            abort(404)

        # Model selection: use ?model= query param or first available
        available_models = discover_models(key)
        selected_model = request.args.get("model")
        if selected_model and selected_model in available_models:
            # Flatten selected model's data to top-level keys
            mdata = issue.get("models", {}).get(selected_model, {})
            if mdata:
                issue["completeness"] = mdata.get("completeness", issue.get("completeness"))
                issue["context_map"] = mdata.get("context_map", issue.get("context_map"))
                issue["fix_attempt"] = mdata.get("fix_attempt", issue.get("fix_attempt"))
                issue["test_plan"] = mdata.get("test_plan", issue.get("test_plan"))
                issue["write_test"] = mdata.get("write_test", issue.get("write_test"))
        elif available_models:
            selected_model = available_models[0]

        return render_template(
            "detail.html", issue=issue,
            available_models=available_models,
            selected_model=selected_model or "",
        )

    @app.route("/rfe/<key>")
    def rfe_detail(key):
        rfe = load_single_rfe(key)
        if rfe is None:
            abort(404)
        return render_template("rfe_detail.html", rfe=rfe)

    @app.route("/strat/<key>")
    def strat_detail(key):
        strat = load_single_strat(key)
        if strat is None:
            abort(404)
        return render_template("strat_detail.html", strat=strat)

    @app.route("/settings")
    def settings():
        config = {
            'JIRA_SERVER': os.getenv('JIRA_SERVER'),
            'JIRA_USER': os.getenv('JIRA_USER'),
            'JIRA_TOKEN': os.getenv('JIRA_TOKEN'),
            'GITHUB_EMULATOR_URL': os.getenv('GITHUB_EMULATOR_URL'),
            'CLAUDE_CODE_USE_VERTEX': os.getenv('CLAUDE_CODE_USE_VERTEX'),
            'CLOUD_ML_REGION': os.getenv('CLOUD_ML_REGION'),
            'ANTHROPIC_VERTEX_PROJECT_ID': os.getenv('ANTHROPIC_VERTEX_PROJECT_ID'),
            'ATLASSIAN_MCP_URL': os.getenv('ATLASSIAN_MCP_URL'),
            'GOOGLE_APPLICATION_CREDENTIALS': os.getenv('GOOGLE_APPLICATION_CREDENTIALS'),
        }

        cluster = {
            'namespace': 'ai-pipeline',
            'platform': 'K3s',
            'storage_class': 'local-path',
        }

        services = [
            {
                'name': 'Jira Emulator',
                'url': os.getenv('JIRA_SERVER', 'https://jira-emulator.ai-pipeline.svc.cluster.local'),
                'status': 'available' if os.getenv('JIRA_SERVER') else 'unknown',
            },
            {
                'name': 'GitHub Emulator',
                'url': os.getenv('GITHUB_EMULATOR_URL', 'https://github-emulator.ai-pipeline.svc.cluster.local'),
                'status': 'available' if os.getenv('GITHUB_EMULATOR_URL') else 'unknown',
            },
            {
                'name': 'Atlassian MCP',
                'url': os.getenv('ATLASSIAN_MCP_URL', 'http://jira-emulator.ai-pipeline.svc.cluster.local:8081/sse'),
                'status': 'available' if os.getenv('ATLASSIAN_MCP_URL') else 'unknown',
            },
            {
                'name': 'Vertex AI',
                'url': f"https://{os.getenv('CLOUD_ML_REGION', 'us-east5')}-aiplatform.googleapis.com",
                'status': 'available' if os.getenv('CLAUDE_CODE_USE_VERTEX') == '1' else 'unknown',
            },
        ]

        return render_template("settings.html", config=config, cluster=cluster, services=services)

    @app.route("/admin")
    def admin():
        return render_template("admin.html")

    @app.route("/jobs")
    def jobs():
        from src.cli.skill_config import list_skills
        return render_template(
            "jobs.html", k8s_available=K8S_AVAILABLE, skills=list_skills()
        )

    @app.route("/evals")
    def evals():
        return render_template("evals.html", k8s_available=K8S_AVAILABLE)

    @app.route("/files")
    def files():
        return render_template("files.html")

    @app.route("/api/issues")
    def api_issues():
        issues = load_all_issues()
        return jsonify(issues)

    @app.route("/api/rfes")
    def api_rfes():
        return jsonify(load_rfe_issues())

    @app.route("/api/strategies")
    def api_strategies():
        return jsonify(load_strat_issues())

    @app.route("/api/mlflow/runs")
    def api_mlflow_runs():
        from src.dashboard.mlflow_client import fetch_all_runs, runs_by_issue
        try:
            issue_key = request.args.get("issue")
            runs = fetch_all_runs()
            if issue_key:
                runs = [r for r in runs if r.get("issue_key") == issue_key]
            grouped = request.args.get("grouped")
            if grouped:
                return jsonify(runs_by_issue(runs))
            return jsonify(runs)
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @app.route("/api/mlflow/traces")
    def api_mlflow_traces():
        from src.dashboard.mlflow_client import (
            fetch_all_traces, traces_by_issue, traces_for_issue,
        )
        try:
            issue_key = request.args.get("issue")
            if issue_key:
                return jsonify(traces_for_issue(issue_key))
            grouped = request.args.get("grouped")
            if grouped:
                return jsonify(traces_by_issue())
            return jsonify(fetch_all_traces())
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @app.route("/api/mlflow/clear", methods=["POST"])
    def api_mlflow_clear():
        """Delete all MLflow experiments, runs, and traces."""
        from src.dashboard.mlflow_client import clear_all_data

        results = clear_all_data()
        if results["errors"] and not (results["runs_deleted"] or results["traces_deleted"] or results["experiments_deleted"]):
            return jsonify(results), 502
        return jsonify(results)

    @app.route("/api/pipeline/status")
    def api_pipeline_status():
        return jsonify(load_pipeline_status())

    @app.route("/api/pipeline/queue")
    def api_pipeline_queue():
        return jsonify(_get_queue_snapshot())

    @app.route("/api/events/push", methods=["POST"])
    def api_events_push():
        payload = request.get_json(force=True)
        if not payload:
            return jsonify({"error": "empty payload"}), 400
        msg_type = payload.get("type", "event")
        if msg_type == "manifest":
            _handle_manifest(payload)
        else:
            _handle_event(payload)
        return jsonify({"ok": True})

    @app.route("/api/events")
    def api_events():
        def generate():
            q = queue.Queue(maxsize=1000)
            with _state_lock:
                _pipeline_state["sse_subscribers"].append(q)
                # Replay recent events so the client catches up
                for evt in _pipeline_state["events"]:
                    q.put_nowait(json.dumps(evt))
            try:
                while True:
                    try:
                        msg = q.get(timeout=30)
                        yield f"data: {msg}\n\n"
                    except queue.Empty:
                        # Send keepalive comment to prevent proxy/browser timeout
                        yield ": keepalive\n\n"
            except GeneratorExit:
                with _state_lock:
                    try:
                        _pipeline_state["sse_subscribers"].remove(q)
                    except ValueError:
                        pass

        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.route("/api/workspace/reset", methods=["POST"])
    def api_reset_workspace():
        """Delete model workspace directories for selected issue*model pairs."""
        data = request.get_json()
        pairs = data.get("pairs", [])
        results = []
        for pair in pairs:
            key, mid = pair["key"], pair["model"]
            ws = model_workspace(key, mid)
            if ws.exists():
                # Ensure all dirs are writable so rmtree can descend and delete.
                # Skip broken symlinks and other non-existent entries.
                for dirpath, dirnames, filenames in os.walk(ws):
                    try:
                        os.chmod(dirpath, stat.S_IRWXU)
                    except (FileNotFoundError, OSError):
                        pass
                    for fn in filenames:
                        try:
                            os.chmod(os.path.join(dirpath, fn), stat.S_IWUSR | stat.S_IRUSR)
                        except (FileNotFoundError, OSError):
                            pass
                shutil.rmtree(ws)
                results.append({"key": key, "model": mid, "status": "deleted"})
            else:
                results.append({"key": key, "model": mid, "status": "not_found"})
        return jsonify({"results": results})

    @app.route("/api/volumes/clear", methods=["POST"])
    def api_clear_volumes():
        """Clear contents of shared data volumes."""
        data = request.get_json()
        requested = data.get("volumes", [])
        volume_map = {
            "issues": "/app/issues",
            "workspace": "/app/workspace",
            "logs": "/app/logs",
            "artifacts": "/app/artifacts",
            "job-logs": "/app/artifacts/jobs",
            "strace": "/app/artifacts/strace",
            "apibodies": "/app/artifacts/apibodies",
            "context": "/app/.context",
        }
        results = {}
        errors = []
        for vol in requested:
            path = volume_map.get(vol)
            if not path:
                errors.append(f"Unknown volume: {vol}")
                continue
            p = Path(path)
            if not p.exists():
                results[vol] = {"status": "empty", "deleted": 0}
                continue
            count = 0
            try:
                for child in list(p.iterdir()):
                    if child.is_dir():
                        for dirpath, _dirnames, filenames in os.walk(child):
                            try:
                                os.chmod(dirpath, stat.S_IRWXU)
                            except (FileNotFoundError, OSError):
                                pass
                            for fn in filenames:
                                try:
                                    os.chmod(
                                        os.path.join(dirpath, fn),
                                        stat.S_IWUSR | stat.S_IRUSR,
                                    )
                                except (FileNotFoundError, OSError):
                                    pass
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    count += 1
                results[vol] = {"status": "cleared", "deleted": count}
            except Exception as e:
                errors.append(f"{vol}: {str(e)}")
                results[vol] = {"status": "error", "deleted": count}
        return jsonify({"results": results, "errors": errors})

    # =========================================================================
    # K8s Job Management APIs
    # =========================================================================

    @app.route("/api/jobs/submit", methods=["POST"])
    def api_submit_job():
        """Submit a new pipeline job to K8s.

        POST body (registered skill):
        {
          "command": "bug-completeness",
          "args": {
            "issue": "RHOAIENG-37036",
            "model": "opus",
            "runner": "cli",
            "force": true
          }
        }

        POST body (ad-hoc FQN):
        {
          "fqn": "github.local/org/repo@branch:skill-name",
          "args": { ... }
        }

        Returns:
        {
          "job_name": "bug-completeness-rhoaieng-37036-opus-1234",
          "status": "pending"
        }
        """
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            from src.cli.skill_config import parse_fqn

            data = request.get_json()
            fqn = data.get("fqn", "").strip()
            phase = data.get("command", "").strip()
            args = data.get("args", {})

            issue_key = args.get("issue", "")
            model = args.get("model", "opus")
            runner = args.get("runner", "cli")
            harness = args.get("harness", "claude-code")

            if args.get("skill_load_mode") not in (None, "auto", "plugin", "skill"):
                return jsonify({"error": f"Invalid skill_load_mode: {args['skill_load_mode']}. Must be auto, plugin, or skill"}), 400

            if fqn:
                parsed = parse_fqn(fqn)
                if not parsed:
                    return jsonify({"error": f"Invalid FQN format: {fqn}. Expected: host/owner/repo@ref:skill-name"}), 400
                phase = parsed["skill"]
            elif phase:
                parsed = parse_fqn(phase)
                if parsed:
                    fqn = phase
                    phase = parsed["skill"]
            else:
                return jsonify({"error": "Missing required field: command or fqn"}), 400

            orchestrator = get_orchestrator()
            job = orchestrator.submit_phase_job(
                phase, issue_key, model, runner, args,
                fqn=fqn or None,
                harness=harness,
            )

            return jsonify({
                "job_name": job.metadata.name,
                "status": "pending"
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs")
    def api_list_jobs():
        """List all pipeline jobs with optional filters.

        Query params:
        - phase: Filter by phase name
        - status: Filter by status (pending|running|completed|failed)

        Returns:
        [{
          "name": "bug-completeness-rhoaieng-37036-opus-1234",
          "phase": "bug-completeness",
          "issue": "rhoaieng-37036",
          "model": "opus",
          "status": "running",
          "created": "2026-04-16T12:34:56",
          "duration": 45.2
        }, ...]
        """
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            phase = request.args.get("phase")
            status = request.args.get("status")

            orchestrator = get_orchestrator()
            jobs = orchestrator.list_jobs(phase=phase, status=status)

            results = []
            for job in jobs:
                job_status = orchestrator._get_job_status(job)

                # Calculate duration
                duration = None
                if job.status.start_time:
                    end_time = job.status.completion_time or datetime.now(job.status.start_time.tzinfo)
                    duration = (end_time - job.status.start_time).total_seconds()

                results.append({
                    "name": job.metadata.name,
                    "phase": job.metadata.labels.get("phase", ""),
                    "issue": job.metadata.labels.get("issue", ""),
                    "model": (job.metadata.annotations or {}).get("model") or job.metadata.labels.get("model", ""),
                    "runner": job.metadata.labels.get("runner", "cli"),
                    "harness": job.metadata.labels.get("harness", "claude-code"),
                    "status": job_status,
                    "created": job.metadata.creation_timestamp.isoformat() if job.metadata.creation_timestamp else None,
                    "duration": duration,
                    "force": job.metadata.labels.get("force", "false") == "true",
                    "strace": job.metadata.labels.get("strace", "false") == "true",
                    "mlflow": job.metadata.labels.get("mlflow", "true") == "true",
                    "otel": job.metadata.labels.get("otel", "true") == "true",
                    "extra_kwargs": (job.metadata.annotations or {}).get("extra_kwargs", ""),
                    "fqn": (job.metadata.annotations or {}).get("fqn", ""),
                })

            return jsonify(results)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs/<job_name>")
    def api_get_job_status(job_name):
        """Get detailed status of a specific job."""
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            orchestrator = get_orchestrator()
            status = orchestrator.get_job_status(job_name)
            return jsonify(status)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs/<job_name>/logs")
    def api_get_job_logs(job_name):
        """Get logs from a job's pod."""
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            orchestrator = get_orchestrator()
            logs = orchestrator.get_job_logs(job_name)

            if logs is None:
                return "No logs available yet", 404

            return Response(logs, mimetype="text/plain")
        except Exception as e:
            return Response(f"Error: {str(e)}", mimetype="text/plain"), 500

    @app.route("/api/jobs/<job_name>/stop", methods=["POST"])
    def api_stop_job(job_name):
        """Stop a running job by deleting it and its pods."""
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            orchestrator = get_orchestrator()
            stopped = orchestrator.stop_job(job_name)

            if stopped:
                return jsonify({"status": "stopped"})
            else:
                return jsonify({"error": "Job not found or not running"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs/<job_name>", methods=["DELETE"])
    def api_delete_job(job_name):
        """Delete a job."""
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            orchestrator = get_orchestrator()
            deleted = orchestrator.delete_job(job_name)

            if deleted:
                return jsonify({"status": "deleted"})
            else:
                return jsonify({"error": "Job not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/jobs/all", methods=["DELETE"])
    def api_delete_all_jobs():
        """Delete all pipeline jobs and their pods."""
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            orchestrator = get_orchestrator()
            jobs = orchestrator.list_jobs()
            deleted = 0
            errors = []
            for job in jobs:
                try:
                    orchestrator.delete_job(job.metadata.name)
                    deleted += 1
                except Exception as e:
                    errors.append(f"{job.metadata.name}: {e}")

            return jsonify({"deleted": deleted, "errors": errors})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    # =========================================================================
    # Eval Job APIs
    # =========================================================================

    @app.route("/api/evals/submit", methods=["POST"])
    def api_submit_eval():
        """Submit a new eval-harness job to K8s.

        POST body:
        {
          "dataset_fqn": "github.local/opendatahub-io/skills@main:claim-fix-validation",
          "model": "opus",
          "context_ref": "main",
          "context_mode": "files",
          "baseline": "",
          "strace": true,
          "mlflow": true,
          "otel": true
        }
        """
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            from src.cli.skill_config import parse_fqn

            data = request.get_json()
            dataset_fqn = data.get("dataset_fqn", "").strip()

            if not dataset_fqn:
                return jsonify({"error": "Missing required field: dataset_fqn"}), 400

            parsed = parse_fqn(dataset_fqn)
            if not parsed:
                return jsonify({"error": f"Invalid FQN format: {dataset_fqn}. Expected: host/owner/repo@ref:eval-config"}), 400

            model = data.get("model", "opus")
            context_repo = data.get("context_repo", "https://github.com/opendatahub-io/architecture-context")
            context_ref = data.get("context_ref", "main")
            context_mode = data.get("context_mode", "files")
            baseline = data.get("baseline", "")
            eval_harness = data.get("eval_harness", "https://github.com/opendatahub-io/agent-eval-harness")

            args = {}
            if data.get("strace"):
                args["strace"] = True
            if data.get("mlflow") is False:
                args["mlflow"] = False
            if data.get("otel") is False:
                args["otel"] = False

            orchestrator = get_orchestrator()
            job = orchestrator.submit_eval_job(
                dataset_fqn, model, context_repo, context_ref, context_mode, baseline, eval_harness, args
            )

            return jsonify({
                "job_name": job.metadata.name,
                "status": "pending",
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/evals")
    def api_list_evals():
        """List all eval jobs."""
        if not K8S_AVAILABLE:
            return jsonify({"error": "K8s orchestration not available"}), 503

        try:
            orchestrator = get_orchestrator()
            jobs = orchestrator.list_eval_jobs()

            results = []
            for job in jobs:
                job_status = orchestrator._get_job_status(job)
                annotations = job.metadata.annotations or {}
                labels = job.metadata.labels or {}

                duration = None
                if job.status.start_time:
                    end_time = job.status.completion_time or datetime.now(job.status.start_time.tzinfo)
                    duration = (end_time - job.status.start_time).total_seconds()

                results.append({
                    "name": job.metadata.name,
                    "dataset_fqn": annotations.get("dataset_fqn", ""),
                    "model": annotations.get("model") or labels.get("model", ""),
                    "context_repo": annotations.get("context_repo", ""),
                    "context_ref": annotations.get("context_ref", "main"),
                    "context_mode": annotations.get("context_mode", "files"),
                    "baseline": annotations.get("baseline", ""),
                    "eval_harness": annotations.get("eval_harness", ""),
                    "status": job_status,
                    "created": job.metadata.creation_timestamp.isoformat() if job.metadata.creation_timestamp else None,
                    "duration": duration,
                    "strace": labels.get("strace", "false") == "true",
                    "mlflow": labels.get("mlflow", "true") == "true",
                    "otel": labels.get("otel", "true") == "true",
                })

            return jsonify(results)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/observatory/clear", methods=["POST"])
    def api_clear_observatory():
        """Delete all hallucination data from Observatory."""
        import urllib.request
        import urllib.error

        observatory_url = os.getenv(
            "OBSERVATORY_URL",
            "http://observatory.ai-pipeline.svc.cluster.local:8000",
        )
        try:
            req = urllib.request.Request(
                f"{observatory_url}/api/hallucinations/all",
                method="DELETE",
            )
            resp = urllib.request.urlopen(req, timeout=30)
            data = json.loads(resp.read())
            return jsonify(data)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            return jsonify({"error": f"Observatory returned {e.code}: {body}"}), 502
        except Exception as e:
            return jsonify({"error": str(e)}), 502

    @app.route("/api/files/list")
    def api_list_files():
        """List files in a directory."""
        path = request.args.get("path", "")

        # Security: only allow browsing within /app directories
        allowed_bases = ["/app/artifacts", "/app/issues", "/app/workspace", "/app/logs", "/app/.context", "/app/tmp"]

        # Resolve path to absolute and check if it's within allowed bases
        try:
            resolved_path = Path(path).resolve()
        except Exception as e:
            return jsonify({"error": f"Invalid path: {e}"}), 400

        # Check if path is within allowed bases
        allowed = any(
            str(resolved_path).startswith(base) or str(resolved_path) == base
            for base in allowed_bases
        )

        if not allowed:
            return jsonify({"error": "Access denied - path outside allowed directories"}), 403

        # Check if directory exists
        if not resolved_path.exists():
            return jsonify({"error": "Directory not found"}), 404

        if not resolved_path.is_dir():
            return jsonify({"error": "Not a directory"}), 400

        # List directory contents
        try:
            entries = []
            for entry in sorted(resolved_path.iterdir(), key=lambda e: (not e.is_dir(), e.name)):
                try:
                    stat_info = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                        "size": stat_info.st_size if entry.is_file() else 0,
                        "modified": datetime.fromtimestamp(stat_info.st_mtime).isoformat(),
                    })
                except (OSError, PermissionError):
                    # Skip entries we can't stat (broken symlinks, permission issues)
                    continue

            return jsonify({
                "path": str(resolved_path),
                "entries": entries
            })
        except PermissionError:
            return jsonify({"error": "Permission denied"}), 403
        except Exception as e:
            return jsonify({"error": f"Error listing directory: {e}"}), 500

    @app.route("/api/files/read")
    def api_read_file():
        """Read file contents."""
        path = request.args.get("path", "")

        # Security: only allow reading within /app directories
        allowed_bases = ["/app/artifacts", "/app/issues", "/app/workspace", "/app/logs", "/app/.context", "/app/tmp"]

        # Resolve path to absolute and check if it's within allowed bases
        try:
            resolved_path = Path(path).resolve()
        except Exception as e:
            return jsonify({"error": f"Invalid path: {e}"}), 400

        # Check if path is within allowed bases
        allowed = any(
            str(resolved_path).startswith(base)
            for base in allowed_bases
        )

        if not allowed:
            return jsonify({"error": "Access denied - path outside allowed directories"}), 403

        # Check if file exists
        if not resolved_path.exists():
            return jsonify({"error": "File not found"}), 404

        if not resolved_path.is_file():
            return jsonify({"error": "Not a file"}), 400

        # Get file info
        try:
            stat_info = resolved_path.stat()
            file_size = stat_info.st_size
            modified = datetime.fromtimestamp(stat_info.st_mtime).isoformat()
        except Exception as e:
            return jsonify({"error": f"Error reading file info: {e}"}), 500

        # Check if binary file (simple heuristic: check for null bytes in first 8KB)
        try:
            with open(resolved_path, 'rb') as f:
                sample = f.read(8192)
                is_binary = b'\x00' in sample

            if is_binary:
                return jsonify({
                    "binary": True,
                    "size": file_size,
                    "modified": modified
                })

            # Read text file (limit to 1MB to prevent memory issues)
            max_size = 1024 * 1024  # 1MB
            if file_size > max_size:
                return jsonify({
                    "error": f"File too large to display ({file_size} bytes, max {max_size} bytes)",
                    "size": file_size,
                    "modified": modified
                }), 400

            with open(resolved_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()

            return jsonify({
                "content": content,
                "size": file_size,
                "modified": modified,
                "binary": False
            })
        except PermissionError:
            return jsonify({"error": "Permission denied"}), 403
        except Exception as e:
            return jsonify({"error": f"Error reading file: {e}"}), 500

    @app.route("/api/files/raw")
    def api_raw_file():
        """Serve a file with its native MIME type."""
        from flask import send_file as flask_send_file

        path = request.args.get("path", "")

        allowed_bases = ["/app/artifacts", "/app/issues", "/app/workspace", "/app/logs", "/app/.context", "/app/tmp"]

        try:
            resolved_path = Path(path).resolve()
        except Exception as e:
            return jsonify({"error": f"Invalid path: {e}"}), 400

        allowed = any(
            str(resolved_path).startswith(base)
            for base in allowed_bases
        )

        if not allowed:
            return jsonify({"error": "Access denied - path outside allowed directories"}), 403

        if not resolved_path.exists() or not resolved_path.is_file():
            return jsonify({"error": "File not found"}), 404

        return flask_send_file(resolved_path)

    return app
