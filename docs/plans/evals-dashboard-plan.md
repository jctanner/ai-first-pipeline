# Plan: Add "Evals" Dashboard Page

## Context

The observability demo pipeline needs a way to run agent-eval-harness evaluations from the dashboard. The existing Jobs page lets users submit pipeline skill jobs to K8s; we need an analogous "Evals" page that submits eval-harness runs. The user specifies a dataset FQN (pointing to a repo with eval.yaml + dataset cases), picks a model, and the system clones the eval harness + dataset repo and runs the evaluation inside a K8s job.

A key use case is testing whether changes to architecture-context (docs fixes, new component entries) improve model reasoning. The eval needs to clone architecture-context at a specific branch/ref (e.g. `fix/RHAIFIRST-1` from a PR) so the model can read the corrected docs. A/B comparison runs the same eval against `main` (baseline) vs the fix branch to measure improvement.

Future evals will also want to test `arch-query` — a Go binary in architecture-context (`src/arch-query/`) that replaces flat file reading with structured queries (`arch-query component kserve`, `arch-query grep httproute`, `arch-query diff --all v1 v2`). When the context mode is `arch-query`, the eval script builds the binary and makes it available on PATH instead of pointing the model at flat files. This lets us measure whether structured queries produce better/faster results than raw file reading.

## Approach

Mirror the existing Jobs architecture (template + JS + API + orchestrator) with eval-specific fields. Reuse the existing job detail/logs/stop/delete APIs since eval jobs are regular K8s jobs, just with different labels and entrypoint.

## Files to Create

### 1. `scripts/run_eval.sh` — K8s container entrypoint

Shell script that runs inside the `pipeline-agent:latest` container. Flow:
- Parse args: `--dataset-fqn`, `--model`, `--baseline`, `--run-id`, `--context-ref`, `--context-mode`
- Decompose FQN into `host/owner/repo@ref:eval-config` components (same bash parsing as `run_skill.sh`)
- Log redirect to `/app/artifacts/jobs/${PIPELINE_JOB_NAME}.log` (reuse pattern from `run_skill.sh`)
- SSL/CA setup, git HTTPS config (copy from `run_skill.sh`)
- Clone agent-eval-harness from `github-emulator.ai-pipeline.svc.cluster.local`
- `pip install -e ./agent-eval-harness`
- Clone dataset repo from parsed FQN (mapping `github.local` → cluster-internal FQDN)
- **Clone architecture-context** at the ref specified by `--context-ref` (defaults to `main`):
  ```
  CONTEXT_DIR="/tmp/eval-workspace/architecture-context"
  git clone --depth 1 -b "$CONTEXT_REF" "https://$GITHUB_HOST/opendatahub-io/architecture-context.git" "$CONTEXT_DIR"
  ```
- **Context mode setup** based on `--context-mode` (defaults to `files`):
  - `files`: Set `ARCH_CONTEXT_PATH=$CONTEXT_DIR/architecture` — dataset cases reference this path to read flat markdown files
  - `arch-query`: Build the binary (`cd $CONTEXT_DIR && make build`), add `$CONTEXT_DIR/bin` to PATH — dataset cases use `arch-query component ...` commands instead of file reads
- Export `ARCH_CONTEXT_PATH` and `ARCH_CONTEXT_MODE` as env vars so eval.yaml's `execution.env` can inject them into case workspaces
- Configure Claude for Vertex AI (reuse Python snippet from `run_skill.sh`)
- Configure MLflow, OTel, strace (same patterns as `run_skill.sh`)
- Run: `cd $DATASET_DIR && claude --print --model $MODEL` with `/eval-run` prompt, streaming through `stream-claude.py`
- Copy results from `eval/runs/$RUN_ID` to `/app/artifacts/eval-runs/`

### 2. `src/dashboard/templates/evals.html` — Page template (~170 lines)

Extends `layout.html`. Structure mirrors `jobs.html`:
- Same `<style>` block (status classes, modal styles) — copy from `jobs.html` lines 4-37
- K8s availability guard (same pattern as `jobs.html` line 42-46)
- **Submit form** with fields:
  - Dataset FQN (text input, required) — placeholder: `github.local/opendatahub-io/skills@main:claim-fix-validation`
  - Model (select: haiku/sonnet/opus, default opus)
  - Context Ref (text input, optional) — placeholder: `github.local/opendatahub-io/architecture-context@main`. Specifies the repo+branch of architecture-context to clone. Defaults to `main`. For testing PRs, use the fix branch (e.g. `@fix/RHAIFIRST-1`).
  - Context Mode (select: `files` / `arch-query`, default `files`) — controls how the model accesses architecture-context:
    - `files`: model reads flat markdown from `architecture/` directory
    - `arch-query`: script builds the Go binary and puts it on PATH; model uses structured CLI queries
  - Baseline run ID (text input, optional) — for A/B comparison
  - Checkboxes: strace, MLflow (checked), OTel (checked)
  - Submit button
- **Evals table** with columns: Name, Dataset, Model, Status, Created, Duration
- **Detail modal** (`<dialog>`) with: status badge, detail grid (Dataset, Model, Context Ref, Context Mode, Baseline, Created, Started, Duration, Result, strace/MLflow/OTel), action buttons (Re-run, Stop, Delete), log viewer
- Scripts block: set `K8S_AVAILABLE` JS var, load `evals.js`

### 3. `src/dashboard/static/js/evals.js` — Frontend JS (~300 lines)

Mirrors `jobs.js` structure. Key functions:
- **Form submit handler**: POST to `/api/evals/submit` with `{dataset_fqn, model, context_ref, context_mode, baseline, strace, mlflow, otel}`
- **`refreshEvals()`**: GET `/api/evals`, sort by created desc, render table rows. Auto-refresh every 3s.
- **`openEvalModal(name)`**: GET `/api/jobs/<name>` (reuse existing job detail API), populate modal, start log polling
- **`fetchModalLogs()`**: GET `/api/jobs/<name>/logs` (reuse existing logs API)
- **`startLogPolling()` / `stopLogPolling()`**: 2s interval, same pattern as `jobs.js`
- **`modalStop()` / `modalDelete()`**: POST/DELETE to existing `/api/jobs/<name>/stop` and `/api/jobs/<name>` 
- **`modalRerun()`**: POST to `/api/evals/submit` with stored opts
- All functions exported to `window.*`

## Files to Modify

### 4. `src/dashboard/templates/layout.html` — Add nav link

Insert after the Jobs link (line 240), before Files (line 241):
```html
<a href="/evals" class="px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-900 dark:hover:text-white transition-colors no-underline">Evals</a>
```

### 5. `src/dashboard/webapp.py` — Add 3 routes

After the `/jobs` route (line 505):

**`GET /evals`** — Page route:
```python
@app.route("/evals")
def evals():
    return render_template("evals.html", k8s_available=K8S_AVAILABLE)
```

**`POST /api/evals/submit`** — Submit eval job:
- Validate `dataset_fqn` (required), parse with `parse_fqn()` from `src/cli/skill_config.py`
- Extract `model` (default "opus"), `context_ref` (default "main"), `context_mode` (default "files"), `baseline` (optional), observability flags
- Call `orchestrator.submit_eval_job(dataset_fqn, model, context_ref, context_mode, baseline, args)`
- Return `{job_name, status: "pending"}`

**`GET /api/evals`** — List eval jobs:
- Call `orchestrator.list_eval_jobs()` (queries K8s with `label_selector="app=pipeline-agent,category=eval"`)
- Return list with: name, dataset_fqn (from annotation), model, context_ref, context_mode, baseline, status, created, duration, observability flags

### 6. `src/dashboard/k8s_orchestrator.py` — Add 3 methods

**`submit_eval_job(dataset_fqn, model, context_ref, context_mode, baseline, args)`**:
- Delegates to `_create_eval_job_manifest()`, then `batch_v1.create_namespaced_job()`

**`list_eval_jobs()`**:
- `list_namespaced_job(label_selector="app=pipeline-agent,category=eval")`

**`_create_eval_job_manifest(dataset_fqn, model, context_ref, context_mode, baseline, args)`**:
- Job naming: `eval-{eval_config}-{model_slug}-{timestamp}` (eval_config = part after `:` in FQN)
- Labels: `app=pipeline-agent`, `category=eval`, `eval-config={...}`, `model={...}`, `context-mode={files|arch-query}`, strace/mlflow/otel
- Annotations: `dataset_fqn`, `model`, `context_ref`, `context_mode`, `baseline`
- Container command: `["/bin/bash", "/app/scripts/run_eval.sh", "--dataset-fqn", fqn, "--model", model, "--context-ref", context_ref, "--context-mode", context_mode]` + optional `["--baseline", baseline]`
- Reuse `_build_env_vars()`, `_build_volume_mounts()`, `_build_volumes()` — same init containers, affinity, resources as `_create_job_manifest()`
- Note: `arch-query` mode requires Go 1.25+ in the container image. For initial implementation, `files` mode is the default and `arch-query` mode will fail gracefully if Go is not available (log a warning and fall back to `files`).

**Note**: Also update `get_job_status()` to include `dataset_fqn`, `context_ref`, `context_mode`, and `baseline` from annotations, and `category` from labels — so the existing `/api/jobs/<name>` endpoint returns eval-specific fields too.

## Data Flow

```
evals.html form → evals.js POST /api/evals/submit
  → webapp.py: validate FQN, call orchestrator.submit_eval_job()
    → k8s_orchestrator.py: _create_eval_job_manifest() → K8s Job
      Container runs run_eval.sh:
        1. Clone agent-eval-harness
        2. Clone dataset repo (from FQN)
        3. Clone architecture-context at --context-ref branch
        4. If --context-mode=arch-query: build Go binary, add to PATH
        5. Export ARCH_CONTEXT_PATH + ARCH_CONTEXT_MODE
        6. Run eval via claude --print /eval-run

evals.js polls GET /api/evals (table) + reuses GET /api/jobs/<name> (detail/logs)
```

## Architecture-Context in Eval Cases

Dataset cases need to tell the model where/how to access architecture docs. The eval.yaml injects env vars into the workspace, and each case's `input.yaml` references them.

**eval.yaml** (in the dataset repo):
```yaml
execution:
  env:
    ARCH_CONTEXT_PATH: "$ARCH_CONTEXT_PATH"
    ARCH_CONTEXT_MODE: "$ARCH_CONTEXT_MODE"
  arguments: "{prompt}"
runner:
  type: cli
  command: "claude --print --model {model} '{args}'"
```

**Case input.yaml** (files mode):
```yaml
prompt: >
  Using the architecture docs at $ARCH_CONTEXT_PATH,
  answer: What UI framework does odh-dashboard use?
expected: "React with PatternFly"
```

**Case input.yaml** (arch-query mode):
```yaml
prompt: >
  Use the arch-query tool to answer: What UI framework does odh-dashboard use?
  Example: arch-query component odh-dashboard
expected: "React with PatternFly"
```

**A/B workflow for testing a PR:**
1. Run eval with `context_ref=main` → baseline scores
2. Run eval with `context_ref=fix/RHAIFIRST-1` → test scores
3. Run with `--baseline <run-1-id>` to get comparison report

**A/B workflow for files vs arch-query:**
1. Run eval with `context_mode=files` → baseline
2. Run eval with `context_mode=arch-query` → test
3. Compare: accuracy, token usage, cost, speed

## What We Reuse

- `parse_fqn()` from `src/cli/skill_config.py` — already handles `host/owner/repo@ref:skill` format
- `_build_env_vars()`, `_build_volume_mounts()`, `_build_volumes()` from orchestrator
- Existing `/api/jobs/<name>`, `/api/jobs/<name>/logs`, `/api/jobs/<name>/stop`, `DELETE /api/jobs/<name>` — eval jobs are K8s jobs, these endpoints work on any job by name
- `_get_job_status()` from orchestrator
- `stream-claude.py` for streaming output in the container
- All SSL/CA/git/Vertex/MLflow/OTel/strace setup patterns from `run_skill.sh`

## Implementation Order

1. `scripts/run_eval.sh` (independent)
2. `k8s_orchestrator.py` (add methods)
3. `webapp.py` (add routes)
4. `layout.html` (one-line nav link)
5. `evals.html` (template)
6. `evals.js` (JS)

## Verification

1. Start dashboard: `python main.py dashboard`
2. Navigate to `/evals` — verify page renders with form and empty table
3. Submit an eval with FQN `github.local/opendatahub-io/skills@main:claim-fix-validation`, model `haiku`
4. Verify K8s job appears: `kubectl get jobs -l category=eval -n ai-pipeline`
5. Verify job appears in evals table with correct metadata
6. Click row to open modal — verify details and log streaming
7. Test Stop and Delete actions
8. Test Re-run button
9. Test validation: submit without FQN → error, submit with malformed FQN → error
