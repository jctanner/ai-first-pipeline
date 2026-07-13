# End-to-End Demo — Markov Workflow

Markov directory workflow for the full planning-to-implementation demo:

```text
RFE → Strategy → Epic decomposition → Investigation → Code generation
```

The default `main` workflow resets the local demo environment, imports the
required repositories, seeds a demo RFE, and runs the complete pipeline. The
reset is destructive: existing data in the local Jira and GitHub emulators,
Observatory runtime data, MLflow data, and the pipeline artifact/context
volumes is removed.

## Prerequisites

- Markov and markovd deployed in the `ai-pipeline` namespace
- The `ai-first-pipeline` project synced and this directory workflow imported
  into markovd
- Jira, GitHub, Observatory, pipeline dashboard, and MLflow services running
- `pipeline-artifacts` mounted at `/app/artifacts`
- `pipeline-context` mounted at `/app/.context`
- `gcp-credentials` mounted at `/home/pipelineagent/.config/gcloud`
- Pipeline secrets and model credentials configured for agent jobs
- Permission for markovd to create and watch Kubernetes Jobs in `ai-pipeline`
- Network access to the upstream GitHub repositories listed in `vars.yaml`

See [`markovd-cli.md`](markovd-cli.md) for project setup, configuration,
result inspection, logs, and troubleshooting.

## Quick Start

Run these commands from the repository root. The repo-local CLI reads the
project's `.markovd-cli-config.toml` automatically.

```bash
CLI=deploy/repos/markovd/bin/markovd-cli

# Make the latest project files available to markovd.
$CLI projects sync ai-first-pipeline --wait

# Required once, or whenever the directory definition has not been imported.
$CLI projects import ai-first-pipeline var/demos/end-to-end --kind directory

# Destructive reset, seed RHAIRFE-1, and run the complete pipeline.
$CLI runs create var-demos-end-to-end \
  --workflow main \
  --var seed_rfe=true \
  --var run_pipeline=true \
  --wait
```

If the CLI config does not define the required mounts, add:

```bash
  --volume pipeline-artifacts:/app/artifacts \
  --volume pipeline-context:/app/.context \
  --secret-volume gcp-credentials:/home/pipelineagent/.config/gcloud
```

## Common Runs

Reset the environment without seeding an RFE or running the pipeline:

```bash
$CLI runs create var-demos-end-to-end \
  --workflow main \
  --var seed_rfe=false \
  --var run_pipeline=false \
  --wait
```

Run individual phases against existing Jira issues:

```bash
# RFE speedrun, submit, rubric gate, and strategy label
$CLI runs create var-demos-end-to-end \
  --workflow run-rfe \
  --var rfe_issue=RHAIRFE-1 \
  --wait

# Strategy create, refine, and review
$CLI runs create var-demos-end-to-end \
  --workflow run-strat \
  --var rfe_issue=RHAIRFE-1 \
  --wait

# Epic decomposition, investigation, and code generation
$CLI runs create var-demos-end-to-end \
  --workflow run-epic \
  --var strat_issue=RHAISTRAT-1 \
  --wait

# Extract, verify, and explain claims for the RFE and all descendants
$CLI runs create var-demos-end-to-end \
  --workflow run-claims \
  --var rfe_issue=RHAIRFE-1 \
  --wait

# Ignore extraction receipts and rebuild claims for every issue
$CLI runs create var-demos-end-to-end \
  --workflow run-claims \
  --var rfe_issue=RHAIRFE-1 \
  --var force_claims=true \
  --wait
```

The local Markov CLI and Make targets remain available:

```bash
markov run var/demos/end-to-end/
markov run var/demos/end-to-end/ --var run_pipeline=false

make demo-reset
make vagrant-demo-reset
```

Despite their names, the Make targets use the defaults and therefore perform
both the destructive reset and the full pipeline run.

## Workflow

```text
main
├── reset-jira
│   ├── reset the Jira emulator
│   ├── ensure RHOAIENG, RHAIRFE, RHAISTRAT, RHAI, and RHAIFIRST
│   └── seed RHAI components used by epic creation
├── reset-github
│   ├── bootstrap an API token and ensure the target organization
│   ├── recreate the local-only skills and eval-datasets repositories
│   └── delete and import every configured upstream repository
├── reset-services
│   ├── wipe and reseed Observatory runtime data
│   ├── hard-clear MLflow
│   └── clear the artifact and context volumes
├── seed-rfe                         when seed_rfe=true
└── run-pipeline                     when run_pipeline=true
    ├── run-rfe
    │   ├── rfe.speedrun
    │   ├── rfe.submit
    │   ├── require the rubric-pass label
    │   └── add strat-creator-3.6
    ├── run-strat
    │   ├── strategy-create
    │   ├── discover the linked RHAISTRAT issue
    │   ├── strategy-refine
    │   └── strategy-review
    └── run-epic
        ├── epic-decompose and submit generated epics to Jira
        ├── run epic-investigate for Investigation epics
        └── run epic-codegen for Implementation epics
```

Each skill is submitted through the pipeline dashboard. Markov then watches
the resulting Kubernetes Job until it completes or fails and captures its pod
logs. Skill jobs enable strace, MLflow, and OpenTelemetry by default and
currently use the Claude Code CLI harness with the resolved
`claude-opus-4-6` model identity.

### Claim assurance, gates, and receipts

`run-claims` segments artifacts, records selection and ambiguity decisions,
evaluates source entailment and coverage, then gates factual verification.
Unresolved ambiguity, omitted verifiable content, or failed entailment routes
the run to review. Verification separately pauses on missing structured output,
high-severity contradictions, and cross-verifier disagreement. An explicit
override requires an actor and rationale and is written to Observatory.

Extraction, verification, and explanation each write schema-v2 receipts under
their artifact directory's `.receipts/`. Receipts include the stage-specific
Git tree identity, its containing repository commit, model, harness,
configuration, source/evidence digests, outputs, and Observatory run IDs. Jobs
execute a
commit-pinned FQN, while reuse compares the stage tree; changing only the
verifier therefore preserves extraction and invalidates verification plus
explanation. Changing a source invalidates extraction and its descendants,
changing architecture evidence invalidates verification and explanation, and
changing only the explainer invalidates explanation. Receipt hits are also sent to
Observatory so the UI can report avoided agent jobs. `force_claims=true`
bypasses all three stages.

Reset publishes the 54-case executable corpus to the emulator's
`eval-datasets` repository. Set `run_claim_regression=true` after a skill or
context change to submit `claim-assurance/eval.yaml` through the dashboard's
agent-eval-harness API. Use `claim_assurance_enforce=false` for shadow rollout.

## Variables

Defaults are defined in `vars.yaml`. The most useful run overrides are:

| Variable | Default | Description |
|----------|---------|-------------|
| `seed_rfe` | `true` | Create the demo RFE after reset |
| `run_pipeline` | `true` | Run the complete RFE-to-code pipeline |
| `rfe_issue` | `RHAIRFE-1` | RFE processed by the pipeline |
| `claims_skill_repo` | `github.local/jctanner/ai-first-pipeline@main` | Logical source FQN containing the three claims skills; execution pins its resolved commit |
| `force_claims` | `false` | Ignore extraction receipts and rerun every issue |
| `claim_assurance_enforce` | `true` | Enforce quality gates; set false for shadow mode |
| `run_claim_regression` | `false` | Submit the claim-assurance regression corpus after explanation |
| `claim_human_override` | `false` | Permit progression after an audited verification override |
| `org` | `opendatahub-io` | Organization in the GitHub emulator |
| `fork_owner` | `opendatahub-io` | Fork owner supplied to code generation |
| `codegen_target_repo` | `odh-cli` | Repository targeted by generated code |
| `github_base` | in-cluster URL | GitHub emulator base URL |
| `jira_base` | in-cluster URL | Jira emulator base URL |
| `jira_user` | `admin` | Jira API username |
| `jira_token` | `admin` | Jira API password/token |
| `observatory_base` | in-cluster URL | Observatory base URL |
| `dashboard_base` | in-cluster URL | Pipeline dashboard base URL |
| `github_api_token` | `ghp_admin_default_token` | Initial emulator token; reset replaces it at runtime |
| `repos` | 8 entries | Upstream repositories recreated during reset |
| `jira_projects` | 5 entries | Jira projects ensured during reset |
| `rhai_components` | component list | RHAI components seeded for epic creation |

The reset also recreates the local-only `skills` and `eval-datasets`
repositories and imports `jctanner/ai-first-pipeline`, the source addressed by
the default claim-skill FQN. These are not entries in `repos` because they use
different ownership or seeding behavior.

## Layout

- `meta.yaml` selects `main` as the default entrypoint and `ai-pipeline` as the
  Kubernetes namespace.
- `vars.yaml` contains service defaults, Jira seed data, and the repository
  import manifest.
- `workflows/main.yaml` coordinates reset, seed, and pipeline execution.
- `workflows/run-rfe.yaml`, `run-strat.yaml`, and `run-epic.yaml` are the main
  independently runnable phases.
- `workflows/run-epic-*.yaml` implement decomposition, investigation, and code
  generation.
- `workflows/run-claims.yaml` discovers the RFE issue tree and coordinates
  extraction, verification, and explanation.
- `workflows/run-claim-extraction.yaml` checks and writes per-issue extraction
  receipts around the agent job.
- `workflows/run-skill.yaml` submits agent jobs and waits for their Kubernetes
  Jobs.
- `workflows/reset-*.yaml` and `seed-*.yaml` prepare the demo environment.
- `step_types/` defines Jira, GitHub, Observatory, dashboard, agent submission,
  and Kubernetes job-wait adapters.
- `rules.yaml` defines extraction, verification, shadow-mode, and override gates.
