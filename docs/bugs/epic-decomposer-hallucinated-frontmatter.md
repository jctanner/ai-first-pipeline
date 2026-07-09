# Epic Task Frontmatter Corrupted After Decompose

## Summary

Markdown artifacts under `artifacts/epic-tasks/` currently have frontmatter
fields that do not match the `epic-task` schema expected by `epic-creator`'s
`scripts/submit.py`.

The bad frontmatter prevents `epic_submit` from creating Jira epics and also
breaks downstream discovery/codegen because the required `type` field is
missing.

Initial suspicion was that `epic-decompose` hallucinated the wrong schema. Newer
evidence from the latest run points elsewhere: the decompose job claimed the
epic files validated successfully, while the files on the PVC were modified
later during `epic-codegen`. The likely current root cause is that the
`epic-codegen` skill updates the same `artifacts/epic-tasks/*.md` files using a
different frontmatter schema and corrupts the `epic-task` contract.

## Observed Impact

The current artifacts on the `pipeline-artifacts` PVC include:

- `/app/artifacts/epic-tasks/RHAISTRAT-1-E001.md`
- `/app/artifacts/epic-tasks/RHAISTRAT-1-E002.md`
- `/app/artifacts/epic-tasks/RHAISTRAT-1-E003.md`

Each file has unknown frontmatter fields:

```text
blocks
codegen_branch
components
effort_size
jira_status
pr_url
readiness_score
status
strategy_key
target_branch
target_repo
```

Each file is also missing required `epic-task` fields:

```text
component
parent_strat
priority
team
type
```

Example from `RHAISTRAT-1-E001.md`:

```yaml
---
epic_id: RHAISTRAT-1-E001
title: Core rhai-cli diagnose subcommand with P0 health checks
strategy_key: RHAISTRAT-1
target_repo: https://github.com/red-hat-data-services/odh-cli.git
status: Generated
dependencies: []
target_branch: ''
components: null
blocks: null
effort_size: null
readiness_score: null
codegen_branch: epic/RHAISTRAT-1-E001
pr_url: null
jira_status: null
---
```

## Expected Schema

`/tmp/epic-creator-submit/scripts/artifact_utils.py` defines
`SCHEMAS["epic-task"]`. Required fields are:

```text
epic_id
title
parent_strat
component
team
type
priority
```

Valid top-level optional fields include:

```text
implementation_type
dependencies
ai_signals
investigation_signals
ai_implementability
ai_implementability_score
jira_key
branch
gated_by
gate_failure_impact
```

`submit.py` uses strict schema validation and rejects unknown fields.

## Downstream Failure

The `run-epic-codegen` discovery step reads `type` from each epic artifact:

```python
epic_type = meta.get("type", "unknown")
```

Because `type` is absent, all epics are classified as `unknown` and skipped.

Observed in `markov-run-b9fd31d1` logs:

```text
Found: RHAISTRAT-1-E001 key= type=unknown
Skipping unknown type: unknown
Found: RHAISTRAT-1-E002 key= type=unknown
Skipping unknown type: unknown
Found: RHAISTRAT-1-E003 key= type=unknown
Skipping unknown type: unknown
```

The result is no investigation epics, no implementation epics, and no useful
codegen fan-out.

## Updated Timeline and Attribution

The latest successful decompose job was:

```text
epic-decompose-rhaistrat-1-opus-0709-025807
```

It completed at:

```text
2026-07-09T03:12:07Z
```

The decompose run report says:

```yaml
started: '2026-07-09T02:58:32Z'
completed: '2026-07-09T03:12:07Z'
batch_size: 25
total: 1
results:
- strat_id: RHAISTRAT-1
  status: passed
  epic_count: 3
  score: 14
```

Captured decompose API bodies show the decompose/revision/re-review agents
explicitly believed the frontmatter was valid:

```text
The batch-read confirms the epic file is consistent with the decomposition summary:
- `epic_id`: RHAISTRAT-1-E001 -- matches
- `type`: Implementation -- matches
- `priority`: P0 -- matches
- `dependencies`: [] (none, single epic) -- matches
- `parent_strat`: RHAISTRAT-1 -- correct
```

The revision agent also stated:

```text
All epic files have valid frontmatter with all required fields -- Confirmed.
All three epics validate successfully with `frontmatter.py read`.
```

The re-review then passed:

```text
The decomposition scored 14/14 with no issues and a recommendation to accept.
```

The current bad files on the PVC have later modification times:

```text
2026-07-09 03:52:44 /app/artifacts/epic-tasks/RHAISTRAT-1-E001.md
2026-07-09 03:45:53 /app/artifacts/epic-tasks/RHAISTRAT-1-E002.md
2026-07-09 03:49:54 /app/artifacts/epic-tasks/RHAISTRAT-1-E003.md
```

Those timestamps are after decompose completed and overlap with the
`epic-codegen-*` jobs.

The `epic-codegen-rhaistrat-1-e001-opus-0709-031243-vllkd` log includes:

```bash
python3 /tmp/skills/opendatahub-io-epic-code-gen/scripts/frontmatter.py set \
  /tmp/skills/opendatahub-io-epic-code-gen/artifacts/epic-tasks/RHAISTRAT-1-E001.md \
  status=Generated codegen_branch=epic/RHAISTRAT-1-E001
```

This strongly suggests codegen touched the same epic artifact after decompose.
The observed invalid fields (`status`, `codegen_branch`, `target_repo`,
`target_branch`, `pr_url`, `jira_status`, etc.) look like codegen/runtime status
metadata, not decomposition metadata.

## Evidence Commands

List current epic artifacts:

```bash
kubectl -n ai-pipeline exec pipeline-dashboard-59d8d7cd84-tdn5x -- \
  find /app/artifacts/epic-tasks -maxdepth 1 -type f -name '*.md' -print
```

Inspect frontmatter:

```bash
kubectl -n ai-pipeline exec pipeline-dashboard-59d8d7cd84-tdn5x -- sh -c '
for f in /app/artifacts/epic-tasks/RHAISTRAT-1-E*.md; do
  echo "FILE:$f"
  sed -n "1,/^---$/p" "$f" | sed -n "1,80p"
done
'
```

Compare against expected schema:

```bash
kubectl -n ai-pipeline exec pipeline-dashboard-59d8d7cd84-tdn5x -- python3 -c '
import glob, os, yaml
allowed = {
    "epic_id", "title", "parent_strat", "component", "team", "type",
    "implementation_type", "priority", "dependencies", "ai_signals",
    "investigation_signals", "ai_implementability",
    "ai_implementability_score", "jira_key", "branch", "gated_by",
    "gate_failure_impact",
}
required = {"epic_id", "title", "parent_strat", "component", "team", "type", "priority"}
for path in sorted(glob.glob("/app/artifacts/epic-tasks/RHAISTRAT-1-E[0-9][0-9][0-9].md")):
    text = open(path).read()
    parts = text.split("---", 2)
    meta = yaml.safe_load(parts[1]) if len(parts) >= 3 else {}
    keys = set(meta or {})
    print(os.path.basename(path))
    print("  unknown:", ", ".join(sorted(keys - allowed)) or "none")
    print("  missing required:", ", ".join(sorted(required - keys)) or "none")
'
```

Check the downstream discovery failure:

```bash
kubectl -n ai-pipeline logs markov-run-b9fd31d1-cfttj --tail=200
```

## Likely Causes

### 1. Codegen Rewrites Epic Task Frontmatter with a Different Schema

The current leading theory is that `epic-codegen` has its own
`scripts/frontmatter.py` and artifact schema. It updates files under
`artifacts/epic-tasks/` after decompose/submit/discovery, but the fields it
writes are not valid for `epic-creator`'s `epic-task` schema.

Evidence:

- The bad file mtimes are after decompose completed.
- The bad fields are codegen/status-oriented.
- Codegen logs show `frontmatter.py set` against
  `artifacts/epic-tasks/RHAISTRAT-1-E001.md`.

If codegen needs run status metadata, it should write to codegen-owned artifacts
such as `artifacts/codegen-runs/<epic-id>/run-metadata.yaml` or to schema-safe
fields agreed with `epic-creator`.

### 2. Earlier Decomposer Runs May Still Have Skipped Validation

Earlier runs did show bootstrap oddities and pipeline continuation despite
component-fetch failure. The decomposer prompt instructs agents to write the
body first, then run:

```bash
python3 scripts/frontmatter.py set artifacts/epic-tasks/{ID}-E001.md ...
```

That script validates against the schema before writing. The observed artifacts
look like a different mental model of an epic/codegen artifact. However, for the
latest `0709-025807` run, captured transcript evidence says decompose validated
successfully before later codegen jobs touched the files.

### 3. Runtime Does Not Fully Match Upstream Plugin Execution

The upstream `epic-decomposer` CI harness runs `epic-creator` as a Claude plugin:

```bash
/epic-creator:epic-decompose ...
```

Our FQN runtime currently clones the repo, symlinks `skills/<skill>` into
`.claude/skills/<skill>`, and invokes:

```bash
/epic-decompose ...
```

That compatibility path may omit plugin namespace behavior, hook behavior, or
other repo context that makes the prompt conventions more reliable.

See `docs/plans/plugin-aware-fqn-skill-loading-plan.md` for the proposed fix.

Plugin-aware loading appears to have been enabled for the latest run:

```text
Resolved skill load mode: plugin
Executing: claude --model opus --print --plugin-dir /tmp/skills/opendatahub-io-epic-creator "/epic-creator:epic-decompose --headless RHAISTRAT-1"
```

That reduces suspicion on the latest decompose run.

### 4. No Deterministic Artifact Contract Gate After Codegen

The demo workflow does not protect the shared `artifacts/epic-tasks/*.md`
contract from later writers. Even if decompose validates correctly, downstream
skills can mutate the same files and break future submit/discovery/codegen
passes.

## Proposed Fixes

1. Stop `epic-codegen` from writing non-`epic-task` fields into
   `artifacts/epic-tasks/*.md`:
   - Move codegen status to `artifacts/codegen-runs/<epic-id>/run-metadata.yaml`
     or another codegen-owned file.
   - If status must appear on the epic task, coordinate schema additions in
     `epic-creator` and keep `submit.py` strict validation aligned.

2. Add a schema guard after codegen writes:
   - Run `epic-creator`'s `scripts/frontmatter.py read` against every
     `artifacts/epic-tasks/RHAISTRAT-*-E*.md` after codegen status updates.
   - Fail the codegen job if it corrupts the shared artifact contract.

3. Keep FQN loading plugin-aware:
   - If `.claude-plugin/plugin.json` exists, pass `--plugin-dir` to Claude.
   - Invoke the skill as `/<plugin-name>:<skill-name>`.
   - Keep the current symlink/direct skill path for non-plugin repos.

4. Add a post-decompose validation gate before `epic_submit`:
   - Clone or reuse `epic-creator`.
   - Run `scripts/frontmatter.py read` or `batch-read` for every generated epic
     artifact.
   - Fail the workflow early with a targeted schema error if any file has
     unknown fields or missing required fields.

5. Consider making `discover_epics` fail on unknown `type`:
   - Today it logs and skips unknown epics, which can mask upstream artifact
     corruption.
   - For the demo pipeline, unknown type should probably be a hard failure when
     matching epic files exist.

## Root Cause Confirmed (2026-07-09)

The two repos define **completely different schemas** for the same `epic-task`
artifact type. Both repos have their own `scripts/artifact_utils.py` with a
`SCHEMAS["epic-task"]` definition, but the field sets are incompatible.

### epic-creator (decomposer) schema

```python
"epic-task": {
    "epic_id":        {"type": "string", "required": True},
    "parent_strat":   {"type": "string", "required": True, "pattern": r"^RHAISTRAT-\d+$"},
    "component":      {"type": "string", "required": True},
    "team":           {"type": "string", "required": True},
    "type":           {"type": "string", "required": True, "enum": ["Implementation", "Investigation"]},
    "priority":       {"type": "string", "required": True, "enum": ["P0", "P1", "P2"]},
    "dependencies":   {"type": "list",   "required": False},
    "ai_signals":     {"type": "dict",   "required": False},
    # also: implementation_type, jira_key, branch, gated_by, gate_failure_impact, ...
}
```

### epic-code-gen (codegen) schema

```python
"epic-task": {
    "epic_id":        {"type": "string", "required": True},
    "title":          {"type": "string", "required": True},
    "strategy_key":   {"type": "string", "required": True, "pattern": r"^[A-Z][A-Z0-9]+-\d+$"},
    "target_repo":    {"type": "string", "required": True},
    "status":         {"type": "string", "required": True, "enum": ["Pending", "Ready", "InProgress", "Generated", "Validated", "Failed"]},
    "target_branch":  {"type": "string", "required": False},
    "components":     {"type": "list",   "required": False},
    "dependencies":   {"type": "list",   "required": False},
    "blocks":         {"type": "list",   "required": False},
    "effort_size":    {"type": "string", "required": False, "enum": ["S", "M", "L", "XL"]},
    # also: codegen_branch, pr_url, jira_status, readiness_score, ...
}
```

### What happens at runtime

1. The decomposer writes valid `epic-task` files with `type`, `parent_strat`,
   `component`, `team`, `priority`. Confirmed by the discover step that ran
   immediately after decompose in `markov-run-8aecc06b`:

   ```
   Found: RHAISTRAT-1-E001 key=RHAI-2 type=Implementation
   Found: RHAISTRAT-1-E002 key=RHAI-3 type=Implementation
   Found: RHAISTRAT-1-E003 key=RHAI-4 type=Implementation
   ```

2. The codegen agent reads the files, calls its own `frontmatter.py schema
   epic-task`, sees its own (different) schema, and concludes the files have
   "non-standard frontmatter." From the codegen agent's thinking log:

   > "The epic task files have non-standard frontmatter. I need to fix the
   > frontmatter to match the expected schema (add `strategy_key`,
   > `target_repo`, `status`)"

3. The codegen agent rewrites the files with `Write` tool calls, replacing the
   decomposer's valid frontmatter with its own schema fields. The only two
   `Write` calls to `epic-tasks/` in the entire run are both from
   `epic-code-gen`:

   ```
   🔧 Write /tmp/skills/opendatahub-io-epic-code-gen/artifacts/epic-tasks/RHAISTRAT-1-E003.md
   🔧 Write /tmp/skills/opendatahub-io-epic-code-gen/artifacts/epic-tasks/RHAISTRAT-1-E001.md
   ```

4. Subsequent discover steps find `type: unknown` because the codegen schema
   doesn't include a `type` field, and everything gets skipped.

### Fix options

The schemas need to be unified. Either:

- **Option A**: Make `epic-code-gen` read-only on `epic-tasks/*.md` and move all
  codegen status to `codegen-runs/<epic-id>/run-metadata.yaml` (already exists).
- **Option B**: Merge the schemas into a shared `artifact_utils.py` with a
  superset of both field sets, used by both repos.
- **Option C**: Add a `codegen_status` sub-dict to `epic-creator`'s schema so
  codegen can write its fields without clobbering the decomposer's fields.

Option A is the least invasive — codegen already writes to `codegen-runs/` for
its own metadata. The `epic-tasks/*.md` files should be treated as the
decomposer's contract output.

## Status

Open — root cause confirmed.

The two repos (`epic-creator` and `epic-code-gen`) independently define
incompatible schemas for `epic-task` artifacts. The codegen agent rewrites the
decomposer's valid output because its own `frontmatter.py` tells it the files
are non-conformant. The fix is to unify or partition the schemas.
