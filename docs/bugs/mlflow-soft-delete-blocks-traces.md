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

Traceback (most recent call last):
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/base.py", line 1967, in _exec_single_context
    self.dialect.do_execute(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/default.py", line 952, in do_execute
    cursor.execute(statement, parameters)
sqlite3.IntegrityError: FOREIGN KEY constraint failed

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/usr/local/lib/python3.10/site-packages/mlflow/store/db/utils.py", line 188, in make_managed_session
    session.commit()
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/session.py", line 2030, in commit
    trans.commit(_to_root=True)
  File "<string>", line 2, in commit
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/state_changes.py", line 137, in _go
    ret_value = fn(self, *arg, **kw)
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/session.py", line 1311, in commit
    self._prepare_impl()
  File "<string>", line 2, in _prepare_impl
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/state_changes.py", line 137, in _go
    ret_value = fn(self, *arg, **kw)
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/session.py", line 1286, in _prepare_impl
    self.session.flush()
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/session.py", line 4331, in flush
    self._flush(objects)
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/session.py", line 4466, in _flush
    with util.safe_reraise():
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/util/langhelpers.py", line 121, in __exit__
    raise exc_value.with_traceback(exc_tb)
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/session.py", line 4427, in _flush
    flush_context.execute()
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/unitofwork.py", line 466, in execute
    rec.execute(self)
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/unitofwork.py", line 679, in execute
    util.preloaded.orm_persistence.delete_obj(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/persistence.py", line 193, in delete_obj
    _emit_delete_statements(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/orm/persistence.py", line 1471, in _emit_delete_statements
    c = connection.execute(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/base.py", line 1419, in execute
    return meth(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/sql/elements.py", line 527, in _execute_on_connection
    return connection._execute_clauseelement(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/base.py", line 1641, in _execute_clauseelement
    ret = self._execute_context(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/base.py", line 1846, in _execute_context
    return self._exec_single_context(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/base.py", line 1986, in _exec_single_context
    self._handle_dbapi_exception(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/base.py", line 2363, in _handle_dbapi_exception
    raise sqlalchemy_exception.with_traceback(exc_info[2]) from e
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/base.py", line 1967, in _exec_single_context
    self.dialect.do_execute(
  File "/usr/local/lib/python3.10/site-packages/sqlalchemy/engine/default.py", line 952, in do_execute
    cursor.execute(statement, parameters)
sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
[SQL: DELETE FROM experiments WHERE experiments.experiment_id = ?]
[parameters: (28,)]
(Background on this error at: https://sqlalche.me/e/20/gkpj)

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/usr/local/bin/mlflow", line 8, in <module>
    sys.exit(cli())
  File "/usr/local/lib/python3.10/site-packages/click/core.py", line 1485, in __call__
    return self.main(*args, **kwargs)
  File "/usr/local/lib/python3.10/site-packages/click/core.py", line 1406, in main
    rv = self.invoke(ctx)
  File "/usr/local/lib/python3.10/site-packages/click/core.py", line 1873, in invoke
    return _process_result(sub_ctx.command.invoke(sub_ctx))
  File "/usr/local/lib/python3.10/site-packages/click/core.py", line 1269, in invoke
    return ctx.invoke(self.callback, **ctx.params)
  File "/usr/local/lib/python3.10/site-packages/click/core.py", line 824, in invoke
    return callback(*args, **kwargs)
  File "/usr/local/lib/python3.10/site-packages/click/decorators.py", line 34, in new_func
    return f(get_current_context(), *args, **kwargs)
  File "/usr/local/lib/python3.10/site-packages/mlflow/cli/__init__.py", line 1237, in gc
    _gc_tracking_resources(
  File "/usr/local/lib/python3.10/site-packages/mlflow/cli/__init__.py", line 913, in _gc_tracking_resources
    backend_store._hard_delete_experiment(experiment_id)
  File "/usr/local/lib/python3.10/site-packages/mlflow/store/tracking/sqlalchemy_store.py", line 721, in _hard_delete_experiment
    with self.ManagedSessionMaker() as session:
  File "/usr/local/lib/python3.10/contextlib.py", line 142, in __exit__
    next(self.gen)
  File "/usr/local/lib/python3.10/site-packages/mlflow/store/db/utils.py", line 201, in make_managed_session
    raise MlflowException(message=e, error_code=BAD_REQUEST) from e
mlflow.exceptions.MlflowException: (sqlite3.IntegrityError) FOREIGN KEY constraint failed
[SQL: DELETE FROM experiments WHERE experiments.experiment_id = ?]
[parameters: (28,)]
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
