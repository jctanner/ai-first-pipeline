# Running the End-to-End Demo with `markovd-cli`

This note shows the common terminal flow for running the end-to-end demo through
markovd: sync the project, start a run with attributes, wait for completion, and
inspect the result.

For the complete CLI reference, see
[`deploy/repos/markovd/docs/reference/markovd-cli.md`](../../../deploy/repos/markovd/docs/reference/markovd-cli.md).

## Setup

Use the repo-local CLI binary:

```bash
CLI=deploy/repos/markovd/bin/markovd-cli
```

If your local markovd uses the default demo credentials and a self-signed
certificate, either pass the global flags on each command:

```bash
$CLI --server https://markovd.local \
  --insecure-skip-tls-verify \
  --username admin \
  --password admin \
  health
```

or export the equivalent environment variables once:

```bash
export MARKOVD_URL=https://markovd.local
export MARKOVD_USERNAME=admin
export MARKOVD_PASSWORD=admin
export MARKOVD_INSECURE_SKIP_TLS_VERIFY=true
```

The examples below assume those environment variables are set.

## Sync the Project

Sync the `ai-first-pipeline` project so markovd sees the latest workflow files:

```bash
$CLI projects sync ai-first-pipeline --wait
```

`--wait` blocks until the project reaches `synced` or fails. After syncing, you
can list importable workflow definitions:

```bash
$CLI projects files ai-first-pipeline
```

If the end-to-end directory workflow has not been imported yet, import it:

```bash
$CLI projects import ai-first-pipeline var/demos/end-to-end --kind directory
```

## Start a Run with Attributes

Create a run from the imported end-to-end workflow definition. The `--workflow`
flag selects the entrypoint inside the directory workflow, and `--var` supplies
run attributes.

Full reset plus seeded RFE plus pipeline:

```bash
$CLI runs create var-demos-end-to-end \
  --workflow main \
  --var seed_rfe=true \
  --var run_pipeline=true \
  --wait
```

Run only the epic phase for an existing strategy:

```bash
$CLI runs create var-demos-end-to-end \
  --workflow run-epic \
  --var strat_issue=RHAISTRAT-1 \
  --wait
```

Run reset only, without seeding or running the pipeline:

```bash
$CLI runs create var-demos-end-to-end \
  --workflow main \
  --var seed_rfe=false \
  --var run_pipeline=false \
  --wait
```

Use explicit volume mounts when your CLI config does not define defaults:

```bash
$CLI runs create var-demos-end-to-end \
  --workflow main \
  --var seed_rfe=true \
  --var run_pipeline=true \
  --volume pipeline-artifacts:/app/artifacts \
  --volume pipeline-context:/app/.context \
  --secret-volume gcp-credentials:/home/pipelineagent/.config/gcloud \
  --wait
```

## Wait for an Existing Run

If you start a run without `--wait`, the command prints a run ID such as
`markov-run-cfb29a83`. Wait for it later with:

```bash
$CLI runs wait markov-run-cfb29a83
```

Wait exits `0` for `completed`, non-zero for `failed` or `cancelled`, and `124`
on timeout.

## Query Results

Get the final run object:

```bash
$CLI runs get markov-run-cfb29a83
```

Use JSON for scripting:

```bash
$CLI --output json runs get markov-run-cfb29a83
```

Read the run logs:

```bash
$CLI runs logs markov-run-cfb29a83
```

Follow logs while a run is active:

```bash
$CLI runs logs markov-run-cfb29a83 --follow
```

List recent runs:

```bash
$CLI runs list
```

## Troubleshooting

- Global flags must appear before the resource command. For example, use
  `$CLI --output json runs get ...`, not `$CLI runs get ... --output json`.
- If `runs create ... --wait` times out, the run may still be active. Use
  `$CLI runs get <run-id>` and `$CLI runs logs <run-id>` to inspect it.
- Keep this note focused on the end-to-end demo. Use the full reference in
  `deploy/repos/markovd/docs/reference/markovd-cli.md` for authentication,
  config files, TLS, volume syntax, and every command option.
