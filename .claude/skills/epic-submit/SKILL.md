---
name: epic-submit
description: Create Jira tickets from epic-task artifact files and update frontmatter with Jira keys
user-invocable: true
allowed-tools: Bash, Read, Glob
---

# Epic Submit

Create Jira tickets for epic-task artifacts produced by epic-decompose.
Updates each artifact's YAML frontmatter with the assigned `jira_key` and
`status: Submitted`. Idempotent — skips artifacts that already have a
`jira_key`.

**Narration:** between tool calls, narrate at most one short line.

## Arguments

Parse `$ARGUMENTS` for:
- `STRAT_KEY` (required) — strategy key, e.g. `RHAISTRAT-1`
- `--dry-run` — print what would be created without making API calls
- `--project PROJECT` — target Jira project (default: `RHAI`)

## Step 1: Discover Artifacts

```bash
ls artifacts/epic-tasks/${STRAT_KEY}-E*.md | grep -v decomposition
```

For each file, read and parse the YAML frontmatter between `---` markers.
Extract: `epic_id`, `parent_strat`, `component`, `team`, `type`, `priority`,
`dependencies`.

Extract the title from the first `# ` heading in the markdown body.

**Idempotency:** if `jira_key` is already set in frontmatter, skip that
artifact and print `SKIP {epic_id}: already submitted as {jira_key}`.

## Step 2: Create Jira Issues

For each artifact without a `jira_key`, create a Jira issue:

```bash
python3 .claude/skills/epic-submit/scripts/jira_ops.py create-issue '{
  "fields": {
    "project": {"key": "RHAI"},
    "issuetype": {"name": "Epic"},
    "summary": "<title from body>",
    "description": "<full markdown body>",
    "priority": {"name": "<mapped priority>"},
    "parent": {"key": "<parent_strat>"},
    "labels": ["epic-submit", "epic-type-<type>", "epic-id:<epic_id>"],
    "components": [{"name": "<component>"}]
  }
}'
```

Priority mapping: `P0` → `Highest`, `P1` → `High`, `P2` → `Medium`,
`P3` → `Low`. Default: `Medium`.

Capture the returned `key` from the JSON response.

## Step 3: Update Frontmatter

After each successful issue creation, update the artifact file's YAML
frontmatter to add `jira_key` and set `status: Submitted`:

```python
python3 -c "
import sys
path = sys.argv[1]
jira_key = sys.argv[2]
with open(path) as f:
    content = f.read()
parts = content.split('---', 2)
if len(parts) >= 3:
    fm = parts[1]
    if 'jira_key:' not in fm:
        fm = fm.rstrip() + f'\njira_key: {jira_key}\n'
    import re
    fm = re.sub(r'status:\s*\S+', f'status: Submitted', fm)
    with open(path, 'w') as f:
        f.write('---' + fm + '---' + parts[2])
" "<artifact_path>" "<jira_key>"
```

## Step 4: Create Dependency Links

For each artifact that has `dependencies` in frontmatter, create Jira
issue links between the dependent epics. Only link epics that have both
been submitted (both have `jira_key` set).

Link type: `Blocks` (the dependency blocks the dependent epic).

## Step 5: Label Strategy

Add `epic-submit-complete` label to the strategy ticket:

```bash
python3 .claude/skills/epic-submit/scripts/jira_ops.py update-issue ${STRAT_KEY} '{
  "update": {"labels": [{"add": "epic-submit-complete"}]}
}'
```

## Step 6: Summary

Print a summary table:

```
Epic ID              Jira Key      Type              Component
RHAISTRAT-1-E001     RHAI-1        Implementation    odh-cli
RHAISTRAT-1-E002     RHAI-2        Investigation     architecture
```

## Error Handling

- If Jira API returns an error, print the error and continue with remaining
  epics (do not abort the entire run).
- If no artifacts are found, print a warning and exit cleanly.
- If all artifacts already have `jira_key`, print "All epics already
  submitted" and exit.
