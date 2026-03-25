# BUG1: Agents cannot start — single-threaded Flask blocks on SSE

## Commit

`90365b0372d731375588837d83dcfc65431b5dda` — "Replace file-based activity coordination with HTTP push from controller to webapp"

## Summary

The commit changed the coordination architecture from file-based (controller writes `activity.jsonl`, webapp polls it) to HTTP push (controller POSTs to webapp via `/api/events/push`). However, Flask was left running in single-threaded mode while the new SSE endpoint (`/api/events`) uses a blocking `queue.Queue.get(timeout=30)` call. This blocks Flask's only thread, preventing the controller's push requests from being served, which cascades into event loop flooding that delays agent startup.

## Root Cause

### The blocking chain

1. Browser opens Activity or Dashboard page. JavaScript opens `new EventSource('/api/events')`.
2. The SSE generator blocks Flask's only werkzeug thread — `q.get(timeout=30)` at `lib/webapp.py:3162` holds the thread in a loop indefinitely.
3. Controller starts the pipeline and calls `await _push_manifest(manifest)` (`lib/phases.py:2373`), which POSTs to `http://127.0.0.1:5000/api/events/push`.
4. Flask cannot serve the POST — its only thread is stuck in the SSE generator.
5. The TCP connection hangs (Flask's socket accepts it at the OS level, but no thread is free to handle the HTTP request) until the httpx 5-second timeout fires.
6. `_push_manifest` catches the exception and prints a warning, but the manifest never reaches the webapp. `_pipeline_state["jobs"]` stays empty, so the dashboard never shows any job progress.
7. Every subsequent `_log_activity` call (`lib/phases.py:523-524`) creates a fire-and-forget `loop.create_task(_push_event(entry))`. With N issues x M models, hundreds of async HTTP tasks pile up on the asyncio event loop, each hanging for 5 seconds waiting on a server that will never respond.

### Why agents are delayed/blocked

- `await _push_manifest(manifest)` at `lib/phases.py:2373` blocks the pipeline for up to 5 seconds (httpx timeout) before the `asyncio.gather()` that launches issue pipelines.
- After that, every `_log_activity` call inside `_run_issue_pipeline` (`lib/phases.py:2249`) and `_run_single_agent` (`lib/phases.py:569`) creates fire-and-forget HTTP POST tasks. The default `httpx.AsyncClient(timeout=5.0)` with a pool of 100 max connections means the event loop gets flooded with hundreds of pending tasks all waiting on a blocked server.
- This contention can delay the actual agent coroutines (`run_agent` calls via the Claude SDK) from being scheduled on the shared asyncio event loop.

### Secondary issue: `--dashboard-url` always defaults

In `lib/cli.py:203`, `--dashboard-url` defaults to `http://127.0.0.1:5000`. This means `_dashboard_url` is always populated, so push attempts always happen — even when no dashboard is running. If the port is closed, ECONNREFUSED is fast. But if the dashboard IS running and blocked by SSE, every push hangs for 5 seconds.

## Key files and lines

| File | Line(s) | What |
|------|---------|------|
| `lib/webapp.py` | 3160-3166 | SSE endpoint with blocking `q.get(timeout=30)` |
| `lib/webapp.py` | 3138-3148 | `/api/events/push` endpoint that can't be reached |
| `lib/phases.py` | 2373 | `await _push_manifest(manifest)` — blocks pipeline up to 5s |
| `lib/phases.py` | 520-526 | Fire-and-forget `_push_event` task creation in `_log_activity` |
| `lib/phases.py` | 476 | `httpx.AsyncClient(timeout=5.0)` — shared client |
| `lib/phases.py` | 569 | `_log_activity` called BEFORE semaphore acquisition |
| `lib/cli.py` | 202-204 | `--dashboard-url` default `http://127.0.0.1:5000` |

## Architecture context

Old flow (pre-commit):
```
Controller --> writes activity.jsonl --> Webapp polls file via tail_activity_log() --> SSE to browser
```

New flow (this commit):
```
Controller --> HTTP POST /api/events/push --> Webapp holds state in memory --> SSE to browser
```

The new flow requires the webapp to be responsive to HTTP requests from the controller, but the SSE endpoint still blocks the thread, making this impossible in single-threaded mode.

## Fixes

### 1. Add `threaded=True` to Flask (critical)

In `lib/phases.py`, `run_report_phase`:
```python
app.run(host=args.host, port=args.port, debug=True, threaded=True)
```
This lets Flask handle SSE connections and push requests on separate threads. Already present in the uncommitted working tree changes.

### 2. Auto-detect dashboard reachability at startup (helpful but not sufficient)

A TCP connect check in `run_all_phases` skips push when nothing is listening. This helps when the dashboard isn't running at all. However, **it does NOT solve the core problem** when the dashboard IS running but is single-threaded — the port is open (TCP check passes), but Flask can't serve push requests because its thread is blocked on SSE. Fix 1 (`threaded=True`) is the essential fix for that case. The reachability check is still useful for avoiding event loop flooding when no dashboard is running.

```python
import socket
from urllib.parse import urlparse

def _dashboard_reachable(url: str, timeout: float = 0.5) -> bool:
    """Quick TCP connect check — is anything listening?"""
    try:
        parsed = urlparse(url)
        with socket.create_connection((parsed.hostname, parsed.port), timeout=timeout):
            return True
    except (OSError, TypeError):
        return False
```

Then in `run_all_phases`:
```python
_dashboard_url = getattr(args, "dashboard_url", None)
if _dashboard_url and not _dashboard_reachable(_dashboard_url):
    print(f"  [dashboard] {_dashboard_url} not reachable — disabling push")
    _dashboard_url = None
```

This is a point-in-time check. If the dashboard goes down mid-run, the existing `try/except` in `_push_event` and `_push_manifest` handles it gracefully. The main value is preventing hundreds of fire-and-forget tasks from flooding the event loop when nothing is listening.

### 3. Move dashboard push to a background thread (critical — the actual fix)

**Finding:** Even with `threaded=True` on Flask and fire-and-forget `create_task()`, agents still hung. The root cause is that hundreds of `loop.create_task(_push_event(...))` calls pile async HTTP tasks onto the same asyncio event loop that runs the agents. The event loop gets saturated managing httpx connections and the agent coroutines can't get scheduled.

**Fix:** Replace the async `httpx.AsyncClient` + `create_task` approach with a dedicated background thread using a synchronous `httpx.Client` and a bounded `queue.Queue`. This completely decouples dashboard communication from the asyncio event loop:

- `_start_push_thread()` — spins up a daemon thread at pipeline start
- `_push_worker()` — synchronous loop that drains the queue and POSTs via `httpx.Client(timeout=1.0)`
- `_enqueue_push(payload)` — non-blocking `put_nowait()` called from `_log_activity`; drops events if queue is full (maxsize=500)
- `_log_activity` no longer touches `asyncio.get_running_loop()` or `create_task()`
- `_push_manifest` is also sent via `_enqueue_push()` — no more `await`

This ensures the asyncio event loop is exclusively used for agent work.

### 5. Debounce `loadQueueState()` in JavaScript (minor)

In the Activity page template, every SSE event triggers `fetch('/api/pipeline/queue')`. Under load (hundreds of events), this is very chatty. Add a debounce so it fires at most once per second.
