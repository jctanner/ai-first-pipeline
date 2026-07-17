# Plan: Skill Disambiguation Experiment

**Status: In Progress**

## Problem

When multiple Claude plugins each expose a skill with the same name, it is
unclear how the runtime resolves an unqualified invocation (`/<name> ...`)
versus a qualified one (`/<plugin>:<name> ...`). We have no empirical data on:

- Whether the model consistently picks the same plugin when two identically
  named skills are available.
- What reasoning the model applies when it disambiguates.
- Whether the choice changes across models, temperatures, or prompt phrasing.
- Whether qualified invocations are reliably routed, or whether the model
  still exercises judgment.

Understanding this is important for the platform because skill registries,
plugin marketplaces, and workflow FQN routing all depend on predictable skill
resolution. If the model silently picks the wrong variant, downstream artifacts
are wrong and the error is invisible without trace inspection.

## Concept

Create a controlled experiment with two plugins that each contain a skill
named `unit-convert`. One plugin converts using metric units (SI), the other
converts using imperial units. The skills are functionally identical except for
which unit system they default to when the user's request is ambiguous (e.g.
"convert 5 miles to kilometers" is unambiguous, but "what is 100 degrees in
the other system" depends on which plugin answers).

A Markov workflow runs a battery of invocations against the dashboard API,
varying:

- **Qualified vs. unqualified** invocation (`/unit-convert` vs.
  `/metric-converter:unit-convert` vs. `/imperial-converter:unit-convert`)
- **Prompt ambiguity** (unambiguous requests that have only one correct
  answer, vs. ambiguous requests where the answer depends on the unit system)
- **Repetition** (N trials per combination for statistical significance)

All runs use the full observability stack (strace, OTel, API body dumps,
MLflow tracing) so we can inspect the model's tool-call reasoning, skill
selection, and answer.

## Experiment Design

### Three repos on github.local

| Repo | Owner | Purpose |
|------|-------|---------|
| `metric-converter` | `experiment` | Plugin with `unit-convert` skill (SI/metric mode) |
| `imperial-converter` | `experiment` | Plugin with `unit-convert` skill (imperial mode) |
| `experiment-registry` | `experiment` | Plugin registry pointing at both converter repos |

### Skill shape

Both `metric-converter` and `imperial-converter` are Claude plugin repos
(`.claude-plugin/plugin.json`). Each contains a single skill at
`.claude/skills/unit-convert/SKILL.md`.

**metric-converter** `unit-convert` SKILL.md:
```
You are a unit conversion assistant operating in METRIC (SI) mode.
When the user asks for a conversion and the source unit system is
ambiguous, assume the input is in imperial and convert TO metric.
When both systems are specified, convert as requested.
Always state which unit system you used and why.
Return JSON: {"result": "...", "from_system": "...", "to_system": "...", "reasoning": "..."}
```

**imperial-converter** `unit-convert` SKILL.md:
```
You are a unit conversion assistant operating in IMPERIAL mode.
When the user asks for a conversion and the source unit system is
ambiguous, assume the input is in metric and convert TO imperial.
When both systems are specified, convert as requested.
Always state which unit system you used and why.
Return JSON: {"result": "...", "from_system": "...", "to_system": "...", "reasoning": "..."}
```

The key difference: when the request is ambiguous, the metric plugin assumes
input is imperial (and converts to metric), while the imperial plugin assumes
input is metric (and converts to imperial). This creates a detectable signal
in the output that tells us which skill actually ran.

### Plugin registry

The `experiment-registry` repo follows the `opendatahub-io/skills-registry`
format. It lists both `metric-converter` and `imperial-converter` as
installable plugins pointing at `github.local/experiment/<repo>@main`.

### Test battery

The battery is a set of prompts organized into categories:

**Category A: Unambiguous requests (both plugins should give identical answers)**
- "Convert 5 miles to kilometers"
- "Convert 100 kilograms to pounds"
- "What is 32 degrees Fahrenheit in Celsius?"

**Category B: Ambiguous requests (answer depends on which plugin runs)**
- "Convert 100 degrees to the other system"
- "What is 1000 units of distance in the other system?"
- "Convert 50 degrees"

**Category C: Qualified invocations (should always route correctly)**
- `/metric-converter:unit-convert Convert 100 degrees`
- `/imperial-converter:unit-convert Convert 100 degrees`

**Category D: Unqualified invocations (disambiguation behavior is the target)**
- `/unit-convert Convert 100 degrees`
- `/unit-convert What is 50 degrees in the other system?`

Each prompt is run N times (suggest N=10 initially, adjustable) to measure
consistency.

### Recorded metrics

For each trial:
- Which plugin was invoked (from tool-call trace)
- The model's reasoning for the choice (from API body dump)
- The answer produced
- Whether the answer is correct given the plugin that ran
- Latency
- Token usage

Aggregate:
- Selection frequency per plugin per category
- Consistency rate (does the model always pick the same one?)
- Correctness rate (given the selection, is the answer right?)
- Reasoning pattern clusters (what justification does the model give?)

## Architecture

### Workflow structure

```
var/demos/skill-disambiguation/
  meta.yaml
  vars.yaml
  README.md
  files/
    test-battery.json          # The prompt matrix
    metric-converter/          # Repo scaffold to import
    imperial-converter/        # Repo scaffold to import
    experiment-registry/       # Registry scaffold to import
  step_types/
    agent_job.yaml
    agent_job_wait.yaml
    dashboard_api.yaml
    github_api.yaml
  workflows/
    main.yaml                  # Entrypoint
    reset-environment.yaml     # Wipe and recreate experiment state
    import-repos.yaml          # Push the three repos to github.local
    install-plugins.yaml       # Register marketplace + install both plugins
    run-battery.yaml           # Loop over test-battery.json, submit jobs
    collect-results.yaml       # Pull MLflow traces, aggregate
```

### Execution flow

```
1. reset-environment     — wipe github.local org, MLflow experiment, artifacts
2. import-repos          — create org "experiment", push all three repos
3. run-battery           — for each prompt in the test matrix:
     a. submit agent job via dashboard API
        - both plugins installed from experiment-registry
        - prompt is the test case
        - strace + otel + api_dump + mlflow all enabled
     b. wait for job completion
     c. capture result metadata
4. collect-results       — query MLflow for all runs in the experiment
                          — parse tool-call traces from API dumps
                          — build summary table
                          — push summary to Observatory (optional)
```

### Agent runner enhancement: multi-plugin support

The current runner is tightly coupled: the FQN or `--skill` flag determines
both the environment (which plugin to install) and the prompt (which skill to
invoke). For this experiment — and for any future multi-plugin scenario — those
concerns need to be independent.

#### Current state

`run_skill.sh` today:
1. Hardcodes `claude plugin marketplace add opendatahub-io/skills-registry`.
2. Reads `pipeline-skills.yaml` to find a single `registry` field for the
   current skill's source repo, installs that one plugin.
3. Derives the prompt from the skill name (`/skill-name --headless ISSUE`).

There is no way to install additional plugins, register custom marketplaces,
or pass a raw prompt.

#### Proposed enhancement

Add three new optional fields to `POST /api/jobs/submit`:

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `registries` | `string[]` | `null` | Additional marketplace repos to register |
| `plugins` | `string[]` | `null` | Plugins to install from registered marketplaces |
| `prompt` | `string` | `null` | Raw prompt — bypasses skill/FQN resolution |

All three default to `null` (absent). A `null` or missing field has zero
effect — existing `command` and `fqn` submissions work identically with no
code path changes.

**Precedence rule for prompt resolution** (runner script):
```
if --prompt is set and non-empty:  use verbatim
elif --fqn:                        resolve via resolve_fqn.sh   [unchanged]
elif --skill:                      resolve via pipeline-skills.yaml [unchanged]
```

A `null` / unset `--prompt` never overrides `--skill` or `--fqn`. The runner
only enters the raw-prompt path when the argument is explicitly provided with
a non-empty value. Similarly, empty `registries` and `plugins` arrays (or
`null`) skip the marketplace/install loops entirely — no clone, no install
calls, no side effects.

#### Runner script changes (`run_skill.sh`)

New repeatable arguments:

```bash
--registry <fqn>    # additional marketplace to register (repeatable)
--plugin <name>     # plugin to install (repeatable)
--prompt <text>     # raw prompt, skip skill/FQN resolution
```

Updated flow:

```
1. Register default marketplace (opendatahub-io/skills-registry)    [unchanged]
2. For each --registry:
     a. Parse as github.local/owner/repo@ref
     b. Clone to /tmp/registries/<repo>
     c. claude plugin marketplace add /tmp/registries/<repo>
3. For each --plugin:
     claude plugin install <name> || true
4. Existing pipeline-skills.yaml install                             [unchanged]
5. Prompt resolution:
     if --prompt:  use verbatim
     elif --fqn:   resolve via resolve_fqn.sh                        [unchanged]
     elif --skill: resolve via pipeline-skills.yaml                  [unchanged]
6. Run Claude CLI                                                    [unchanged]
```

Step 2b is the key detail: the Claude CLI `plugin marketplace add` command
takes a local directory path (the SDK runner already does this with
`/app/skills-registry`). For github.local-hosted registries, we clone the
repo first, then register the local path.

**Critical detail**: the registry repo must contain a
`.claude-plugin/marketplace.json` file — Claude Code reads this file, not
`registry.yaml`. The `registry.yaml` is a human-editable source of truth
that must be transpiled via `scripts/sync_marketplace.py` (from the
`opendatahub-io/skills-registry` repo) into `marketplace.json`.

**Git URL rewriting for non-github.com hosts**: `claude plugin install`
hardcodes `github.com` when cloning plugin source repos. When the registry
references repos on `github.local`, we add scoped `git config insteadOf`
rules to redirect only the relevant org's traffic:

```
git config --global url."https://<emulator>/<owner>/".insteadOf "https://github.com/<owner>/"
git config --global url."https://<emulator>/<owner>/".insteadOf "git@github.com:<owner>/"
```

This ensures `claude plugin install metric-converter` (which internally
tries `github.com/experiment/metric-converter`) hits the emulator instead,
without affecting unrelated `github.com` traffic like the default
`opendatahub-io/skills-registry` marketplace.

#### Orchestrator changes (`k8s_orchestrator.py`)

Only append arguments when the fields are non-null and non-empty:

```python
registries = args.get("registries") or []
for reg in registries:
    cmd_args.extend(["--registry", reg])

plugins = args.get("plugins") or []
for plugin in plugins:
    cmd_args.extend(["--plugin", plugin])

prompt = args.get("prompt")
if prompt:
    cmd_args.extend(["--prompt", prompt])
```

The `or []` / truthiness guards ensure that `null`, missing keys, and empty
arrays all collapse to no-op. A job submitted with `{"command": "bug-completeness",
"args": {"issue": "RHOAIENG-1"}}` produces the exact same container command
as it does today — no new arguments appear.

#### Example job submission for a trial

```json
{
  "args": {
    "model": "claude-sonnet-4-20250514",
    "runner": "cli",
    "harness": "claude-code",
    "registries": ["github.local/experiment/experiment-registry@main"],
    "plugins": ["metric-converter", "imperial-converter"],
    "prompt": "/unit-convert Convert 100 degrees",
    "strace": true,
    "mlflow": true,
    "otel": true,
    "api_dump": true
  }
}
```

No `command` or `fqn` needed — `prompt` is the invocation.

#### What this enables beyond this experiment

- Installing any combination of plugins for A/B testing, integration
  testing, or multi-skill workflows.
- Running arbitrary prompts against a configured plugin environment
  without needing a registered skill or FQN.
- Using custom registries hosted on github.local for isolated experiments
  without polluting the production skill registry.

## Open Questions

1. **Plugin install verification**: After installing both plugins, should the
   runner verify that both are present and that the shared skill name exists
   in both? Or is silent failure acceptable (as it is today with `|| true`)?

2. **Trial isolation**: Should each trial be a fresh K8s Job (clean
   environment), or can we batch multiple prompts in a single job? Fresh jobs
   are more isolated but slower and more expensive. Batching risks state
   leakage between trials.

3. **Sample size**: How many repetitions per prompt to get meaningful
   statistics? 10 is a starting point, but for a binary choice the confidence
   interval at N=10 is wide. N=30 would be more robust but 3x the cost.

4. **Model matrix**: Should we test across models (sonnet, opus, haiku) or
   start with a single model and expand later? Cross-model comparison is
   interesting but multiplies the trial count.

5. **Analysis tooling**: Where should the analysis live? Options:
   - A Python notebook in the demo directory
   - An Observatory pipeline that ingests the results
   - A dashboard page
   - A Markov post-processing workflow step that produces a summary artifact

6. **Registry format**: The SDK runner already registers a local directory
   as a marketplace (`claude plugin marketplace add /app/skills-registry`).
   We need to confirm that the `opendatahub-io/skills-registry` repo format
   is what the CLI expects when given a local path. If the format differs
   from a directory-based marketplace, we may need an adapter.

7. **Prompt design**: The test battery above uses unit conversion as the
   domain. Are there better domain choices that make the disambiguation
   signal cleaner? The key requirement is that the two skills must produce
   detectably different outputs for ambiguous inputs while being legitimate
   implementations for unambiguous ones.

8. **Naming**: The plan uses `unit-convert` as the shared skill name and
   `metric-converter` / `imperial-converter` as plugin names. Better
   suggestions welcome — the names should make the experiment's purpose
   self-evident in traces and dashboards.

9. **Baseline**: Should we also run trials with only one plugin installed
   (not both) to confirm the skill works correctly in isolation before
   testing the disambiguation scenario?

10. **Determinism controls**: Should we pin temperature to 0 for all trials
    to minimize randomness, or is observing the variance at default
    temperature part of the experiment?

11. **Plugin install ordering**: Does the order in which plugins are installed
    affect which one the model selects? If so, the experiment should vary
    install order as another dimension. The runner enhancement should preserve
    the order of `--plugin` arguments.

12. **Working directory**: When running with `--prompt` (no FQN/skill), what
    should the agent's working directory be? Options: the pipeline repo root
    (`/app`), a temporary directory, or a new `--cwd` argument. The cwd
    affects what project-level CLAUDE.md and `.claude/` config the agent sees.

## Success Criteria

The experiment succeeds if we produce:

1. A reproducible Markov workflow that can be re-run to gather fresh data.
2. A dataset of N * (prompts * categories) trials with full trace data.
3. A summary showing selection frequency, consistency, and correctness.
4. The model's reasoning patterns extracted and clustered.
5. Actionable findings about whether unqualified skill invocations are safe
   when identically-named skills exist across plugins.

## Dependencies

- K3s cluster running with github-emulator, dashboard, MLflow, and pipeline
  agent deployed (`make host-deploy-all`).
- The `claude plugin marketplace add` and `claude plugin install` CLI
  commands functioning inside the agent runner container.
- `experiment-registry` formatted correctly for Claude's marketplace system.

## Cost Estimate

Per trial: ~1 agent job = ~2-5k tokens (simple conversion prompt).
Battery: 4 categories * ~3 prompts * 10 repetitions = 120 trials.
At ~3k tokens average: ~360k tokens total, roughly $2-5 depending on model.
Cross-model (3 models): ~$6-15.

The cost is modest; the wall-clock time for 120 sequential K8s jobs is the
bigger concern. If each job takes ~60s (pod startup + execution + teardown),
that's ~2 hours. Parallelism via Markov fan-out could reduce this.

## Follow-On Work

If the experiment reveals problematic disambiguation behavior:

- Propose changes to the plugin resolution spec (e.g. require qualified
  invocation when name collisions exist).
- Add a pre-flight check to `run_skill.sh` that detects name collisions
  and warns or errors.
- Feed findings into the Observatory as a verified quality signal.
- Use the battery as a regression suite for future Claude CLI versions.
