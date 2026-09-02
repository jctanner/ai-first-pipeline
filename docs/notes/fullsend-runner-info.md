# Fullsend Runner and `strategy-create` Notes

**Investigated:** 2026-09-02  
**Fullsend checkout:** `checkouts.tmp/fullsend.latest`  
**Strategy checkout:** `checkouts.tmp/strat-creator`

## Execution flow

```text
configuration repository or directory              target repository
<repo>/.fullsend/                                     <repository>
  config.yaml  ── registers ──> harness YAML          source files
  harness/                         │                       │
                                  image, policy,           │
                                  skills, environment      │
                                        │                  │
                                        v                  v

fullsend run <agent-name> --fullsend-dir ... --target-repo ...

                                        │
                                        v

                         Fullsend runner CLI / runner image
                         (host-side orchestration, not sandbox)
                                        │ explicit harness image
                                        v

                              OpenShell gateway / driver
                                        │
                         uses gateway default image only
                         when no image was requested
                                        │
                                        v

                          agent sandbox running Claude/pi
                          with the target repository copied in
```

## Fullsend runner

Fullsend has a real host-side runner CLI. Its executable is `fullsend`; the
relevant command is:

```bash
fullsend run <agent-name> --fullsend-dir <configuration-dir> --target-repo <repository>
```

`<configuration-dir>` is the directory containing Fullsend's `config.yaml`.
By convention it is a repository's `.fullsend/` directory, so a typical value
is `/path/to/repo/.fullsend`, not `/path/to/repo`. It may instead be a separate
central configuration directory. It supplies the agent registry and usually
the local harness files; `--target-repo` independently identifies the
repository that the agent will operate on.

The command resolves an agent harness, provisions an OpenShell sandbox, runs
the selected agent runtime to completion, and emits run artifacts such as
`metrics.json` and transcripts. The runner owns the sandbox, credentials, and
run verdict; the runtime (`claude`, `pi`, and internal test runtimes) owns the
model/tool-use session.

`ghcr.io/fullsend-ai/fullsend-runner` packages that same CLI and its host-side
dependencies. It is not the agent sandbox image and it is not a separate
`fullsend-runner` executable.

### OpenShell requirement

`fullsend run` provisions its agent sandbox through OpenShell. Therefore the
machine running the Fullsend CLI needs working OpenShell client configuration
and connectivity to the OpenShell gateway/sandbox supervisor. This applies
whether `fullsend` runs natively or from the `fullsend-runner` container image:
the image moves the CLI and its host-side dependencies into a container, but
the OpenShell gateway and sandboxes remain on the host.

This is an added dependency of a Fullsend integration. The existing
`strat-creator` workflow can run its Claude Code skills directly and does not
need OpenShell in that mode.

### Sandbox image selection

The Fullsend harness normally selects the agent runtime image. On every run,
Fullsend resolves the harness and passes its `image:` value to OpenShell when
creating the sandbox. Thus an upstream Fullsend run commonly uses the image
named by the selected role's harness: `fullsend-sandbox` for triage,
prioritize, and retro, or `fullsend-code` for code, fix, and review.

OpenShell also has a gateway-level default sandbox image. It is used only when
the sandbox-create request does not specify an image; it does not override an
explicit Fullsend harness image. The OpenShell instance still determines
whether the requested image can run: its compute driver, sandbox namespace,
image pull policy and credentials, registry reachability, and image
compatibility must all support that image.

Breadboard's Fullsend development scenario deliberately replaces the upstream
role images in its seeded harnesses with `fullsend-sandbox-dev:k3s`. That local
image extends `pipeline-agent:latest` with the tools needed by the Fullsend
roles. Breadboard's OpenShell gateway separately declares
`docker.io/library/pipeline-agent:latest` as its fallback image, but Fullsend
runs use the explicit harness override and therefore do not use that fallback.

## Agent names and resolution

`<agent-name>` is resolved from `config.yaml` in the configuration directory
passed to `--fullsend-dir` (normally `<repo>/.fullsend/`), not inherently from
`--target-repo`. The configuration and target-repository directories may be
the same repository, but have separate roles:

- `--fullsend-dir` supplies Fullsend configuration and the agent registry.
- `--target-repo` is the repository mounted for the agent to operate on.

Custom agents are registered under `agents:`. An entry may give an explicit
`name`, or its name is derived from the local or remote harness filename:

```yaml
agents:
  - name: strategy-create
    source: harness/strategy-create.yaml
```

When a requested name is not registered, Fullsend can fetch a known
first-party harness from `fullsend-ai/agents`, provided the configuration's
`allowed_remote_resources` permits that source. The known fallback names are:

- `triage`
- `code`
- `review`
- `fix`
- `retro`
- `prioritize`

The `fullsend.latest` checkout's own `.fullsend/config.yaml` registers only a
remote `qualityflow` harness and allowlists only its source. Consequently,
with that exact configuration, `qualityflow` is the configured custom agent;
the first-party fallback cannot be fetched until the allowlist is expanded.

## What `strategy-create` actually is

`strat-creator` does **not** currently contain a Fullsend harness,
`.fullsend/` configuration, or `plugin.json`-style plugin.

It contains a Claude Code skill at:

```text
.claude/skills/strategy-create/SKILL.md
```

The skill's front matter declares `name: strategy-create` and
`user-invocable: true`, making it available to Claude Code as
`/strategy-create`. It owns the strategy-creation behavior: it reads approved
RFEs, applies its status/label gates, optionally clones Jira issues, and writes
the `artifacts/strat-tasks/` handoff consumed by the refinement and review
skills. The existing CI lifecycle runs `strategy-create`, `strategy-refine`,
and `strategy-review` as separate Claude sessions with on-disk artifacts as
their handoff.

## Meaning of a thin Fullsend harness

A Fullsend integration would need an adapter harness, but it would not turn
the skill into a Markov-like primitive or duplicate its implementation.

The harness would be a small YAML profile that starts a normal Claude Code
agent and adds only the strategy-specific configuration:

- make the pinned `strategy-create` skill directory available to the agent;
- provide an agent instruction that invokes `/strategy-create` for the desired
  RFE keys or batch;
- configure the needed sandbox policy, Jira/MCP access, and credentials;
- target the `strat-creator` checkout, because the skill expects its existing
  scripts and `artifacts/` layout.

It should inherit routine runner settings from a standard Fullsend base
harness. That is why it is *thin*: Fullsend remains the outer agent-session
runner, while `strat-creator` remains the owner of the skill, deterministic
helper scripts, and artifact contract.

Fullsend supports `skills:` resources in a harness; a remote skill source must
be pinned and covered by `allowed_remote_resources`. The exact adapter should
be designed only after verifying the intended Fullsend harness base, the skill
directory URL/commit, and the Jira credential bridge.

## Credentials and environment variables

`fullsend run --env-file <dotenv-file>` loads values into the **runner**
process before harness expansion. It does not automatically pass every value
to the agent sandbox. A harness must explicitly choose which values to export
through `env.sandbox`:

```dotenv
# strategy-create.env -- local secret file; do not commit it
JIRA_URL=https://issues.example.com
JIRA_USER=example-user
JIRA_API_TOKEN=...
```

```yaml
env:
  sandbox:
    JIRA_SERVER: "${JIRA_URL}"
    JIRA_USER: "${JIRA_USER}"
    JIRA_TOKEN: "${JIRA_API_TOKEN}"
```

```bash
fullsend run strategy-create \
  --fullsend-dir /path/to/fullsend-config \
  --target-repo /path/to/strat-creator \
  --env-file /secure/path/strategy-create.env
```

The names in the harness intentionally match the existing skill's fallback
contract: `JIRA_SERVER`, `JIRA_USER`, and `JIRA_TOKEN`. The skill tries Jira
MCP tools first and uses those environment variables only as a fallback.

Passing a raw token through `env.sandbox` makes it available to processes in
the agent sandbox. A Jira MCP or other brokered credential path is the better
long-term boundary when one is available. Never commit a dotenv secret file or
put a token literal in a harness.

## Skill arguments and input contract

The `strategy-create` skill receives positional RFE keys and flags through
Claude Code's `$ARGUMENTS`, for example:

```text
/strategy-create RHAIRFE-123 RHAIRFE-456 --dry-run
```

Explicit RFE IDs cause the skill to process those IDs without asking the user
to select them; `--dry-run` suppresses Jira writes while retaining safe reads
and local artifact creation.

The currently inspected `fullsend run` command has no general `--args`,
`--kwargs`, or `--prompt` flag. It accepts the agent name and runner options,
then starts the selected runtime with the fixed initial prompt `Run the agent
task` (apart from internal validation-feedback retries). `agent_input` only
copies a configured directory into the sandbox; it does not populate a skill's
`$ARGUMENTS`.

Consequently, a thin harness can install the skill but cannot natively make a
parameterized slash-command invocation. A possible convention is to export a
value such as `STRATEGY_CREATE_ARGS` through `env.sandbox` and instruct the
agent definition to invoke `/strategy-create` using exactly those tokens. That
is a model-mediated workaround, not a direct runner-to-skill call.

The clean generic Fullsend capability would be an initial-prompt option, for
example:

```bash
fullsend run strategy-create ... \
  --prompt '/strategy-create RHAIRFE-123 RHAIRFE-456 --dry-run'
```

This has not been implemented in the inspected Fullsend checkout. It would
keep Fullsend generic while handing Claude Code the same command text that
normally populates `$ARGUMENTS`.

## Non-goals

- No Fullsend configuration or integration is implemented by this note.
- `/strategy-create` is not itself a Fullsend agent name or CLI subcommand.
- A Fullsend `plugins:` entry is not the right mechanism for this repository's
  Claude skill; the relevant harness resource is `skills:`.
