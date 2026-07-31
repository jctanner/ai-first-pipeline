# Strat-creator SME/refine-loop integration test

This standalone Markov demo exercises the dashboard metrics work on
`jctanner-opendatahub-io/strat-creator@feature/dashboard-sme-and-loop-metrics`.

It resets Jira and shared pipeline services, creates a test RFE, runs the RFE
speedrun, and creates/refines a strategy. The `main` workflow deliberately ends
after the initial refine so the Jira issue and shared artifact can be inspected.

The continuation workflow then records an authenticated Jira comment as
`sme-reviewer`, populates the shared strategy artifact's SME section, re-runs
refine, and reviews the result.

The workflow asserts that:

- the initial productive refine writes `refine_count: 1`;
- the SME-driven productive refine writes `refine_count: 2`;
- the SME section survives refinement; and
- the Business Need section remains unchanged.

Run it from the repository root:

```bash
CLI=deploy/repos/markovd/bin/markovd-cli
$CLI projects sync ai-first-pipeline --wait
$CLI projects import ai-first-pipeline var/demos/strat-dashboard-sme-loop-test --kind directory
$CLI runs create var-demos-strat-dashboard-sme-loop-test \
  --workflow main \
  --wait
```

Inspect the resulting `RHAISTRAT` issue and artifact. Then continue the same
environment using the discovered strategy key:

```bash
$CLI runs create var-demos-strat-dashboard-sme-loop-test \
  --workflow continue-sme-loop \
  --var strat_issue=RHAISTRAT-1 \
  --wait
```

The runner must have access to the configured pipeline volumes, Jira,
dashboard, Observatory, MLflow, and external GitHub skill repositories.
