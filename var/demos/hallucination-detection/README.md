# Hallucination Detection Test

End-to-end test that generates a strategy from a seeded RFE, then runs the
Observatory claim-assurance pipeline to detect hallucinated or unsupported
claims in the strategy output.

## What It Does

```text
reset environment
       |
       v
  seed RFE (RHAIRFE-3001)
       |
       v
  strategy-create  ──> discovers RHAISTRAT-*
       |
       v
  strategy-refine
       |
       v
  strategy-review
       |
       v
  extract-claims   ──> atomic factual claims from strategy
       |
       v
  verify-claims    ──> checks claims against evidence
       |
       v
  explain-claims   ──> routes findings to improvement targets
```

## Workflow DAG

```text
main
 |-- reset-environment
 |    |-- reset-services (clear volumes)
 |    |-- reset-jira
 |    +-- populate-context (clone architecture-context)
 |-- seed-rfe
 |-- run-strategy
 |    |-- run-skill (strategy-create)
 |    |-- discover_strategy
 |    |-- run-skill (strategy-refine)
 |    +-- run-skill (strategy-review)
 +-- run-claims
      |-- run-skill (extract-claims)
      |-- run-skill (verify-claims)
      +-- run-skill (explain-claims)
```

## Skill Sources

| Skill | FQN |
|-------|-----|
| strategy-create | `github.com/opendatahub-io/strat-creator@main:strategy-create` |
| strategy-refine | `github.com/opendatahub-io/strat-creator@main:strategy-refine` |
| strategy-review | `github.com/opendatahub-io/strat-creator@main:strategy-review` |
| extract-claims | `github.com/opendatahub-io/observatory@main:extract-claims` |
| verify-claims | `github.com/opendatahub-io/observatory@main:verify-claims` |
| explain-claims | `github.com/opendatahub-io/observatory@main:explain-claims` |

## Running

```bash
deploy/repos/markovd/bin/markovd-cli projects sync hallucination-detection --wait
```

## Rules

The demo ships with a single shadow rule that reports all claim findings
without blocking. To enforce quality gates, replace `rules.yaml` with the
full extraction/verification/explanation gate set from
`var/demos/end-to-end/rules.yaml`.

## RFE Fixture

The test seeds `RHAIRFE-3001` from the MCP Catalog Admin UI RFE fixture at
`files/RHAIRFE-2259.json` (a captured Jira export). The fixture is loaded from
the project directory and imported with the `strat-creator-3.6` label so
strategy skills pick it up.
