## Goal

Make OpenCode jobs produce MLflow traces using the official `@mlflow/opencode` npm plugin (v0.2.0-rc.1). Claude Code jobs already produce MLflow traces via `mlflow autolog claude` hooks — we need parity for OpenCode.

## How the Plugin Works

The `@mlflow/opencode` plugin registers an event handler that listens for `session.idle`. When fired, it:
1. Calls `client.session.messages()` to fetch all session messages
2. Creates an MLflow trace with an AGENT parent span, LLM child spans (with token usage), and TOOL child spans
3. POSTs the trace to the MLflow tracking server via `flushTraces()`

It requires two env vars: `MLFLOW_TRACKING_URI` and `MLFLOW_EXPERIMENT_ID` (not name — ID). Silently does nothing if either is missing.

## What's Already Done (Uncommitted)

- **Dockerfile** (`deploy/pipeline-agent/Dockerfile`): Writes `opencode.json` config enabling the plugin, pre-installs it into OpenCode's npm cache so it loads instantly
- **Entrypoint scripts** (`scripts/run_skill_opencode.sh`, `scripts/run_skill_opencode_sdk.sh`): Resolve `MLFLOW_EXPERIMENT_NAME` → `MLFLOW_EXPERIMENT_ID` via Python mlflow SDK
- **K8s orchestrator** (`src/dashboard/k8s_orchestrator.py`): Auto-upgrades OpenCode CLI→SDK runner when MLflow is enabled

## The Problem

**OpenCode CLI mode kills the plugin before it can flush traces.** The root cause is two things in OpenCode's source:

1. **Fire-and-forget dispatch** — `plugin/index.ts:255`: `void hook["event"]?.(...)` — the plugin's async event handler is NOT awaited
2. **Immediate process.exit()** — `index.ts:141`: `process.exit()` in a `finally` block after the CLI command completes

The session goes idle → plugin handler fires (async, not awaited) → `process.exit()` runs immediately → Node.js process dies → plugin's HTTP POST to MLflow never executes.

**SDK mode has a similar but fixable problem.** The `opencode serve` process stays alive, but the entrypoint script's EXIT trap kills it almost immediately after the Python driver detects idle. A 5-second sleep grace period (added but not yet deployed) should fix this.

## Strace Evidence

Job: `cookiemonster-all-claude-haiku-4-5-0622-185811` (CLI mode, completed)

Strace files location:
```
/data/k3s/storage/pvc-9acffda0-4dda-4fa5-80a3-ced82db48109_ai-pipeline_pipeline-artifacts/strace/cookiemonster-all-claude-haiku-4-5-0622-185811/
```

Key findings:
- `18:58:19` — `opencode.json` read, plugin config loaded
- `18:58:35` — Plugin loaded from cache (`dist/index.js` read)
- `18:58:35-36` — MLflow SDK dependencies loaded (databricks client, `@mlflow/core`)
- **Zero TCP connections to MLflow** (`10.43.113.51:5000`) — plugin never reached the HTTP POST
- Two connections to Observatory (`10.43.168.244:8000`) — built-in OTEL works fine
- `18:58:40` — `exit_group(0)` — process dead

MLflow confirms: experiment ID 6 exists, zero runs/traces.

## OpenCode Source (Read-Only Reference)

Cloned at `checkouts/opencode/packages/opencode/src/`:
- `index.ts:141` — `process.exit()` in finally block
- `plugin/index.ts:255` — `void hook["event"]?.(...)` fire-and-forget dispatch
- `session/status.ts:82` — `session.idle` event emission
- Plugin npm cache check: `packages/core/src/npm.ts:124`

Plugin source (extracted):
- `/tmp/mlflow-check/package/dist/index.js` — `ensureInitialized()`, `MLflowTracingPlugin`, `processSession()`

## Files to Change

| File | Status | What |
|------|--------|------|
| `deploy/pipeline-agent/Dockerfile` | Done (uncommitted) | Plugin config + cache pre-install |
| `scripts/run_skill_opencode.sh` | Done (uncommitted) | Experiment ID resolution + CLI warning |
| `scripts/run_skill_opencode_sdk.sh` | Done (uncommitted) | Experiment ID resolution + 5s grace period sleep |
| `src/dashboard/k8s_orchestrator.py` | Done (uncommitted) | Auto-upgrade OpenCode CLI→SDK when MLflow enabled |

## What Needs Testing

Rebuild the container image with current uncommitted changes, then run an OpenCode job with MLflow enabled. The orchestrator should auto-select SDK mode. After completion, check MLflow experiment ID 6 for a trace with AGENT/LLM/TOOL spans. The 5-second grace period in the SDK script is the key untested fix.
