#!/usr/bin/env python3
"""CLI for querying the markovd API.

Usage:
    python scripts/markovd-query.py runs
    python scripts/markovd-query.py runs --status failed --limit 5
    python scripts/markovd-query.py status markov-run-dfac1c58
    python scripts/markovd-query.py steps markov-run-56d12448
    python scripts/markovd-query.py logs markov-run-56d12448
    python scripts/markovd-query.py workflows
    python scripts/markovd-query.py cancel markov-run-56d12448

Environment variables (or use --url / --user / --password flags):
    MARKOVD_URL        Base URL (default: https://markovd.local)
    MARKOVD_USER       Username
    MARKOVD_PASSWORD   Password
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.rstrip("Z").split("+")[0]
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _duration_secs(start: str | None, end: str | None) -> float | None:
    s, e = _parse_dt(start), _parse_dt(end)
    if not s:
        return None
    if not e:
        e = datetime.now(timezone.utc)
    return (e - s).total_seconds()


def _fmt_duration(secs: float | int | None) -> str:
    if secs is None:
        return "-"
    secs = int(secs)
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {(secs % 3600) // 60}m"


def _duration(start: str | None, end: str | None) -> str:
    return _fmt_duration(_duration_secs(start, end))


def _trunc(s: str, n: int = 60) -> str:
    s = s.replace("\n", " ").strip()
    return s[:n] + "..." if len(s) > n else s


def _status_marker(status: str) -> str:
    markers = {
        "completed": "+",
        "failed": "X",
        "running": ">",
        "cancelled": "-",
        "pending": ".",
        "skipped": "~",
    }
    return markers.get(status, "?")


def _table(rows: list[list[str]], headers: list[str]) -> str:
    if not rows:
        return "(no results)"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    lines = [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
    for row in rows:
        padded = row + [""] * (len(headers) - len(row))
        lines.append(fmt.format(*padded))
    return "\n".join(lines)


def _bar(done: int, total: int, width: int = 30) -> str:
    if total == 0:
        return "[" + " " * width + "]"
    filled = int(width * done / total)
    return "[" + "#" * filled + "." * (width - filled) + f"] {done}/{total}"


class MarkovClient:
    def __init__(self, url: str, user: str, password: str):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.session = requests.Session()
        self.session.verify = False

    def _auth(self):
        if not self.user or not self.password:
            print("Error: MARKOVD_USER and MARKOVD_PASSWORD required (set in .env or use --user/--password)", file=sys.stderr)
            sys.exit(1)
        resp = self.session.post(
            f"{self.url}/api/v1/auth/login",
            json={"username": self.user, "password": self.password},
        )
        resp.raise_for_status()
        token = resp.json()["token"]
        self.session.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        self._auth()
        resp = self.session.get(f"{self.url}/api/v1{path}", params=params)
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> dict:
        self._auth()
        resp = self.session.delete(f"{self.url}/api/v1{path}")
        resp.raise_for_status()
        try:
            return resp.json()
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            return {"status": "ok"}

    def get_runs(self, limit: int | None = None, status: str | None = None,
                 workflow: str | None = None) -> list[dict]:
        params = {}
        if limit:
            params["limit"] = limit
        if status:
            params["status"] = status
        runs = self._get("/runs", params)
        if workflow:
            runs = [r for r in runs if workflow in r.get("workflow_name", "")]
        return runs

    def get_run(self, run_id: str) -> dict:
        if run_id.isdigit():
            runs = self._get("/runs")
            for r in runs:
                if str(r.get("id")) == run_id:
                    run_id = r["run_id"]
                    break
        return self._get(f"/runs/{run_id}")

    def cancel_run(self, run_id: str) -> dict:
        return self._delete(f"/runs/{run_id}")

    def get_workflows(self) -> list[dict]:
        return self._get("/workflows")


def cmd_runs(client: MarkovClient, args: argparse.Namespace):
    runs = client.get_runs(limit=args.limit, status=args.status, workflow=args.workflow)
    if args.json:
        print(json.dumps(runs, indent=2))
        return
    rows = []
    for r in runs:
        wf = r.get("workflow_name", "").replace("markov.workflows-", "")
        rows.append([
            str(r.get("id", "")),
            r.get("run_id", ""),
            _trunc(wf, 30),
            r.get("status", ""),
            (r.get("started_at") or "")[:19],
            _duration(r.get("started_at"), r.get("completed_at")),
        ])
    print(_table(rows, ["ID", "RUN_ID", "WORKFLOW", "STATUS", "STARTED", "DURATION"]))


def cmd_status(client: MarkovClient, args: argparse.Namespace):
    run_id = getattr(args, "run_id", None)
    if not run_id:
        runs = client.get_runs()
        for r in runs:
            if r.get("status") == "running":
                run_id = r["run_id"]
                break
        if not run_id:
            print("No running workflows found")
            return

    run = client.get_run(run_id)
    if args.json:
        print(json.dumps(run, indent=2))
        return

    steps = run.get("steps", [])
    jobs = [s for s in steps if s.get("step_type") == "agent_job"]
    done = [s for s in jobs if s.get("status") == "completed"]
    running = [s for s in jobs if s.get("status") == "running"]
    failed = [s for s in jobs if s.get("status") == "failed"]

    # Classify by phase (answer vs judge) and mode (flat vs query)
    def _classify(s):
        fork = s.get("fork_id") or ""
        phase = "answer" if "answer_all" in fork else "judge" if "judge_all" in fork else "other"
        mode = "flat_files" if "run_modes-0" in fork else "arch_query" if "run_modes-1" in fork else "unknown"
        return phase, mode

    buckets: dict[tuple[str, str], dict[str, int]] = {}
    for s in jobs:
        key = _classify(s)
        counts = buckets.setdefault(key, {"completed": 0, "running": 0, "failed": 0})
        st = s.get("status", "")
        if st in counts:
            counts[st] += 1

    # Compute durations from completed jobs
    durations = []
    for s in done:
        d = _duration_secs(s.get("started_at"), s.get("completed_at"))
        if d is not None:
            durations.append(d)

    avg = sum(durations) / len(durations) if durations else 0.0

    wf = run.get("workflow_name", "").replace("markov.workflows-", "")
    elapsed = _duration(run.get("started_at"), run.get("completed_at"))
    print(f"Run:      {run.get('run_id')}  ({wf})")
    print(f"Status:   {run.get('status')}  |  Elapsed: {elapsed}")
    print()
    print(f"Agent jobs: {len(done)} done, {len(running)} running, {len(failed)} failed")
    print(_bar(len(done), len(done) + len(running) + len(failed)))
    print()

    if buckets:
        order = [("answer", "flat_files"), ("answer", "arch_query"),
                 ("judge", "flat_files"), ("judge", "arch_query")]
        rows = []
        for key in order:
            if key not in buckets:
                continue
            c = buckets[key]
            total = c["completed"] + c["running"] + c["failed"]
            rows.append([
                f"{key[0]}/{key[1]}",
                str(c["completed"]),
                str(c["running"]),
                str(c["failed"]),
                str(total),
            ])
        if rows:
            print(_table(rows, ["PHASE", "DONE", "RUNNING", "FAILED", "TOTAL"]))
            print()

    if durations:
        print(f"Avg job: {avg:.0f}s  (min {min(durations):.0f}s, max {max(durations):.0f}s)")

    # ETA: estimate remaining work
    # Heuristic: count questions from the corpus path or from step fan-out
    # Use the total expected jobs based on what we've seen so far
    seen_phases = set()
    for key in buckets:
        seen_phases.add(key)

    # Count unique question IDs per mode to estimate total questions
    question_ids: dict[str, set[str]] = {"flat_files": set(), "arch_query": set()}
    for s in jobs:
        fork = s.get("fork_id") or ""
        for mode_key, mode_name in [("run_modes-0", "flat_files"), ("run_modes-1", "arch_query")]:
            if mode_key in fork:
                # Extract question ID pattern like "t1-003" from fork_id
                parts = fork.split("-answer_all-")
                if len(parts) < 2:
                    parts = fork.split("-judge_all-")
                if len(parts) >= 2:
                    question_ids[mode_name].add(parts[1])

    n_questions = max(len(question_ids["flat_files"]), len(question_ids["arch_query"]), 1)
    # Total expected: n_questions * 2 modes * 2 phases (answer + judge)
    total_expected = n_questions * 4
    remaining = total_expected - len(done)

    if avg > 0 and remaining > 0:
        concurrency = max(len(running), 5)
        batches = remaining / concurrency
        eta_secs = batches * avg
        print(f"\nEstimated remaining: ~{remaining} jobs")
        print(f"ETA: ~{_fmt_duration(eta_secs)}")
    elif remaining <= 0 and run.get("status") == "running":
        print("\nAll agent jobs done — aggregation/finalization in progress")
    elif run.get("status") != "running":
        print(f"\nRun finished: {run.get('status')}")


def cmd_steps(client: MarkovClient, args: argparse.Namespace):
    run = client.get_run(args.run_id)
    if args.json:
        print(json.dumps(run.get("steps", []), indent=2))
        return
    steps = run.get("steps", [])
    if not steps:
        print("No steps found")
        return
    print(f"Run: {run.get('run_id')}  Status: {run.get('status')}")
    print(f"Duration: {_duration(run.get('started_at'), run.get('completed_at'))}")
    print()
    rows = []
    for s in steps:
        error = s.get("error", "")
        marker = _status_marker(s.get("status", ""))
        name = s.get("step_name", "")
        fork = s.get("fork_id", "")
        if fork:
            name = f"{fork}/{name}"
        rows.append([
            marker,
            _trunc(name, 50),
            s.get("step_type", ""),
            s.get("status", ""),
            _duration(s.get("started_at"), s.get("completed_at")),
            _trunc(error, 60) if error else "",
        ])
    print(_table(rows, ["", "STEP", "TYPE", "STATUS", "DURATION", "ERROR"]))


def cmd_logs(client: MarkovClient, args: argparse.Namespace):
    run = client.get_run(args.run_id)
    if args.json:
        print(json.dumps(run.get("steps", []), indent=2))
        return
    steps = run.get("steps", [])
    for s in steps:
        output_json = s.get("output_json")
        if not output_json:
            continue
        try:
            output = json.loads(output_json) if isinstance(output_json, str) else output_json
        except json.JSONDecodeError:
            continue
        stderr = output.get("stderr", "").strip()
        stdout = output.get("stdout", "").strip()
        error = s.get("error", "").strip()
        if not stderr and not stdout and not error:
            continue
        name = s.get("step_name", "unknown")
        fork = s.get("fork_id", "")
        if fork:
            name = f"{fork}/{name}"
        print(f"--- {name} ({s.get('status', '')}) ---")
        if stderr:
            print(stderr)
        if stdout:
            print(stdout)
        if error:
            print(f"ERROR: {error}")
        print()


def cmd_workflows(client: MarkovClient, args: argparse.Namespace):
    workflows = client.get_workflows()
    if args.json:
        print(json.dumps(workflows, indent=2))
        return
    if isinstance(workflows, list):
        rows = []
        for w in workflows:
            rows.append([
                str(w.get("id", "")),
                w.get("name", ""),
                (w.get("created_at") or "")[:19],
            ])
        print(_table(rows, ["ID", "NAME", "CREATED"]))
    else:
        print(json.dumps(workflows, indent=2))


def cmd_cancel(client: MarkovClient, args: argparse.Namespace):
    result = client.cancel_run(args.run_id)
    print(f"Cancelled {args.run_id}")
    if args.json:
        print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Query the markovd API")
    parser.add_argument("--url", default=os.environ.get("MARKOVD_URL", "https://markovd.local"))
    parser.add_argument("--user", default=os.environ.get("MARKOVD_USER", ""))
    parser.add_argument("--password", default=os.environ.get("MARKOVD_PASSWORD", ""))
    parser.add_argument("--json", action="store_true", help="Raw JSON output")

    sub = parser.add_subparsers(dest="command", required=True)

    p_runs = sub.add_parser("runs", help="List runs")
    p_runs.add_argument("--limit", type=int, help="Max results")
    p_runs.add_argument("--status", help="Filter by status")
    p_runs.add_argument("--workflow", help="Filter by workflow name (substring)")
    p_runs.add_argument("--json", action="store_true", help="Raw JSON output")

    p_status = sub.add_parser("status", help="Progress + ETA for a run (default: latest running)")
    p_status.add_argument("run_id", nargs="?", help="Run ID (default: latest running)")
    p_status.add_argument("--json", action="store_true", help="Raw JSON output")

    p_steps = sub.add_parser("steps", help="Show steps for a run")
    p_steps.add_argument("run_id", help="Run ID or numeric ID")
    p_steps.add_argument("--json", action="store_true", help="Raw JSON output")

    p_logs = sub.add_parser("logs", help="Show logs (stderr/stdout) for a run")
    p_logs.add_argument("run_id", help="Run ID or numeric ID")
    p_logs.add_argument("--json", action="store_true", help="Raw JSON output")

    p_wf = sub.add_parser("workflows", help="List workflows")
    p_wf.add_argument("--json", action="store_true", help="Raw JSON output")

    p_cancel = sub.add_parser("cancel", help="Cancel a run")
    p_cancel.add_argument("run_id", help="Run ID to cancel")
    p_cancel.add_argument("--json", action="store_true", help="Raw JSON output")

    args = parser.parse_args()
    client = MarkovClient(args.url, args.user, args.password)

    try:
        {"runs": cmd_runs, "status": cmd_status, "steps": cmd_steps,
         "logs": cmd_logs, "workflows": cmd_workflows,
         "cancel": cmd_cancel}[args.command](client, args)
    except requests.exceptions.ConnectionError:
        print(f"Error: cannot connect to {args.url}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
