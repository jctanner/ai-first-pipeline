# Test Notes — Layer 2 Agent Self-Parallelism

## 2026-04-05: Initial Findings

### Test: `test_background_completion` (N=30, batch_size=5)

#### Setup
- Container: Fedora 42, Python 3.13, claude-agent-sdk 0.1.48
- Model: claude-opus-4-6 via Vertex AI
- Agent is instructed to process 30 tasks in batches of 5
- Each task runs `fixtures/workload.py` (black-box script, 2-6s random duration)
- Agent cannot shortcut the work — must run the script and wait

#### Finding 1: Agent drops batches after batch 1 (60% of the time)

**Data** (5 iterations, original SDK usage — single `query()`):
```
Perfect runs (all 30 completed): 2/5 (40.0%)
Completion rate: 16.7% – 100.0% (mean 50.0%)
```

**Pattern**: Bimodal — the agent either completes 5/30 (one batch) or 30/30 (all six batches). Never partial (e.g., 15/30). When it fails, it always stops after exactly batch 1.

- Iterations 1, 3, 5: completed 5/30, took ~28-32s
- Iterations 2, 4: completed 30/30, took ~141-149s

**No items are ever dropped within a batch.** The failure is always at the batch boundary.

#### Finding 2: Root cause — SDK `end_turn` kills the session

From the agent logs (iteration 1, failed run):

```
[agent] AssistantMessage(content=[TextBlock(text='TASK-04 complete. Waiting for remaining...')])
[agent] ResultMessage(subtype='success', ... stop_reason='end_turn', ...)
```

After receiving a task completion notification, the agent emits a text-only response (no tool calls). The SDK interprets this as `end_turn` and closes the stream — even though 3 sub-agents from batch 1 are still running and batches 2-6 haven't started.

**This does not happen in CLI mode.** The CLI keeps the session alive because the user turn is always pending. The SDK has no equivalent — when the agent stops calling tools, the session ends.

#### Finding 3: Prior run (N=8, no batching) — 100% per-item completion

With only 8 tasks (all launched in one message, no batching needed):
```
Tasks completed every time: 100.0%
Summary written: 20.0%
```

All items complete reliably when no batching is needed. The agent just forgets the follow-up step (writing summary.txt) 80% of the time.

### Hypotheses

1. **Re-querying the agent after `end_turn` should fix batch continuation.**
   The SDK supports multi-turn via `client.query()` called again on the same session.
   We implemented a harness-level nudge loop that detects pending background tasks
   and re-queries the agent to continue. Status: **testing in progress**.

2. **`Task` is the correct SDK tool name, not `Agent`.**
   The agent init message shows `Task`, `TaskOutput`, `TaskStop` — not `Agent`.
   `Agent` worked as an alias but we switched to the explicit names.

3. **`continue_conversation` is a `ClaudeAgentOptions` constructor param, not a `query()` kwarg.**
   We incorrectly passed it to `query()`, causing `TypeError` and 0% completion
   across all 5 iterations in one run. Fixed by removing the kwarg —
   multi-turn works by simply calling `query()` again on the same client.

4. **The production pipeline (`lib/agent_runner.py`) has the same bug.**
   It uses the same single `query()` + `receive_response()` pattern. Any skill
   that relies on multi-batch background agents (rfe.auto-fix, assess-rfe rolling
   pipeline of 30) would hit the same `end_turn` problem when run via the SDK.

### SDK API Reference (claude-agent-sdk 0.1.48)

```python
# ClaudeAgentOptions key params:
#   allowed_tools: list[str]         — e.g. ["Read", "Bash", "Task"]
#   permission_mode: str             — "bypassPermissions" for tests
#   max_turns: int | None            — default None (unlimited)
#   continue_conversation: bool      — constructor only, not for query()
#   resume: str | None               — pass session_id to resume
#   agents: dict[str, AgentDefinition]  — named sub-agent definitions

# ClaudeSDKClient.query() signature:
#   query(prompt: str, session_id: str = "default") -> None

# Multi-turn: call query() again on the same client instance.
# The session context is preserved automatically.
```

#### Finding 4: Re-query loop works but agent ignores batch constraint

**Data** (1 iteration, with nudge loop, `Task` tool instead of `Agent`):

The agent launched **all 30 tasks at once** — completely ignoring the batch_size=5
instruction. The harness detected 30 pending tasks and began nudging:

```
[harness] task started: ... (pending=1)
... 30 task_started messages ...
[harness] agent hit end_turn with 30 pending tasks — re-querying (nudge 1)
[harness] task completed: ... (pending=29)
[harness] agent hit end_turn with 29 pending tasks — re-querying (nudge 2)
[harness] agent hit end_turn with 29 pending tasks — re-querying (nudge 3)
[harness] task completed: ... (pending=28)
[harness] agent hit end_turn with 28 pending tasks — re-querying (nudge 4)
```

The nudge loop kept the session alive but each re-query only drained ~1 completion.
The test hit the 600s timeout. However, **all 30 task files existed on disk** — the
tasks completed, the test just didn't check after the timeout error.

**Three problems exposed:**
1. Agent ignored batch_size=5 and launched all 30 at once
2. Nudge loop is expensive — each re-query is a full API round-trip just to hear "still waiting"
3. Error handler returned 0 completed without checking the filesystem (fixed)

#### Finding 5: `Agent` tool vs `Task` tool

When we switched `allowed_tools` from `["Agent"]` to `["Task", "TaskOutput", "TaskStop"]`,
the agent's behavior changed. With `Agent`, it launched 5 at a time (sometimes).
With `Task`, it launched all 30 at once. This suggests:
- `Agent` may have had an implicit batching mechanism or different sub-agent model
- `Task` gives the agent direct access to fire-and-forget sub-agents without constraints
- We may need to test both tool configurations and compare

#### Finding 6: SDK cannot replicate CLI session semantics

The CLI and SDK have fundamentally different session models:

| | CLI | SDK |
|---|-----|-----|
| Session lifetime | Persistent — agent is always "in conversation" | Request/response — stream ends on `end_turn` |
| Background task notifications | Arrive as system messages, naturally re-prompt the agent | Only visible while `receive_response()` is active |
| "Keep alive" signal | Implicit — human is always there | Must be faked via re-query loop |
| Agent behavior | Agent can emit status text and keep working | Status text with no tool call = session over |

This is not a bug we can fix in the harness. The SDK is architecturally
request/response. Our nudge loop approximates the CLI's persistent session, but:
- It's expensive (one API round-trip per nudge)
- It changes the agent's context (injecting "you still have N pending" messages)
- It can't perfectly replicate the CLI's notification delivery timing

**Implication for production:** The production pipeline (`lib/agent_runner.py`)
uses the SDK with a single `query()` + `receive_response()` cycle. Any skill
that relies on multi-batch background agents will behave differently than it
does in CLI development/testing. This is a fundamental gap — skills developed
and tested in the CLI may fail when run via the SDK orchestrator.

**Implication for these tests:** SDK test results measure "agent + our harness"
behavior, not pure agent behavior. This is still the right thing to test because
production uses the SDK. But we should consider also testing via `claude` CLI
subprocess to establish a CLI baseline for comparison.

### Possible Approaches

1. **Keep SDK harness + nudge loop** — tests what production actually does,
   but harness complexity is itself a variable. Iterate on reducing nudge
   overhead (e.g., sleep between re-queries, batch nudges).

2. **Test via CLI subprocess** — run `claude --print` or `claude -p` in the
   container, pipe the prompt in, capture stdout. Removes the SDK session
   management issue entirely. Tests pure agent behavior with persistent session.

3. **Both** — run the same test scenario via SDK and CLI, compare results.
   The delta between them quantifies the SDK session management gap.

### Test Runner Modes

We now have three runner modes in `conftest.py`, selectable via `TEST_RUNNER` env var:

| Mode | Env value | Description |
|------|-----------|-------------|
| SDK simple | `sdk` | Single `query()` + `receive_response()`. Baseline — shows the `end_turn` problem. |
| SDK nudge | `sdk-nudge` | Re-queries the agent when background tasks are still pending. Approximates CLI behavior. |
| CLI | `cli` | Runs `claude -p` subprocess. Persistent session, exits when fully done. No nudge needed. |

#### CLI runner implementation notes

- Uses `claude -p <prompt> --dangerously-skip-permissions --bare --verbose`
- `--bare` skips hooks, auto-memory, CLAUDE.md discovery for a clean test env
- `--verbose` required for streaming output (without it, `-p` only prints final result)
- `--allowed-tools Read,Write,Edit,Glob,Grep,Bash,Agent` — uses `Agent` tool name (CLI convention)
- `--output-format stream-json` requires `--verbose` flag — initial attempt without it failed
- Requires `@anthropic-ai/claude-code` npm package installed in the container

#### Finding 7: CLI runner — initial attempt failed on flag mismatch

First CLI run failed immediately (1.1s) with:
```
Error: When using --print, --output-format=stream-json requires --verbose
```

Fixed by dropping `--output-format stream-json` and using `--verbose` for
plain-text streaming output.

#### Finding 8: CLI runner — 30/30 on first attempt

**Data** (1 iteration, CLI runner, N=30, batch_size=5):
```
passed: true
completion_rate: 100.0%
tasks_completed: 30/30
duration: 135.0s
missing: 0
corrupt: 0
```

All 30 tasks completed with real duration spread (2.2s – 6.5s). The CLI's
persistent session model handles background tasks natively — no nudge loop,
no dropped batches, no premature `end_turn`.

**This confirms the SDK `end_turn` is the root cause** of the batch-dropping
behavior seen in Findings 1-2. The agent itself is capable of managing
multi-batch workloads; the SDK session model prevents it from doing so.

**Comparison across runner modes (N=30, batch_size=5):**

| Runner | Completion rate | Batching respected? | Notes |
|--------|----------------|---------------------|-------|
| SDK simple | 40% (2/5 perfect) | Yes (when it worked) | Bimodal: 5/30 or 30/30 |
| SDK nudge | 100% on disk, timed out | No — fired all 30 at once | Nudge loop too slow to drain |
| CLI | 100% (5/5 perfect) | Yes — perfect 6x5 batches | Confirmed over 5 iterations |

#### Finding 9: CLI runner — verified batching from task timestamps

Analyzing `start_epoch` from each task's JSON output confirms the agent
batched exactly as instructed (6 batches of 5):

```
Batch 1: TASK-01–05  start=1775425294.5  (all within 0.1s)
Batch 2: TASK-06–10  start=1775425309.4  (+15s gap)
Batch 3: TASK-11–15  start=1775425322.0  (+13s gap)
Batch 4: TASK-16–20  start=1775425334.9  (+13s gap)
Batch 5: TASK-21–25  start=1775425347.5  (+13s gap)
Batch 6: TASK-26–30  start=1775425360.3  (+13s gap)
```

Each batch starts ~13s after the previous (workload time + agent overhead).
Tasks within a batch start simultaneously (within 0.1s). The agent followed
the batch_size=5 constraint perfectly in CLI mode.

This confirms:
- The agent **can** manage multi-round batched work correctly
- The SDK session model is what prevents it, not the agent's reasoning
- The CLI's persistent session is critical for background task orchestration

#### Finding 10: CLI runner — 5/5 perfect over 5 iterations (150/150 tasks)

**Data** (5 iterations, CLI runner, N=30, batch_size=5):
```
Perfect runs (all 30 completed): 5/5 (100.0%)
Completion rate: 100.0% – 100.0% (mean 100.0%)
Total items: 150/150 (missing 0, corrupt 0)
Duration range: 128.5s – 170.9s (mean 142.3s)
```

Per-iteration breakdown:
| Iteration | Completed | Duration | Task duration range |
|-----------|-----------|----------|---------------------|
| 1 | 30/30 | 134.9s | 2.38s – 6.98s |
| 2 | 30/30 | 170.9s | 2.14s – 6.24s |
| 3 | 30/30 | 142.0s | 2.20s – 6.65s |
| 4 | 30/30 | 135.4s | 2.98s – 6.79s |
| 5 | 30/30 | 128.5s | 2.46s – 6.88s |

Zero items dropped across all 150 tasks. Zero corrupt outputs.
The CLI runner is **deterministically reliable** for multi-batch background
task orchestration — the `end_turn` problem is entirely an SDK artifact.

#### Finding 11: SDK simple runner — confirms bimodal pattern (3/5 perfect, 105/150 tasks)

**Data** (5 iterations, SDK simple runner, N=30, batch_size=5, `Task` tool):
```
Perfect runs (all 30 completed): 3/5 (60.0%)
Completion rate: 16.7% – 100.0% (mean 70.0%)
Total items: 105/150 (missing 45, corrupt 0)
Duration range: 28.4s – 144.9s (mean 102.7s)
```

Per-iteration breakdown:
| Iteration | Completed | Duration | Pattern |
|-----------|-----------|----------|---------|
| 1 | 10/30 | 59.3s | Stopped after batch 2 (TASK-01–10) |
| 2 | 5/30 | 28.4s | Stopped after batch 1 (TASK-01–05) |
| 3 | 30/30 | 136.9s | Perfect |
| 4 | 30/30 | 143.8s | Perfect |
| 5 | 30/30 | 144.9s | Perfect |

Same bimodal `end_turn` pattern as Finding 1. Iteration 1 is notable — it
completed **two** batches (10/30) instead of the usual one (5/30), showing
the failure point isn't always at the same batch boundary. Iteration 2 is
the classic one-batch-then-dead failure.

Compared to Finding 1 (also SDK simple, also `Task` tool): 60% vs 40% perfect
rate. Small sample sizes — likely just variance, not a meaningful difference.

**Updated comparison across all runner modes (N=30, batch_size=5):**

| Runner | Perfect rate | Completion mean | Batching? | Notes |
|--------|-------------|-----------------|-----------|-------|
| SDK simple (F1) | 40% (2/5) | 50.0% | Yes (when it worked) | Bimodal: 5/30 or 30/30 |
| SDK simple (F11) | 60% (3/5) | 70.0% | Yes | Got 10/30 once (2 batches) |
| SDK nudge | 100% on disk, timed out | No — fired all 30 | Nudge loop too slow |
| CLI | 100% (5/5) | 100.0% | Yes — perfect 6x5 | Deterministically reliable |

The SDK simple runner remains unreliable. The CLI runner is the only deterministic path.

#### Finding 12: SDK nudge runner — 5/5 perfect but 2.4x slower than CLI

**Data** (5 iterations, SDK nudge runner, N=30, batch_size=5, `Task` tool):
```
Perfect runs (all 30 completed): 5/5 (100.0%)
Completion rate: 100.0% – 100.0% (mean 100.0%)
Total items: 150/150 (missing 0, corrupt 0)
Duration range: 184.9s – 600.1s (mean 340.1s)
```

Per-iteration breakdown:
| Iteration | Completed | Duration | Notes |
|-----------|-----------|----------|-------|
| 1 | 30/30 | 600.1s | Barely under the 600s timeout |
| 2 | 30/30 | 184.9s | |
| 3 | 30/30 | 469.3s | |
| 4 | 30/30 | 239.7s | |
| 5 | 30/30 | 206.5s | |

The nudge loop **can** achieve 100% completion — this is the first 5/5 perfect
SDK run. But the cost is enormous:
- **2.4x slower** on average vs CLI (340.1s vs 142.3s)
- **Highly variable** — 184.9s to 600.1s (3.2x spread) vs CLI's 128.5s–170.9s (1.3x spread)
- Iteration 1 took 600.1s — effectively hit the timeout boundary
- Each nudge is a full API round-trip, adding latency and token cost

Contrast with the earlier SDK nudge attempt (Finding 4) where the agent fired
all 30 tasks at once and timed out. This run respected batching, suggesting
the agent's behavior with the nudge loop is also non-deterministic.

**Updated comparison across all runner modes (N=30, batch_size=5):**

| Runner | Perfect rate | Completion mean | Duration mean | Batching? | Notes |
|--------|-------------|-----------------|---------------|-----------|-------|
| SDK simple (F1) | 40% (2/5) | 50.0% | — | Yes (when it worked) | Bimodal: 5/30 or 30/30 |
| SDK simple (F11) | 60% (3/5) | 70.0% | 102.7s | Yes | Got 10/30 once |
| SDK nudge (F4) | 100% on disk | — | timed out | No — fired all 30 | Different behavior |
| SDK nudge (F12) | 100% (5/5) | 100.0% | 340.1s | Yes | 2.4x slower than CLI |
| CLI (F10) | 100% (5/5) | 100.0% | 142.3s | Yes — perfect 6x5 | Deterministically reliable |

#### Finding 13: CLI runner supports skill invocation and argument passthrough

**Data** (CLI runner, no `--bare`):

| Subtest | Passed | Duration |
|---------|--------|----------|
| Basic skill invocation (`test-echo`) | Yes | 9.9s |
| Skill with args (`test-echo-args`, args=`"RHOAIENG-12345 --priority high"`) | Yes | 8.7s |

**Setup:** Test skills placed in `.claude/skills/` inside the container. CLI
invoked without `--bare` so it discovers skills via normal auto-discovery.
Agent uses `Skill` tool with `skill` and `args` parameters.

**Key findings:**
- Skills are discovered and invokable via `claude -p` when `--bare` is omitted
- Arguments are passed through intact (validated by echoing them back in output JSON)
- `--allowed-tools` must include `Skill` for the agent to use the Skill tool
- Both subtests passed on first attempt — no flakiness

**Implication for production:** The CLI runner can replace the SDK for
production workloads that need:
1. Reliable multi-batch background task orchestration (Findings 8-10)
2. Skill invocation with argument passthrough (this finding)
3. CLAUDE.md and project context discovery (inherent without `--bare`)

The SDK cannot do #1 reliably and has no skill discovery mechanism at all.

### SDK API Learnings (accumulated)

```python
# ClaudeAgentOptions key params:
#   allowed_tools: list[str]         — e.g. ["Read", "Bash", "Task"]
#   permission_mode: str             — "bypassPermissions" for tests
#   max_turns: int | None            — default None (unlimited)
#   continue_conversation: bool      — constructor param, NOT for query()
#   resume: str | None               — pass session_id to resume
#   agents: dict[str, AgentDefinition]  — named sub-agent definitions

# ClaudeSDKClient.query() signature:
#   query(prompt: str, session_id: str = "default") -> None
#   *** Does NOT accept continue_conversation or other kwargs ***

# Multi-turn: call query() again on the same client instance.
# The session context is preserved automatically.

# CLI equivalent:
#   claude -p "prompt" --dangerously-skip-permissions --bare --verbose
#   Handles background tasks natively — no nudge loop needed.
```

### Open Questions

- ~~Does the CLI runner produce 100% completion on the batching test?~~ **Yes — 5/5 perfect, 150/150 tasks (Finding 10).**
- Should we revert SDK tests to use `Agent` tool instead of `Task`?
- Is there a way to constrain sub-agent concurrency at the SDK level (via `agents` param)?
- Does `continue_conversation=True` on ClaudeAgentOptions change SDK behavior?
- Would defining sub-agents via the `agents` param improve reliability?
- At what N does the agent start dropping individual items within a batch?
- Can we reduce SDK nudge overhead by sleeping between re-queries?
