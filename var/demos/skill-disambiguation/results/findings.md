# Skill Disambiguation Experiment — Findings

Runs: `markov-run-a481f69d` (initial), `markov-run-f60ec749` (plugin-dir ordering)
Date: 2026-07-17 / 2026-07-18
Model: `claude-sonnet-4-20250514`
Trials per prompt: 10

## Results

### Run 1 — baseline (120 trials, imperial-first CLI order)

| Category | Plugin used | Count | Rate |
|----------|------------|-------|------|
| unambiguous | imperial-converter | 30/30 | 100% |
| ambiguous-unqualified | imperial-converter | 30/30 | 100% |
| qualified-metric | metric-converter | 30/30 | 100% |
| qualified-imperial | imperial-converter | 30/30 | 100% |

### Run 2 — plugin-dir ordering (180 trials, includes metric-first CLI order)

| Category | Plugin order | Plugin used | Count | Rate |
|----------|-------------|------------|-------|------|
| unambiguous | imperial-first | imperial-converter | 30/30 | 100% |
| ambiguous-unqualified | imperial-first | imperial-converter | 30/30 | 100% |
| qualified-metric | imperial-first | metric-converter | 30/30 | 100% |
| qualified-imperial | imperial-first | imperial-converter | 30/30 | 100% |
| unambiguous-metric-first | metric-first | imperial-converter | 30/30 | 100% |
| ambiguous-metric-first | metric-first | imperial-converter | 30/30 | 100% |

## Observations

1. **Qualified invocations route correctly.** `/metric-converter:unit-convert`
   always dispatched to metric-converter, `/imperial-converter:unit-convert`
   always dispatched to imperial-converter. 60/60, no misroutes.

2. **Unqualified `/unit-convert` is deterministic, not random.** When both
   plugins register the same skill name, Claude Code always picked
   imperial-converter (30/30 unambiguous, 30/30 ambiguous). There is no
   round-robin, random selection, or content-aware routing.

3. **Selection order appears to be plugin load order.** The `--plugin-dir`
   flags were passed alphabetically (imperial before metric). This likely
   determines which plugin wins an unqualified name collision. The agent does
   not inspect the prompt to decide which plugin is more appropriate.

4. **The agent does not disambiguate based on prompt content.** Ambiguous
   prompts like "Convert 100 degrees to the other system" were handled
   identically to unambiguous prompts like "Convert 5 miles to kilometers" —
   both went to imperial-converter without consideration of which plugin
   would give a more useful answer.

## Skill routing mechanism (from API body analysis)

Inspection of the raw Anthropic API request bodies reveals the routing
mechanism. When the user invokes `/unit-convert`, Claude Code resolves
the unqualified skill name to a qualified `plugin:skill` pair **before**
the API request is sent. The model never sees the ambiguity.

For the bare `/unit-convert` prompt, the API request contains:

```xml
<command-message>imperial-converter:unit-convert</command-message>
<command-name>/imperial-converter:unit-convert</command-name>
<command-args>Convert 5 miles to kilometers</command-args>
```

The SKILL.md content from imperial-converter is then injected as a
subsequent user message:

```
Base directory for this skill: .../imperial-converter/1.0.0/skills/unit-convert

You are a unit conversion assistant operating in **IMPERIAL** mode.
...
ARGUMENTS: Convert 5 miles to kilometers
```

For the qualified `/metric-converter:unit-convert`, the routing is
identical in structure but correctly targets the metric plugin:

```xml
<command-message>metric-converter:unit-convert</command-message>
<command-name>/metric-converter:unit-convert</command-name>
```

This confirms:
- **Routing is a Claude Code CLI decision, not an LLM decision.** The skill
  resolver picks the plugin before the model is invoked.
- **The model only sees one skill's instructions.** It has no opportunity to
  compare or choose between competing plugins.
- **The `<command-message>` tag is the authoritative routing signal.** Whatever
  plugin Claude Code's resolver selects gets its SKILL.md injected as the
  prompt context.

No MLflow traces were captured — the runs (~5-7 seconds) were too short for
the MLflow Stop hook to flush data before the container exited.

## Strace analysis — skill discovery internals

Strace captures (`strace -ffttv -s 1024`) from one unambiguous trial
(`/unit-convert Convert 5 miles to kilometers`) reveal the end-to-end
routing sequence at the syscall level:

### Timeline

```
22:26:08.513  execve claude ... --plugin-dir .../imperial-converter/1.0.0
                                --plugin-dir .../metric-converter/1.0.0
22:26:09.445  read(installed_plugins.json)  ← metric listed first, imperial second
22:26:09.561  statx .../imperial-converter/1.0.0/skills/unit-convert/SKILL.md  → OK
22:26:09.562  openat+readlink imperial SKILL.md (fd 13, 115 bytes)
22:26:09.565  statx .../metric-converter/1.0.0/skills/unit-convert/SKILL.md   → OK
22:26:09.566  openat+readlink metric SKILL.md (fd 13, 113 bytes)
22:26:22.032  write(init message)  → slash_commands includes both
              "imperial-converter:unit-convert" and "metric-converter:unit-convert"
22:26:33.768  write(assistant response)  → model used imperial-converter
22:26:34.498  sendto(Stop hook)  → final answer in imperial mode
```

### What the strace proves

1. **Both SKILL.md files are read during discovery.** Claude Code does not
   stop at the first match. It registers all skills from all plugins, then
   resolves the unqualified name to the first registration.

2. **Discovery order follows `--plugin-dir` CLI argument order.** Imperial
   is the first `--plugin-dir` on the command line, so its `skills/` directory
   is walked first. The 4ms gap (22:26:09.561 vs 22:26:09.565) confirms
   sequential, not parallel, traversal.

3. **`installed_plugins.json` order is irrelevant.** The manifest lists
   metric-converter before imperial-converter (metric was installed first at
   22:26:03, imperial at 22:26:08). But discovery order is controlled by the
   `--plugin-dir` arguments, not the install manifest.

4. **`--plugin-dir` order comes from shell glob order.** In `run_skill.sh`,
   the loop `for PLUGIN_BASE in "$CACHE_ROOT"*/` iterates alphabetically.
   Since `imperial-converter` sorts before `metric-converter`, imperial gets
   the first `--plugin-dir` flag and wins all unqualified collisions.

5. **The resolution is a pure first-match, not a comparison.** There is no
   evidence of any scoring, content comparison, or tiebreaker logic between
   competing skills. The first plugin to register a given skill name owns
   that name for unqualified invocations.

### Predicting collision winners — resolved

A follow-up experiment (run `markov-run-f60ec749`) reversed the `--plugin-dir`
order so metric-converter appeared first on the CLI:

```
claude ... --plugin-dir .../metric-converter/1.0.0 \
           --plugin-dir .../imperial-converter/1.0.0
```

Results:

| Category | Plugin used | Count |
|----------|------------|-------|
| unambiguous-metric-first | imperial-converter | 30/30 |
| ambiguous-metric-first | imperial-converter | 30/30 |

**Imperial-converter still wins 60/60.** This rules out the CLI-arg-order
hypothesis and confirms:

**Claude Code sorts plugins alphabetically internally.** The `--plugin-dir`
argument order is irrelevant. When two plugins register the same skill name,
the plugin whose name sorts first lexicographically always wins unqualified
invocations. There is no way to influence the winner by reordering CLI
arguments.

```
winner = lexicographically first plugin name
```

## Issues discovered during setup

- **Plugin skill directory:** Plugins must use `skills/` at the plugin root,
  not `.claude/skills/`. The latter is for project-level skills only. Plugins
  with `.claude/skills/` load (appear in `plugins` list) but their skills are
  not discovered.

### Recommended plugin and marketplace structure

A skill repository distributed through a Claude Code marketplace should be a
self-describing plugin repository:

```text
metric-converter/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    └── unit-convert/
        ├── SKILL.md
        ├── scripts/        # optional
        ├── references/     # optional
        └── assets/         # optional
```

The plugin manifest owns the plugin metadata:

```json
{
  "name": "metric-converter",
  "version": "1.0.0",
  "description": "Unit conversion in metric mode"
}
```

Each skill lives under the conventional root-level `skills/` directory:

```markdown
---
name: unit-convert
description: Convert measurements into metric units
user-invocable: true
---

Skill instructions...
```

The separate marketplace repository should locate and describe the plugin,
without repeating its component paths:

```text
experiment-registry/
└── .claude-plugin/
    └── marketplace.json
```

```json
{
  "name": "experiment-registry",
  "owner": {
    "name": "experiment"
  },
  "plugins": [
    {
      "name": "metric-converter",
      "description": "Unit conversion in metric mode",
      "version": "1.0.0",
      "source": {
        "source": "github",
        "repo": "experiment/metric-converter",
        "ref": "main"
      }
    }
  ]
}
```

The ownership rules are:

- Use `skills/<skill-name>/SKILL.md` for a distributed plugin skill.
- Reserve `.claude/skills/` for project-local skills.
- Do not declare the conventional root `skills/` path; Claude Code discovers
  it automatically.
- Let `.claude-plugin/plugin.json` be authoritative for plugin components.
- Leave marketplace `strict` unspecified when the plugin has `plugin.json`;
  it defaults to `true`.
- Use `strict: false` only for a manifest-less plugin whose definition is
  supplied entirely by the marketplace entry.
- Do not declare components such as `skills`, `commands`, or `agents` in both
  a non-strict marketplace entry and a repository containing `plugin.json`.

With this structure, normal marketplace registration and plugin installation
should be sufficient. `--plugin-dir` is not part of the expected installed
plugin workflow.

- **Installed-plugin discovery failure — root cause resolved:** The failure was
  not a general limitation of `--print` mode. Both experiment marketplace
  entries declared `strict: false` and `skills: ["./.claude/skills"]`, while
  each plugin also contained `.claude-plugin/plugin.json`. Claude Code treats
  a non-strict marketplace component declaration plus a plugin manifest as a
  conflicting pair of manifests and rejects the plugin at load time. The
  `plugin install` command still reports success because it successfully
  caches and registers the plugin; that does not mean the plugin subsequently
  loaded successfully. Passing `--plugin-dir` bypasses the marketplace entry,
  loads the cached plugin directly from `plugin.json`, and auto-discovers the
  conventional root-level `skills/` directory. It therefore masked the
  manifest conflict.

  The source path is `finishLoadingPluginFromPath()` in
  `deleteme/claude-code/src/utils/plugins/pluginLoader.ts`: when a plugin has a
  manifest, `strict` is false, and the marketplace entry declares `skills` or
  another component, the loader records a `generic-error` and returns `null`.
  Session-only plugins supplied through `--plugin-dir` instead go through
  `loadSessionOnlyPlugins()` and do not merge the conflicting marketplace
  component metadata.

  **Validated by Codex on 2026-07-17 against the experiment's exact Claude
  Code 2.1.212 binary.** Codex ran a network-free local marketplace fixture in
  the existing `pipeline-agent` image. With the original metadata, marketplace
  registration and `plugin install` both succeeded, but `plugin list` reported:

  ```text
  Status: failed to load
  Error: Plugin metric-converter has conflicting manifests: both plugin.json
  and marketplace entry specify components.
  ```

  A subsequent `--print` invocation reported `Unknown command` for the
  qualified skill. In the control, Codex removed `skills` and `strict: false`
  from the marketplace entry, retained the plugin's `plugin.json` and root
  `skills/` directory, and ran from `/app` without `--plugin-dir` and without
  manually adding project-level `enabledPlugins`. `plugin list` then reported
  the plugin as enabled, the debug log recorded one plugin skill loaded, and
  `/metric-converter:unit-convert` was recognized and expanded into the skill
  prompt. Execution stopped only because the isolated control had no Claude
  login credentials.

  The correct configuration is therefore to remove the redundant `skills`
  and `strict: false` fields from these marketplace entries and let each
  plugin's manifest plus root `skills/` directory be authoritative. After that
  correction, the project-settings enablement and `--plugin-dir` cache-walking
  code in `run_skill.sh` should not be necessary. The collision experiment
  should be rerun through normal installed-plugin discovery because its current
  ordering findings describe the `--plugin-dir` workaround path.

- **`--output-format stream-json` with `--print`:** The stream parser
  (`stream-claude.py`) was only handling `stream_event` messages. In
  `--print` mode, Claude emits a single `assistant` message with the full
  response instead of streaming `content_block_delta` events. The parser
  needed to handle both paths.

## Open questions

- Does reversing the `--plugin-dir` order (metric before imperial) cause
  metric-converter to win unqualified invocations?
- Is there a way to make Claude Code content-aware when routing unqualified
  skill names to competing plugins?
- Would a single plugin with multiple skill variants (e.g.
  `/unit-convert-metric`, `/unit-convert-imperial`) behave differently?
