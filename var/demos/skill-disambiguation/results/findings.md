# Skill Disambiguation Experiment — Findings

Runs:
- `markov-run-a481f69d` — initial baseline
- `markov-run-f60ec749` — intended plugin-dir ordering test
- `markov-run-77f785b1` — marketplace fix
- `markov-run-cc197efe` — reversed order + no-plugin-dir (verified)

Date: 2026-07-17 / 2026-07-18
Model: `claude-sonnet-4-20250514`
Trials per prompt: 10

## Results

All three runs used `--plugin-dir` with imperial-converter before
metric-converter (alphabetical glob order from `run_skill.sh`). The intended
variation in Runs 2 and 3 did not reach the container — see Provenance below.

### Run 1 — baseline (120 trials)

| Category | Plugin used | Count | Rate |
|----------|------------|-------|------|
| unambiguous | imperial-converter | 30/30 | 100% |
| ambiguous-unqualified | imperial-converter | 30/30 | 100% |
| qualified-metric | metric-converter | 30/30 | 100% |
| qualified-imperial | imperial-converter | 30/30 | 100% |

### Run 2 — intended plugin-dir ordering test (180 trials)

Pod logs show `--plugin-dir .../imperial-converter/1.0.0` before
`--plugin-dir .../metric-converter/1.0.0` on all trials, including those
labeled "metric-first." The order-preserving `run_skill.sh` change was not
present in the deployed image. Results are therefore a repeat of Run 1
conditions, not a reversed-order test.

| Category | Intended order | Actual CLI order | Plugin used | Count |
|----------|---------------|-----------------|------------|-------|
| unambiguous | imperial-first | imperial-first | imperial-converter | 30/30 |
| ambiguous-unqualified | imperial-first | imperial-first | imperial-converter | 30/30 |
| qualified-metric | imperial-first | imperial-first | metric-converter | 30/30 |
| qualified-imperial | imperial-first | imperial-first | imperial-converter | 30/30 |
| unambiguous-metric-first | metric-first | imperial-first | imperial-converter | 30/30 |
| ambiguous-metric-first | metric-first | imperial-first | imperial-converter | 30/30 |

### Run 3 — marketplace fix (180 trials)

Fixed marketplace entries (removed `skills` and `strict: false`). However,
the `--plugin-dir` workaround in `run_skill.sh` was still active, so plugins
were loaded via `--plugin-dir` rather than normal installed-plugin discovery.
Pod logs confirm `--plugin-dir` arguments were present in the `execve`. Same
actual conditions as Runs 1 and 2.

| Category | Intended order | Actual CLI order | Plugin used | Count |
|----------|---------------|-----------------|------------|-------|
| unambiguous | imperial-first | imperial-first | imperial-converter | 30/30 |
| ambiguous-unqualified | imperial-first | imperial-first | imperial-converter | 30/30 |
| qualified-metric | imperial-first | imperial-first | metric-converter | 30/30 |
| qualified-imperial | imperial-first | imperial-first | imperial-converter | 30/30 |
| unambiguous-metric-first | metric-first | imperial-first | imperial-converter | 30/30 |
| ambiguous-metric-first | metric-first | imperial-first | imperial-converter | 30/30 |

### Run 4 — reversed order + no-plugin-dir (240 trials, verified)

Both outstanding experiments executed with verified provenance. Pod logs
confirm `--plugin-dir` order was genuinely reversed for metric-first
categories and genuinely absent for no-plugin-dir categories.

Metric-first pod log:
```
--plugin-dir .../metric-converter/1.0.0
--plugin-dir .../imperial-converter/1.0.0
```

No-plugin-dir pod log:
```
--no-plugin-dir: skipping --plugin-dir workaround, using normal plugin discovery
Executing: claude --model claude-sonnet-4-20250514 --print "/unit-convert ..."
```

| Category | Plugin-dir mode | Plugin used | Count |
|----------|----------------|------------|-------|
| unambiguous | imperial-first | imperial-converter | 30/30 |
| ambiguous-unqualified | imperial-first | imperial-converter | 30/30 |
| qualified-metric | imperial-first | metric-converter | 30/30 |
| qualified-imperial | imperial-first | imperial-converter | 30/30 |
| unambiguous-metric-first | metric-first | metric-converter | 30/30 |
| ambiguous-metric-first | metric-first | metric-converter | 30/30 |
| unambiguous-no-plugin-dir | none | imperial-converter | 30/30 |
| ambiguous-no-plugin-dir | none | imperial-converter | 30/30 |

## What the data supports

Across 720 trials (480 with identical conditions + 240 with verified
variations):

1. **Qualified invocations route correctly.** `/metric-converter:unit-convert`
   always dispatched to metric-converter, `/imperial-converter:unit-convert`
   always dispatched to imperial-converter. 240/240 across all runs.

2. **Unqualified `/unit-convert` is deterministic, not random.** When both
   plugins register the same skill name, Claude Code always picked one
   winner consistently. There is no round-robin, random selection, or
   content-aware routing. 480/480 unqualified invocations across all runs.

3. **The agent does not disambiguate based on prompt content.** Ambiguous
   prompts like "Convert 100 degrees to the other system" were handled
   identically to unambiguous prompts like "Convert 5 miles to kilometers" —
   both went to the same plugin without consideration of which plugin
   would give a more useful answer.

4. **`--plugin-dir` argument order determines the collision winner.** When
   imperial-converter was the first `--plugin-dir`, imperial won 360/360.
   When metric-converter was first, metric won 60/60. This is a pure
   first-registration-wins model. (Run 4, verified by pod logs.)

5. **Normal installed-plugin discovery is deterministic under the tested
   installation order.** Without `--plugin-dir`, imperial-converter won
   60/60. Plugins were installed imperial-first in all no-plugin-dir
   trials. Whether the winner is determined by installation order,
   settings order, or alphabetical plugin name remains untested — a
   reversed-install/no-plugin-dir combination would distinguish them.
   (Run 4, verified by pod logs showing no `--plugin-dir` in `execve`.)

6. **The collision rule is: first plugin to register a skill name owns it
   for unqualified invocations.** With `--plugin-dir`, "first" means CLI
   argument order. With normal discovery, "first" means whatever order
   Claude Code iterates installed plugins — empirically the
   alphabetically first plugin won, but installation order was also
   alphabetical in the tested configuration.

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

### What the strace shows

1. **Both SKILL.md files are read during discovery.** Claude Code does not
   stop at the first match. It registers all skills from all plugins, then
   resolves the unqualified name to one of them.

2. **Observed syscall order follows `--plugin-dir` CLI argument order.**
   Imperial is the first `--plugin-dir` on the command line, and its
   `skills/` directory was accessed first at the syscall level. The 4ms gap
   (22:26:09.561 vs 22:26:09.565) shows the observed ordering but does not
   by itself prove the JavaScript discovery tasks weren't scheduled
   concurrently.

3. **`installed_plugins.json` order does not control `--plugin-dir` order.**
   The manifest lists metric-converter before imperial-converter (metric was
   installed first at 22:26:03, imperial at 22:26:08). But the `--plugin-dir`
   arguments come from an alphabetical shell glob, not the install manifest.

4. **Imperial wins because it is discovered first.** Run 4 confirmed the
   CLI-order hypothesis: reversing `--plugin-dir` order so metric-converter
   appeared first caused metric-converter to win 60/60. Claude Code does
   not sort plugins alphabetically after discovery — it uses
   first-registration-wins.

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
  code in `run_skill.sh` should not be necessary. Run 4 confirmed that
  normal installed-plugin discovery works with the corrected marketplace
  entries (no `--plugin-dir` needed). A reversed-install/no-plugin-dir
  combination remains untested.

- **`--output-format stream-json` with `--print`:** The stream parser
  (`stream-claude.py`) was only handling `stream_event` messages. In
  `--print` mode, Claude emits a single `assistant` message with the full
  response instead of streaming `content_block_delta` events. The parser
  needed to handle both paths.

## Resolved questions

- **Does CLI argument order or internal alphabetical sort determine the
  collision winner?** CLI argument order. Reversing `--plugin-dir` so
  metric-converter appeared first caused metric-converter to win 60/60.
  Confirmed by Run 4 pod logs.

- **Does the collision behavior hold on the normal installed-plugin
  discovery path?** Yes — collisions are deterministic on the normal path.
  Without `--plugin-dir`, imperial-converter won 60/60. However, plugins
  were installed imperial-first in all no-plugin-dir trials, so the winner
  could reflect installation order, settings order, or alphabetical order.
  Confirmed by Run 4 pod logs showing no `--plugin-dir` in the `execve`.

## Open questions

- What determines iteration order on the normal installed-plugin discovery
  path — installation order, settings order, or alphabetical plugin name?
  (Requires a reversed-install/no-plugin-dir run.)
- Is there a way to make Claude Code content-aware when routing unqualified
  skill names to competing plugins?
- Would a single plugin with multiple skill variants (e.g.
  `/unit-convert-metric`, `/unit-convert-imperial`) behave differently?
