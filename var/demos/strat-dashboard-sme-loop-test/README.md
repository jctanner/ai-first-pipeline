# Strat-creator SME/refine-loop integration test

This standalone Markov demo exercises the dashboard metrics work on
`jctanner-opendatahub-io/strat-creator@feature/dashboard-sme-and-loop-metrics`.

It resets Jira and shared pipeline services, creates a seeded/refined RFE with
the expected RFE Creator labels, and creates/refines a strategy directly. The
`main` workflow deliberately ends after the initial refine so the Jira issue and
shared artifact can be inspected.

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
scripts/run_strat_dashboard_sme_loop_test.sh
```

Inspect the resulting `RHAISTRAT` issue and artifact. Then continue the same
environment using the discovered strategy key:

```bash
scripts/run_strat_dashboard_sme_loop_test.sh continue-sme-loop \
  --var strat_issue=RHAISTRAT-1
```

The runner must have access to the configured pipeline volumes, Jira,
dashboard, Observatory, MLflow, and external GitHub skill repositories.
