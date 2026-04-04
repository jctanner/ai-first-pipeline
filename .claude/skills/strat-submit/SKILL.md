---
name: strat.submit
description: >
  Push refined strategy content back to RHAISTRAT Jira tickets. Reads local
  strat-task artifacts, updates the Jira ticket description with the full
  strategy content, and applies a label to mark submission.
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash, mcp__atlassian__editJiraIssue, mcp__atlassian__getJiraIssue
---

You are a strategy submission assistant. Your job is to push locally refined strategy content back to the corresponding RHAISTRAT Jira tickets.

## Inputs

`$ARGUMENTS` — optional: one or more RHAISTRAT keys (e.g., `RHAISTRAT-1 RHAISTRAT-2`). If provided, submit only those strategies. If empty, submit all strategies that are ready.

## Step 1: Find Strategies Ready to Submit

Scan `remote_skills/rfe-creator/artifacts/strat-tasks/*.md` for strategy files. For each file, read its frontmatter:

```bash
python3 remote_skills/rfe-creator/scripts/frontmatter.py read remote_skills/rfe-creator/artifacts/strat-tasks/<filename>.md
```

A strategy is **ready to submit** if ALL of the following are true:
- `jira_key` is set (not null) — the strategy has a corresponding RHAISTRAT ticket
- `status` is `Refined` or `Reviewed` — the strategy has been through refinement

If `$ARGUMENTS` specifies keys, filter to only those keys. If a requested key is not found or not ready, report it and continue with the others.

If no strategies are ready to submit, report that and stop.

## Step 2: For Each Strategy, Prepare the Submission

For each strategy ready to submit:

1. **Read the full file** using the Read tool to get the markdown body (everything after the frontmatter closing `---`).

2. **Extract the strategy content.** The file has two main sections:
   - `## Business Need (from RFE)` — the original RFE content
   - `## Strategy` — the refined technical strategy

   Both sections should be included in the Jira description update.

3. **Fetch the current Jira ticket** to verify it exists and check its current state:

   Call `mcp__atlassian__getJiraIssue` with:
   - `cloudId`: `"https://redhat.atlassian.net"`
   - `issueIdOrKey`: the `jira_key` from frontmatter (e.g., `"RHAISTRAT-1"`)
   - `fields`: `["summary", "description", "labels"]`
   - `responseContentFormat`: `"markdown"`

   If the ticket cannot be fetched, report the error and skip this strategy.

## Step 3: Update the Jira Ticket

For each strategy, update the RHAISTRAT Jira ticket:

1. **Update the description** with the full strategy content (Business Need + Strategy sections). Call `mcp__atlassian__editJiraIssue` with:
   - `cloudId`: `"https://redhat.atlassian.net"`
   - `issueIdOrKey`: the `jira_key`
   - `fields`: set `description` to the full markdown body from the local artifact

2. **Add the `strat-refined` label** to mark the ticket as having received refined content. Include this in the same `editJiraIssue` call by setting `labels` to the existing labels plus `strat-refined`. Do not remove existing labels — append to them.

   If the ticket already has the `strat-refined` label, skip adding it (avoid duplicates).

## Step 4: Report Results

After processing all strategies, print a summary table:

```
## Submission Results

| Strategy | Jira Key | Status | Link |
|----------|----------|--------|------|
| <title> | RHAISTRAT-NNN | Updated | https://redhat.atlassian.net/browse/RHAISTRAT-NNN |
| <title> | RHAISTRAT-NNN | Skipped — no jira_key | — |
| <title> | RHAISTRAT-NNN | Error — <reason> | — |
```

For each successfully updated ticket, include the direct Jira link.

## Important Notes

- **Do not modify the local artifact files.** The strat-task frontmatter schema does not include a "Submitted" status, so local status remains unchanged. The `strat-refined` Jira label serves as the submission marker.
- **Preserve the Business Need section.** When updating the Jira description, include both the Business Need (from RFE) and the Strategy sections — the full artifact body.
- **Do not create new tickets.** This skill only updates existing RHAISTRAT tickets. If a strategy has no `jira_key`, skip it.
- **Handle errors gracefully.** If a Jira update fails, report the error and continue with remaining strategies.

$ARGUMENTS
