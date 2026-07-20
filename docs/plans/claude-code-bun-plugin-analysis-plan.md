# Plan: Recover Claude Code Plugin Behavior from the Bun Binary

**Status: Proposed**

## Purpose

Develop a reproducible method for recovering the current Claude Code plugin
discovery, loading, collision-resolution, and execution behavior from an
installed Bun standalone executable. Use the older source tree under
`deleteme/claude-code/` as a semantic map for the minified JavaScript, while
treating the exact binary and observed runtime behavior as authoritative.

The first target is Claude Code 2.1.214:

```text
Binary:   /home/jtanner/.local/share/claude/versions/2.1.214
SHA-256:  3c029136f7c81f54ed4a38e9d52e655aad536433dbbde50519c8c31bb646ad14
Build ID: 788318c9115981678ca1a25f40cdb3b39df71403
Runtime:  Bun 1.4.0, Linux x64 baseline
Format:   x86-64 ELF containing a 178,847,228-byte .bun section
```

The older source tree is an unofficial, unlicensed snapshot and must be used
only as a fallible correspondence aid. Its repository HEAD is currently
`6a2590911df240ff5ea56aa355696cfb94d128cb`; the substantive source snapshot
was introduced by commit `b564857c` on 2026-03-31.

## Evidence model

Use this precedence order for every finding:

```text
actual 2.1.214 execution, debug logs, API bodies, and strace
                              |
                              v
          extracted JavaScript from the 2.1.214 .bun payload
                              |
                              v
      older source snapshot used to explain names and intent
```

The old source can suggest where to look and what a minified block probably
does. It cannot override the exact bundle or actual execution.

Each published claim must state which evidence levels support it. Use these
confidence labels:

| Label | Required evidence |
|-------|-------------------|
| `runtime-confirmed` | Controlled execution, retained command provenance, and debug/strace/API evidence |
| `bundle-confirmed` | Exact bundle logic recovered and matched to stable anchors and control flow |
| `source-correlated` | Old source structurally matches the bundle, but runtime validation is incomplete |
| `hypothesis` | Plausible interpretation requiring a discriminating experiment |

## Questions to answer

The analysis should reconstruct the complete plugin path:

1. How marketplace registration populates `known_marketplaces.json`.
2. How `plugin install` populates the cache, `installed_plugins.json`, and
   `enabledPlugins` settings.
3. How user, project, local, managed, and CLI plugin settings are merged.
4. When the installed-plugin snapshot is initialized relative to command
   discovery in interactive and `--print` modes.
5. How installed marketplace plugins differ from session-only
   `--plugin-dir` plugins.
6. How `plugin.json`, marketplace entries, `strict`, and conventional or
   custom component paths are combined and validated.
7. How root `skills/` directories become namespaced slash commands.
8. How duplicate qualified and unqualified skill names are ordered and
   resolved.
9. Whether ordering comes from CLI arguments, installation order, settings
   insertion order, marketplace order, filesystem order, or an explicit sort.
10. When slash commands are expanded, which skill content is injected, and
    what is sent to the model.
11. Which operations are logically concurrent and what filesystem order is
    observable at the syscall layer.

## Scope and non-goals

The initial scope is the plugin and skill pipeline. Authentication, billing,
browser integration, model routing, and unrelated tools should only be
examined when they directly affect plugin startup or execution.

This work is not intended to recreate or redistribute Claude Code. Do not
commit the installed binary, the extracted `.bun` section, large minified
segments, source maps, bundled prompts, or third-party assets. Commit only:

- Reusable extraction and indexing tools.
- Binary/source manifests containing hashes and offsets.
- Small anchor strings where necessary to identify behavior.
- Pseudocode and concise reconstructed control flow.
- Experiment definitions, retained provenance, and findings.

## Analysis workspace

Keep generated material under the repository's ignored `tmp/` directory:

```text
tmp/claude-code-binary-analysis/2.1.214/
├── input/
│   └── claude
├── manifest/
│   ├── binary.json
│   ├── elf-header.txt
│   ├── sections.txt
│   ├── segments.txt
│   ├── dynamic-dependencies.txt
│   └── source-baseline.json
├── payload/
│   ├── bun-section.bin
│   ├── strings.tsv
│   ├── printable-runs.json
│   └── representations.json
├── anchors/
│   ├── source-anchors.json
│   ├── bundle-hits.json
│   └── correspondences.json
├── segments/
│   ├── raw/
│   ├── formatted/
│   └── pseudocode/
├── traces/
├── fixtures/
└── reports/
```

The version directory must be immutable once its binary hash has been
recorded. A new Claude version gets a new directory and a new manifest.

## Phase 1: Establish binary provenance

Create an inspection script that accepts an explicit binary path and refuses
to proceed unless it is a regular executable file. It should never discover a
binary through an unresolved glob or overwrite an existing version directory
whose recorded hash differs.

Record:

- Absolute source path, size, mode, owner, and modification time.
- SHA-256 and ELF Build ID.
- `claude --version` output.
- `file`, `readelf -h`, `readelf -SW`, `readelf -l`, and `ldd` output.
- Bun and JavaScriptCore identifying strings.
- Tool versions used for extraction.
- Git HEAD and dirty state of `deleteme/claude-code`.

Copy the binary into the ignored analysis workspace before invoking
`objcopy`. This avoids `objcopy` trying to create a temporary file beside the
read-only installed binary.

Example procedure:

```bash
analysis_root=tmp/claude-code-binary-analysis/2.1.214
binary_source=/home/jtanner/.local/share/claude/versions/2.1.214

mkdir -p "$analysis_root/input" "$analysis_root/payload" "$analysis_root/manifest"
cp "$binary_source" "$analysis_root/input/claude"
sha256sum "$analysis_root/input/claude"
objcopy --dump-section .bun="$analysis_root/payload/bun-section.bin" \
  "$analysis_root/input/claude"
```

The script should compare the extracted byte count with the `.bun` size from
the ELF section table and fail if they differ.

## Phase 2: Characterize the Bun payload

The `.bun` section is not a plain JavaScript file. It contains binary records,
large NUL regions, plaintext strings, minified JavaScript, bundled assets, and
an index/trailer ending in the Bun standalone marker. The same anchor can
occur in multiple representations. For example, initial inspection found the
manifest-conflict string at two widely separated offsets.

Do not assume the first string hit is executable application code. Classify
the payload before mapping behavior:

1. Produce an offset-preserving string index with decimal and hexadecimal
   offsets.
2. Identify long printable spans and test whether they parse as JavaScript.
3. Locate Bun record boundaries, embedded filenames, indexes, and the trailer.
4. Group duplicate occurrences of distinctive application strings.
5. Classify each occurrence as one of:
   - Executable minified bundle candidate.
   - Serialized runtime or heap data.
   - Embedded asset or documentation.
   - Third-party dependency.
   - Index or metadata record.
6. Confirm the primary application representation by finding several ordered
   Claude-specific anchors and valid surrounding JavaScript syntax.

Useful offset-preserving commands include:

```bash
strings -a -t d -n 8 payload/bun-section.bin
rg -a --byte-offset -o 'distinctive literal' payload/bun-section.bin
xxd -s OFFSET -l LENGTH payload/bun-section.bin
```

Implement carving as a script rather than a collection of manual byte ranges.
It must retain the original payload start/end offsets in sidecar metadata.

## Phase 3: Build an anchor catalog from the old source

Start with the old modules most likely to define the target behavior:

| Concern | Old source candidates |
|---------|-----------------------|
| CLI option collection | `src/main.tsx` |
| Headless startup timing | `src/main.tsx`, `src/cli/print.ts`, `src/utils/plugins/headlessPluginInstall.ts` |
| Marketplace discovery | `src/utils/plugins/marketplaceManager.ts`, `pluginLoader.ts` |
| Installation state | `src/services/plugins/pluginOperations.ts`, `pluginInstallationHelpers.ts`, `installedPluginsManager.ts` |
| Plugin manifest merging | `src/utils/plugins/pluginLoader.ts`, `schemas.ts` |
| Skill file loading | `src/utils/plugins/loadPluginCommands.ts` |
| Command list construction | `src/commands.ts` |
| Slash-command resolution | `src/utils/processUserInput/processSlashCommand.tsx` |
| Prompt/API expansion | `src/utils/processUserInput/processSlashCommand.tsx`, print/query code |

For each relevant old-source function, extract a semantic fingerprint:

- Exported and local function name.
- Source file and line.
- Ordered distinctive string literals.
- Telemetry and debug event names.
- Environment variables, CLI flags, settings keys, and JSON fields.
- Error types and return shapes.
- Ordered property accesses and important branch predicates.
- Names of directly called functions.

Prefer anchors that are both distinctive and likely to survive minification,
such as:

```text
installed_plugins.json
session-only plugins from --plugin-dir
has conflicting manifests
plugin-cache-miss
Unknown command:
<command-message>
slash_commands
enabledPlugins
```

Avoid relying on common words or minified function names. Store anchors in a
machine-readable catalog and record every bundle hit, not only the preferred
one.

## Phase 4: Create old-build training pairs

If dependencies can be installed in an isolated environment, build the old
source in two forms:

1. An unminified bundle with a source map.
2. A production-minified bundle.

The old tree provides `scripts/build-bundle.ts`, `bun.lock`, and a production
build path. Pin all dependency and tool versions; do not silently resolve newer
packages. Record any deviation from the original build chain.

The resulting pair provides a supervised example of how recognizable source
structures become minified:

```text
old TypeScript -> old unminified bundle -> old minified bundle
                                              |
                                              v
                                exact 2.1.214 minified bundle
```

Use the old source map to learn:

- Module wrapper patterns.
- How exported functions and initializers are represented.
- Which identifiers survive.
- How async branches, `Promise.all`, schema definitions, and error objects are
  transformed.
- Which bundle neighborhoods correspond to each old module.

This phase is an aid, not a prerequisite. If the old build cannot be reproduced
without unpinned or unavailable internal dependencies, record the limitation
and continue with literal/control-flow matching.

## Phase 5: Map minified 2.1.214 code to source concepts

For each target behavior:

1. Select three or more ordered anchors from the old function or module.
2. Locate all occurrences in the exact `.bun` payload.
3. Select candidate neighborhoods that contain the anchors in compatible
   order and valid JavaScript.
4. Carve the smallest parseable region containing the relevant module
   initializer, function, or call chain.
5. Format the segment with a pinned JavaScript formatter/parser.
6. Compare its branch structure with the old source.
7. Assign descriptive aliases to minified identifiers only after their role is
   supported by multiple observations.
8. Write pseudocode preserving branch order, collection order, awaits, early
   returns, mutations, and error handling.
9. Record differences from the old source explicitly.

Each correspondence record should resemble:

```json
{
  "topic": "marketplace manifest conflict",
  "binary_sha256": "3c029136...",
  "payload_offset_start": 38800000,
  "payload_offset_end": 38900000,
  "anchor_hits": [
    "has conflicting manifests",
    "generic-error"
  ],
  "old_source": {
    "file": "src/utils/plugins/pluginLoader.ts",
    "function": "finishLoadingPluginFromPath",
    "commit": "b564857c"
  },
  "mapping_confidence": "bundle-confirmed",
  "differences": []
}
```

Offsets in examples are illustrative; generated records must contain exact
values.

## Phase 6: Reconstruct the plugin pipeline

Recover and document the pipeline in dependency order rather than examining
isolated functions:

```text
CLI parsing
   |
   v
settings and enabledPlugins merge
   |
   +--> installed marketplace discovery --> cache/install metadata
   |
   +--> --plugin-dir session-only discovery
   |
   v
plugin manifest and component resolution
   |
   v
SKILL.md enumeration and command construction
   |
   v
qualified/unqualified command lookup
   |
   v
skill expansion and API request construction
```

For every collection in this path, determine:

- The producer and consumer.
- Whether it is an array, object, map, or set.
- Insertion and iteration order.
- Any explicit `sort`, filesystem glob, or deduplication step.
- Whether `Promise.all` or another concurrency primitive preserves result
  order while allowing overlapping work.
- Which source wins when installed and session-only versions duplicate one
  another.
- Where errors are accumulated versus thrown.

The output should be a concise reconstructed module map plus pseudocode for
the critical order-sensitive functions.

## Phase 7: Validate with controlled runtime experiments

Every order or precedence claim needs an experiment that varies one factor at
a time. Use minimal plugins with unmistakable JSON outputs and retain the
actual final `execve` command.

### Discovery and manifest matrix

| Case | Plugin manifest | Marketplace components | `strict` | Expected question |
|------|-----------------|------------------------|----------|-------------------|
| A | Present | None | omitted | Does conventional root `skills/` load? |
| B | Present | `skills` declared | `false` | Is the plugin rejected as conflicting? |
| C | Absent | `skills` declared | `false` | Does the marketplace act as the manifest? |
| D | Present | Custom `skills` in plugin manifest | omitted | Is the custom path authoritative or additive? |
| E | Present | None | omitted | Does `.claude/skills/` load without declaration? |

### Collision-order matrix

Use plugin names whose alphabetical order differs from every other ordering
factor. Run both ambiguous and unambiguous prompts.

| Case | Install order | Marketplace order | `enabledPlugins` order | `--plugin-dir` order |
|------|---------------|-------------------|------------------------|----------------------|
| A | A, B | A, B | A, B | A, B |
| B | A, B | A, B | A, B | B, A |
| C | B, A | A, B | B, A | none |
| D | A, B | B, A | A, B | none |
| E | A, B | A, B | explicitly reversed | none |

Cases C through E are required before describing normal installed-plugin
discovery as alphabetical, installation-ordered, settings-ordered, or
marketplace-ordered.

### Required evidence per trial

- Binary version and hash.
- Container image digest or host environment manifest.
- Marketplace and plugin repository commits.
- Installation and settings files after setup.
- Final command line from pod log and `strace` `execve`.
- `--debug-file` plugin and skill loading messages.
- Relevant `statx`, `openat`, and `read` ordering from strace.
- `stream-json` init message command/skill lists.
- API request body showing command qualification and injected skill content.
- Parsed response identifying the selected plugin.

Do not infer logical serialization solely from a gap between syscalls. Strace
is authoritative about observed syscall order; the recovered JavaScript is
needed to determine whether tasks were scheduled concurrently and whether
their result order was preserved.

## Phase 8: Build a claim ledger

Maintain a machine-readable ledger so conclusions can be reevaluated against
new Claude versions:

```yaml
- id: plugin-collision-inline-first-registration
  claim: The first session-only plugin to register an unqualified skill wins.
  binary:
    version: 2.1.214
    sha256: 3c029136...
  bundle:
    offsets: []
    anchors: []
  old_source:
    files: []
    commit: b564857c
  runtime:
    runs: []
    strace_artifacts: []
  verdict: runtime-confirmed
  limitations: []
```

Separate observation from interpretation. For example:

```text
Observation: imperial was installed first and won 60/60 without plugin-dir.
Unsupported interpretation: normal discovery is alphabetical.
Missing control: reverse installation/settings order without plugin-dir.
```

## Phase 9: Compare future versions

Once 2.1.214 is mapped, analyze a new binary incrementally:

1. Create a new immutable version workspace and manifest.
2. Re-run the anchor catalog against the new `.bun` section.
3. Compare anchor multiplicity and neighborhood hashes.
4. Re-carve only changed target modules.
5. Diff formatted segments structurally, not merely by minified names.
6. Re-run only experiments affected by changed branches or ordering.
7. Carry forward unchanged claims only when their bundle fingerprints and
   runtime preconditions still match.

This turns the old source snapshot into a one-time bootstrap aid and the
2.1.214 mappings into the baseline for later binary-to-binary analysis.

## Proposed tooling

Add a small, self-contained toolset under:

```text
scripts/claude_binary_analysis/
├── inspect_binary.sh
├── extract_bun_section.sh
├── index_payload.py
├── build_source_anchors.py
├── match_anchors.py
├── carve_segment.py
├── format_segment.sh
├── compare_segments.py
└── validate_claims.py
```

Tool requirements:

- Explicit input and output paths.
- Refuse accidental overwrites unless hashes match.
- Preserve byte offsets through every transformation.
- Emit JSON sidecars for generated artifacts.
- Avoid network access during analysis.
- Never read credential files or include environment dumps.
- Include fixture-based tests using a small locally compiled Bun executable,
  not the proprietary Claude binary.

Prefer standard tools already available on the host (`file`, `readelf`,
`objcopy`, `nm`, `strings`, `xxd`, `rg`, and `jq`). Pin any formatter or parser
introduced for JavaScript analysis.

## Deliverables

1. Reproducible extraction and payload-indexing scripts.
2. A manifest for Claude Code 2.1.214 and the old source baseline.
3. An anchor catalog for the plugin subsystem.
4. Offset-preserving correspondences between old source concepts and exact
   2.1.214 minified segments.
5. Pseudocode for plugin discovery, loading, command resolution, and skill
   expansion.
6. A controlled experiment suite covering manifest ownership, custom skill
   paths, installed discovery order, and `--plugin-dir` order.
7. A claim ledger connecting binary offsets, source correspondences, runtime
   runs, strace artifacts, and conclusions.
8. A concise report under `docs/notes/` and corrections to the skill
   disambiguation findings where warranted.

## Acceptance criteria

The initial analysis is complete when:

- The extraction is repeatable from the original binary and reproduces the
  recorded `.bun` hash and size.
- The primary minified application representation has been distinguished from
  duplicate serialized or asset representations.
- The critical plugin-loading blocks have exact offsets and at least three
  stable anchors each.
- Reconstructed pseudocode accounts for collection ordering, asynchronous
  boundaries, manifest conflicts, error handling, and command lookup.
- Every behavioral conclusion is backed by the exact bundle, a controlled
  runtime experiment, or is explicitly labeled as incomplete.
- Normal installed-plugin ordering has been tested with installation,
  marketplace, settings, and alphabetical order varied independently.
- The report contains no committed binary, large proprietary code excerpt,
  credential, token, or raw environment dump.
- A second binary version can be analyzed by rerunning the documented process
  rather than starting over manually.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Old source differs materially from 2.1.214 | Treat it as an index only; require bundle/runtime confirmation |
| Multiple copies of strings cause false matches | Require ordered multi-anchor matches and parseable JavaScript context |
| Minification or tree shaking erases module boundaries | Use semantic fingerprints, call chains, telemetry strings, and old-build training pairs |
| Bun payload format changes | Keep extraction/version logic manifest-driven and test each version independently |
| Runtime setup accidentally varies more than one factor | Use generated fixtures and record final commands, settings, commits, and hashes |
| Strace order is overinterpreted | Distinguish syscall observation from JavaScript scheduling and result ordering |
| Extracted material is accidentally committed | Keep raw data under ignored `tmp/`; add explicit pre-commit checks for analysis paths |
| Analysis exposes secrets from runtime logs | Filter from the end-of-environment marker and retain only scoped debug/trace events |
| Unofficial source is mistaken for authoritative source | Label its origin and commit in every correspondence and finding |

## First implementation slice

The first slice should stay narrow and prove the method end to end:

1. Implement binary manifest generation and `.bun` extraction.
2. Index the payload and classify the duplicate manifest-conflict anchors.
3. Map the exact 2.1.214 manifest-conflict block to old
   `finishLoadingPluginFromPath()`.
4. Recover pseudocode for that block.
5. Link it to the existing failing and corrected marketplace controls.
6. Add one claim-ledger entry with binary offsets, old-source lines, runtime
   evidence, and limitations.

After that slice is reproducible, expand outward to installed-plugin loading,
skill enumeration, collision order, and slash-command execution.
