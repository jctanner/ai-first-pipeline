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

## Expected baseline result

The workflow succeeds while reporting that the contradiction was reproduced:

- the Business Need contains `DataRegistry CR`;
- the generated Strategy section contains `FeatureStore CR`;
- the review has feasibility, testability, scope, and architecture sections;
- the review has no `## Consistency Review` section.

The final condition is expected for upstream `main`; it becomes the regression
assertion when the new reviewer is implemented.
