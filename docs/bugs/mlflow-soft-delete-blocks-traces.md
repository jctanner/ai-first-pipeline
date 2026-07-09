# MLflow soft-deleted experiments block future trace ingestion

## Status: Open

## Symptom

Codegen agents log warnings on every trace export:

```
WARNING mlflow.tracing.export.mlflow_v3: Failed to send trace to MLflow backend:
INVALID_PARAMETER_VALUE: The experiment 28 must be in the 'active' state.
Current state is deleted.
```

Traces are silently dropped for the entire run.

## Root cause

The end-to-end workflow reset step deletes MLflow experiments via the API, but the MLflow `DELETE /api/2.0/mlflow/experiments/delete` endpoint performs a **soft delete** — it moves the experiment to `deleted` lifecycle stage rather than removing it. When the next run creates a new experiment with the same name, MLflow reuses the deleted experiment ID and rejects traces because the experiment is inactive.

## Evidence

```
$ kubectl exec mlflow-pod -- mlflow experiments search --view deleted_only | grep codegen
28  github.local/opendatahub-io/epic-code-gen@main:epic-codegen/claude-code/opus/cli
```

## No API-based hard delete

`mlflow gc` can hard-delete experiments, but it's a CLI-only operation — there is no REST API endpoint for hard delete. The workflow reset step uses HTTP API calls to clean up, so it can only soft-delete via `POST /api/2.0/mlflow/experiments/delete`. Once soft-deleted, the experiment name is poisoned: any future experiment created with the same name reuses the deleted ID and inherits the `deleted` state, causing trace ingestion to fail.

## `mlflow gc` doesn't work either

`mlflow gc --experiment-ids 28` fails with `FOREIGN KEY constraint failed` because it tries to delete the experiment record without first deleting traces and spans that reference it. This appears to be a bug in `mlflow gc` itself — it handles runs but not traces.

```
$ mlflow gc --experiment-ids 28 --backend-store-uri sqlite:///data/mlflow.db

sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
[SQL: DELETE FROM experiments WHERE experiments.experiment_id = ?]
[parameters: (28,)]

  File ".../mlflow/cli/__init__.py", line 913, in _gc_tracking_resources
    backend_store._hard_delete_experiment(experiment_id)
  File ".../mlflow/store/tracking/sqlalchemy_store.py", line 721, in _hard_delete_experiment
    with self.ManagedSessionMaker() as session:
```

## Verified fix: manual SQL delete in FK order

Tested and confirmed working:

```python
conn.execute('DELETE FROM spans WHERE experiment_id=28')
conn.execute('DELETE FROM trace_info WHERE experiment_id=28')
conn.execute('DELETE FROM experiments WHERE experiment_id=28')
conn.commit()
```

After this, creating a new experiment with the same name succeeds (reuses the ID).

## Workarounds for the reset workflow

1. **SQL-based hard delete** — add a step that connects to the SQLite DB and deletes spans → traces → experiment in FK order. Most complete but couples to the DB schema.
2. **Restore before reuse** — call `POST /api/2.0/mlflow/experiments/restore` on soft-deleted experiments so they're active when the next run starts. Simplest API-based fix.
3. **Don't delete experiments during reset** — leave them active and let new runs append. Avoids the problem entirely but historical data accumulates.
