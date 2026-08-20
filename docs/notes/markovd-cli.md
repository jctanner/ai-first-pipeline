# Using `markovd-cli`

This repository uses the repo-local `markovd-cli` to sync projects, import any
Markov workflow, start runs, wait for completion, and inspect results. The
commands in this note apply to all workflows in the repository; they are not
specific to the end-to-end demo.

For every command and option, see the complete
[`markovd-cli` reference](../../checkouts/markovd/docs/reference/markovd-cli.md).

## Repository Configuration

The project root contains **`.markovd-cli-config.toml`**. Run the CLI from the
project root so it discovers this file automatically:

```bash
cd /path/to/ai-first-pipeline
CLI=checkouts/markovd/bin/markovd-cli
$CLI health
```

The repository-local config is the normal way to define settings shared by
commands. It currently defines:

- the markovd server URL;
- username and password authentication;
- TLS verification behavior;
- the default project, timeout, polling interval, and output format;
- the `pipeline-artifacts` and `pipeline-context` default volumes; and
- the `gcp-credentials` default secret volume.

Consequently, normal commands should not repeat server, authentication, TLS,
timeout, or volume flags:

```bash
$CLI projects list
$CLI runs create WORKFLOW_NAME --workflow main --wait
```

The configured `server` determines which markovd installation receives the
command. In particular, check how `markovd.local` resolves in `/etc/hosts` or
DNS; it may refer to another host rather than the Vagrant VM.

The file is intentionally ignored by Git because it can contain local
credentials and environment-specific routing. Do not commit it. A typical
configuration is:

```toml
server = "https://markovd.local"
username = "admin"
password = "admin"
ssl_verify = false

[defaults]
project = "ai-first-pipeline"
timeout = "30m"
poll_interval = "2s"
output = "table"

[[defaults.volumes]]
name = "pipeline-artifacts"
mount_path = "/app/artifacts"

[[defaults.volumes]]
name = "pipeline-context"
mount_path = "/app/.context"

[[defaults.secret_volumes]]
name = "gcp-credentials"
mount_path = "/home/pipelineagent/.config/gcloud"
read_only = true
```

Configuration precedence, from highest to lowest, is:

1. CLI flags
2. Environment variables
3. An explicit `--config PATH`
4. `./.markovd-cli-config.toml`
5. `${XDG_CONFIG_HOME}/markovd/cli-config.toml`
6. `~/.config/markovd/cli-config.toml`
7. Built-in defaults

Use flags or environment variables only when intentionally overriding the
repository config. Global flags must appear before the resource command:

```bash
$CLI --server https://other-markovd.example.test \
  --insecure-skip-tls-verify \
  projects list

MARKOVD_URL=https://other-markovd.example.test $CLI projects list
```

## Validate a Workflow Locally

Before committing, validate the workflow directory with the local `markov` CLI
(not `markovd-cli`):

```bash
checkouts/markov/bin/markov validate var/demos/my-workflow
```

This catches missing required files (e.g. `rules.yaml`), YAML syntax errors, and
invalid step type references without needing a server round-trip.

## Sync a Project

Syncing pulls the latest **pushed** commit from the remote. Commits that are
only local are not visible to the server — you must `git push` before syncing:

```bash
git push
$CLI projects sync ai-first-pipeline --wait
```

`--wait` blocks until the project is synced or fails. List files known to the
synced project with:

```bash
$CLI projects files ai-first-pipeline
```

Although `[defaults].project` is recorded in the config, project commands
currently still require the explicit project name.

## Import a Workflow

Import a workflow file or directory from the synced project:

```bash
$CLI projects import ai-first-pipeline PATH/TO/WORKFLOW --kind directory
```

For example:

```bash
$CLI projects import ai-first-pipeline var/demos/end-to-end --kind directory
$CLI projects import ai-first-pipeline \
  var/demos/dashboard-strat-arch-context-test \
  --kind directory
```

Use `projects files` to confirm the available path and the import output to find
the resulting workflow name.

## Start a Run

Start an imported workflow by name and select its entrypoint:

```bash
$CLI runs create WORKFLOW_NAME \
  --workflow main \
  --wait
```

Supply workflow variables with repeatable `--var` options:

```bash
$CLI runs create WORKFLOW_NAME \
  --workflow main \
  --var issue=RHAIRFE-2259 \
  --var run_review=true \
  --wait
```

`--var` values are sent as strings. For a larger set of values, load a JSON or
YAML mapping with `--vars-file`:

```bash
$CLI runs create WORKFLOW_NAME \
  --workflow main \
  --vars-file ./run-vars.yaml \
  --wait
```

The volumes and secret volume in `.markovd-cli-config.toml` are included
automatically. Use explicit mounts only when a particular run needs an
additional mount not already configured:

```bash
$CLI runs create WORKFLOW_NAME \
  --workflow main \
  --volume another-pvc:/app/extra \
  --wait
```

Do not repeat a configured mount path: duplicate paths are rejected rather than
silently overriding config defaults.

## Wait for a Run

When a run is created without `--wait`, the command prints an ID such as
`markov-run-cfb29a83`. Wait for it later with:

```bash
$CLI runs wait markov-run-cfb29a83
```

The command exits `0` for `completed`, non-zero for `failed` or `cancelled`, and
`124` on timeout. A client timeout does not necessarily stop the server-side
run; query its status before assuming it ended.

## Inspect Runs and Logs

Get a run:

```bash
$CLI runs get markov-run-cfb29a83
```

Request structured output for scripts. `--output` is a global flag, so it must
precede `runs`:

```bash
$CLI --output json runs get markov-run-cfb29a83
```

Read or follow logs:

```bash
$CLI runs logs markov-run-cfb29a83
$CLI runs logs markov-run-cfb29a83 --follow
```

List recent runs:

```bash
$CLI runs list
```

## Troubleshooting

- Confirm the active endpoint with `.markovd-cli-config.toml` and the local
  resolution of its hostname before investigating the wrong cluster.
- Run commands from the repository root or pass
  `--config /absolute/path/to/.markovd-cli-config.toml` explicitly.
- Put global flags before resource commands: use
  `$CLI --output json runs get ...`, not
  `$CLI runs get ... --output json`.
- If `runs create --wait` or `runs wait` times out, inspect the run with
  `runs get` and `runs logs`; it may still be active.
- Explicit `--volume` and `--secret-volume` values are appended to configured
  defaults. They do not replace them.
- `auth login --save` writes the user config at
  `~/.config/markovd/cli-config.toml`; it does not update the repository's
  `.markovd-cli-config.toml`.
