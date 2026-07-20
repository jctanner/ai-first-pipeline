# Claude Bun binary analysis tools

These tools recover small, evidence-scoped plugin control-flow regions from a
Bun standalone executable. Generated binaries, payloads, formatted segments,
and traces belong only under the ignored `tmp/claude-code-binary-analysis/`
tree. Do not commit them.

## Reproduce the 2.1.214 baseline

Run from the repository root with explicit inputs:

```bash
root=tmp/claude-code-binary-analysis/2.1.214
binary=/home/jtanner/.local/share/claude/versions/2.1.214

scripts/claude_binary_analysis/inspect_binary.sh \
  "$binary" "$root" deleteme/claude-code
scripts/claude_binary_analysis/extract_bun_section.sh "$root"
scripts/claude_binary_analysis/index_payload.py \
  "$root/payload/bun-section.bin" "$root/payload"
scripts/claude_binary_analysis/build_source_anchors.py \
  deleteme/claude-code "$root/anchors/source-anchors.json"
scripts/claude_binary_analysis/match_anchors.py \
  "$root/payload/bun-section.bin" \
  "$root/anchors/source-anchors.json" \
  "$root/payload/representations.json" \
  "$root/anchors/bundle-hits.json" \
  "$root/anchors/correspondences.json" \
  --binary-manifest "$root/manifest/binary.json"
```

`inspect_binary.sh` makes the version workspace immutable by recorded binary
hash. `extract_bun_section.sh` verifies the ELF section size and refuses a
different existing payload. `carve_segment.py` records exact source offsets
and hashes in a JSON sidecar. Format only deliberately carved small segments:

```bash
scripts/claude_binary_analysis/carve_segment.py \
  "$root/payload/bun-section.bin" "$root/segments/raw/topic.js" \
  --start OFFSET --end OFFSET --topic topic
scripts/claude_binary_analysis/format_segment.sh \
  "$root/segments/raw/topic.js" "$root/segments/formatted/topic.js" \
  tmp/claude-code-binary-analysis/tooling/node_modules/.bin/prettier
```

The formatter must report exactly Prettier 3.6.2. `compare_segments.py`
normalizes identifiers, strings, and numbers for a coarse structural diff; it
does not establish semantic equivalence by itself.

## Runtime controls

The experiment runner creates a fresh `CLAUDE_CONFIG_DIR`, local fixture
marketplaces, deterministic fixed-date Git commits covering every marketplace
and plugin fixture, and a loopback-only Anthropic response server. It inherits
no credential, retains only fixture/command-bearing request strings, and
requires Claude Code to parse each mock SSE response to a successful result:

```bash
scripts/claude_binary_analysis/run_plugin_experiments.py \
  --strace "$binary" "$root/traces/local-manifest-state-strace-v1"
```

The output directory is immutable. Use a new name for every rerun. Binding the
loopback server and using `strace` may require local sandbox approval.
`experiment.json` and `collision-matrix.json` record fixture commit/tree IDs;
`results.json` summarizes every command and selected marker. Each command
directory retains argv, debug/stdout/stderr output, raw strace, and extracted
`execve` records.

## Tests and commit checks

```bash
BUN_BIN=/path/to/pinned/bun \
  python3 -m unittest discover -s scripts/claude_binary_analysis/tests -v
python3 scripts/claude_binary_analysis/validate_claims.py \
  docs/notes/claude-code-2.1.214-plugin-claims.json --check-paths
python3 scripts/claude_binary_analysis/check_commit_safety.py
```

The Bun fixture test was verified with public Bun 1.3.14. The analyzed target
identifies itself as Bun 1.4.0, which was not a public Bun release when this
baseline was produced. The safety check rejects staged raw analysis paths,
NUL-containing files, analysis deliverables over 1 MiB, and common token
shapes.

## A later Claude version

Choose a new version directory, run the same inspection/index/anchor commands,
compare `representations.json` and anchor multiplicity, and re-carve only
changed neighborhoods. Carry a claim forward only when its exact bundle
fingerprint and runtime preconditions still match. Never reuse or overwrite a
workspace whose manifest has a different binary hash.
