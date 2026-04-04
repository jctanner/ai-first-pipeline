# strat-create Batch Run Issues (2026-04-04)

97 total runs, all completed with `success` status. No crashes, timeouts, or Jira API errors. Total cost: $36.95 (~$0.38/run avg).

## 1. STRAT-NNN ID Collisions (5 collisions, data loss)

Multiple concurrent agents picked the same local `STRAT-NNN` ID, causing the last writer to overwrite the previous content. This is a **data-loss scenario**.

| Local File | Written By | Overwritten By | Lost Jira Ticket |
|-----------|-----------|----------------|-----------------|
| STRAT-005.md | RHAIRFE-1333 | RHAIRFE-1351 | RHAISTRAT-32 |
| STRAT-006.md | RHAIRFE-1423 | RHAIRFE-1434 | RHAISTRAT-36 |
| STRAT-008.md | RHAIRFE-1648 | RHAIRFE-1649 | RHAISTRAT-56 |
| STRAT-009.md | RHAIRFE-1727 | RHAIRFE-1728 | (none created) |
| STRAT-011.md | RHAIRFE-503 | RHAIRFE-663 | RHAISTRAT-78 |

**Fix**: The local counter is not concurrency-safe. Agents should either use the RHAISTRAT Jira key as the filename immediately after creation, or use an atomic global counter.

## 2. Issues That Did Not Create Jira Tickets (11 issues)

These runs created local `STRAT-NNN.md` stubs and a `strat-jira-guide.md` for manual cloning but never called the Jira create API.

| RHAIRFE Issue | Local STRAT ID |
|---------------|---------------|
| RHAIRFE-1041 | STRAT-001 |
| RHAIRFE-1171 | STRAT-002 |
| RHAIRFE-1231 | STRAT-003 |
| RHAIRFE-1252 | STRAT-004 |
| RHAIRFE-1351 | STRAT-005 |
| RHAIRFE-1630 | STRAT-007 |
| RHAIRFE-1648 | STRAT-008 |
| RHAIRFE-1727 | STRAT-009 |
| RHAIRFE-1728 | STRAT-009 |
| RHAIRFE-1731 | STRAT-010 |
| RHAIRFE-726 | STRAT-012 |

**Fix**: Re-run these with `--issue` or manually clone to Jira.

## 3. Orphaned Jira Tickets (6 tickets)

RHAISTRAT tickets exist in Jira but the corresponding local artifact file was overwritten by a collision or saved with a `STRAT-NNN` name instead of `RHAISTRAT-NNN`.

Affected: RHAISTRAT-32, RHAISTRAT-36, RHAISTRAT-37, RHAISTRAT-56, RHAISTRAT-78, RHAISTRAT-81

**Fix**: Re-fetch these from Jira or regenerate local artifacts.

## 4. strat-tickets.md Contention (39 of 57 total errors)

94 of 97 runs edited the shared `artifacts/strat-tickets.md` file. Concurrent writes caused two types of recoverable errors:

- **"File has not been read yet"** (23 occurrences) -- agent tried to Write before Read
- **"File has been modified since read"** (16 occurrences) -- file changed between Read and Write (likely the `frontmatter.py` linter)

All were self-healed by the agent retrying. No data loss from these, but they waste turns and cost.

**Fix**: Generate `strat-tickets.md` from individual strat-task frontmatter (like `frontmatter.py rebuild-index`) instead of having every agent append to it.

## 5. Minor Errors (recovered)

- **"File has not been read yet"** on individual strat-task files: 10 occurrences across 10 issues. All recovered.
- **"File has been modified since read"** on `strat-jira-guide.md` and individual files: 6 occurrences. All recovered.
- **`ls` exit code 2** on nonexistent `artifacts/strat-tasks/` directory: RHAIRFE-1061, RHAIRFE-1074. Agents created the directory and continued.

## Aggregate Stats

| Metric | Value |
|--------|-------|
| Total runs | 97 |
| Completion rate | 100% |
| RHAISTRAT tickets created | 86 |
| Local-only stubs (no Jira) | 11 |
| File collisions (data loss) | 5 |
| Orphaned Jira tickets | 6 |
| Total tool errors (all recovered) | 57 |
| Runs with 0 errors | 52 (54%) |
| Total cost | $36.95 |
| Avg cost/run | $0.38 |
| Avg duration | 114s |
