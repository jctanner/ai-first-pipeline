# Plugin-Aware FQN Skill Loading

**Status: Implemented**

## Context

The end-to-end epic demo invokes `epic-creator` through the dashboard job API using an FQN:

```json
{
  "fqn": "github.local/opendatahub-io/epic-creator@main:epic-decompose"
}
```

The current FQN runtime clones the repo, symlinks `skills/<skill>` into `.claude/skills/<skill>`, changes into the cloned repo, and invokes:

```bash
/epic-decompose --headless RHAISTRAT-1
```

That works for simple skill repos, but it does not fully match how the upstream `epic-decomposer` CI harness runs `epic-creator`. The upstream path clones `epic-creator` into `/tmp/claude-workdir`, registers it as a Claude plugin via `.claude-plugin/plugin.json`, and invokes the namespaced plugin command:

```bash
/epic-creator:epic-decompose ...
```

The mismatch is a credible contributor to agent drift. In the observed failure, the decomposer wrote raw YAML frontmatter with hallucinated fields instead of using `scripts/frontmatter.py set`. Running plugin-shaped repos as plain symlinked skills can change namespace behavior, hook behavior, and the context Claude sees from the repo/plugin layout.

## Goal

Make FQN skill loading automatically honor the cloned repo's shape:

- Plugin-shaped repos run as plugins.
- Plain skill repos keep using the existing symlink/direct skill path.
- Existing dashboard and workflow API calls keep working without new required fields.
- An advanced override exists only for debugging or exceptional repos.

## Runtime Modes

Add an internal skill load mode with three values:

| Mode | Behavior |
|------|----------|
| `auto` | Default. Use plugin mode when `.claude-plugin/plugin.json` exists; otherwise use direct skill mode. |
| `plugin` | Require plugin mode. Fail clearly if `.claude-plugin/plugin.json` is missing or invalid. |
| `skill` | Force the current symlink/direct skill behavior even if plugin metadata exists. |

The public API should default to `auto`. The Jobs UI does not need a new control for this initially.

## Proposed API Shape

Keep the top-level body unchanged. If an override is ever needed, pass it through `args`:

```json
{
  "fqn": "github.local/opendatahub-io/epic-creator@main:epic-decompose",
  "args": {
    "issue": "RHAISTRAT-1",
    "model": "opus",
    "runner": "cli",
    "harness": "claude-code",
    "skill_load_mode": "auto"
  }
}
```

`skill_load_mode` is runner behavior, so it belongs under `args` with `runner`, `harness`, `extra_env`, `strace`, and `mlflow`. It should not be required and should not be exposed as a first-pass dashboard toggle.

## Implementation Plan

### 1. `scripts/resolve_fqn.sh`

After cloning the FQN repo:

1. Detect `.claude-plugin/plugin.json`.
2. Parse the plugin name from `plugin.json`.
3. Export:

```bash
FQN_LOAD_MODE_RESOLVED="plugin"
FQN_PLUGIN_DIR="$FQN_CLONE_DIR"
FQN_PLUGIN_NAME="<plugin name>"
```

For repos without plugin metadata, export:

```bash
FQN_LOAD_MODE_RESOLVED="skill"
```

Keep the existing `.claude/skills/<skill>` symlink setup for direct skill mode.

### 2. `scripts/run_skill.sh`

Add an optional argument:

```bash
--skill-load-mode auto|plugin|skill
```

Default to `auto`.

Prompt construction:

```bash
if [ "$FQN_LOAD_MODE_RESOLVED" = "plugin" ]; then
  PROMPT="/${FQN_PLUGIN_NAME}:${SKILL_NAME} --headless${FORCE:+ $FORCE}${ISSUE_KEY:+ $ISSUE_KEY}"
else
  PROMPT="/$SKILL_NAME --headless${FORCE:+ $FORCE}${ISSUE_KEY:+ $ISSUE_KEY}"
fi
```

Claude invocation:

```bash
PLUGIN_ARGS=()
if [ "$FQN_LOAD_MODE_RESOLVED" = "plugin" ]; then
  PLUGIN_ARGS=(--plugin-dir "$FQN_PLUGIN_DIR")
fi

claude --model "$MODEL" --print "${PLUGIN_ARGS[@]}" ...
```

The plugin mode should still `cd "$FQN_CLONE_DIR"` before running. That preserves repo-relative script paths such as `python3 scripts/frontmatter.py`.

### 3. `scripts/run_skill_sdk.sh`

Mirror the mode resolution so SDK and CLI runners behave consistently. If SDK support for plugin dirs differs from CLI support, fail clearly for `skill_load_mode=plugin` instead of silently falling back to direct skill mode.

### 4. `src/dashboard/k8s_orchestrator.py`

Read `args.get("skill_load_mode", "auto")` and, when present, append:

```bash
--skill-load-mode <mode>
```

Store the requested mode in a job annotation, for example:

```python
"skill_load_mode": args.get("skill_load_mode", "auto")
```

Optionally store the resolved mode later if the runner prints it in logs; the K8s manifest cannot know the resolved repo shape before the pod clones the repo.

### 5. `src/dashboard/webapp.py`

Validate `skill_load_mode` only if supplied:

```python
if args.get("skill_load_mode") not in (None, "auto", "plugin", "skill"):
    return jsonify({"error": "Invalid skill_load_mode"}), 400
```

No UI change is required for the initial version.

### 6. `src/dashboard/static/js/jobs.js`

No first-pass form change. Preserve `extra_kwargs`, `extra_env`, and rerun behavior.

If the annotation is added, display it in the job detail modal later as low-priority metadata.

## Epic Demo Follow-Up

After plugin-aware loading is in place, the epic demo can continue using the same workflow FQN:

```yaml
skill_fqn: "github.local/{{ org }}/epic-creator@main:epic-decompose"
```

No workflow flag should be required.

For debugging, the workflow could force plugin mode through `skill_extra_kwargs` only if needed:

```yaml
skill_extra_kwargs: "skill_load_mode=plugin"
```

However, the preferred behavior is automatic detection from `.claude-plugin/plugin.json`.

## Guardrail Still Needed

Plugin-aware loading reduces the chance that the decomposer ignores repo-local conventions, but it is not a substitute for validation.

Add a deterministic post-decompose gate before `epic_submit`:

```bash
python3 scripts/frontmatter.py batch-read /app/artifacts/epic-tasks/${STRAT}-E*.md
```

or the equivalent using the cloned `epic-creator` scripts. The gate should fail before Jira submission if any epic artifact has unknown fields, missing required fields, or invalid enum values.

This catches future model drift even when plugin loading is correct.

## Verification

1. Submit a plain skill repo FQN and verify the runner logs `resolved skill load mode: skill`.
2. Submit `github.local/opendatahub-io/epic-creator@main:epic-decompose` and verify the runner logs `resolved skill load mode: plugin`.
3. Verify the Claude command includes `--plugin-dir "$FQN_CLONE_DIR"` for `epic-creator`.
4. Verify the prompt uses `/epic-creator:epic-decompose`, not `/epic-decompose`.
5. Run the end-to-end epic workflow and confirm decomposer artifacts validate before `epic_submit`.
6. Force `skill_load_mode=plugin` on a non-plugin repo and confirm the job fails with a clear error.
7. Force `skill_load_mode=skill` on `epic-creator` and confirm it preserves the existing compatibility path for debugging.
