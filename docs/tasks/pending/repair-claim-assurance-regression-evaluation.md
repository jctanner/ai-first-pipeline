# Task: Repair Claim-Assurance Regression Evaluation

## Goal

Make the 54-unit claim-assurance evaluation produce meaningful, replayable
quality results and allow the Markov workflow to retain its terminal outcome.

## Context

Kubernetes job
`eval-claim-assurance-claude-opus-4-6-0714-023445` completed successfully after
approximately three and a half hours. Markov run `markov-run-a1639481` stopped
waiting at its three-hour deadline and was marked failed before the job
completed.

The completed evaluation found:

- 47 of 54 cases produced the expected `.extraction.json` file;
- all produced outputs passed the full decontextualization contract;
- both model judges received no generated artifact or annotation content and
  returned the same `3/5` score for every case; and
- the workflow did not record the terminal regression result in Observatory
  after its wait timed out.

## Acceptance Criteria

- [ ] Judge inputs include the generated staged output and matching annotation.
- [ ] The seven missing-output cases are explained and fixed in the local
      `ai-first-pipeline` skill or evaluation integration, as appropriate.
- [ ] Existing outputs are rescored when possible; extraction is rerun only if
      the missing outputs require it.
- [ ] Markov can wait for or later reconcile a long-running evaluation without
      reporting a successful Kubernetes job as a failed regression run.
- [ ] The terminal regression result and affected explanation-run provenance
      are recorded in Observatory.
- [ ] The resulting scores and report location are recorded in the Claimify
      plan.

## Scope Constraint

Do not modify external skill repositories or their imported `github.local`
copies. Skill changes are limited to `.claude/skills/` in this repository.

## Status

Pending
