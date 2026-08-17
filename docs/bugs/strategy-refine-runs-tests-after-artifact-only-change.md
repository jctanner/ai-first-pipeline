# strategy-refine runs the repository test suite after an artifact-only change

## Status: Open

## Summary

The `strategy-refine` agent runs repository unit tests and then the full test
suite after refining a strategy document, even though it made no source-code
changes and the `strategy-refine` skill does not require tests.

## Observed run

- Markov run: `markov-run-7104497e`
- Markov step: `run_strategy → strat_refine`
- Kubernetes Job: `strategy-refine-rhaistrat-1-claude-opus-4-6-0805-193115-27c8b9`
- Skill: `github.com/opendatahub-io/strat-creator@main:strategy-refine`
- Issue: `RHAISTRAT-1`
- Skill commit: `36131d1dbd80030e80eefc8707e27faab89cff39`

## Symptom

After completing the refinement and Jira update, the agent logged:

```text
Now let me run the tests to verify.
make test-unit
uv run pytest tests/ -v --tb=short
All 618 tests passed (1 skipped)
```

The unit-test command and full-suite command added roughly four minutes to the
agent job. The create and review jobs in the same run did not run tests.

## Changes made before testing

The agent converted the initial 1.1 KB strategy stub into a 14.1 KB refined
strategy artifact. It added the generated Strategy section, including:

- a TL;DR and technical approach;
- FeatureStore CR GitOps provisioning;
- cross-registry fan-out and namespace-isolation design;
- affected components, teams, requirements, dependencies, and NFRs;
- scope, acceptance criteria, estimate, risks, assumptions, and open questions.

It also:

- set `status: Refined`;
- set `refine_count: 1`;
- wrote the cached RFE comments artifact;
- pushed the Strategy section to Jira `RHAISTRAT-1`;
- added the Jira provenance label `strat-creator-auto-refined`.

The Business Need section was preserved. No Python, library, test, or other
source file was changed.

The persisted pre-push snapshot confirms the change was an artifact-only
strategy expansion:

```text
artifacts/strat-originals/RHAISTRAT-1-pre-push.md
  -> artifacts/strat-tasks/RHAISTRAT-1.md
```

## Root cause

The `strategy-refine` skill correctly treats a changed Strategy body as a
productive refinement and increments `refine_count`, but it does not instruct
the agent to run tests.

The repository `CLAUDE.md` contains broad testing guidance:

> After every code change, run the test suite ... Use `make test-unit` for
> changes to scripts or library code.

The agent appears to have generalized “change” to include the strategy
artifact and then chose to run both the unit-test target and the full pytest
suite. There is no Markov test gate, source diff check, or failure-retry path
that required these commands.

## Expected behavior

An artifact-only strategy refinement should complete after validating the
strategy artifact and required Jira updates. Repository tests should run only
when the agent changes source code, test code, or explicitly requests a code
validation check.

## Impact

- Adds unnecessary runtime and compute/model-job occupancy.
- Makes strategy-pipeline duration depend on the entire `strat-creator` test
  suite.
- Can create misleading observability: a successful test run may appear to
  validate the generated strategy content, although the tests exercise the
  repository implementation rather than the strategy artifact.

## Proposed fix

Clarify the repository and/or skill instructions so that test execution is
conditional on source-code changes:

1. State explicitly that edits under `artifacts/`, Jira updates, frontmatter
   changes, and documentation-only changes do not require `make test-unit` or
   `make test`.
2. Tell the agent not to run repository tests as a post-refinement step unless
   it modified source or test files.
3. If a deterministic safeguard is desired, have the runner detect changed
   source/test paths before offering or invoking test commands.

The `refine_count` update and strategy-artifact validation should remain; they
are the appropriate checks for this workflow.

## Evidence commands

```bash
kubectl -n ai-pipeline logs \
  job/strategy-refine-rhaistrat-1-claude-opus-4-6-0805-193115-27c8b9 \
  --all-containers=true

kubectl -n ai-pipeline logs job/markov-run-7104497e --all-containers=true
```

