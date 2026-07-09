# Dashboard job modal displays extra_env as character array

## Status: Open

## Symptom

The job detail modal in the dashboard shows `extra_env` values character-by-character instead of as key=value pairs:

```
Env vars
0={ 1=" 2=E 3=P 4=I 5=C 6=_ 7=C 8=O 9=D 10=E ...
```

The actual value arriving is the JSON string `{"EPIC_CODEGEN_GITHUB_TOKEN": "ghp_admin_default_token"}`.

## Impact

Cosmetic only. The env var is correctly injected onto the K8s pod — this is purely a display bug in the dashboard UI.

## Root cause

The dashboard stores `extra_env` as a JSON string in the K8s job annotation. When the job modal renders env vars, it iterates over the value as a sequence (string characters) instead of parsing it with `json.loads()` first and displaying the resulting dict as key=value pairs.

## Where to fix

- `src/dashboard/webapp.py` — the `/api/jobs/<name>` endpoint or the job detail data loader
- `src/dashboard/templates/` — whichever template renders the "Env vars" section of the job modal
- The annotation value is set at `src/dashboard/k8s_orchestrator.py:298`: `"extra_env": json.dumps(args.get("extra_env") or {})`

The fix is to `json.loads()` the annotation string before passing it to the template, so the template iterates over dict items instead of string characters.
