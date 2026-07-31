# Strat-creator SME/refine-loop integration test

This standalone Markov demo exercises the dashboard metrics work on
`jctanner-opendatahub-io/strat-creator@feature/dashboard-sme-and-loop-metrics`.

It resets Jira and shared pipeline services, creates a seeded/refined RFE with
the expected RFE Creator labels, and runs strategy-create, strategy-refine, and
strategy-review. The `main` workflow deliberately ends after the initial review
so the Jira issue and shared artifacts can be inspected.

The continuation workflow then records an authenticated Jira comment as
`sme-reviewer`, updates only the Jira description's SME section, and asks the
`strategy-refine` agent to import that Jira-authored section into its local
artifact before refining and reviewing the result. The workflow itself never
edits the strategy artifact. The Jira edit uses REST v3 and Atlassian Document
Format (ADF), matching the strategy skills so the existing description
formatting is preserved.

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
