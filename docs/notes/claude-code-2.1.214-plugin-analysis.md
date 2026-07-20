# Claude Code 2.1.214 Bun plugin analysis

## Outcome

Claude Code 2.1.214 resolves plugin skill collisions deterministically before
calling the model. Normal installed plugins are ordered by the insertion order
of keys in the merged `enabledPlugins` object. Session-only plugins are ordered
by `--plugin-dir` argument order. The first command whose qualified name,
display name, or alias matches wins an unqualified lookup; a qualified
`plugin:skill` name selects that exact command.

This conclusion is supported by exact target-bundle control flow and fresh,
credential-free runtime controls in which installation order, marketplace
order, settings order, CLI order, and lexical plugin order were varied. It
corrects the earlier narrower conclusion that normal order was merely
“derived from installation state.”

The authoritative target is:

```text
Claude Code       2.1.214
Binary SHA-256    3c029136f7c81f54ed4a38e9d52e655aad536433dbbde50519c8c31bb646ad14
ELF Build ID      788318c9115981678ca1a25f40cdb3b39df71403
.bun size         178,847,228 bytes
.bun SHA-256      a94ea3ca79d28c95a009cbdbed9962e300e9c0de6118d16380bd6f46a35440f5
```

Machine-readable provenance is in
`docs/notes/claude-code-2.1.214-binary-manifest.json`; exact function ranges
are seeded by the 12-topic catalog in
`docs/notes/claude-code-2.1.214-plugin-anchor-catalog.json`; exact function
ranges and hashes are in
`docs/notes/claude-code-2.1.214-plugin-correspondences.json`; the claim ledger
is `docs/notes/claude-code-2.1.214-plugin-claims.json`.

## Method and evidence boundary

The `.bun` section is not plain JavaScript. The index found 183,441 printable
runs and 42 long runs. The primary application representation is the
20,157,336-byte CommonJS span `[152220936, 172378272)`, hash
`a62b69a387ee62aa779c37242ef51aa861fb52550decf144c085853939050078`.
It begins with Bun's CommonJS wrapper and contains seven ordered,
Claude-specific plugin and slash-command anchors.

The manifest-conflict literal illustrates why representation classification
matters: its first occurrence, at `38812961`, sits in a NUL-rich serialized
record; the executable occurrence is at `161265125` inside the primary span.
No conclusion selected a hit merely because it appeared first.

Evidence was applied in this order:

1. Controlled execution, parsed loopback API responses, debug output, and strace.
2. Exact JavaScript/control flow carved from the 2.1.214 payload.
3. The unofficial old snapshot at commit
   `6a2590911df240ff5ea56aa355696cfb94d128cb` as a semantic index only.

The old build was probed in an isolated `/tmp` clone with its pinned Bun 1.1.0.
Locked dependency installation succeeded after supplying the pinned executable
to install scripts, but the bundle build failed on omitted generated/internal
modules and packages absent from the snapshot's declared build inputs. No
externalization or source edits were used to manufacture a misleading
training pair. Literal and control-flow correspondence therefore remained the
authoritative static technique.

## Reconstructed pipeline

```text
settings cascade: user -> project -> local -> flag -> policy
        |
        v
Object.entries(merged.enabledPlugins) ----------+
        |                                        |
        v                                        |
installed marketplace load                      |
                                                 +--> Promise.all source loading
--plugin-dir specs in CLI order -----------------+        |
skill-folder and built-in plugins ---------------+        v
                                              source precedence merge
                                                        |
                                                        v
manifest + conventional/custom component resolution
                                                        |
                                                        v
concurrent SKILL.md reads -> per-directory name sort
                                                        |
                                                        v
ordered command array -> Array.find(first match)
                                                        |
                                                        v
qualified command metadata + one expanded skill -> API
```

Detailed order- and error-preserving pseudocode is in
`docs/notes/claude-code-2.1.214-plugin-pseudocode.md`.

## Answers to the analysis questions

### 1. Marketplace registration

The exact registration function normalizes local paths, applies enterprise
source policy before filesystem/network work, treats an already materialized
exact source idempotently, loads and validates the catalog, and writes:

```json
{
  "marketplace-name": {
    "source": {},
    "installLocation": "/absolute/materialized/path",
    "lastUpdated": "timestamp"
  }
}
```

Name collisions overwrite the prior record unless reserved/managed policy
blocks them. Cleanup of an overwritten materialization occurs only when the
old path is inside the expected cache root; a suspicious outside path is left
alone and logged. The marketplace cache is then invalidated. This is
bundle-confirmed at `[161170925,161172738)` and exercised by the local fixture
registration.

### 2. `plugin install` state

The exact install path first resolves policy and a version-aware transitive
dependency closure. It writes the proposed closure to the selected scope's
`enabledPlugins` object in one settings action, then materializes/cache-
registers the closure. A materialization error triggers a settings rollback;
successful materialization is followed by `defaultEnabled` corrections and
cache invalidation. The CLI wrapper then reports the installed plugin and any
dependency/default-disabled note.

The helper is exact at `[161215646,161224391)` and its CLI wrapper at
`[164811776,164815186)`. Fresh snapshots retain the settings and
`plugins/installed_plugins.json` transitions after every install. A successful
install can still produce a later discovery-time load error, as the conflicting
manifest fixture demonstrates.

### 3. Settings merge

The target's enabled-source order is exactly:

```text
userSettings, projectSettings, localSettings, flagSettings, policySettings
```

Here `flagSettings` is the CLI/flag layer and `policySettings` is the managed
policy layer. Plugin defaults sit below that cascade. Later scalar/object values win. Arrays
are unioned/deduplicated except designated replacement fields such as
`fallbackModel`. JavaScript object property position comes from first
insertion: overwriting an existing `enabledPlugins` key does not move it.
Policy therefore wins the value without necessarily moving the key's ordering
slot.

### 4. Installed snapshot startup timing

The exact startup call chain obtains the initial command list and records its
loaded checkpoint before starting versioned installed-plugin initialization.
Interactive startup fires that initialization without awaiting it. Print/
headless startup also starts afterward, then registers cleanup that awaits it
before process exit. Both modes therefore discover their initial commands from
the pre-existing snapshot; synchronization affects a refresh or later session.

This differs from comments/shape in the older snapshot and is
`bundle-confirmed`; the interactive branch was not separately driven through
a terminal trial.

### 5. Installed versus session-only plugins

Installed plugins are produced from `Object.entries(enabledPlugins)`. Catalog
and plugin work overlaps, but `Promise.allSettled` results are consumed in that
input order. Cache-only startup uses `installed_plugins.json` paths and emits
non-fatal cache-miss/not-installed errors instead of fetching.

Session specifications are all mapped through `Promise.all`; results preserve
CLI argument order. They support local paths, URLs, and ZIP archives. During
source merge, enabled session copies precede and replace same-name installed
copies, except policy-managed names cannot be bypassed. A disabled session
copy does not replace an installed one. Skill-folder pseudo-plugins follow,
then built-ins.

### 6. Manifest and component ownership

The controlled matrix produced these target results:

| Case | Result |
|---|---|
| A: manifest, no declared components | Conventional root `skills/` loaded |
| B: manifest plus marketplace `skills`, `strict:false` | Plugin installed but load rejected as conflicting |
| C: no manifest, marketplace `skills`, `strict:false` | Marketplace acted as the manifest; skill loaded |
| D: manifest custom `skills` plus conventional root | Both custom and conventional skills loaded |
| E: manifest plus only undeclared `.claude/skills/` | Plugin loaded; that skill did not register |

Case D corrects the older documentation: custom plugin skill paths are
additive in 2.1.214, not authoritative over the conventional root. Manifest
and non-strict marketplace declarations of the same component ownership are
instead a fatal conflict. The target also handles themes and warning
propagation beyond the older source function.

### 7. Root skill enumeration

A direct `skills/SKILL.md` uses its frontmatter name or directory basename.
Child `skills/<child>/SKILL.md` files become qualified
`plugin:<frontmatter-name-or-child>`. Only regular files at or below the 1 MiB
limit are loaded. Child reads overlap, errors are logged and skipped, and the
valid directory result is explicitly sorted by qualified skill name with
`localeCompare`.

Custom paths are processed alongside the conventional path. Canonical-realpath
deduplication keeps the first preserved occurrence.

### 8–9. Duplicate names and their ordering source

The target's lookup predicate is:

```text
qualified name equals input
OR user-facing name equals input
OR aliases contains input
```

It is passed to `Array.find`, so the first matching command wins. The relevant
base command order is:

```text
skill-directory, workflow, plugin-command, plugin-skill,
bundled-skill, builtin-plugin-skill, builtin-command
```

A later filter removes only fallback skills whose suffix conflicts with a
qualified plugin/MCP suffix; it does not globally sort or deduplicate plugin
skills.

For plugin skills, each directory is sorted internally, but plugin-level
results retain their input plugin order. Installed input order is merged
`enabledPlugins` insertion order. Session input order is CLI argument order.
Marketplace catalog order and raw filesystem order do not reorder either.

### 10. Slash expansion and model input

Slash input is resolved locally. The selected prompt command is expanded,
hooks and invoked-skill metadata are registered, and two relevant user-side
messages are constructed: qualified command metadata and the expanded content
of the one selected skill, including base-directory context, argument and
plugin/session substitutions, attachments, and permission metadata. Only then
is the request sent.

The loopback server retained only fixture-bearing request strings and returned
a minimal valid Anthropic SSE response naming the selected marker. Claude Code
parsed every probe to a successful result with the expected qualified
selection and marker for all installed, inline, and qualified controls. The
model is not asked to arbitrate a collision.

### 11. Concurrency and observed filesystem order

The bundle uses `Promise.all` or `allSettled` for marketplace/session/skill-
folder source loading, installed entries, session specifications, plugins,
custom paths, and directory entries. These tasks can overlap while their
result arrays preserve input order. Non-fatal failures are accumulated in the
corresponding input/result pass.

The strace rerun observed interleaved `statx`, `openat`, and `read` activity
for both collision plugins across processes/threads. It also captured the
final command transcript containing the resolved qualified command. Those
syscalls establish observed access/interleaving only; the logical concurrency
claim comes from the exact Promise control flow.

## Collision controls

The installed controls used names with lexical order `alpha, zulu`:

| Case | Install order | Marketplace order | `enabledPlugins` order | Ambiguous winner |
|---|---|---|---|---|
| A | alpha, zulu | alpha, zulu | alpha, zulu | alpha |
| B | zulu, alpha | alpha, zulu | alpha, zulu | alpha |
| C | zulu, alpha | alpha, zulu | zulu, alpha | zulu |
| D | alpha, zulu | zulu, alpha | alpha, zulu | alpha |
| E | alpha, zulu | alpha, zulu | zulu, alpha | zulu |

Against baseline A, case B reverses installation alone and does not reverse
the winner, case D reverses marketplace alone and does not, and case E
reverses settings alone and does. Cases C/E rule out alphabetical order; the
retained `installed_plugins.json` files separately prove installation record
order. Qualified alpha and zulu controls selected the named plugin in every
case.

The later containerized Run 7 reversed only project-local `enabledPlugins`
after `plugin install` had already inserted the same IDs into lower user
settings. It therefore did not reverse the effective merged insertion order:
overwriting an existing JavaScript object property changes its value, not its
slot. Its unchanged imperial winner is consistent with this reconstruction.
That run independently confirms that reversing only `installed_plugins.json`
does not reorder discovery.

For session-only plugins, `zulu, alpha` CLI order selected zulu and the reverse
selected alpha. This independently agrees with the earlier Markov trials while
removing authentication and remote-service variables.

## Reproducibility and limitations

The reusable commands and future-version procedure are documented in
`scripts/claude_binary_analysis/README.md`. Tests cover injected ELF sections,
a locally compiled public Bun 1.3.14 standalone, duplicate representation
classification, offset-preserving immutable carving, ledger validation, and
commit safety. The target identifies as Bun 1.4.0, but no public 1.4.0 release
was available; this does not affect extraction from the target, only exact
compiler fixture parity.

Generated `.bun` data, formatted proprietary segments, scoped API captures,
and raw strace remain under ignored `tmp/`. No binary, large proprietary code
excerpt, credential, token, environment dump, or full API request is committed.
The loopback runner constructs a fixed environment and records keys/policy,
not values.

The final run is
`tmp/claude-code-binary-analysis/2.1.214/traces/local-manifest-state-strace-v4`.
Its primary marketplace/plugin fixture repository is clean at commit
`8ce7a29b0e1cf22208e1f9afed47231a37eeba69`; each collision trial records its
own clean fixture commit. All 45 commands exited successfully, all 21 API
probes completed as parsed Anthropic SSE results, and each command retains its
final `execve` transcript plus the underlying file/process/read/write strace.

Remaining incomplete areas are deliberately labeled:

- The full Bun serialization format was not reverse engineered beyond the
  representation classification necessary for reliable bundle selection.
- Interactive startup timing is exact-bundle confirmed, not runtime-driven
  through an interactive terminal control.
- Policy-managed collision behavior is exact-bundle confirmed but was not
  mutated on the host.
- The old snapshot cannot currently produce a faithful training-pair build
  without unavailable/generated sources; forcing externalization would weaken
  the comparison.

## Acceptance audit

| Criterion | Result |
|---|---|
| Repeat extraction from original binary | Pass: copied input remains at binary hash `3c0291…`; repeated `.bun` extraction remains 178,847,228 bytes at `a94ea3…` |
| Distinguish duplicate payload representations | Pass: NUL-rich serialized hit and primary CommonJS hit classified separately |
| Critical blocks have exact offsets and at least three anchors | Pass: ten correspondence groups record exact ranges, hashes, and 3–7 stable anchors |
| Pseudocode preserves ordering, awaits, conflicts, errors, and lookup | Pass: dedicated pseudocode document and 11 validated ledger claims |
| Behavioral conclusions evidence-labeled | Pass: runtime-, bundle-confirmed, or explicitly incomplete in the machine-readable ledger |
| Installation, marketplace, settings, CLI, and lexical orders varied | Pass: Git-pinned local Cases A–E isolate baseline, install, marketplace, and settings order; session reversals isolate CLI order; Run 7's settings-scope precondition is reconciled explicitly |
| No committed raw binary, payload, secrets, or environment dump | Pass: raw material remains ignored; explicit commit-safety checker passes scoped deliverables |
| Later version is rerunnable | Pass: manifest-driven commands and incremental comparison procedure are documented with fixture tests |
