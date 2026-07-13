# Task: Add API Body Dump Observability Flag

## Goal

Add `api_dump` as a fourth observability toggle (alongside strace, mlflow,
otel) that flows from the dashboard frontend through the backend to the K8s
job container, setting `ANTHROPIC_LOG` so Claude Code dumps raw API
request/response bodies to the artifacts volume.

## Context

See `docs/decisions/ADR-0001-api-body-dump-observability-flag.md`.

The existing three flags follow an identical pattern across six touchpoints.
This task replicates that pattern for the new flag.

## Acceptance Criteria

- [ ] Dashboard skill-job form has a default-checked "API dump" checkbox
- [ ] Dashboard eval-job form has a default-checked "API dump" checkbox
- [ ] Job detail modal shows API dump enabled/disabled status
- [ ] `/api/jobs/submit` accepts `api_dump` boolean in POST body
- [ ] `/api/evals/submit` accepts `api_dump` boolean in POST body
- [ ] K8s Job gets label `api_dump=true|false`
- [ ] When enabled, container gets `ANTHROPIC_LOG=/app/artifacts/apibodies/<job-name>`
- [ ] Job list API returns `api_dump` status for each job
- [ ] `agent_job` step type defaults `api_dump: true`
- [ ] `run-skill` workflow passes `api_dump` through
- [ ] Re-run button preserves api_dump state

## Files Likely Involved

- `src/dashboard/static/js/jobs.js` — skill-job submission form + modal
- `src/dashboard/static/js/evals.js` — eval-job submission form + modal
- `src/dashboard/templates/tab_jobs.html` — checkbox markup
- `src/dashboard/templates/tab_evals.html` — checkbox markup
- `src/dashboard/webapp.py` — job submit endpoint, job list serialization
- `src/dashboard/k8s_orchestrator.py` — env var injection, label, volume
- `var/demos/end-to-end/step_types/agent_job.yaml` — default params
- `var/demos/end-to-end/workflows/run-skill.yaml` — pass-through

## Notes

Follow the exact pattern used by `strace`:
- Frontend: default-checked checkbox with `id="enable-api-dump"` (jobs) / `id="eval-api-dump"` (evals)
- JS: `if (document.getElementById('enable-api-dump').checked) args.api_dump = true;`
- Backend: `if args.get("api_dump"): env_vars.append(...)` with `ANTHROPIC_LOG` value
- Label: `"api_dump": "true" if args.get("api_dump") else "false"`
- The env var value is a directory path, not a boolean: `/app/artifacts/apibodies/<job-name>`
