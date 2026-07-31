# Strat-creator SME/refine-loop integration test

https://redhat.atlassian.net/browse/RHAIFIRST-390

This standalone Markov demo exercises the dashboard metrics work on
`jctanner-opendatahub-io/strat-creator@feature/dashboard-sme-and-loop-metrics`.

It resets Jira and shared pipeline services, creates a seeded/refined RFE with
the expected RFE Creator labels, and runs the complete strategy-create,
strategy-refine, strategy-review, SME-edit, strategy-refine, strategy-review
loop in one invocation, with two successive SME edits and final
`refine_count: 3`.

The reusable continuation workflow records an authenticated Jira comment as
`sme-reviewer`, updates only the Jira description's SME section, and asks the
`strategy-refine` agent to import that Jira-authored section into its local
artifact before refining and reviewing the result. The workflow itself never
edits the strategy artifact. The Jira edit uses REST v3 and Atlassian Document
Format (ADF), matching the strategy skills so the existing description
formatting is preserved.

The workflow asserts that:

- the initial productive refine writes `refine_count: 1`;
- the first SME-driven productive refine writes `refine_count: 2`;
- the second SME-driven productive refine writes `refine_count: 3`;
- the SME section survives refinement; and
- the Business Need section remains unchanged.

Run it from the repository root:

```bash
CLI=deploy/repos/markovd/bin/markovd-cli
scripts/run_strat_dashboard_sme_loop_test.sh
```

The default run leaves the final `RHAISTRAT` issue and artifact ready for
inspection. To rerun only the continuation against an already-created strategy:

```bash
scripts/run_strat_dashboard_sme_loop_test.sh continue-sme-loop \
  --var strat_issue=RHAISTRAT-1
```

The runner must have access to the configured pipeline volumes, Jira,
dashboard, Observatory, MLflow, and external GitHub skill repositories.
