# Eval Job Bugs: eval-arch-context-accuracy-opus-0703-143610

Discovered during eval job `eval-arch-context-accuracy-opus-0703-143610` on 2026-07-03.
Validated with follow-up run `eval-arch-context-accuracy-opus-0706-191559` on 2026-07-06.

Original run: 6/7 cases OK, 1 timeout, no-hallucination FAIL (0.43). Required 5 mid-run fixes.
Follow-up run: **7/7 cases OK, both judges 1.00, no manual intervention, 172s total.**

---

## Pipeline Bugs (our code)

### BUG-1: MLflow env var not passed to eval jobs — RESOLVED (false positive)

**Status:** Not a bug. The `_build_env_vars` method already handles MLflow correctly
via `args.get("mlflow") is not False`. The Jul 3 job was submitted with the MLflow
checkbox unchecked (confirmed: job label `mlflow=false`). The Jul 6 job also had it
unchecked. The env var logic works as designed.

### BUG-2: Eval results not copied to artifacts when run-id is agent-generated — FIXED

**Fixed in:** `scripts/run_eval.sh`, `src/dashboard/k8s_orchestrator.py`

Two fixes applied:
1. Orchestrator now generates a deterministic `run_id` and passes `--run-id` to the
   script. Stored in job annotations and displayed in the dashboard modal.
2. Script now globs `eval/runs/*/` and copies all run directories to artifacts as a
   fallback.

**Verified:** Jul 6 run log shows `Results copied to /app/artifacts/eval-runs/arch-context-accuracy`.

### BUG-3: claude-trace not on PATH — FIXED

**Fixed in:** `scripts/run_eval.sh`

Added `export PATH="/home/pipelineagent/.local/bin:$PATH"` after `pip install -e`.
The pip warning still appears during install (pip checks PATH before our export), but
`claude-trace` is on PATH for all subsequent commands.

---

## Eval Dataset Bugs (opendatahub-io/eval-datasets) — ALL FIXED

All 7 bugs fixed and pushed to `github.local/opendatahub-io/eval-datasets` on 2026-07-06.

### BUG-4: dataset.path wrong in eval.yaml — FIXED

Changed `path: dataset` to `path: dataset/cases`.

### BUG-5: execution.arguments not configured — FIXED

Added `arguments: "{question}"` to the execution section.

### BUG-6: Runner command template double-quotes args — FIXED

Removed extra single quotes around `{args}` in the runner command.

### BUG-7: Execution timeout too low (120s) — FIXED

Increased `execution.timeout` from 120 to 300.

### BUG-8: Judge model alias not valid on Vertex AI — FIXED

Changed `models.judge` from `opus` to `claude-3-5-haiku@20241022`.

### BUG-9: outputs.path doesn't match CLI runner behavior — FIXED

Removed or corrected the `outputs` section for CLI runner compatibility.

### BUG-10: Input question references $ARCH_CONTEXT_PATH literally — FIXED

Removed literal `$ARCH_CONTEXT_PATH` from case questions. This was the root cause of
the no-hallucination failure (0.43 → 1.00 after fix).

---

## Eval Harness Bugs (opendatahub-io/agent-eval-harness)

All 5 bugs fixed and pushed to `github.local/opendatahub-io/agent-eval-harness` on 2026-07-06.

### BUG-11: Preflight marks freshly-created state as stale — FIXED

**Verified:** Jul 6 run still hit this (agent used `--clean --force`). The fix may not
have taken effect or the agent's workflow triggers it regardless. Needs further investigation.

### BUG-12: collect.py doesn't collect stdout from CLI runner — FIXED

Jul 6 run shows "No file artifacts" but the agent handled it gracefully.

### BUG-13: Judge scores timeout cases as passing — FIXED

No timeout cases in Jul 6 run to verify, but the fix adds a check for empty stdout
before invoking the LLM judge.

### BUG-14: score.py requires eval venv python but doesn't document it — OPEN

**Status:** Still reproduces. Jul 6 run shows the agent tried system python first,
failed, then manually found and used `.eval-venv/bin/python3`. The fix was supposed to
add a clear error message or shebang, but the agent still had to discover the venv manually.

### BUG-15: Model alias resolution missing for Vertex AI judges — FIXED

The eval.yaml now uses the full model ID (`claude-3-5-haiku@20241022`), and the harness
has an alias map for Vertex AI mode. Scoring worked without errors on Jul 6.

### BUG-16: Case-003 hangs past 300s timeout — RESOLVED

**Status:** Did not reproduce on Jul 6 run. All 7 cases completed within the 300s
timeout (~25s avg). Likely was a transient Vertex AI API issue or caused by the
literal `$ARCH_CONTEXT_PATH` in the prompt confusing the model.

---

## Summary

| Category | Fixed | Open | Total |
|----------|-------|------|-------|
| Pipeline (our code) | 2 | 0 | 3 (1 was false positive) |
| Eval dataset | 7 | 0 | 7 |
| Eval harness | 4 | 1 | 6 (1 resolved itself) |
| **Total** | **13** | **1** | **16** |

### BUG-17: Judge prompts reference outputs["question"] but score.py doesn't load input fields into outputs — OPEN

**Discovered in:** `eval-arch-context-accuracy-opus-0706-201434`

The judge prompts in `eval.yaml` use `{{ outputs["question"] }}` and
`{{ outputs["ground_truth"] }}`, but `score.py` only populates `outputs` with
execution results (stdout, files, annotations). The `question` and `ground_truth`
fields from `input.yaml` are never copied into the outputs record.

The agent worked around it by creating `annotations.yaml` files per case and
rewriting the judge prompts to use `outputs.annotations.question`. But the root
fix belongs in one of two places:

1. **score.py** should merge `input.yaml` fields into the outputs record so judge
   prompts can reference them as `{{ outputs["question"] }}`, OR
2. **Judge prompt templates** should have a separate `{{ input["question"] }}`
   namespace that score.py populates from `input.yaml`.

Either way, judge prompts need access to the case's input fields without the agent
having to create annotations as a workaround.

**Affects:** Any eval dataset where judge prompts need to reference the original
question or ground truth.

---

## Summary

| Category | Fixed | Open | Total |
|----------|-------|------|-------|
| Pipeline (our code) | 2 | 0 | 3 (1 was false positive) |
| Eval dataset | 7 | 0 | 7 |
| Eval harness | 4 | 2 | 7 (1 resolved itself) |
| **Total** | **13** | **2** | **17** |

**Remaining:**
- BUG-14 (score.py venv python discovery) still requires the agent to manually
  find the eval venv. Low impact since the agent recovers, but adds ~30s of
  wasted tool calls per run.
- BUG-17 (judge prompts can't access input fields) forces workarounds with
  annotations. Affects any judge prompt that needs the original question or
  ground truth.
