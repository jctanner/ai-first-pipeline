---
name: epic-submit
description: >
  Create RHOAIENG Jira epics from epic-decompose artifact files. Reads
  artifacts/epic-tasks/{STRAT}-E*.md, creates Jira tickets with parent
  link to the RHAISTRAT, and updates each artifact's frontmatter with
  the created jira_key. Supports --headless and --dry-run.
user-invocable: true
allowed-tools: "Bash, Read, Glob"
---

# Epic Submit Skill

Create RHOAIENG Jira epics from epic-decompose artifact files. Each artifact file in `artifacts/epic-tasks/` becomes a Jira Epic linked to its parent RHAISTRAT ticket.

## Usage

```
/epic-submit RHAISTRAT-1234
/epic-submit RHAISTRAT-1234 --headless
/epic-submit RHAISTRAT-1234 --dry-run
/epic-submit RHAISTRAT-1234 --headless --dry-run
```

| Flag | Behavior |
|------|----------|
| *(no flags)* | Interactive. Present epics, ask for confirmation, then create. |
| `--headless` | Non-interactive. Create all epics automatically. |
| `--dry-run` | Show what would be created but do NOT mutate anything. Skips `create-issue`, `link-issues`, `update-issue`, and artifact frontmatter writes. |

## Jira API

All Jira operations use the bundled script. Requires `JIRA_SERVER`, `JIRA_USER`, and `JIRA_TOKEN` environment variables.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/jira_ops.py create-issue '<JSON>'
python3 ${CLAUDE_SKILL_DIR}/scripts/jira_ops.py search '<JQL>'
python3 ${CLAUDE_SKILL_DIR}/scripts/jira_ops.py update-issue RHAISTRAT-1234 '<JSON>'
```

## Instructions

### Step 0: Resolve Artifact Root

Determine the artifacts directory. In K8s jobs the PVC is mounted at `/app/artifacts`; locally it's `./artifacts`.

```bash
ARTIFACTS_ROOT="${ARTIFACTS_ROOT:-/app/artifacts}"
[ -d "$ARTIFACTS_ROOT" ] || ARTIFACTS_ROOT="./artifacts"
```

Use `$ARTIFACTS_ROOT` for all artifact paths below — never hardcode `artifacts/...` directly.

### Step 1: Find Epic Artifact Files

Glob for artifact files:

```bash
ls ${ARTIFACTS_ROOT}/epic-tasks/{STRAT}-E*.md
```

Exclude `*-decomposition.md` files — those are the decomposition summary, not individual epics.

If no files match, exit with: `"No epic artifacts found for {STRAT} in artifacts/epic-tasks/"`

### Step 2: Read Each Artifact

For each file, extract:

1. **YAML frontmatter** — parse the content between `---` delimiters:
   - `epic_id` (string, e.g. `RHAISTRAT-1234-E001`)
   - `parent_strat` (string, e.g. `RHAISTRAT-1234`)
   - `component` (string)
   - `team` (string)
   - `type` (string: `Implementation` or `Investigation`)
   - `priority` (string: `P0`, `P1`, or `P2`)
   - `dependencies` (list of epic IDs, may be empty)
   - `jira_key` (string, may be absent — used for idempotency)

2. **Body title** — the first line starting with `#` after the frontmatter closing `---`. Strip the `#` prefix and whitespace.

3. **Body content** — everything after the frontmatter closing `---`.

Use this Python snippet to parse:

```bash
python3 -c "
import yaml, sys
with open('$FILE') as f:
    content = f.read()
parts = content.split('---', 2)
if len(parts) >= 3:
    meta = yaml.safe_load(parts[1])
    body = parts[2].strip()
    import json
    print(json.dumps({'meta': meta, 'body': body}))
else:
    print('ERROR: no frontmatter', file=sys.stderr)
    sys.exit(1)
"
```

### Step 3: Idempotency Check

For each artifact, first check if `jira_key` is already set in the frontmatter. If it is, skip that epic and print:

```
SKIP: {epic_id} already submitted as {jira_key}
```

If `jira_key` is NOT set, search Jira for an existing ticket before creating a new one. This handles the case where a previous run created the ticket but crashed before updating the frontmatter:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/jira_ops.py search 'project = RHOAIENG AND labels = "epic-id:{epic_id}"' --fields key --max 1
```

If a result is found, update the artifact frontmatter with the found `jira_key` (Step 5) and skip creation. Print:

```
RECOVERED: {epic_id} already exists as {jira_key}, updated frontmatter
```

### Step 4: Create Jira Tickets

For each epic that needs creation, build the payload:

```json
{
  "fields": {
    "project": {"key": "RHOAIENG"},
    "issuetype": {"name": "Epic"},
    "parent": {"key": "{parent_strat}"},
    "summary": "{title from body}",
    "description": "{full body content}",
    "priority": {"name": "{mapped_priority}"},
    "labels": ["epic-submit", "epic-type-{type_lower}", "epic-id:{epic_id}"],
    "components": [{"name": "{component}"}]
  }
}
```

**Priority mapping:**

| Artifact | Jira |
|----------|------|
| P0 | Highest |
| P1 | High |
| P2 | Medium |
| *(missing)* | Medium |

**Summary format:** Use the first heading from the body. If no heading found, use: `{epic_id}: {component} - {type}`

Create the ticket:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/jira_ops.py create-issue '<payload>'
```

Extract the created issue key from the response JSON (`.key` field).

### Step 5: Update Artifact Frontmatter

After creating each ticket, update the artifact file's frontmatter with the Jira key and status. Use this approach:

```bash
python3 -c "
import yaml, sys

path = '$FILE'
with open(path) as f:
    content = f.read()

parts = content.split('---', 2)
meta = yaml.safe_load(parts[1])
meta['jira_key'] = '$JIRA_KEY'
meta['status'] = 'Submitted'

with open(path, 'w') as f:
    f.write('---\n')
    f.write(yaml.dump(meta, default_flow_style=False, sort_keys=False))
    f.write('---\n')
    if len(parts) >= 3:
        f.write(parts[2])
"
```

In `--dry-run` mode, do NOT update the frontmatter.

### Step 6: Create Dependency Links

In `--dry-run` mode, skip this step entirely.

After all epics are created, process `dependencies` from each artifact's frontmatter. For each dependency:

1. Look up the dependent epic's `jira_key` (read its artifact file)
2. If both the current epic and the dependency have `jira_key` set, create a link:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/jira_ops.py link-issues {DEP_KEY} {EPIC_KEY}
```

This creates a "Blocks" link (dependency blocks the current epic). Skip any dependency whose artifact file is missing or has no `jira_key`. Duplicate links are treated as success (the command is idempotent).

### Step 7: Label the Strategy

In `--dry-run` mode, skip this step entirely.

Add `epic-submit-complete` label to the parent RHAISTRAT ticket:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/jira_ops.py update-issue {STRAT} '{"update": {"labels": [{"add": "epic-submit-complete"}]}}'
```

If this fails, report the error but do not fail the overall skill.

### Step 8: Summary

Print a summary table:

```
## Epic Submit Results for {STRAT}

| Epic ID | Jira Key | Type | Component | Status |
|---------|----------|------|-----------|--------|
| RHAISTRAT-1-E001 | RHOAIENG-42 | Implementation | odh-cli | Created |
| RHAISTRAT-1-E002 | RHOAIENG-43 | Investigation | odh-cli | Created |
```

In `--dry-run` mode, show the table with `Status: Would create`.

$ARGUMENTS
