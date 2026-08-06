# Strat-creator contradiction-reconciliation reproduction

This standalone Markov demo reproduces the contradiction described by
RHAIFIRST-372 against the upstream `opendatahub-io/strat-creator@main` skills.

It deliberately gives the strategy pipeline two incompatible inputs:

- the immutable RFE Business Need says GitOps provisioning uses a
  `DataRegistry CR`;
- the removed implementation context says to use the existing `FeatureStore CR`
  and introduce no `DataRegistry` CRD.

The demo runs the real `strategy-create` → `strategy-refine` →
`strategy-review` path, then asserts that both claims are present in the
resulting strategy while the review contains only the existing four review
sections. That is the baseline failure: upstream `main` has no dedicated
consistency-reconciliation reviewer.

This is intentionally a new demo. It does not modify or depend on
`var/demos/strat-dashboard-sme-loop-test/`.

## Run

From the repository root, with the integrated Markov services available:

```bash
bash var/demos/strat-contradiction-reconciliation-test/run.sh
```

The run leaves the generated RFE, strategy, and review artifacts available in
the shared pipeline artifact volume for inspection.

After the consistency-review branch is pushed, run its fixed-mode workflow:

```bash
bash var/demos/strat-contradiction-reconciliation-test/run.sh fixed
```

The `main` workflow remains the upstream baseline. The `fixed` workflow uses
`jctanner-opendatahub-io/strat-creator@bugfix-review-consistency` and expects a
dedicated consistency section in the review.

## Expected baseline result

The workflow succeeds while reporting that the contradiction was reproduced:

- the Business Need contains `DataRegistry CR`;
- the generated Strategy section contains `FeatureStore CR`;
- the review has feasibility, testability, scope, and architecture sections;
- the review has no `## Consistency Review` section.

The final condition is expected for upstream `main`; it becomes the regression
assertion when the new reviewer is implemented.

Fixed-mode additionally expects the review to contain `## Consistency Review`,
classify the case as `contradictions-found`, and name the conflicting
`DataRegistry CR`/`FeatureStore CR` claims with a required resolution and an
explicit open question for SME/PM resolution. The existing numeric score and
verdict behavior remain unchanged, but a high-severity contradiction applies
the `strat-creator-consistency-needs-attention` and
`strat-creator-needs-attention` labels instead of `strat-creator-rubric-pass`.

To test the resolution loop, run:

```bash
bash var/demos/strat-contradiction-reconciliation-test/run.sh resolved
```

Resolved mode records an explicit SME decision that `DataRegistry CR` is the
business-level alias for `FeatureStore CR` before refinement. The review must
produce a consistency result (`clear`, or a low-severity documented finding),
and the SME decision must permit signoff: the workflow expects
`strat-creator-rubric-pass` and omits both needs-attention labels.
