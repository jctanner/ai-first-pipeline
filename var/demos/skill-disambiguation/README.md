# Skill Disambiguation Experiment

Tests how the Claude runtime resolves skill name collisions when two plugins
expose identically named skills.

## Setup

Two plugins — `metric-converter` and `imperial-converter` — each contain a
skill called `unit-convert`. The skills are functionally identical except for
their default behavior on ambiguous inputs:

- **metric-converter**: assumes ambiguous input is imperial, converts to metric
- **imperial-converter**: assumes ambiguous input is metric, converts to imperial

Both plugins are listed in `experiment-registry`, a custom plugin marketplace
hosted on github.local.

## What it tests

| Category | Invocation | Expected behavior |
|----------|-----------|-------------------|
| Unambiguous | `/unit-convert Convert 5 miles to km` | Both plugins give identical answers |
| Ambiguous (unqualified) | `/unit-convert Convert 100 degrees` | **Answer depends on which plugin runs** — this is the target measurement |
| Qualified (metric) | `/metric-converter:unit-convert ...` | Must always route to metric plugin |
| Qualified (imperial) | `/imperial-converter:unit-convert ...` | Must always route to imperial plugin |

Each prompt is repeated N times (`trials_per_prompt`, default 10) to measure
consistency.

## Prerequisites

- K3s cluster with github-emulator, pipeline dashboard, MLflow, and pipeline
  agent deployed (`make host-deploy-all`)
- Dashboard and agent images rebuilt with multi-plugin support (the
  `--registry`, `--plugin`, `--prompt` runner args)

## Running

```bash
# Full experiment with defaults (10 trials per prompt, sonnet model)
markovd-cli run var/demos/skill-disambiguation/

# Fewer trials for a quick smoke test
markovd-cli run var/demos/skill-disambiguation/ --var trials_per_prompt=3

# Different model
markovd-cli run var/demos/skill-disambiguation/ --var model=claude-opus-4-6
```

## Observability

Every trial captures:
- **strace** — system call trace of the Claude CLI process
- **OTel** — OpenTelemetry spans for skill invocation
- **API body dumps** — full request/response to the Claude API
- **MLflow** — agent trace with tool calls and reasoning

The API body dumps and MLflow traces are the primary analysis targets. They
show which skill the model selected, the tool-call sequence, and the model's
reasoning.

## Analysis

After the battery completes, query MLflow for all experiment runs and parse
the API body dumps to extract:
- Which plugin was invoked per trial (from tool-call trace)
- The model's reasoning for the choice
- The answer produced and whether it's correct
- Selection frequency, consistency, and correctness rates per category

## Plan

See `docs/plans/skill-disambiguation-experiment-plan.md` for the full design.
