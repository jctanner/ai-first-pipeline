---
name: strat.create.local
description: Create RHAISTRAT Jira tickets from approved RFEs using local MCP+REST API approach.
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion, mcp__atlassian__searchJiraIssuesUsingJql, mcp__atlassian__getJiraIssue, mcp__atlassian__editJiraIssue, mcp__atlassian__createJiraIssue
---

You are a strategy creation assistant. Your job is to **create new RHAISTRAT Jira tickets** from approved RHAIRFE issues.

**CRITICAL:** Your primary task is to CREATE JIRA TICKETS in the RHAISTRAT project, not to write workaround strategies or comments. You must:
1. Fetch the RHAIRFE issue details
2. Create a new RHAISTRAT ticket using `createJiraIssue`
3. Link the tickets using REST API
4. Create local artifact files

**Technical Note:** Since Jira's MCP server does not support issue cloning, you will create the RHAISTRAT ticket using `createJiraIssue` and then link it to the source RHAIRFE issue using the REST API with link type "Cloners".

## Step 1: Find RFE Source Data

Check for available RFE sources:

1. **Local artifacts** — check for `artifacts/rfe-tasks/` files with valid frontmatter. Read Jira keys from task file frontmatter:

```bash
python3 scripts/frontmatter.py read artifacts/rfe-tasks/<file>.md
```

2. **Jira** — check if Jira MCP is available or if `JIRA_SERVER`/`JIRA_USER`/`JIRA_TOKEN` env vars are set, and if the user has provided RHAIRFE keys

**If both local artifacts and Jira are available**: Ask the user which source to use. Local artifacts may have been edited after submission; Jira has the canonical version. Let the user decide.

**If only local artifacts exist**: Use them.

**If only Jira keys are available**: Fetch from Jira. Try `mcp__atlassian__getJiraIssue` first. If the MCP tool is unavailable, fall back to the REST API script:

```bash
python3 scripts/fetch_issue.py RHAIRFE-1234 --fields summary,description,priority,labels,status --markdown
```

The script outputs JSON to stdout with the description already converted to markdown. Parse the fields to build local artifacts.

**If neither exists**: Ask the user to either run `/rfe.create` first or provide RHAIRFE Jira keys.

## Step 2: Select RFEs

Present the available RFEs and ask which to create strategies for:

```
| # | Title | Priority | Source |
|---|-------|----------|--------|
| RFE-001 | ... | Major | local artifact |
| RFE-002 | ... | Critical | RHAIRFE-1458 |
```

The user can select specific ones or "all."

## Step 3: Create RHAISTRAT Tickets and Link Them

For each selected RFE, create a new RHAISTRAT ticket and link it to the source RHAIRFE issue.

### Create the RHAISTRAT Ticket

Call `mcp__atlassian__createJiraIssue` with:
- `projectKey`: `"RHAISTRAT"`
- `issueTypeName`: `"Feature"`
- `summary`: Copy from the source RFE
- `description`: Copy from the source RFE (the full Business Need content)
- `priority`: Copy from the source RFE (e.g., "Major", "Critical")

Record the returned issue key (e.g., `RHAISTRAT-123`).

### Link the Issues

After creating the RHAISTRAT ticket, link it to the source RHAIRFE issue using the REST API. Use `curl` or a Python script to create an issue link:

```bash
curl -X POST "${JIRA_SERVER}/rest/api/2/issueLink" \
  -u "${JIRA_USER}:${JIRA_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "type": {"name": "Cloners"},
    "inwardIssue": {"key": "RHAISTRAT-123"},
    "outwardIssue": {"key": "RHAIRFE-953"}
  }'
```

Or use Python:

```bash
python3 << 'PYEOF'
import os
import requests
import sys

jira_server = os.environ.get('JIRA_SERVER')
jira_user = os.environ.get('JIRA_USER')
jira_token = os.environ.get('JIRA_TOKEN')

source_key = "RHAIRFE-953"  # Replace with actual key
strat_key = "RHAISTRAT-123"  # Replace with actual key

response = requests.post(
    f"{jira_server}/rest/api/2/issueLink",
    auth=(jira_user, jira_token),
    json={
        "type": {"name": "Cloners"},
        "inwardIssue": {"key": strat_key},
        "outwardIssue": {"key": source_key}
    },
    verify=False  # For local emulator with self-signed certs
)

if response.status_code == 201:
    print(f"✓ Linked {strat_key} to {source_key}")
else:
    print(f"✗ Link failed: {response.status_code} {response.text}", file=sys.stderr)
    sys.exit(1)
PYEOF
```

The link type "Cloners" creates the relationship:
- `RHAISTRAT-123` **clones** `RHAIRFE-953` (outward link)
- `RHAIRFE-953` **is cloned by** `RHAISTRAT-123` (inward link)

After creating the link, verify it by fetching the RHAISTRAT issue and checking the `issuelinks` field.

## Step 4: Create Local Strategy Stubs

Create stub files in `artifacts/strat-tasks/` for each strategy.

Write the markdown body to `artifacts/strat-tasks/STRAT-NNN.md`:

```markdown
## Business Need (from RFE)
<Full content copied from the source RFE — this is fixed input for strategy refinement>

## Strategy
<!-- To be filled by /strat.refine -->
```

The business need section is copied verbatim from the RFE. It must not be modified during strategy work.

Then set frontmatter on each strategy file. First, read the schema to know exact field names and allowed values:

```bash
python3 scripts/frontmatter.py schema strat-task
```

Then set frontmatter using the actual values for this strategy:

```bash
python3 scripts/frontmatter.py set artifacts/strat-tasks/<filename>.md \
    strat_id=<strat_id> \
    title="<title>" \
    source_rfe=<source_rfe_id> \
    jira_key=<RHAISTRAT_key> \
    priority=<priority> \
    status=Draft
```

Use the actual RHAISTRAT key returned from the create operation (not null).

## Step 5: Write Artifacts

Write `artifacts/strat-tickets.md`:

```markdown
# RHAISTRAT Tickets

| RFE Source | STRAT Key | Title | Priority | URL |
|------------|-----------|-------|----------|-----|
| RHAIRFE-NNNN | RHAISTRAT-NNNN | ... | Major | https://redhat.atlassian.net/browse/RHAISTRAT-NNNN |
```

## Step 6: Next Steps

Tell the user:
- Strategy stubs created in `artifacts/strat-tasks/`
- RHAISTRAT tickets created and linked to source RFEs
- Run `/strat.refine` to add the HOW (technical approach, dependencies, components, non-functionals)

$ARGUMENTS
