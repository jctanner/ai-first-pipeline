# Vertex AI Claude Runtime Wiring

## Summary

This project runs Claude models through Google Vertex AI rather than directly through Anthropic API keys. The same core credentials are used by both direct pipeline agent jobs and Markov/markovd-launched workflow jobs:

- `pipeline-secrets` provides Vertex control env vars.
- `gcp-credentials` provides Google ADC JSON credentials.
- agent entrypoint scripts translate those values into the provider-specific settings expected by Claude Code, OpenCode, or agentic-ci.

The normal Claude model IDs in the Jobs UI are Vertex provider IDs such as:

```text
google-vertex-anthropic/claude-haiku-4-5@20251001
google-vertex-anthropic/claude-sonnet-4-6@default
google-vertex-anthropic/claude-opus-4-6@default
```

## Kubernetes Secrets

`deploy/scripts/06-create-secrets.sh` creates the main `pipeline-secrets` secret from `.env`:

| Secret key | Runtime env var | Purpose |
|------------|-----------------|---------|
| `CLAUDE_CODE_USE_VERTEX` | `CLAUDE_CODE_USE_VERTEX` | Enables Claude Code's Vertex provider path. Defaults to `1`. |
| `CLOUD_ML_REGION` | `CLOUD_ML_REGION` | Vertex region. Defaults to `us-east5`. |
| `ANTHROPIC_VERTEX_PROJECT_ID` | `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project used for Anthropic-on-Vertex calls. |

The same script can create `gcp-credentials` when `GOOGLE_APPLICATION_CREDENTIALS` points at a local credentials file. `deploy/scripts/11-create-gcp-credentials-secret.sh` is the explicit helper for creating that secret from Google ADC credentials.

The credential secret is mounted into agent jobs at:

```text
/home/pipelineagent/.config/gcloud/credentials.json
```

The runtime env var is:

```text
GOOGLE_APPLICATION_CREDENTIALS=/home/pipelineagent/.config/gcloud/credentials.json
```

## Agent Image

`deploy/pipeline-agent/Dockerfile` builds the `pipeline-agent:latest` image. It contains:

- Claude Code CLI from `npm install -g @anthropic-ai/claude-code`
- OpenCode binary built from local source under `deploy/repos/opencode`
- Python dependencies from `pyproject.toml` and `uv.lock`
- the project scripts under `/app/scripts`
- local skills and skill registry data under `/app/.claude` and `/app/var`
- agentic-ci installed from local source under `deploy/repos/agentic-ci`

The image does not bake in Vertex credentials. Credentials are injected at pod runtime through Kubernetes secrets.

## Direct Dashboard Jobs

The dashboard creates Kubernetes Jobs in `src/dashboard/k8s_orchestrator.py`.

For every agent container, `_build_env_vars()` injects:

```text
CLAUDE_CODE_USE_VERTEX      from pipeline-secrets
CLOUD_ML_REGION            from pipeline-secrets
ANTHROPIC_VERTEX_PROJECT_ID from pipeline-secrets
GOOGLE_APPLICATION_CREDENTIALS=/home/pipelineagent/.config/gcloud/credentials.json
```

The job volume mounts include the `gcp-credentials` secret at `/home/pipelineagent/.config/gcloud`, so Google client libraries and CLIs can find the ADC JSON file.

The orchestrator selects one of the entrypoint scripts based on `harness` and `runner`:

| Harness | Runner | Script |
|---------|--------|--------|
| `claude-code` | `cli` | `/app/scripts/run_skill.sh` |
| `claude-code` | `sdk` | `/app/scripts/run_skill_sdk.sh` |
| `opencode` | `cli` | `/app/scripts/run_skill_opencode.sh` |
| `opencode` | `sdk` | `/app/scripts/run_skill_opencode_sdk.sh` |
| `claude-code` / `opencode` | `agentic-ci` | `/app/scripts/run_skill_agentic_ci.sh` |

## Claude Code CLI Path

`scripts/run_skill.sh` configures Claude Code for Vertex before launching the CLI.

It writes or updates:

```text
~/.claude/settings.json
```

with:

```json
{
  "apiProvider": "vertex",
  "vertexProjectId": "$ANTHROPIC_VERTEX_PROJECT_ID",
  "vertexRegion": "$CLOUD_ML_REGION"
}
```

Then it runs:

```bash
claude --model "$MODEL" --print --dangerously-skip-permissions ...
```

Claude Code uses the Vertex provider settings plus `GOOGLE_APPLICATION_CREDENTIALS` to authenticate to Vertex AI.

## Claude SDK Path

`scripts/run_skill_sdk.sh` uses `claude-agent-sdk` from Python. The SDK path inherits the same environment from the Kubernetes Job:

```text
CLAUDE_CODE_USE_VERTEX
CLOUD_ML_REGION
ANTHROPIC_VERTEX_PROJECT_ID
GOOGLE_APPLICATION_CREDENTIALS
```

The SDK client is created inside the script's embedded Python driver. It relies on the same provider environment used by Claude Code rather than a separate Anthropic API key.

## OpenCode Paths

OpenCode uses Google/Vertex env vars directly. Both `scripts/run_skill_opencode.sh` and `scripts/run_skill_opencode_sdk.sh` export:

```bash
export GOOGLE_CLOUD_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_LOCATION="${CLOUD_ML_REGION:-us-east5}"
```

They also inherit:

```text
GOOGLE_APPLICATION_CREDENTIALS=/home/pipelineagent/.config/gcloud/credentials.json
```

The OpenCode model string includes the provider prefix, for example:

```text
google-vertex-anthropic/claude-opus-4-6@default
```

The CLI runner invokes `opencode run`. The SDK runner starts `opencode serve` and drives it through the OpenCode HTTP API.

## agentic-ci Path

`scripts/run_skill_agentic_ci.sh` runs `agentic-ci run --backend local` inside the existing pipeline agent pod. It supports both Claude Code and OpenCode harnesses through `AGENTIC_CI_HARNESS`.

Before invoking agentic-ci, the wrapper exports the same OpenCode-compatible Vertex vars:

```bash
export GOOGLE_CLOUD_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_PROJECT="${ANTHROPIC_VERTEX_PROJECT_ID:-}"
export GOOGLE_VERTEX_LOCATION="${CLOUD_ML_REGION:-us-east5}"
```

For OpenCode, it also enables native OpenTelemetry in `opencode.json` and removes the `@mlflow/opencode` plugin so agentic-ci owns trace capture and MLflow push. This is separate from Vertex auth, but it matters because this runner is intended to test OpenCode CLI with native OTel rather than the plugin path.

## Markov and markovd

There are two layers:

1. `markovd` is the workflow service and UI.
2. `markov` is the workflow runner that executes workflow YAML and creates child Kubernetes Jobs.

`deploy/k8s/15-markovd.yaml` deploys markovd with:

```text
MARKOVD_RUNNER=kubernetes
MARKOVD_MARKOV_IMAGE=markov:latest
MARKOVD_JOB_SECRETS=pipeline-secrets
```

In Kubernetes-runner mode, markovd creates a `markov:latest` Job. The markovd runner adds `pipeline-secrets` as `envFrom`, so the markov pod receives the same Vertex variables.

The workflow YAML files under `var/markov-workflows/` define an `agent_job` step type that extends Markov's `k8s_job` executor. That step type launches `pipeline-agent:latest` child Jobs with:

```yaml
env:
  GOOGLE_APPLICATION_CREDENTIALS: /home/pipelineagent/.config/gcloud/credentials.json
secrets:
  - pipeline-secrets
volumes:
  - name: gcp-credentials
    mount: /home/pipelineagent/.config/gcloud
    secret: gcp-credentials
    read_only: true
```

Markov's `k8s_job` executor turns `secrets: [pipeline-secrets]` into Kubernetes `envFrom.secretRef` entries, and turns the `gcp-credentials` volume into a mounted secret. The child `pipeline-agent` job therefore gets the same environment and ADC file as a dashboard-submitted job.

## End-to-End Flow

For direct dashboard jobs:

```text
.env
  -> pipeline-secrets + gcp-credentials
  -> dashboard-created Kubernetes Job
  -> pipeline-agent container
  -> run_skill*.sh entrypoint
  -> Claude Code / Claude SDK / OpenCode / agentic-ci
  -> Vertex AI Anthropic model endpoint
```

For Markov jobs:

```text
.env
  -> pipeline-secrets + gcp-credentials
  -> markovd deployment
  -> markov runner Job with pipeline-secrets envFrom
  -> workflow agent_job step
  -> pipeline-agent child Job with pipeline-secrets + gcp-credentials mount
  -> run_skill*.sh entrypoint
  -> Claude Code / OpenCode / agentic-ci
  -> Vertex AI Anthropic model endpoint
```

## Practical Checks

Inside a running agent pod, these should be true:

```bash
echo "$CLAUDE_CODE_USE_VERTEX"
echo "$CLOUD_ML_REGION"
echo "$ANTHROPIC_VERTEX_PROJECT_ID"
echo "$GOOGLE_APPLICATION_CREDENTIALS"
test -f "$GOOGLE_APPLICATION_CREDENTIALS"
```

For Claude CLI jobs, also check:

```bash
cat ~/.claude/settings.json
```

It should show `apiProvider: vertex`, the expected project ID, and the expected region.
