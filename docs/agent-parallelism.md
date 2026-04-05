# Agent Parallelism Architecture

This document describes all the parallelism mechanisms in the pipeline — both the outer Python orchestrator (`lib/phases.py`) and the inner agent-level self-parallelism in the RFE/strategy skills. The two layers interact because the Python orchestrator can launch N agents concurrently, and each of those agents may itself launch sub-agents in parallel.

## Table of Contents

- [Layer 1: Python Orchestrator (lib/phases.py)](#layer-1-python-orchestrator)
- [Layer 2: Agent Self-Parallelism (RFE/Strategy Skills)](#layer-2-agent-self-parallelism)
- [Detailed Skill Walkthroughs](#detailed-skill-walkthroughs)
- [Concurrency Control Mechanisms](#concurrency-control-mechanisms)
- [State Persistence for Compression Resilience](#state-persistence-for-compression-resilience)
- [Progress Monitoring](#progress-monitoring)
- [Consistency Risks and Test Considerations](#consistency-risks-and-test-considerations)

---

## Layer 1: Python Orchestrator

The Python orchestrator in `lib/phases.py` uses `asyncio` with a shared `asyncio.Semaphore` to limit concurrent agent sessions. Each agent session is launched via `lib/agent_runner.py`, which calls the Claude Agent SDK (`claude_agent_sdk.ClaudeSDKClient`).

### Single-Phase Batch (`_run_phase`)

Used by: `bug-completeness`, `bug-context-map`, `bug-fix-attempt`, `bug-test-plan`, `bug-write-test`

```
┌─────────────────────────────────────────────────────┐
│  _run_phase("completeness", jobs, args)             │
│                                                     │
│  semaphore = Semaphore(max_concurrent)  # e.g. 5    │
│                                                     │
│  asyncio.gather(                                    │
│    run_with_semaphore(job_1),  ─┐                   │
│    run_with_semaphore(job_2),   │  All launched      │
│    run_with_semaphore(job_3),   │  simultaneously,   │
│    ...                          │  semaphore gates    │
│    run_with_semaphore(job_N),  ─┘  actual execution  │
│  )                                                  │
└─────────────────────────────────────────────────────┘
```

**Key details:**
- `_run_phase` at `lib/phases.py:659` creates a semaphore and launches all jobs via `asyncio.gather`
- Each job is a dict with `name`, `cwd`, `prompt`, `model_id`, `model_shorthand`, `stale_files`
- Inside `run_with_semaphore` (`lib/phases.py:682`), the semaphore is acquired before calling `run_agent()`
- Stale output files are deleted inside the semaphore (after acquiring, before running) to prevent a killed orchestrator from leaving deleted-but-never-regenerated files
- `return_exceptions=True` ensures one failure doesn't cancel others
- After all jobs complete, per-model summaries are printed

### Per-Issue Pipeline (`_run_issue_pipeline` / `run_all_phases`)

Used by: `bug-all`

This is a more sophisticated model where each issue flows through phases 2-6 sequentially, but all issues (and all models) run concurrently sharing a single semaphore.

```
┌─────────────────────────────────────────────────────────────────────┐
│  run_all_phases(args)                                               │
│                                                                     │
│  semaphore = Semaphore(max_concurrent)  # shared across everything  │
│                                                                     │
│  asyncio.gather(                                                    │
│    ┌── _run_issue_pipeline(issue_1, model_opus, semaphore) ──┐      │
│    │   phases 2+3 in parallel (asyncio.gather)               │      │
│    │   phase 4 (sequential, waits for 2+3)                   │      │
│    │   phase 5 (sequential, waits for 4)                     │      │
│    │   phase 6 (sequential, waits for 5)                     │      │
│    └─────────────────────────────────────────────────────────┘      │
│    ┌── _run_issue_pipeline(issue_1, model_haiku, semaphore) ──┐     │
│    │   (same structure)                                       │     │
│    └──────────────────────────────────────────────────────────┘     │
│    ┌── _run_issue_pipeline(issue_2, model_opus, semaphore) ──┐      │
│    │   (same structure)                                       │     │
│    └──────────────────────────────────────────────────────────┘     │
│    ...                                                              │
│  )                                                                  │
└─────────────────────────────────────────────────────────────────────┘
```

**Within each issue pipeline** (`_run_issue_pipeline` at `lib/phases.py:2256`):

1. **Phases 2+3 (completeness + context-map)** run in parallel via `asyncio.gather` — they're independent
2. **Phase 4 (fix-attempt)** runs after both 2+3 complete — needs their outputs
3. **Phase 5 (test-plan)** runs after 4 completes
4. **Phase 6 (write-test)** runs after 5 completes

Each `_maybe_run_*` function acquires the shared semaphore before launching its agent. So if `max_concurrent=5`, at most 5 agents run at any time across all issues and all models.

**Multi-model support:** When `--model opus --model haiku` is specified, the outer `asyncio.gather` creates `len(issues) * len(models)` concurrent pipelines. The semaphore is the sole throttle — it doesn't distinguish between models.

### Batch Native-Skill Orchestration (`run_rfe_speedrun_phases`)

Used by: `rfe-speedrun`, `rfe-all` (batch mode via `lib/phases.py`)

```
┌────────────────────────────────────────────────────────────┐
│  run_rfe_speedrun_phases(args)                             │
│                                                            │
│  semaphore = Semaphore(max_concurrent)                     │
│                                                            │
│  _gather_with_progress(                                    │
│    _run_native_skill_for_issue("rfe-speedrun", key_1, sem),│
│    _run_native_skill_for_issue("rfe-speedrun", key_2, sem),│
│    _run_native_skill_for_issue("rfe-speedrun", key_3, sem),│
│    ...                                                     │
│  )                                                         │
│                                                            │
│  Each agent internally runs /rfe.speedrun --headless <key> │
│  which itself launches sub-agents (see Layer 2 below)      │
└────────────────────────────────────────────────────────────┘
```

**Key details:**
- `_run_native_skill_for_issue` at `lib/phases.py:2755` acquires the semaphore, then calls `run_agent()` with the prompt `/{skill_name} --headless {issue_key}`
- `_gather_with_progress` at `lib/phases.py:2879` wraps `asyncio.gather` with a Rich progress bar
- Each launched agent gets its own Claude SDK session that discovers skills via `setting_sources=["project"]`
- The agent's prompt is a slash command (e.g., `/rfe.speedrun --headless RHAIRFE-1234`)
- **Idempotency:** `_rfe_is_complete()` checks if all expected artifacts exist and skips completed RFEs

**This is where the two layers interact:** The Python semaphore controls how many top-level agents run. Each agent is a full `/rfe.speedrun` session that internally launches its own sub-agents (see Layer 2). The semaphore does NOT count sub-agents — only top-level SDK sessions.

### Strategy Pipeline (`_run_strat_pipeline` / `run_strat_all_phases`)

Used by: `strat-all`

Each strategy runs through 4 phases sequentially: `strat-refine` -> `strat-review` -> `strat-submit` -> `strat-security-review`. Multiple strategies run concurrently via the shared semaphore.

```
┌──────────────────────────────────────────────────────┐
│  _run_strat_pipeline(strat_info, args, semaphore)    │
│                                                      │
│  strat-refine  ──(if not already refined)──>         │
│  strat-review  ──(sequential)──>                     │
│  strat-submit  ──(sequential)──>                     │
│  strat-security-review                               │
│                                                      │
│  Each phase acquires the semaphore independently     │
│  (via _run_native_skill_for_issue)                   │
│  If any phase fails, the pipeline short-circuits     │
└──────────────────────────────────────────────────────┘
```

---

## Layer 2: Agent Self-Parallelism

When an agent runs a skill like `/rfe.review` or `/rfe.speedrun`, the agent itself can launch sub-agents using the Claude Code `Agent` tool. This is the **inner parallelism layer** — the agent is the orchestrator, not Python code.

### Agent Tool Mechanics

The Claude Code `Agent` tool supports:
- `run_in_background: true` — launch an agent without blocking, get notified on completion
- `subagent_type` — specify a specialized agent type (e.g., `rfe-scorer`)
- Multiple `Agent` tool calls in a single message — launches them simultaneously

Sub-agents are independent Claude Code sessions. They share the filesystem but have separate contexts. The orchestrator agent communicates with them only through files on disk.

### Key Difference from Python Orchestration

| Aspect | Python Orchestrator | Agent Self-Parallelism |
|--------|-------------------|----------------------|
| **Concurrency control** | `asyncio.Semaphore` — hard limit | No explicit limit — relies on tool-calling rate |
| **Agent launch** | `ClaudeSDKClient.query()` | Agent tool with `run_in_background: true` |
| **Progress tracking** | Return values from `asyncio.gather` | File-based polling via `check_review_progress.py` |
| **State management** | Python variables | `scripts/state.py` to disk files |
| **Error handling** | Exception propagation | Check file existence + frontmatter error fields |
| **Context isolation** | Each SDK session is fully isolated | Sub-agents share filesystem but not context window |

---

## Detailed Skill Walkthroughs

### rfe.review — Multi-Phase Parallel Review

**Location:** `remote_skills/rfe-creator/.claude/skills/rfe.review/SKILL.md`
**Sub-agent prompts:** `remote_skills/rfe-creator/.claude/skills/rfe.review/prompts/`

This is the most complex orchestrator skill. It runs 5 sequential steps, with parallelism within steps.

```
Step 0: Parse arguments, persist flags and IDs to disk
        ↓
Step 1: Fetch missing RFEs from Jira
        ┌── fetch-agent(ID_1, background=true)
        ├── fetch-agent(ID_2, background=true)
        └── fetch-agent(ID_N, background=true)
        Poll via check_review_progress.py --phase fetch
        ↓
Step 1.5: Bootstrap (parallel, two Bash calls)
        ┌── fetch-architecture-context.sh
        └── bootstrap-assess-rfe.sh
        ↓
Step 2: Assessment + Feasibility (2N agents for N IDs)
        ┌── assess-agent(ID_1, background=true)
        ├── feasibility-agent(ID_1, background=true)
        ├── assess-agent(ID_2, background=true)
        ├── feasibility-agent(ID_2, background=true)
        └── ...
        Poll via check_review_progress.py --phase assess + --phase feasibility
        ↓
Step 3: Review agents (N agents)
        ┌── review-agent(ID_1, background=true)
        ├── review-agent(ID_2, background=true)
        └── review-agent(ID_N, background=true)
        Poll via check_review_progress.py --phase review
        ↓
Step 3.5: Revise agents (for IDs needing revision)
        filter_for_revision.py → IDs needing revision
        ┌── revise-agent(ID_x, background=true)
        ├── revise-agent(ID_y, background=true)
        └── ...
        Poll via check_review_progress.py --phase revise
        Post-processing: check_revised.py to fix auto_revised flags
        ↓
Step 4: Re-assess if revised (max 2 cycles)
        4a. Save cumulative state, remove review files
        4b. Re-run assess agents (parallel)
        4c. Re-run review agents (parallel)
        4d. Restore before_scores and revision history
        4e. Filter for revision, revise if needed
        Increment cycle counter on disk, repeat if < 2
        ↓
Step 5: Finalize
        rebuild-index, present summary (if interactive)
```

**Sub-agent launch details:**

Each sub-agent is launched with a prompt that references a file in the `prompts/` directory:

| Agent | Prompt file | Model | Key inputs |
|-------|------------|-------|------------|
| fetch-agent | `prompts/fetch-agent.md` | opus | `{KEY}` — Jira issue key |
| assess-agent | `prompts/assess-agent.md` | opus | `{KEY}`, `{DATA_FILE}`, `{RUN_DIR}`, `{PROMPT_PATH}` |
| feasibility-agent | (inline — reads `rfe-feasibility-review/SKILL.md`) | opus | `{ID}` — RFE ID |
| review-agent | `prompts/review-agent.md` | opus | `{ID}`, `{ASSESS_PATH}`, `{FEASIBILITY_PATH}`, `{FIRST_PASS}` |
| revise-agent | `prompts/revise-agent.md` | opus | `{ID}` |

**How sub-agents are launched:**

The orchestrator agent sends a message with one or more `Agent` tool calls. Example for Step 2 with 3 IDs (6 agents):

```
# Single message with 6 Agent tool calls:
Agent(prompt="Read .claude/skills/rfe.review/prompts/assess-agent.md ...", model=opus, run_in_background=true)
Agent(prompt="Read the skill file at .claude/skills/rfe-feasibility-review/SKILL.md ...", model=opus, run_in_background=true)
Agent(prompt="Read .claude/skills/rfe.review/prompts/assess-agent.md ...", model=opus, run_in_background=true)
Agent(prompt="Read the skill file at .claude/skills/rfe-feasibility-review/SKILL.md ...", model=opus, run_in_background=true)
Agent(prompt="Read .claude/skills/rfe.review/prompts/assess-agent.md ...", model=opus, run_in_background=true)
Agent(prompt="Read the skill file at .claude/skills/rfe-feasibility-review/SKILL.md ...", model=opus, run_in_background=true)
```

All 6 launch simultaneously. The orchestrator then enters a polling loop.

**What each sub-agent produces:**

| Agent | Output file | Completion signal |
|-------|------------|-------------------|
| fetch-agent | `artifacts/rfe-tasks/{KEY}.md` + `artifacts/rfe-originals/{KEY}.md` + `artifacts/rfe-tasks/{KEY}-comments.md` | Task file exists |
| assess-agent | `/tmp/rfe-assess/single/{KEY}.result.md` | Result file exists |
| feasibility-agent | `artifacts/rfe-reviews/{ID}-feasibility.md` | Feasibility file exists |
| review-agent | `artifacts/rfe-reviews/{ID}-review.md` (with frontmatter) | Review file exists with `score` set |
| revise-agent | Modified `artifacts/rfe-tasks/{ID}.md` + updated frontmatter | `auto_revised=true` in review frontmatter |

### rfe.split — Parallel Split + Review

**Location:** `remote_skills/rfe-creator/.claude/skills/rfe.split/SKILL.md`

```
Step 0: Parse arguments, persist IDs to disk
        ↓
Step 1: Launch split agents (one per ID, all parallel)
        ┌── split-agent(ID_1, background=true)
        ├── split-agent(ID_2, background=true)
        └── ...
        Poll via check_review_progress.py --phase split
        ↓
Step 2: Collect children, invoke /rfe.review on all children
        This triggers the full rfe.review pipeline above
        ↓
Step 3: Right-sizing self-correction (max 3 cycles)
        For children with right_sized < 2/2:
          Re-split → collect new children → /rfe.review
        ↓
Step 4: Finalize
```

**Split agent details:**
- Prompt: `prompts/split-agent.md`
- The split agent reads the RFE, decides whether to split (some 1/2-scored RFEs are delivery-coupled and shouldn't split), decomposes into children, allocates IDs atomically via `scripts/next_rfe_id.py`, writes child files, archives the parent
- ID allocation uses `scripts/next_rfe_id.py <count>` which is file-locked to prevent races when multiple split agents allocate IDs simultaneously
- Completion signal: `artifacts/rfe-reviews/{ID}-split-status.yaml` exists

### rfe.auto-fix — Batch Processing with Retry

**Location:** `remote_skills/rfe-creator/.claude/skills/rfe.auto-fix/SKILL.md`

```
Step 0: Parse arguments (JQL or explicit IDs)
        ↓
Step 1: Bootstrap assess-rfe
        ↓
Step 2: Resume check (skip already-reviewed IDs)
        ↓
Step 3: Batch processing
        Split IDs into batches of batch_size (default 5)
        For each batch:
          3a. /rfe.review --headless <batch_IDs>    ← triggers full review pipeline
          3b. collect_recommendations.py             ← parse results
          3c. /rfe.split --headless <split_IDs>     ← if any need splitting
          3d. Progress summary
        ↓
Step 4: Retry queue
        Re-scan all IDs for errors
        Clean up partial splits
        Re-run failed IDs through Steps 3a-3c
        ↓
Step 5: Generate reports
Step 6: Final summary
```

**Batching detail:** The auto-fix skill does NOT launch batch agents in parallel. It processes one batch at a time, calling `/rfe.review` as an inline Skill. The parallelism happens inside `/rfe.review`, which launches its sub-agents in parallel. The batch size controls how many IDs are processed in each `/rfe.review` invocation, which controls how many sub-agents that review instance launches.

**Between-batch state persistence:** Before processing, all batch ID lists are written to individual files (`tmp/autofix-batch-N-ids.txt`). The current batch number is tracked in `tmp/autofix-config.yaml`. This survives context compression.

### rfe.speedrun — End-to-End Pipeline

**Location:** `remote_skills/rfe-creator/.claude/skills/rfe.speedrun/SKILL.md`

```
Phase 1: Create
        /rfe.create --headless <idea>
        ↓
Phase 2: Auto-fix
        /rfe.auto-fix --headless <IDs>
        (internally: batched /rfe.review + /rfe.split)
        ↓
Phase 3: Submit
        /rfe.submit <passing_IDs>
        ↓
Phase 4: Summary
```

**Speedrun is sequential at the top level.** Parallelism is delegated to `/rfe.auto-fix` -> `/rfe.review` -> sub-agents. However, the **Python orchestrator** (`run_rfe_speedrun_phases` in `lib/phases.py`) launches multiple `/rfe.speedrun` sessions concurrently — one per RFE key. So the effective parallelism is:

```
Python orchestrator (asyncio.Semaphore)
  ├── Agent session: /rfe.speedrun --headless RHAIRFE-1234
  │     └── /rfe.auto-fix
  │           └── /rfe.review --headless RHAIRFE-1234
  │                 ├── fetch-agent (background)
  │                 ├── assess-agent (background)
  │                 ├── feasibility-agent (background)
  │                 ├── review-agent (background)
  │                 └── revise-agent (background)
  ├── Agent session: /rfe.speedrun --headless RHAIRFE-1235
  │     └── (same structure)
  ├── Agent session: /rfe.speedrun --headless RHAIRFE-1236
  │     └── (same structure)
  └── ...
```

**This creates a fan-out:** If `max_concurrent=5` and each speedrun launches 5 background sub-agents, there could be 25+ agent sessions active simultaneously. The Python semaphore only gates the top-level 5 — it does not see or control the sub-agents.

### assess-rfe — Rolling Pipeline of 30

**Location:** `remote_skills/rfe-creator/.claude/skills/assess-rfe/SKILL.md`

The assess-rfe skill (from the vendored `assess-rfe` plugin) uses its own parallelism model for bulk assessment:

```
Phase 2: Rolling pipeline of 30 concurrent agents
        ┌── scorer-agent(KEY_1, background=true, subagent_type=rfe-scorer)
        ├── scorer-agent(KEY_2, background=true, subagent_type=rfe-scorer)
        ├── ... (up to 30 running at once)
        │
        │   As each agent completes, immediately launch the next pending key
        │   Active polling every 30 seconds
        │   Progress: check_progress.py
        └── scorer-agent(KEY_N, ...)
```

**Key differences from rfe.review's model:**
- **Rolling pipeline:** New agents launch as soon as one completes (not batch-based)
- **Fixed concurrency cap:** Always 30 concurrent agents (not configurable via CLI)
- **Fixed polling interval:** 30 seconds (not adaptive)
- **Active polling mandate:** "Do not passively wait for completion notifications — they can be missed, causing the pipeline to hang"
- **Specialized sub-agent type:** Uses `subagent_type: rfe-scorer` (maps to a specific agent configuration)

### strat.review — Forked Sub-Reviewers

**Location:** `remote_skills/rfe-creator/.claude/skills/strat.review/SKILL.md`

```
Step 3: Run 4 reviews in parallel (forked context)
        ┌── /feasibility-review  (context: fork, model: opus)
        ├── /testability-review  (context: fork, model: opus)
        ├── /scope-review        (context: fork, model: opus)
        └── /architecture-review (context: fork, model: opus)
```

**Fork isolation:** Each reviewer runs with `context: fork`, meaning it gets an isolated copy of the context. No reviewer can see another's output. This prevents groupthink — all four assessments are independent.

The orchestrator (`strat.review`) invokes these as inline Skill calls, not background Agent calls. They run in parallel because the orchestrator launches all four in a single message with multiple Skill tool calls.

---

## Concurrency Control Mechanisms

### 1. Python asyncio.Semaphore

**Where:** `lib/phases.py` — all `_run_phase`, `_run_issue_pipeline`, `_run_strat_pipeline`, `_run_native_skill_for_issue`
**Configured by:** `--max-concurrent N` CLI flag (default: 5)
**Scope:** Controls top-level Claude SDK sessions only. Does not see or control sub-agents launched by skills.

```python
semaphore = asyncio.Semaphore(args.max_concurrent)

async with semaphore:
    result = await run_agent(...)
```

### 2. Atomic ID Allocation (File Lock)

**Where:** `remote_skills/rfe-creator/scripts/next_rfe_id.py`
**Purpose:** Prevent parallel split agents from allocating the same RFE-NNN ID

The script uses file-level locking to atomically allocate sequential IDs. When multiple split agents run simultaneously, each calls `python3 scripts/next_rfe_id.py <count>` and gets unique IDs.

### 3. Agent Tool Rate (Implicit)

**Where:** Agent-level parallelism (all orchestrator skills)
**Mechanism:** The number of `Agent` tool calls in a single message determines how many sub-agents launch simultaneously. There is no explicit cap — the orchestrator skill decides how many to launch.

**Observed patterns:**
- `rfe.review` launches 2N agents for N IDs in Step 2 (assess + feasibility)
- `assess-rfe` caps at 30 running agents (self-enforced in the skill prompt)
- `rfe.split` launches one agent per ID (no inherent cap)

### 4. Stale File Deletion Inside Semaphore

**Where:** `lib/phases.py:603-609`, `lib/phases.py:688-691`
**Purpose:** Prevent race condition where orchestrator is killed after deleting stale files but before regenerating them

```python
async with semaphore:
    # Delete stale outputs INSIDE the semaphore
    for stale_path in stale_files:
        if stale_path.exists():
            stale_path.unlink()
    # Then run the agent
    result = await run_agent(...)
```

---

## State Persistence for Compression Resilience

Long-running orchestrator skills (rfe.review, rfe.split, rfe.auto-fix, rfe.speedrun) must survive **context compression** — when the agent's conversation history is truncated to fit the context window. If IDs, flags, or cycle counters are only in the agent's memory, they can be lost.

### scripts/state.py

**Location:** `remote_skills/rfe-creator/scripts/state.py`

```bash
# Initialize a config file
python3 scripts/state.py init tmp/review-config.yaml headless=true

# Write/read config values
python3 scripts/state.py set tmp/review-config.yaml reassess_cycle=1
python3 scripts/state.py set-default tmp/review-config.yaml reassess_cycle=0  # won't overwrite
python3 scripts/state.py read tmp/review-config.yaml

# Write/read ID lists
python3 scripts/state.py write-ids tmp/review-all-ids.txt RHAIRFE-1234 RHAIRFE-1235
python3 scripts/state.py read-ids tmp/review-all-ids.txt  # outputs space-separated

# Timestamp for reports
python3 scripts/state.py timestamp

# Clean up all tmp/ files
python3 scripts/state.py clean
```

### File Prefix Convention

Each skill uses distinct file prefixes to avoid collisions when skills call each other:

| Skill | Prefix | Example files |
|-------|--------|--------------|
| `rfe.review` | `review-` | `tmp/review-config.yaml`, `tmp/review-all-ids.txt`, `tmp/rfe-poll-fetch.txt` |
| `rfe.split` | `split-` | `tmp/split-config.yaml`, `tmp/split-all-ids.txt` |
| `rfe.auto-fix` | `autofix-` | `tmp/autofix-config.yaml`, `tmp/autofix-all-ids.txt`, `tmp/autofix-batch-1-ids.txt` |
| `rfe.speedrun` | `speedrun-` | `tmp/speedrun-config.yaml`, `tmp/speedrun-all-ids.txt` |

### Anti-Compression Patterns

These patterns appear throughout the orchestrator skills:

**1. Persist before launching agents:**
```bash
python3 scripts/state.py write-ids tmp/review-all-ids.txt RHAIRFE-1234 RHAIRFE-1235
```

**2. Re-read from disk before every step (not from memory):**
```bash
# "Context compression may have corrupted in-memory lists"
python3 scripts/state.py read-ids tmp/review-all-ids.txt
```

**3. Use set-default for cycle counters (idempotent re-entry):**
```bash
# "Safe if compression causes re-entry — it won't reset an existing counter"
python3 scripts/state.py set-default tmp/review-config.yaml reassess_cycle=0
```

**4. Re-read config before checking flags:**
```bash
# "Context compression may have lost them during agent execution"
python3 scripts/state.py read tmp/review-config.yaml
```

**5. Persist batch lists individually:**
```bash
python3 scripts/state.py write-ids tmp/autofix-batch-1-ids.txt ID1 ID2 ID3
python3 scripts/state.py write-ids tmp/autofix-batch-2-ids.txt ID4 ID5 ID6
```

---

## Progress Monitoring

### check_review_progress.py

**Location:** `remote_skills/rfe-creator/scripts/check_review_progress.py`

File-based progress checker that determines completion by checking for expected output files:

| Phase | Completion signal |
|-------|------------------|
| `fetch` | `artifacts/rfe-tasks/{id}.md` exists |
| `assess` | `/tmp/rfe-assess/single/{id}.result.md` exists |
| `feasibility` | `artifacts/rfe-reviews/{id}-feasibility.md` exists |
| `review` | `artifacts/rfe-reviews/{id}-review.md` exists AND has `score` in frontmatter |
| `revise` | `artifacts/rfe-reviews/{id}-review.md` has `auto_revised=true` in frontmatter |
| `split` | `artifacts/rfe-reviews/{id}-split-status.yaml` exists |

**Adaptive polling interval:**
```python
if pending == 0:        next_poll = 0    # done
elif completed >= 75%:  next_poll = 15   # almost done, poll faster
elif completed >= 50%:  next_poll = 30
else:                   next_poll = 60   # early, poll less frequently
```

**Output format:**
```
COMPLETED=3/5, PENDING=2, NEXT_POLL=30
```

The orchestrator skill parses this output and sleeps for `NEXT_POLL` seconds before polling again. It only outputs a status line when the COMPLETED count changes.

### check_progress.py (assess-rfe plugin)

**Location:** `.context/assess-rfe/scripts/check_progress.py` (vendored)

Separate progress script for the assess-rfe bulk scoring pipeline. Reports `COMPLETED=N`, `TOTAL=N`, `REMAINING=N` for a run directory.

---

## Consistency Risks and Test Considerations

### 1. Uncontrolled Fan-Out

**Risk:** The Python semaphore controls top-level agents, but each agent can launch unlimited sub-agents. With `max_concurrent=5` and each agent launching 5+ sub-agents, actual parallelism could be 25-100+ sessions.

**Test approach:**
- Monitor total concurrent SDK sessions during a batch run
- Verify system resource usage (API rate limits, memory) under fan-out
- Test with `max_concurrent=1` to serialize top-level agents and observe sub-agent behavior

### 2. File Contention Between Sub-Agents

**Risk:** Multiple sub-agents write to the same directories (`artifacts/rfe-tasks/`, `artifacts/rfe-reviews/`). While each writes to different files (keyed by ID), concurrent directory operations could race.

**Test approach:**
- Run parallel reviews on 10+ IDs and verify all output files are complete and non-corrupt
- Check that `next_rfe_id.py` file locking works under concurrent split agents
- Verify `frontmatter.py set` operations don't corrupt YAML when called concurrently on different files

### 3. Context Compression Causing State Loss

**Risk:** An orchestrator agent's context is compressed mid-pipeline, losing in-memory ID lists or flags. The disk-based state system (`scripts/state.py`) is designed to handle this, but edge cases exist.

**Test approach:**
- Run a pipeline with enough IDs to trigger context compression (10+ IDs through rfe.review)
- Verify that post-compression steps re-read IDs correctly from disk
- Test that `set-default` cycle counters prevent infinite loops after compression
- Artificially trigger compression (large prompts) and verify recovery

### 4. Agent Completion Detection Reliability

**Risk:** The assess-rfe skill explicitly warns: "Do not passively wait for completion notifications — they can be missed, causing the pipeline to hang." The rfe.review skill doesn't have this warning but uses the same background agent pattern.

**Test approach:**
- Launch agents with `run_in_background: true` and verify all completions are detected
- Test the polling loop fallback — does the orchestrator eventually detect completed agents?
- Verify behavior when an agent crashes (does the orchestrator detect it or hang?)

### 5. Ordering and Idempotency

**Risk:** Because agents complete in arbitrary order, the orchestrator must handle out-of-order results correctly. Additionally, if a pipeline is interrupted and re-run, previously completed work should be skipped.

**Test approach:**
- Verify `_rfe_is_complete()` correctly detects all required artifacts
- Kill a pipeline mid-run, re-start it, and verify it resumes correctly
- Verify that `--force` overrides the completeness check

### 6. Nested Skill Invocation Depth

**Risk:** The call chain can be deep: Python orchestrator -> agent -> `/rfe.speedrun` -> `/rfe.auto-fix` -> `/rfe.review` -> `Agent(assess-agent)`. Each layer adds latency and potential failure points.

**Test approach:**
- Trace a single RFE through the full stack and measure latency at each layer
- Test error propagation — does a failure in a deeply nested sub-agent surface correctly?
- Verify that `--headless` propagation works through all layers

### 7. Frontmatter Post-Processing Race

**Risk:** After revise agents complete, the orchestrator runs `check_revised.py` and may update the `auto_revised` flag. If another agent is still writing to the same review file, this could race.

**Test approach:**
- Verify that post-processing only runs after ALL agents in a step have completed
- Check that the orchestrator polls until `PENDING=0` before proceeding

### 8. Error Cascading in Pipelines

**Risk:** In `_run_strat_pipeline`, if `strat-refine` fails, subsequent phases are skipped. But in `rfe.review`, a failed assess agent is removed from the processing list while others continue. The error handling models differ.

**Test approach:**
- Inject failures at each step and verify the correct behavior (skip vs continue)
- Verify error frontmatter (`error="assess_failed"`) is set correctly
- Test the retry queue in `rfe.auto-fix` — do retried failures get permanent error status?

### 9. tmp/ Directory Cleanup

**Risk:** State files accumulate in `tmp/` across runs. If not cleaned, stale state could affect subsequent runs.

**Test approach:**
- Verify `scripts/state.py clean` removes all state files
- Run a pipeline twice without cleaning and verify no interference
- Test that `rfe.speedrun` calls `state.py clean` at the start (it does in Step 0)

### 10. Multi-Model Interaction

**Risk:** `bug-all` supports multiple `--model` flags, creating `issues * models` concurrent pipelines sharing one semaphore. Model-specific workspace directories (`workspace/{KEY}/{model_id}/`) should prevent file contention, but this needs verification.

**Test approach:**
- Run `bug-all --model opus --model haiku --max-concurrent 3` on 5 issues
- Verify outputs exist in both `workspace/{KEY}/claude-opus-4-6/` and `workspace/{KEY}/claude-haiku-3-5/`
- Verify the semaphore correctly limits total agents (not per-model)
