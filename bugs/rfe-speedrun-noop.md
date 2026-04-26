# rfe-speedrun agent exits after setup without doing work

## Summary

The `rfe-speedrun` skill occasionally completes with exit code 0 but
produces no artifacts. The agent initializes config, runs a few setup
bash commands, and then stops — never fetching the Jira ticket, running
reviews, or writing task/review files.

## Observed behavior

**Failing run (RHAIRFE-1040 in markov-run-6effe0d7):**

```
Executing: claude --model opus --print "/rfe.speedrun --headless RHAIRFE-1040"

💬 Claude
I'll start by parsing the arguments and setting up the speedrun pipeline
for the existing RFE RHAIRFE-1040.
This is **Mode B** (existing Jira key) — skip create, go straight to
auto-fix and submit.

🔧 Bash $ ls scripts/
📊 TOKENS in=2 out=166 cache_r=14471 cache_w=4495 total=19134
🔧 Bash $ python3 scripts/state.py clean
🔧 Bash $ ls tmp/ 2>/dev/null; echo "---"; ls artifacts/ 2>/dev/null
🔧 Bash $ rm -rf tmp && mkdir -p tmp
🔧 Bash $ python3 scripts/state.py init tmp/speedrun-config.yaml ...

Execution finished at: Sun Apr 26 05:23:20 UTC 2026
Exit code: 0
```

Total duration: 26 seconds. One model turn, 166 output tokens, 5 bash
calls (all setup). No Jira fetch, no sub-agents, no artifacts written.

**Successful re-run (same ticket, same parameters):**

```
Executing: claude --model opus --print "/rfe.speedrun --headless RHAIRFE-1040"

📊 TOKENS in=2 out=418 cache_r=0 cache_w=18966 total=19386
🤖 Agent Fetch RHAIRFE-1040 from Jira
📊 TOKENS in=1 out=730 cache_r=24106 cache_w=728 total=25565
...
```

The re-run immediately proceeds past setup to fetch the ticket and
launch sub-agents.

## Impact

- One noop failure in a `for_each` batch kills the entire run due to
  fail-fast semantics. RHAIRFE-1040's missing artifacts caused
  `load_rfe_results` to fail, which aborted all 100 tickets in
  markov-run-6effe0d7.
- The noop also occurred for RHAIRFE-1017 in a prior run
  (markov-run-2c224dcd), same pattern.

## Environment

- Runner: CLI (`claude --model opus --print`)
- Invocation: `run_skill.sh --skill rfe-speedrun --issue RHAIRFE-XXXX --model opus`
- Concurrency: 10 parallel agent jobs via markov `for_each`

## Likely cause

The `--print` flag makes Claude run in single-shot mode. The model
non-deterministically decides its work is "done" after the setup phase,
especially when:
- Cache hit rate is high (14471 cache_r tokens on the failing run vs 0
  on the successful re-run) — suggesting context was pre-warmed from a
  concurrent run on the same pod/node
- Many concurrent agents are running (contention for model capacity)

The skill prompt expects the model to execute a multi-step pipeline
(fetch → assess → review → write artifacts), but the model treats the
config initialization as task completion.

## Mitigation implemented

We implemented a **recursive retry sub-workflow** using markov's gate
rules engine and recursive workflow calls. The pattern replaces the
direct `rfe_speedrun` → `load_rfe_results` sequence with a retry loop
that tolerates noop failures.

### Design

The `per-ticket` workflow now calls `rfe-speedrun-retry` (max 3
attempts) instead of running `rfe_speedrun` directly:

```
per-ticket
  └─ ensure_rfe_artifacts → rfe-speedrun-retry (retries_remaining: 3)
       ├─ check_artifacts    — load task + review (both optional)
       ├─ eval_retry_state   — set artifacts_ready boolean
       ├─ retry_gate         — rules engine decides:
       │    • artifacts exist (salience 200) → skip, done
       │    • missing + retries > 0 (salience 100) → continue
       │    • missing + retries = 0 (salience 150) → skip, mark failed
       ├─ run_speedrun       — agent_job (only if needed)
       ├─ decrement_retries  — retries_remaining - 1
       └─ recurse            — calls rfe-speedrun-retry again
```

Three gate rules control the loop:

| Rule | Salience | Condition | Action |
|------|----------|-----------|--------|
| `retry_artifacts_ready` | 200 | `artifacts_ready` | skip (done) |
| `retry_exhausted` | 150 | `not artifacts_ready and retries_remaining <= 0` | skip (give up) |
| `retry_continue` | 100 | `not artifacts_ready and retries_remaining > 0` | continue (retry) |

After the retry sub-workflow returns, `load_rfe_results` loads both
artifacts as `optional: true`. A `check_rfe_artifacts` fact
(`rfe_artifacts_ready`) gates all downstream steps, so a ticket that
failed all 3 attempts is silently skipped instead of crashing the batch.

### Initial observations (markov-run-19ab5533, 10 tickets)

- Tickets with existing artifacts (RHAIRFE-1, 101, 1000, 1007, 1016)
  hit the retry gate, `retry_artifacts_ready` fires at salience 200,
  and the sub-workflow exits immediately — no agent job spawned.
- Tickets needing work enter the speedrun agent job as expected.
- All 10 tickets dispatched at concurrency 10 simultaneously.
- The gate rules engine correctly evaluates all three rules and picks
  the highest-salience match.
- No batch-level failures from missing artifacts.

### Remaining concerns

1. **Post-execution validation**: `run_skill.sh` still returns exit 0
   on noop runs. Adding artifact existence checks to the script would
   let markov detect failures earlier (non-zero exit → step failure →
   immediate retry) rather than waiting for the recursive check.

2. **SDK runner**: The CLI `--print` mode may be inherently more
   susceptible to early termination than the SDK runner. The dashboard
   supports both; switching the workflow to SDK could reduce noop
   frequency.

3. **Root cause**: The noop behavior correlates with high prompt cache
   hit rates (14471 cache_r on the failing run vs 0 on successful
   re-run), suggesting shared prompt caching across concurrent agents
   on the same node may confuse the model's sense of task completion.

## Related

- markov-run-2c224dcd failed on RHAIRFE-1017 (same noop pattern)
- markov-run-6effe0d7 failed on RHAIRFE-1040 (same noop pattern)
- Both failures occurred mid-batch with high concurrency
- Manual re-run of RHAIRFE-1040 succeeded on second attempt,
  confirming the failure is non-deterministic
