# Optional agentic-ci Runner in the Pipeline Agent Image

## Context

The pipeline currently runs agents through local entrypoint scripts:

- `scripts/run_skill.sh` for Claude Code CLI
- `scripts/run_skill_sdk.sh` for Claude SDK
- `scripts/run_skill_opencode.sh` for OpenCode CLI
- `scripts/run_skill_opencode_sdk.sh` for OpenCode serve/API mode

OpenCode MLflow tracing is currently tied to the `@mlflow/opencode` plugin path. That path is fragile in CLI mode because OpenCode dispatches plugin events asynchronously and then exits the Node.js process immediately. The `deploy/repos/agentic-ci` checkout shows another viable approach: use OpenCode CLI with native OpenTelemetry enabled, capture OTLP locally, then push traces to MLflow after the agent run.

**Goal**: Install `agentic-ci` into the pipeline agent image and expose it as an optional runner path, without replacing the existing scripts. This gives us a second OpenCode execution path with different MLflow behavior and lets us compare reliability before making it the default.

## Proposed Runner Model

Keep the existing `harness` selection and add a new runner value:

| Harness | Runner | Entrypoint |
|---------|--------|------------|
| `claude-code` | `cli` | `/app/scripts/run_skill.sh` |
| `claude-code` | `sdk` | `/app/scripts/run_skill_sdk.sh` |
| `opencode` | `cli` | `/app/scripts/run_skill_opencode.sh` |
| `opencode` | `sdk` | `/app/scripts/run_skill_opencode_sdk.sh` |
| `opencode` | `agentic-ci` | `/app/scripts/run_skill_agentic_ci.sh --harness opencode` |
| `claude-code` | `agentic-ci` | `/app/scripts/run_skill_agentic_ci.sh --harness claude-code` |

The first useful target is `opencode + agentic-ci`, because it tests the OpenCode native OTel path and avoids the `@mlflow/opencode` plugin flush problem.

## Image Changes

### `deploy/pipeline-agent/Dockerfile`

Install the local checkout from `deploy/repos/agentic-ci` into the agent image:

```dockerfile
COPY deploy/repos/agentic-ci /tmp/agentic-ci
RUN /app/.venv/bin/pip install /tmp/agentic-ci
```

If MLflow trace pushing requires optional dependencies not already present, install the needed extras or explicit packages:

```dockerfile
RUN /app/.venv/bin/pip install /tmp/agentic-ci \
    && /app/.venv/bin/pip install opentelemetry-proto requests protobuf
```

Prefer installing from the local checkout rather than PyPI so the image uses the same audited source under `deploy/repos/agentic-ci`.

## New Entrypoint

### `scripts/run_skill_agentic_ci.sh`

Create a wrapper that keeps the pipeline contract stable:

1. Parse the same common args as the existing entrypoints: `--skill`, `--fqn`, `--issue`, `--model`, `--extra-kwargs`, `--strace`, `--mlflow`.
2. Resolve local or FQN skills using the existing helper path where possible.
3. Build the same prompt content the current scripts pass to Claude/OpenCode.
4. Run `agentic-ci run` in local backend mode inside the already-running pipeline pod.
5. Copy or expose artifacts in the same locations the dashboard expects.
6. If MLflow is enabled, call `agentic-ci mlflow-push` after the run for any captured `/v1/traces` records.

The wrapper should avoid nested Podman. In the pipeline Kubernetes job, `agentic-ci` should run the agent directly via its local backend or an equivalent direct execution mode, because the pipeline pod already is the isolation boundary.

Sketch:

```bash
agentic-ci run \
  --backend local \
  --harness "$AGENTIC_CI_HARNESS" \
  --model "$MODEL" \
  "$PROMPT"

if [[ "${MLFLOW_ENABLED:-true}" == "true" && -n "${MLFLOW_TRACKING_URI:-}" ]]; then
  agentic-ci mlflow-push "$WORK_DIR/_run/claude-otel.jsonl" \
    --endpoint "$MLFLOW_TRACKING_URI" \
    --experiment "$MLFLOW_EXPERIMENT_NAME"
fi
```

The exact CLI flags need verification against the installed `agentic-ci` version. If `--backend local` is not currently exposed, add a small compatibility wrapper or use the Python API from `agentic_ci.skill` directly.

## OpenCode OTel Configuration

For `opencode + agentic-ci`, rely on agentic-ci's native OpenCode OTel setup:

- Write `opencode.json` with `experimental.openTelemetry: true`
- Set `OTEL_EXPORTER_OTLP_ENDPOINT` to the local collector
- Set `OTEL_EXPORTER_OTLP_PROTOCOL=http/json`
- Set `OTEL_BSP_SCHEDULE_DELAY=0`

The last setting is important. It forces immediate span export so OpenCode's `process.exit()` does not kill a queued batch of spans.

This is intentionally separate from the existing `@mlflow/opencode` plugin configuration. The plugin can remain installed for the current SDK experiment, but the `agentic-ci` runner should not depend on it.

## Orchestrator Changes

### `src/dashboard/k8s_orchestrator.py`

Add script mapping:

```python
("opencode", "agentic-ci"): "/app/scripts/run_skill_agentic_ci.sh",
("claude-code", "agentic-ci"): "/app/scripts/run_skill_agentic_ci.sh",
```

Update validation to allow `runner == "agentic-ci"`.

Do not auto-upgrade `opencode + agentic-ci` to SDK when MLflow is enabled. The point of this runner is to test OpenCode CLI with native OTel plus post-run MLflow push.

Existing auto-upgrade should become more specific:

```python
if harness == "opencode" and runner == "cli" and args.get("mlflow") is not False:
    runner = "sdk"
```

That should not catch `agentic-ci`.

Pass enough environment to the pod:

- `MLFLOW_TRACKING_URI`
- `MLFLOW_EXPERIMENT_NAME`
- `MLFLOW_TRACKING_TOKEN` if authentication is needed
- `AGENTIC_CI_BACKEND=local`
- `AGENTIC_CI_HARNESS=<harness>`

## Dashboard Changes

### `src/dashboard/static/js/jobs.js`

Add `agentic-ci` as a runner option for both harnesses:

```javascript
const runnerOptionsByHarness = {
  'claude-code': ['cli', 'sdk', 'agentic-ci'],
  'opencode': ['cli', 'sdk', 'agentic-ci'],
};
```

When the user selects OpenCode with MLflow enabled, keep the current CLI-to-SDK warning or auto-upgrade only for runner `cli`. Do not override an explicit `agentic-ci` selection.

### `src/dashboard/templates/jobs.html`

No structural change is required if the runner dropdown is populated by JavaScript. If runner options are hard-coded anywhere else, add `agentic-ci`.

## MLflow Behavior

There will be two OpenCode MLflow paths:

| Path | Mechanism | Risk |
|------|-----------|------|
| `opencode + sdk` | `@mlflow/opencode` plugin through `opencode serve` | Depends on patched OpenCode SDK server behavior and plugin flush grace period |
| `opencode + agentic-ci` | Native OTel capture, then `agentic-ci mlflow-push` | Depends on OpenCode OTel spans being emitted before exit |

The `agentic-ci` path should be treated as the candidate replacement for OpenCode CLI observability, not as proof that the plugin path is fixed.

## Artifact Handling

The existing dashboard expects agent output and logs from known locations. The wrapper should write or copy:

- agent stdout to the current job log stream
- OTEL JSONL to a predictable artifact path, e.g. `/tmp/pipeline-artifacts/otel.jsonl`
- MLflow push logs to the job log
- any verdict or skill output to the same path the current scripts use

If agentic-ci writes `_run/claude-otel.jsonl`, keep that name initially to avoid patching upstream code. The file can be copied to an OpenCode-neutral alias later.

## Implementation Phases

### Phase 1: Package and Smoke Test

- Install local `deploy/repos/agentic-ci` into the image.
- Add `scripts/run_skill_agentic_ci.sh`.
- Run a minimal OpenCode prompt with `MLFLOW_ENABLED=false`.
- Verify OpenCode output is streamed and the job exits correctly.

### Phase 2: Native OTel Capture

- Enable `agentic-ci` OTel collection for OpenCode.
- Verify the job produces an OTEL JSONL with `/v1/traces` records.
- Confirm `OTEL_BSP_SCHEDULE_DELAY=0` is present in the OpenCode environment.

### Phase 3: MLflow Push

- Resolve or create the MLflow experiment from `MLFLOW_EXPERIMENT_NAME`.
- Run `agentic-ci mlflow-push` after the agent exits.
- Verify MLflow receives at least one trace for the job.
- Compare trace shape against the current `@mlflow/opencode` plugin output if both exist.

### Phase 4: Dashboard Exposure

- Add `agentic-ci` to the runner dropdown.
- Preserve CLI and SDK behavior.
- Add job labels for `runner=agentic-ci` and `harness=<harness>`.
- Make re-run preserve the selected runner.

### Phase 5: Defaulting Decision

After several successful jobs, decide whether OpenCode with MLflow should default to:

- `sdk`, if the plugin path is stable and gives better MLflow semantics
- `agentic-ci`, if native OTel plus post-run push is more reliable

Until then, keep `agentic-ci` opt-in.

## Verification

1. Build the agent image and confirm `agentic-ci --help` works.
2. Submit `harness=opencode`, `runner=agentic-ci`, `mlflow=false`; verify the LLM is called and the job completes.
3. Submit the same job with MLflow enabled; verify an OTEL JSONL is produced.
4. Verify `agentic-ci mlflow-push` posts traces to `MLFLOW_TRACKING_URI`.
5. Confirm `deploy/repos/agentic-ci` remains excluded from the outer repo commit unless intentionally vendored.
6. Confirm `opencode + cli` and `opencode + sdk` still work as before.

## Open Questions

- Does the current `agentic-ci run` CLI expose local backend selection, or do we need to call its Python API directly?
- Does OpenCode's native OTel trace shape contain enough prompt/tool/token detail for the dashboard and Elasticsearch sync?
- Should `agentic-ci mlflow-push` use experiment name or pre-resolved experiment ID in this environment?
- Should the image install all of `agentic-ci`, or only the small subset needed for local harness and MLflow push?
