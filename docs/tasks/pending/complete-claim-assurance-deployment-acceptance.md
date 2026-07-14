# Task: Complete Claim-Assurance Deployment Acceptance

## Goal

Close the remaining live acceptance checks for the Claimify-aligned assurance
pipeline and record enough evidence to evaluate the plan's completion criteria.

## Completed Evidence

- Unchanged extraction, verification, and explanation stages reused receipts
  and launched no agent jobs.
- A claim-skill revision invalidated verification and its dependent explanation
  without unnecessarily invalidating extraction.
- An architecture-context revision invalidated verification; the review gate
  stopped progression until an audited human override was supplied.
- Markov run `markov-run-6eb39813` completed with the override bound to the
  applicable verification runs and reran the dependent explanation stage.
- Focused project tests and Observatory tests pass, the workflow validates, and
  the Observatory frontend production build succeeds.

## Acceptance Criteria

- [ ] Import the latest `ai-first-pipeline@main` commits into `github.local` and
      sync the Markov project.
- [ ] Change one controlled source artifact and demonstrate that extraction and
      only its dependent stages are invalidated.
- [ ] Complete the regression-evaluation task and capture its terminal result.
- [ ] Decide whether the final acceptance demonstration must run the complete
      RFE-to-code pipeline twice or whether the existing claim-stage idempotency
      evidence satisfies the intended criterion.
- [ ] Update the Claimify plan with final run IDs, metrics, and limitations.
- [ ] Move this task and the regression-evaluation task to `docs/tasks/done/`
      only after their acceptance criteria are satisfied.

## Scope Constraint

Do not modify external skill repositories or their imported `github.local`
copies. Skill changes are limited to `.claude/skills/` in this repository.

## Status

Pending
