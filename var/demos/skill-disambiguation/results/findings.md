# Skill Disambiguation Experiment — Findings

Runs:
- `markov-run-a481f69d` — initial baseline
- `markov-run-f60ec749` — intended plugin-dir ordering test
- `markov-run-77f785b1` — marketplace fix
- `markov-run-cc197efe` — reversed order + no-plugin-dir (verified)
- `markov-run-30e9421a` — reversed install order + no-plugin-dir (verified)
- Run 6 (local binary analysis, Claude Code 2.1.214)
  — isolated settings/marketplace/install-order controls (verified;
  evidence under gitignored `tmp/claude-code-binary-analysis/`)
- `markov-run-76e9545f` — swap-order isolation controls (360 trials)

Date: 2026-07-17 / 2026-07-18
Model: `claude-sonnet-4-20250514`
Trials per prompt: 10

## Results

Runs 1–3 used `--plugin-dir` with imperial-converter before
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

### Run 5 — reversed install order + no-plugin-dir (300 trials, verified)

Same battery as Run 4 plus two new categories that install
metric-converter before imperial-converter with `--no-plugin-dir`.
Pod logs confirm metric was installed first, no `--plugin-dir` in
the `execve`, and metric-converter won — ruling out alphabetical
ordering on the normal discovery path.

```
  Installing plugin: metric-converter
  Installing plugin: imperial-converter
  --no-plugin-dir: skipping --plugin-dir workaround, using normal plugin discovery
  Executing: claude --model claude-sonnet-4-20250514 --print "/unit-convert ..."
```

| Category | Plugin-dir mode | Install order | Plugin used | Count |
|----------|----------------|--------------|------------|-------|
| unambiguous | imperial-first | imperial-first | imperial-converter | 30/30 |
| ambiguous-unqualified | imperial-first | imperial-first | imperial-converter | 30/30 |
| qualified-metric | imperial-first | imperial-first | metric-converter | 30/30 |
| qualified-imperial | imperial-first | imperial-first | imperial-converter | 30/30 |
| unambiguous-metric-first | metric-first | imperial-first | metric-converter | 30/30 |
| ambiguous-metric-first | metric-first | imperial-first | metric-converter | 30/30 |
| unambiguous-no-plugin-dir | none | imperial-first | imperial-converter | 30/30 |
| ambiguous-no-plugin-dir | none | imperial-first | imperial-converter | 30/30 |
| unambiguous-no-plugin-dir-metric-first | none | metric-first | metric-converter | 30/30 |
| ambiguous-no-plugin-dir-metric-first | none | metric-first | metric-converter | 30/30 |

### Run 6 — exact-binary installed-order controls (Claude Code 2.1.214, verified)

Credential-free local controls ran the exact Claude Code 2.1.214 binary with
a fresh `CLAUDE_CONFIG_DIR` and a loopback-only API recorder. Plugin names were
chosen so lexical order was alpha then zulu. Each ambiguous control was paired
with both qualified controls.

| Case | Install record order | Marketplace order | `enabledPlugins` key order | Winner |
|------|----------------------|-------------------|----------------------------|--------|
| C | zulu, alpha | alpha, zulu | zulu, alpha | zulu |
| D | alpha, zulu | zulu, alpha | alpha, zulu | alpha |
| E | alpha, zulu | alpha, zulu | zulu, alpha | zulu |

Reversing only marketplace order did not reverse the winner. Reversing only
the final `enabledPlugins` key order did. Retained state files establish
installation-record order independently, and scoped API captures show the
selected fixture content. A separate strace rerun retained the final commands
and interleaved filesystem accesses without treating syscall gaps as proof of
logical serialization.

### Run 7 — swap-order isolation controls (Claude Code 2.1.212, 360 trials, verified)

Same 10 baseline categories as Run 5, plus two new controls that
isolate `enabledPlugins` key order from `installed_plugins.json`
record order. Both controls install imperial-first, metric-second, with
`--no-plugin-dir`.

- **Control A (`unambiguous-swap-enabled-order`):** After installation,
  reversed `enabledPlugins` so metric-converter key appeared first.
  Left `installed_plugins.json` unchanged.
- **Control B (`unambiguous-swap-installed-order`):** After installation,
  reversed `installed_plugins.json` so metric-converter record appeared
  first. Left `enabledPlugins` unchanged.

Pod logs confirm both reversals executed (metric listed first in the
reversed file), and no `--plugin-dir` arguments were present.

| Category | Plugin-dir mode | Swap target | Plugin used | Count |
|----------|----------------|-------------|------------|-------|
| unambiguous | imperial-first | — | imperial-converter | 30/30 |
| ambiguous-unqualified | imperial-first | — | imperial-converter | 30/30 |
| qualified-metric | imperial-first | — | metric-converter | 30/30 |
| qualified-imperial | imperial-first | — | imperial-converter | 30/30 |
| unambiguous-metric-first | metric-first | — | metric-converter | 30/30 |
| ambiguous-metric-first | metric-first | — | metric-converter | 30/30 |
| unambiguous-no-plugin-dir | none | — | imperial-converter | 30/30 |
| ambiguous-no-plugin-dir | none | — | imperial-converter | 30/30 |
| unambiguous-no-plugin-dir-metric-first | none | — | metric-converter | 30/30 |
| ambiguous-no-plugin-dir-metric-first | none | — | metric-converter | 30/30 |
| unambiguous-swap-enabled-order | none | enabledPlugins reversed | imperial-converter | 30/30 |
| unambiguous-swap-installed-order | none | installed_plugins.json reversed | imperial-converter | 30/30 |

**Key finding:** Neither reversal changed the winner. This agrees with the
exact settings merge once the settings scopes are included. `plugin install`
first wrote imperial then metric into user-level `settings.json`. The runner
then copied those IDs into project-local `settings.local.json` and reversed
only that higher-layer object. Deep merge overwrote the existing values but,
under JavaScript object insertion semantics, did not move the key slots first
created by the lower user layer. The effective merged order therefore remained
imperial then metric. Reversing `installed_plugins.json` separately also had no
effect, as predicted by the exact loader.

Run 7 is not a reversal of the effective merged `enabledPlugins` insertion
order. To reverse that order, the lower-layer keys must be removed/reordered or
the controlled IDs must first appear only in the reversed layer. Run 6 used a
single isolated settings layer and exercised that discriminating condition.

## What the data supports

Across 1380 model trials (Runs 1–5 and 7), plus the local exact-binary
controls in Run 6:

1. **Qualified invocations route correctly.** `/metric-converter:unit-convert`
   always dispatched to metric-converter, `/imperial-converter:unit-convert`
   always dispatched to imperial-converter. 360/360 across all runs.

2. **Unqualified `/unit-convert` is deterministic, not random.** When both
   plugins register the same skill name, Claude Code always picked one
   winner consistently. There is no round-robin, random selection, or
   content-aware routing. 1020/1020 unqualified invocations across all runs.

3. **The agent does not disambiguate based on prompt content.** Ambiguous
   prompts like "Convert 100 degrees to the other system" were handled
   identically to unambiguous prompts like "Convert 5 miles to kilometers" —
   both went to the same plugin without consideration of which plugin
   would give a more useful answer.

4. **`--plugin-dir` argument order determines the collision winner.** When
   imperial-converter was the first `--plugin-dir`, imperial won 480/480.
   When metric-converter was first, metric won 180/180. This is a pure
   first-registration-wins model. (Runs 1–5 and 7, verified by pod logs.)

5. **Normal installed-plugin discovery follows effective merged
   `enabledPlugins` insertion order.** Run 5 ruled out fixed alphabetical
   order. Run 6 independently varied effective settings order, marketplace
   order, installation records, and lexical order. Run 7 reversed only a
   higher duplicate settings layer, so lower user-settings insertion slots
   remained unchanged; its imperial winner is the expected result, not a
   contradiction. Reversing `installed_plugins.json` had no effect.

6. **The collision rule is: first plugin to register a skill name owns it
   for unqualified invocations.** With `--plugin-dir`, "first" means CLI
   argument order. With normal discovery, "first" follows effective merged
   `enabledPlugins` insertion order. Normal installation often creates that
   order, but later higher-layer overwrites do not move existing slots.

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
  `src/utils/plugins/pluginLoader.ts` (Claude Code bundle): when a plugin has a
  manifest, `strict` is false, and the marketplace entry declares `skills` or
  another component, the loader records a `generic-error` and returns `null`.
  Session-only plugins supplied through `--plugin-dir` instead go through
  `loadSessionOnlyPlugins()` and do not merge the conflicting marketplace
  component metadata.

  **Initially validated on 2026-07-17 against 2.1.212 and reproduced on
  2026-07-18 against the exact 2.1.214 binary.** Codex ran a network-free local marketplace fixture in
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
  code in `run_skill.sh` should not be necessary. Runs 4 and 5 confirmed
  that normal installed-plugin discovery works with the corrected
  marketplace entries (no `--plugin-dir` needed). Run 5 further ruled out
  alphabetical order. The later exact-binary controls isolated merged
  `enabledPlugins` key insertion order as the proximate source; normal install
  order matters only because installation initially creates those keys in the
  same order.

- **`--output-format stream-json` with `--print`:** The stream parser
  (`stream-claude.py`) was only handling `stream_event` messages. In
  `--print` mode, Claude emits a single `assistant` message with the full
  response instead of streaming `content_block_delta` events. The parser
  needed to handle both paths.

## Conclusion

Skill routing in Claude Code is a CLI-level decision, not an LLM decision.
When two plugins register the same skill name, the resolver picks a winner
before the API request is sent — the model only ever sees one plugin's
SKILL.md. There is no content-aware disambiguation: the prompt "Convert
100 degrees" routes to the same plugin as "Convert 5 miles to kilometers."

The collision rule is **first-registration-wins**. Whichever plugin
registers a skill name first owns that name for all unqualified
invocations. With `--plugin-dir`, "first" is determined by CLI argument
order (proven by reversing it — metric-converter won 180/180 when listed
first). On the normal installed-plugin discovery path, "first" follows the
effective merged `enabledPlugins` insertion order. Run 6 isolated that order.
Run 7 changed a higher duplicate settings layer but left the lower user layer's
original insertion slots intact, so its unchanged winner is consistent with
the exact merge semantics. `installed_plugins.json` is cache/install metadata,
not the ordering producer.

Qualified invocations (`/metric-converter:unit-convert`) bypass the
collision entirely and always route correctly.

Practical implications:

- **Plugin authors** who share a skill name with another plugin cannot
  rely on winning unqualified invocations — the outcome depends on load
  order, which plugin authors cannot control across other users'
  environments. Users can influence it through CLI ordering or
  installation/settings insertion order, but qualified names are the
  reliable path.
- **Users** who care about which plugin handles an ambiguous skill should
  use qualified names.
- **There is no mechanism today** for Claude Code to inspect the prompt
  and pick the more appropriate plugin. That would require a different
  routing architecture — comparing skill descriptions or performing a
  pre-routing LLM call.

## Resolved questions

- **Does CLI argument order or internal alphabetical sort determine the
  collision winner?** CLI argument order. Reversing `--plugin-dir` so
  metric-converter appeared first caused metric-converter to win 180/180.
  Confirmed by Runs 4, 5, and 7 pod logs.

- **Does the collision behavior hold on the normal installed-plugin
  discovery path?** Yes — collisions are deterministic on the normal path.
  Confirmed by Runs 4 and 5 pod logs showing no `--plugin-dir` in the
  `execve`.

- **What determines iteration order on the normal discovery path —
  installation order, settings order, or alphabetical plugin name?**
  Effective merged `enabledPlugins` insertion order. Installation order
  usually establishes first insertion; later higher-scope overwrites do not
  move existing keys. Run 6 varied the effective order. Run 7 did not, because
  its user-settings layer already contained both keys.

## Open questions

- Is there a way to make Claude Code content-aware when routing unqualified
  skill names to competing plugins?
- Would a single plugin with multiple skill variants (e.g.
  `/unit-convert-metric`, `/unit-convert-imperial`) behave differently?
