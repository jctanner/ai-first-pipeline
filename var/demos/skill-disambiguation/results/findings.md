# Skill Disambiguation Experiment — Findings

Run: `markov-run-a481f69d`
Date: 2026-07-17
Model: `claude-sonnet-4-20250514`
Trials per prompt: 10 (120 total across 4 categories x 3 prompts)

## Results

| Category | Plugin used | Count | Rate |
|----------|------------|-------|------|
| unambiguous | imperial-converter | 30/30 | 100% |
| ambiguous-unqualified | imperial-converter | 30/30 | 100% |
| qualified-metric | metric-converter | 30/30 | 100% |
| qualified-imperial | imperial-converter | 30/30 | 100% |

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

### Predicting collision winners — open question

Imperial-converter wins every unqualified invocation. Two hypotheses remain:

1. **CLI arg order** — Claude Code processes `--plugin-dir` in the order
   given on the command line. Imperial appears first because the shell glob
   iterates alphabetically (`i` before `m`). Reversing the CLI order would
   reverse the winner.

2. **Internal alphabetical sort** — Claude Code sorts plugin directories
   internally regardless of CLI argument order. Imperial would always win
   because its name sorts first.

Both hypotheses produce the same result when the CLI order is alphabetical.
A follow-up experiment with reversed `--plugin-dir` order is needed to
distinguish them.

## Issues discovered during setup

- **Plugin skill directory:** Plugins must use `skills/` at the plugin root,
  not `.claude/skills/`. The latter is for project-level skills only. Plugins
  with `.claude/skills/` load (appear in `plugins` list) but their skills are
  not discovered.

- **Plugin discovery in `--print` mode:** Plugins installed via
  `claude plugin install` and enabled in `settings.json` (`enabledPlugins`)
  are not discovered in `--print` mode. Passing `--plugin-dir` explicitly
  for each installed plugin is required as a workaround.

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
