# ADR-0001: Add API Body Dump as a First-Class Observability Flag

## Status

Accepted

## Context

Pipeline agent jobs already expose three observability toggles — strace,
MLflow, and OTel — as default-on checkboxes in the dashboard frontend. Each
flows through the backend job submission API, becomes a K8s Job label and
environment variable, and is consumed by the container entrypoint.

Claude Code supports dumping raw API request/response bodies when the
`ANTHROPIC_LOG` environment variable is set to a directory path. These dumps
are valuable for forensic claim explanation (the `explain-claims` skill already
looks for them in `artifacts/apibodies/`) and for debugging model interactions.

Currently there is no way to enable or disable API body dumps from the
dashboard. The flag must be manually injected via `extra_env`, which means it
is rarely used and the explain-claims skill often finds no API body evidence.

## Decision

Add `api_dump` as a fourth observability flag alongside strace, mlflow, and
otel. It will follow the identical wiring pattern:

1. **Frontend** — default-enabled checkbox in both the skill-job and eval-job
   submission forms, and in the job detail modal.
2. **Backend API** — accepted in the `/api/jobs/submit` and `/api/evals/submit`
   POST bodies; stored as a K8s Job label.
3. **K8s orchestrator** — when enabled, sets `ANTHROPIC_LOG` to a job-specific
   subdirectory under the artifacts volume (`/app/artifacts/apibodies/<job-name>`).
4. **Markov workflow** — the `agent_job` step type includes `api_dump: true` in
   its default params, matching strace/mlflow/otel.
5. **run-skill workflow** — the run-skill sub-workflow passes the flag through.

The environment variable is `ANTHROPIC_LOG=<dir>` (not a boolean). The
orchestrator constructs the directory path; the entrypoint does not need
changes because Claude Code reads the env var directly.

## Consequences

Positive:
- API body evidence is available by default for every job.
- explain-claims skill finds evidence without manual configuration.
- Consistent UX — all observability options in one place.

Negative:
- Increased artifact volume usage (request/response JSON per API call).
- Sensitive prompt content is stored on disk (same risk as strace).
