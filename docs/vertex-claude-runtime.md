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
| `CLOUD_ML_REGION` | `CLOUD_ML_REGION` | Vertex region. Defaults to `global`. |
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
- OpenCode binary built from local source under `checkouts/opencode`
- Python dependencies from `pyproject.toml` and `uv.lock`
- the project scripts under `/app/scripts`
- local skills and skill registry data under `/app/.claude` and `/app/var`
- agentic-ci installed from local source under `checkouts/agentic-ci`

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
export GOOGLE_VERTEX_LOCATION="${CLOUD_ML_REGION:-global}"
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
export GOOGLE_VERTEX_LOCATION="${CLOUD_ML_REGION:-global}"
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

## AnthropicVertex Model IDs

The Anthropic Python SDK's `AnthropicVertex` client expects the Agent Platform
API model ID, not the provider-prefixed model string used by OpenCode or the
dashboard UI.

Verified on 2026-07-06 with:

```text
GCP project: itpc-gcp-ai-eng-claude
Anthropic SDK: anthropic 0.116.0
```

### Sonnet

For Claude Sonnet 4.6, use:

```text
claude-sonnet-4-6
```

Do not use these forms with `AnthropicVertex.messages.create`:

```text
claude-sonnet-4-6-20250514
claude-sonnet-4-6@20250514
google-vertex-anthropic/claude-sonnet-4-6@default
```

The dated model ID that was also verified to work is:

```text
claude-sonnet-4-5@20250929
```

The current Sonnet family model listed by Anthropic docs was also verified:

```text
claude-sonnet-5
```

There is no verified Sonnet 4.7 model ID for this project. The current
Anthropic Google Cloud docs do not list a Claude Sonnet 4.7 entry, and live
checks returned 404 in both `global` and `us-east5` for:

```text
claude-sonnet-4-7
claude-sonnet-4-7@default
claude-sonnet-4-7@20260601
```

Use `claude-sonnet-4-6` or `claude-sonnet-5` instead.

`region="global"` works with the Python SDK. In `anthropic 0.116.0`, the SDK
special-cases global and constructs:

```text
https://aiplatform.googleapis.com/v1
/projects/<project>/locations/global/publishers/anthropic/models/<model>:rawPredict
```

Regional endpoints use:

```text
https://<region>-aiplatform.googleapis.com/v1
```

Multi-region endpoints use:

```text
https://aiplatform.us.rep.googleapis.com/v1
https://aiplatform.eu.rep.googleapis.com/v1
```

Minimal smoke test:

```python
from anthropic import AnthropicVertex

client = AnthropicVertex(
    project_id="itpc-gcp-ai-eng-claude",
    region="global",
)

resp = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=10,
    messages=[{"role": "user", "content": "say hi"}],
)

print(resp.content[0].text)
```

Observed successful output:

```text
Hi there! 👋 How are you
```

Live verification results:

| Region | Model | Result |
|--------|-------|--------|
| `global` | `claude-sonnet-4-6` | OK |
| `global` | `claude-sonnet-4-5@20250929` | OK |
| `global` | `claude-sonnet-5` | OK |
| `global` | `claude-sonnet-4-7` | 404 |
| `global` | `claude-sonnet-4-7@default` | 404 |
| `global` | `claude-sonnet-4-7@20260601` | 404 |
| `us-east5` | `claude-sonnet-4-6` | OK |
| `us-east5` | `claude-sonnet-4-5@20250929` | OK |
| `us-east5` | `claude-sonnet-4-7` | 404 |
| `us-east5` | `claude-sonnet-4-7@default` | 404 |
| `us-east5` | `claude-sonnet-4-7@20260601` | 404 |

### Opus

For the Opus model currently available to this project, use:

```text
claude-opus-4-6
```

The `@default` alias also works with `AnthropicVertex.messages.create` for this
project:

```text
claude-opus-4-6@default
```

Do not use the OpenCode/dashboard provider-prefixed form with
`AnthropicVertex.messages.create`:

```text
google-vertex-anthropic/claude-opus-4-6@default
```

That provider-prefixed form produced a 404 when sent through the Python SDK.

The current Anthropic docs also list newer Opus API IDs:

```text
claude-opus-4-8
claude-opus-4-7
```

Both returned 404 for this project in `global` and `us-east5` during live
verification. The error body reported that the publisher model was not found or
that the project does not have access to it. Treat those as documented upstream
IDs, not currently usable IDs for `itpc-gcp-ai-eng-claude`.

The dated Opus model ID that was also verified to work is:

```text
claude-opus-4-5@20251101
```

Minimal Opus smoke test:

```python
from anthropic import AnthropicVertex

client = AnthropicVertex(
    project_id="itpc-gcp-ai-eng-claude",
    region="global",
)

resp = client.messages.create(
    model="claude-opus-4-6",
    max_tokens=10,
    messages=[{"role": "user", "content": "say hi"}],
)

print(resp.content[0].text)
```

Observed successful output:

```text
Hi there! 👋 How are you
```

Live Opus verification results:

| Region | Model | Result |
|--------|-------|--------|
| `global` | `claude-opus-4-6` | OK |
| `global` | `claude-opus-4-6@default` | OK |
| `global` | `claude-opus-4-5@20251101` | OK |
| `global` | `claude-opus-4-8` | 404 |
| `global` | `claude-opus-4-7` | 404 |
| `us-east5` | `claude-opus-4-6` | OK |
| `us-east5` | `claude-opus-4-6@default` | OK |
| `us-east5` | `claude-opus-4-5@20251101` | OK |
| `us-east5` | `claude-opus-4-8` | 404 |
| `us-east5` | `claude-opus-4-7` | 404 |

The official Anthropic Google Cloud documentation lists `claude-sonnet-4-6` as
the Agent Platform API model ID for Claude Sonnet 4.6, lists the current Opus
Agent Platform API IDs, and shows `region = "global"` in the Python
`AnthropicVertex` example:

```text
https://platform.claude.com/docs/en/build-with-claude/claude-on-vertex-ai
```
