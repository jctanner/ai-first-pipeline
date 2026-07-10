# MLflow hard delete for demo resets

## Context

The dashboard currently clears MLflow through `src/dashboard/mlflow_client.py`,
which uses MLflow's public client/API. That path deletes runs and traces, then
soft-deletes non-default experiments. Soft-deleted experiments keep their IDs and
names in the SQLite backend. On the next end-to-end reset, trace ingestion can
fail with:

```text
experiment must be in active state
```

`mlflow gc` is not enough for this deployment either. It has been observed to
fail on trace/spans foreign keys in the SQLite backend. The manual fix recorded
in `docs/bugs/mlflow-soft-delete-blocks-traces.md` is direct SQL deletion in
foreign-key-safe order.

This is an admin-only demo reset feature, not a general MLflow product API. It
may couple to MLflow's SQLite schema, so the implementation should be defensive
and visible when it cannot safely clear data.

## Decision

Add a dashboard hard-clear path that executes a Python cleanup script inside the
running `mlflow` pod. The script opens `/data/mlflow.db`, deletes all MLflow data
except the Default experiment row, and removes artifact files under
`/data/artifacts`.

Use this hard-clear endpoint from the end-to-end reset workflow. Keep the
existing soft-clear endpoint available from the UI for API-level cleanup/testing,
but do not use it for the demo reset.

## Implementation Plan

### 1. RBAC

File: `deploy/k8s/16-pipeline-rbac.yaml`

Add `pods/exec` permission to the `pipeline-orchestrator` Role:

```yaml
- apiGroups: [""]
  resources: ["pods/exec"]
  verbs: ["create"]
```

This grants exec to all service accounts bound to the role today:
`pipeline-dashboard`, `markovd`, and `pipeline-agent`. If that is broader than
desired, split dashboard admin operations into a narrower RoleBinding later.

### 2. Kubernetes Orchestrator

File: `src/dashboard/k8s_orchestrator.py`

Add `exec_mlflow_hard_delete()`:

- Find exactly one running MLflow pod with label selector `app=mlflow`.
- Exec into container `mlflow` with:
  `python3 -c <cleanup-script>`
- Use `kubernetes.stream.stream()` with stderr enabled.
- Return a structured result:

```json
{
  "experiments_deleted": 0,
  "default_experiment_cleared": true,
  "runs_deleted": 0,
  "traces_deleted": 0,
  "spans_deleted": 0,
  "artifacts_deleted": 0,
  "output": "...",
  "errors": []
}
```

Fail loudly if:

- no MLflow pod is found,
- more than one matching pod is running,
- `/data/mlflow.db` is missing,
- the exec command exits non-zero,
- the cleanup script reports foreign-key failures.

### 3. Cleanup Script Shape

The embedded script should be schema-aware instead of hardcoding only three
tables. MLflow 3.x tracing adds tables beyond classic runs/params/metrics, and
future patch versions may add more.

Recommended behavior:

1. Connect with `sqlite3.connect("/data/mlflow.db")`.
2. Enable `PRAGMA foreign_keys = ON`.
3. Read table names from `sqlite_master`.
4. Read foreign-key relationships using `PRAGMA foreign_key_list(<table>)`.
5. Build a child-before-parent delete order for rows that ultimately reference:
   - `experiments.experiment_id`
   - `runs.run_uuid`
   - `trace_info.request_id` or equivalent trace primary key, if present
6. Delete rows for every experiment ID except `0`.
7. For experiment `0`, delete dependent run/trace/span data but keep the
   `experiments` row.
8. Delete soft-deleted experiment rows too; do not filter by lifecycle stage.
9. Run `PRAGMA foreign_key_check` before commit and fail if any violations remain.
10. Clear `/data/artifacts` contents, preserving the directory itself.

At minimum, cover the currently observed tables:

- tracing: `spans`, `trace_info`, trace metadata/tag/request tables if present
- run data: `metrics`, `params`, `tags`, `latest_metrics`, `inputs`, datasets
- experiments: `experiment_tags`, `experiments`

The script should make missing tables a no-op. The endpoint should not depend on
the exact MLflow minor schema as long as foreign keys disclose the relationship.

### 4. Dashboard API

File: `src/dashboard/webapp.py`

Add:

```text
POST /api/mlflow/hard-clear
```

Behavior:

- Requires `K8S_AVAILABLE`.
- Calls `get_orchestrator().exec_mlflow_hard_delete()`.
- Returns `200` with the structured result on success.
- Returns `502` for Kubernetes exec or SQL cleanup failures.
- Does not log full SQL output if it could include experiment names from user
  data; counts and table names are enough.

Keep `POST /api/mlflow/clear` unchanged as the existing soft/API clear.

### 5. Admin UI

Files:

- `src/dashboard/templates/admin.html`
- `src/dashboard/static/js/admin.js`

Revise the MLflow section to expose two explicit actions:

- `Clear MLflow` — existing soft/API clear via `/api/mlflow/clear`
- `Hard Delete MLflow` — new SQL clear via `/api/mlflow/hard-clear`

Use separate confirmation modals. The hard-delete modal should state that it
execs into the MLflow pod and directly modifies `/data/mlflow.db` and
`/data/artifacts`.

Do not hide the existing soft clear. It is still useful for checking MLflow API
behavior and for lower-risk manual cleanup.

### 6. End-To-End Reset Workflow

File: `var/demos/end-to-end/workflows/reset-services.yaml`

Change the MLflow reset step from:

```yaml
path: /api/mlflow/clear
```

to:

```yaml
path: /api/mlflow/hard-clear
```

This is the critical workflow change. Without it, the demo reset continues to
poison experiment names through soft deletes.

### 7. Bug Note

File: `docs/bugs/mlflow-soft-delete-blocks-traces.md`

Update the workaround section after implementation:

- mark SQL hard delete as implemented through dashboard admin API,
- note that the reset workflow uses `/api/mlflow/hard-clear`,
- retain the `restore before reuse` option as an alternative if hard delete ever
  becomes too coupled to the MLflow schema.

## Verification

1. Apply RBAC:

   ```bash
   kubectl apply -f deploy/k8s/16-pipeline-rbac.yaml
   ```

2. Rebuild and redeploy the dashboard image.

3. Confirm the dashboard service account can exec:

   ```bash
   kubectl -n ai-pipeline auth can-i create pods/exec --as system:serviceaccount:ai-pipeline:pipeline-dashboard
   ```

4. Seed a soft-deleted experiment by using the current soft clear once, or by
   reproducing the failing reset.

5. Call the new endpoint:

   ```bash
   curl -ks -X POST https://dashboard.local/api/mlflow/hard-clear
   ```

6. Verify no deleted experiments remain:

   ```bash
   kubectl -n ai-pipeline exec deploy/mlflow -- python3 -c "import sqlite3; c=sqlite3.connect('/data/mlflow.db'); print(c.execute(\"SELECT experiment_id, name, lifecycle_stage FROM experiments WHERE lifecycle_stage='deleted'\").fetchall())"
   ```

7. Verify foreign keys are clean:

   ```bash
   kubectl -n ai-pipeline exec deploy/mlflow -- python3 -c "import sqlite3; c=sqlite3.connect('/data/mlflow.db'); c.execute('PRAGMA foreign_keys=ON'); print(c.execute('PRAGMA foreign_key_check').fetchall())"
   ```

8. Run `var/demos/end-to-end/workflows/reset-services.yaml`, then run the
   end-to-end demo. Trace ingestion should not fail with
   `experiment must be in active state`.

## Open Questions

- Should hard clear also restart the MLflow pod after SQL mutation? Prefer not
  initially; SQLite changes should be visible to the running server, but a
  restart is a fallback if the server caches experiment metadata.
- Should this become a cleanup Job that mounts `mlflow-data` instead of
  `pods/exec`? Exec is simpler and uses the already-running MLflow image with
  Python/sqlite available. A Job would avoid granting exec but needs separate PVC
  mount permissions and image dependency management.
