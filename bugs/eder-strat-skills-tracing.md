Problem: No per-ticket scoping or RFE-to-STRAT traceability index
==================================================================

The strat-creator skills (strategy-create, strategy-refine, strategy-review)
were designed for interactive single-user use. When run as parallel K8s jobs
with per-ticket scoping, several issues emerge.


1. No per-ticket filtering
--------------------------

All three skills glob `artifacts/strat-tasks/*` and process every file they
find. The `--issue` argument passed by our pipeline is available in
`$ARGUMENTS` but the skills don't use it to filter which artifacts to work on.

Consequences:
  - A job submitted for RHAISTRAT-2 will also refine/review RHAISTRAT-1,
    RHAISTRAT-3, and any dry-run stubs (STRAT-001, etc.)
  - Wastes tokens re-processing artifacts that weren't targeted
  - Makes per-ticket job logs misleading (logs show work on unrelated tickets)

Desired behavior: skills should accept an `--issue RHAISTRAT-NNNN` filter
and only process matching artifacts.


2. Race conditions on shared files
-----------------------------------

Multiple concurrent jobs write to the same files without locking or
append-only semantics:

  - `artifacts/strat-tickets.md` — strategy-create rewrites the entire
    table on every run. Two concurrent create jobs race; last writer wins
    and the other's entries are lost.

  - `artifacts/strat-skipped.md` — strategy-create says "append" but the
    agent may rewrite the file. Concurrent appends are not atomic on a
    shared PVC.

  - `artifacts/strat-tasks/*.md` — strategy-refine reads and rewrites
    each file. Two concurrent refine jobs targeting different tickets will
    still both read all files and could interleave writes if they happen
    to process the same file.

  - `artifacts/strat-reviews/*.md` — same issue with strategy-review.

  - `artifacts/strat-rubric.md` — strategy-review fetches and writes
    the rubric; concurrent reviews would race on this.

These are not theoretical — our pipeline submits jobs per-ticket, so
concurrent runs are expected.


3. RFE-to-STRAT mapping is fragile
------------------------------------

The only mapping from RFE to STRAT exists in two places:

  a) `source_rfe` field in YAML frontmatter of each `strat-tasks/*.md`
     file. Requires reading and parsing every artifact file to find
     which STRAT corresponds to a given RFE.

  b) `artifacts/strat-tickets.md` — a markdown table written by
     strategy-create at clone time. However:
     - Only includes tickets that were actually cloned to Jira
       (dry-run stubs like STRAT-001 are missing)
     - Subject to race conditions (see #2 above)
     - Not maintained by refine or review (becomes stale if strats
       are added or removed outside of strategy-create)

There is no durable, atomic index that the pipeline can query to
resolve "which STRAT(s) exist for RHAIRFE-NNNN?" without scanning
every artifact file.


4. Observed artifact state (2026-04-21)
----------------------------------------

Current contents of `artifacts/strat-tasks/` on the cluster:

  - RHAISTRAT-1.md (source: RHAIRFE-2003, status: Refined)
  - RHAISTRAT-2.md (source: RHAIRFE-1982, status: Refined)
  - RHAISTRAT-3.md (source: RHAIRFE-1981, status: Refined)
  - STRAT-001.md   (dry-run stub, jira_key=null)
  - STRAT-002.md   (dry-run stub, jira_key=null)
  - STRAT-2000.md  (dry-run stub, jira_key=null)

Reviews exist for RHAISTRAT-2 and RHAISTRAT-3 only.

`strat-tickets.md` maps:
  RHAIRFE-2003 → RHAISTRAT-1
  RHAIRFE-1982 → RHAISTRAT-2
  RHAIRFE-1981 → RHAISTRAT-3


5. Validated from job logs (markov-* jobs, 2026-04-22)
-------------------------------------------------------

Examined logs from the markov pipeline run that executed strategy-create,
strategy-refine, and strategy-review sequentially for RHAIRFE-1981.

### strategy-refine (markov-5557b706-strategy-refine)

The agent's first action was to read frontmatter from every file in the
directory:

    for f in artifacts/strat-tasks/*.md; do
      python3 .../frontmatter.py read "$f"
    done

It read all 6 files (RHAISTRAT-1, 2, 3, STRAT-001, 002, 2000), then
used LLM reasoning to determine which one matched:

    "Found RHAISTRAT-3 linked to RHAIRFE-1981"

The agent correctly identified the target, but only because it parsed
the `source_rfe` frontmatter field from every artifact and matched it
against the RHAIRFE key in $ARGUMENTS. This is non-deterministic
filtering — the model decides which files to skip based on reasoning,
not code.

### strategy-review (markov-5557b706-strategy-review)

Same pattern. The agent enumerated all 6 artifacts and reasoned:

    "Since the command is --headless RHAIRFE-1981, I need to focus on
     strategies sourced from that RFE, which means RHAISTRAT-3..."

    "So only RHAISTRAT-2 and RHAISTRAT-3 are refined. The others are
     Draft or placeholder."

It correctly skipped unrefined stubs and the already-reviewed RHAISTRAT-2,
but again this was an LLM judgment call, not a deterministic filter.

### strategy-create (markov-10aa6638-strategy-create)

This job wrote `strat-tickets.md` as a full table rewrite. The log shows
it first wrote a single-row table, then noticed the file already existed,
read it, and used Edit to append the new row. This worked because only
one create job was running, but with concurrent creates the read-then-edit
pattern would race.

### Implications

- **Token waste**: Each refine/review job reads and parses frontmatter
  from every artifact in the directory. At 6 files this is minor; at 50+
  artifacts it becomes significant.
- **Correctness depends on model reasoning**: The filtering works today
  because the model is smart enough to match source_rfe fields, but
  there is no guarantee it will always skip unrelated artifacts,
  especially under context pressure with many files.
- **strat-tickets.md is fragile**: The read-then-edit approach to
  maintaining the index table will lose entries under concurrent writes.


Possible fixes
--------------

### >>> Option 1: Symlinks + targeted globs (RECOMMENDED) <<<

Two small changes that eliminate the scan-everything problem entirely:

a) strategy-create adds a symlink after writing each artifact:

       ln -sf RHAISTRAT-3.md artifacts/strat-tasks/RHAIRFE-1981.md

   This creates an RFE-keyed entry that resolves to the STRAT file:

       artifacts/strat-tasks/
         RHAISTRAT-1.md
         RHAISTRAT-2.md
         RHAISTRAT-3.md
         RHAIRFE-2003.md → RHAISTRAT-1.md
         RHAIRFE-1982.md → RHAISTRAT-2.md
         RHAIRFE-1981.md → RHAISTRAT-3.md

b) Skills use targeted glob patterns instead of `*.md`:

   - Per-ticket mode (--headless RHAIRFE-1981):
     Open `artifacts/strat-tasks/RHAIRFE-1981.md` directly.
     Symlink resolves to the correct STRAT file. No scanning.

   - Batch mode (no --issue):
     Glob `artifacts/strat-tasks/RHAISTRAT-*.md`.
     Skips dry-run stubs (STRAT-*) and symlinks (RHAIRFE-*)
     automatically — no duplicates, no stubs.

Why this is the best approach:
  - Zero scanning: per-ticket jobs open exactly one file by name
  - No frontmatter parsing needed to find the right artifact
  - No LLM reasoning to filter — deterministic file resolution
  - Symlink creation is atomic — no race conditions on an index file
  - Each RFE maps to exactly one STRAT — no clobbering risk
  - Backwards-compatible: existing tools that glob *.md still work
    (they just see both the real file and the symlink, which resolve
    to the same content)
  - Trivial to implement: one `ln -sf` in strategy-create, change
    glob patterns from `*.md` to `RHAISTRAT-*.md` in refine/review

### Option 2: Add --issue filtering via a pre-filter script

Add a `filter_artifacts.py` script that reads `$ARGUMENTS`, scans
frontmatter, and outputs matching filename(s). Each SKILL.md calls
this first and only processes returned files.

Pros: works without changing directory structure.
Cons: still requires a one-time scan of all frontmatter; adds a
script dependency; the LLM must still be told to use the filter
output rather than globbing on its own.

### Option 3: Pass STRAT key directly instead of RFE key

Have the pipeline runner resolve the RFE-to-STRAT mapping before
submitting the job (by scanning frontmatter or reading strat-tickets.md
once at submit time), then pass `--headless RHAISTRAT-3` instead of
`--headless RHAIRFE-1981`. The skill opens the file by name.

Pros: no skill changes needed.
Cons: pushes complexity to the pipeline runner; requires the runner
to maintain awareness of the RFE-to-STRAT mapping; doesn't help
the skill's batch mode; strat-tickets.md is still fragile.

### Option 4: Add a durable index file

Maintain a machine-readable index (YAML or JSON) at
`artifacts/strat-index.yaml` that maps RFE keys to STRAT keys,
filenames, and status. Use atomic writes (write to temp, rename)
and append-friendly format.

Pros: gives the pipeline a queryable lookup.
Cons: another file to maintain and keep in sync; atomic writes
require discipline in SKILL.md instructions; adds complexity
compared to symlinks which are inherently atomic.

### Option 5: Per-ticket artifact directories (breaking change)

Restructure from flat `artifacts/strat-tasks/*.md` to
`artifacts/strat-tasks/RHAISTRAT-NNNN/` per ticket. Eliminates
most race conditions but requires changes to all skills and any
code that reads the artifacts directory.

### Option 6: Pipeline-side per-job scratch directory (workaround)

Before launching a job, symlink or copy only the target ticket's
artifact into a per-job temp directory, point the skill at that
directory. Copy results back after completion.

Pros: no upstream changes.
Cons: fragile — the skill still writes to relative `artifacts/`
paths for index files; requires post-job reconciliation; doesn't
help with batch mode.

### Option 7: File-level locking for shared index files (partial)

Wrap writes to `strat-tickets.md` and `strat-skipped.md` with
`flock` in the skill scripts.

Pros: prevents clobbering of index files.
Cons: only addresses race conditions on index files, not the
scan-everything or per-ticket filtering problems.

Summary
-------

Option 1 (symlinks + targeted globs) is the clear winner. It solves
per-ticket resolution, eliminates full-directory scans, avoids race
conditions on index files, and requires minimal changes — one symlink
creation in strategy-create and a glob pattern change in refine/review.
All other options are either partial fixes, more complex, or push
complexity to the wrong layer.
