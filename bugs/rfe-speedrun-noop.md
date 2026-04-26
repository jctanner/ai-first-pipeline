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

## Possible mitigations

1. **Post-execution validation in `run_skill.sh`**: Check that expected
   artifacts exist before returning exit 0. Exit non-zero if missing,
   so markov can detect the failure and retry.

2. **Make `load_rfe_results` artifacts optional**: Add `optional: true`
   and guard downstream steps with `when` checks, so one bad ticket
   doesn't kill the batch.

3. **Switch to SDK runner**: The SDK runner (`lib/agent_runner.py`)
   manages the conversation loop programmatically and may be less
   susceptible to early termination. The dashboard already supports
   both CLI and SDK runners.

4. **Retry at the workflow level**: Add a retry mechanism for
   `rfe_speedrun` or `load_rfe_results` failures, though markov's
   current `for_each` only retries on resume, not automatically.

## Related

- markov-run-2c224dcd also failed on RHAIRFE-1017 (same pattern, same
  missing task artifact)
- Both failures occurred mid-batch when many concurrent agents were
  running
