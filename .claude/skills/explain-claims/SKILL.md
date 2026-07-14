---
name: explain-claims
description: Explain why a contradicted or insufficient-evidence claim was produced by correlating source artifacts, verification evidence, job logs, traces, and tool activity. Use after verification to route improvements to skills, context, retrieval, workflows, tools, models, policies, or human-owned sources.
allowed-tools: Read, Write, Glob, Grep, Bash
user-invocable: true
---

# Explain Claims

Perform forensic analysis on verified claims to determine why each problematic
claim was made and which system layer should improve. A verdict is not itself a
root cause: distinguish generator failures from evidence, retrieval, workflow,
tooling, and human-source failures.

Treat causal attribution as an evidence-backed hypothesis. State material
alternative explanations and use `unknown` when the available traces cannot
distinguish them; never present speculation about hidden model state as fact.

## Inputs

This skill accepts inputs as positional arguments and/or kwargs in a `## Inputs` section appended to the prompt:

- **Issue key** (positional, e.g. `RHAISTRAT-1676`) — explain claims linked to this Jira key
- **claim_id** (kwarg, e.g. `123`) — explain a specific claim by ID
- **verdict_filter** (kwarg, e.g. `contradicted,insufficient_evidence`) — only explain claims with these verdicts (default: `contradicted,insufficient_evidence`; legacy aliases remain accepted)
- **limit** (kwarg, e.g. `10`) — max claims to process (default: 20)
- **implementation_revision**, **repository_revision**, **model**, **harness**,
  and **configuration_digest** — resolved explainer tree identity and resolved
  repository commit to persist
- **evidence_revision** and **evidence_context_digest** — immutable forensic
  input identity; bind output to these values
- **`--force`** or **force** (boolean kwarg) — re-explain claims that already
  have explanation files

Example prompt with kwargs:
```
/explain-claims --headless RHAISTRAT-1676

## Inputs
- verdict_filter: contradicted
- limit: 5
```

## Step 1: Index All Evidence Sources

Run the evidence-gathering script to discover all available data sources for the issue. This script does NOT read the evidence — it produces a JSON manifest of pointers (file paths, job names, trace IDs, API URLs).

Locate the script relative to this SKILL.md file:

```bash
SKILL_FILE=$(find . /app/.claude/skills/explain-claims \
  -path "*/explain-claims/SKILL.md" -type f 2>/dev/null | head -1)
SKILL_DIR=$(dirname "${SKILL_FILE:-.claude/skills/explain-claims/SKILL.md}")
python3 "$SKILL_DIR/scripts/gather-evidence.py" "$ISSUE_KEY" 2>/dev/null
```

Save the JSON output — it is your evidence index for all subsequent steps. The manifest contains:

- **`evidence_sources.k8s_jobs`** — matching jobs with `has_logs` boolean and `log_cmd` to fetch logs
- **`evidence_sources.mlflow_traces`** — traces with `trace_id`, token counts, duration, and `url`
- **`evidence_sources.strace`** — directories with `file_count` and `total_mb`
- **`evidence_sources.otel_logs`** — matching structured execution events
- **`evidence_sources.api_bodies`** — captured request/response body directories
- **`evidence_sources.artifacts`** — file paths grouped by type (`pipeline_output`, `claims_json`, `verification_log`, `existing_explanation`)
- **`evidence_sources.observatory`** — claims with `id`, `claim_text`, `verdict`, and per-claim `url`

**Before proceeding**, report the summary counts. If
`evidence_sources.observatory.overflow` is true, stop with an explicit error;
partial explanation selection would silently omit occurrences. If the script
is not found, fall back to manual discovery (see Appendix).

## Step 2: Select Claims to Explain

From the manifest's `evidence_sources.observatory.claims`, filter to claims needing explanation:

- If `claim_id` kwarg was provided, select only that claim
- Otherwise filter by `verdict_filter` (default: `contradicted,insufficient_evidence`; map legacy `refuted`, `insufficient`, and `inconclusive` when using fallback data)
- Apply `limit` (default: 20)
- Skip claims that already have files in `evidence_sources.artifacts` with `type: existing_explanation` unless `--force`

Report the number of claims selected and their verdict distribution.
Maintain an explicit list of the selected claim occurrence IDs and immutable
verification run IDs. That list defines this execution's output set; do not
later discover outputs by globbing the shared explanations directory.

## Step 3: Gather Forensic Evidence

For each selected claim, start with its source artifact and verification log,
then inspect the execution sources most likely to distinguish competing causes.
Do not read every trace or strace file merely because it exists. Record what was
checked, what was unavailable, and why each used source affected the conclusion.

### 3a. K8s Job Logs

For each job where `has_logs` is true, run the `log_cmd` from the manifest:

```bash
kubectl logs job/${job_name} -n ai-pipeline --tail=5000
```

In the logs, search for:
- The claim text or key phrases from it (grep for distinctive words)
- Tool calls that read files (`Read`, `Bash`)
- The agent's reasoning about the topic

Extract relevant excerpts. Focus on what information the agent had when it formulated the claim.

### 3b. MLflow Traces

For relevant traces, note the model, duration, spans, token usage, and tool
activity. These values describe execution behavior; token ratios and span counts
alone are not evidence of hallucination or failed retrieval.

### 3c. Strace Output

For each strace directory in the manifest, grep selectively — NEVER read full strace files:

```bash
# What files the agent opened
grep "openat.*artifacts\|openat.*context" ${directory}/*.* 2>/dev/null | head -20

# Claim-related keywords
grep -l "keyword_from_claim" ${directory}/*.* 2>/dev/null | head -5
```

### 3d. Source Artifacts

Read the files listed in `evidence_sources.artifacts`:
- **`pipeline_output`** — the original strategy/RFE document the claims were extracted from
- **`claims_json`** — the structured claims file
- **`verification_log`** — the verifier's evidence for why the claim was refuted (most valuable for root cause analysis)

## Step 4: Analyze Root Cause

For each claim, analyze the gathered evidence and assign a primary root cause category.

### Root Cause Categories

Choose the category that identifies the primary improvement target:

**`skill_instruction_gap`** — Relevant evidence was available, but the skill did
not require the necessary check, distinction, or output constraint.

**`context_gap`** — The authoritative component, version, or policy information
was missing, stale, or contradictory in the supplied context.

**`retrieval_failure`** — Relevant evidence existed and the skill called for it,
but the agent did not find, select, or read it.

**`source_misinterpretation`** — The agent read the relevant evidence but
distorted, overstated, or combined it incorrectly.

**`workflow_gap`** — Required context, sequencing, validation, or a quality gate
was absent from the orchestration around the skill.

**`tool_or_harness_gap`** — A missing, failed, or constrained tool or harness
prevented the required evidence gathering or validation.

**`model_reasoning_error`** — Instructions, tools, and authoritative evidence
were sufficient and used, but the model still reached an unsupported conclusion.

**`human_source_quality`** — The authoritative human-owned requirement or source
was ambiguous, stale, or internally inconsistent.

**`compound_error`** — The claim depends on another incorrect claim from the
same generated artifact.

**`unknown`** — Available forensic evidence cannot distinguish the cause.

### Analysis Guidelines

- First decide whether authoritative evidence existed at generation time.
- Then decide whether the skill required it, the agent retrieved it, and the
  agent interpreted it correctly—in that order.
- Do not infer what the agent read from token counts alone. Prefer tool calls,
  file opens, API bodies, or quoted log evidence.
- Distinguish unavailable evidence from evidence that was available but missed.
- Name one primary category, contributing factors, an improvement target, and a
  concrete regression test. Use `unknown` when evidence cannot support more.
- A verification log establishes the factual verdict, not the cause. It cannot
  be the only evidence for `retrieval_failure`, `source_misinterpretation`,
  `workflow_gap`, `tool_or_harness_gap`, `model_reasoning_error`, or
  `compound_error`.
- Assign `retrieval_failure` only when evidence shows all three facts: the
  relevant source was available at generation time, the generating skill
  required or reasonably implied its retrieval, and execution evidence shows
  the agent did not retrieve or select it. A context-setup write or clone does
  not prove the generating agent read the source. If execution evidence cannot
  distinguish a missed retrieval from unavailable context or
  misinterpretation, use `unknown` and require human review.
- Assign `source_misinterpretation` or `model_reasoning_error` only when a job
  log, tool event, trace, API body, or file-access record demonstrates that the
  generating agent actually consumed the relevant evidence.
- Assign `compound_error` only when the source artifacts establish the upstream
  and downstream claims and execution or workflow evidence establishes that the
  downstream phase consumed the upstream artifact. Similar wording alone does
  not prove propagation.

## Step 5: Write Explanation Reports

For each claim, write a markdown report to:

```
{artifacts_dir}/explanations/{claim_id}.md
```

Also write
`{artifacts_dir}/explanations/{verification_run_id}/{run_key}.explanation.json`
with the
verification run ID, explainer revision, primary category, improvement target,
contributing factors, evidence for and against attribution, alternatives,
remediation, and a replayable regression-test definition. Use `unknown` and
mark human review required when the evidence cannot support a causal route.
Every JSON file must be independently understandable. Do not write shorthand
such as `same as claim 11`, `same root cause`, or `same regression test`; repeat
the concrete evidence-backed explanation, remediation, and assertion in each
immutable run. Cross-claim links may be additional context, never the only
definition of a field.
The run key incorporates the explainer revision and evidence digest so replay
never overwrites an earlier explanation.
After successful v2 ingestion, atomically record `observatory_run_id` so a
later regression run can attach its result to this precise explanation.

Create parent directories with `mkdir -p`.

If working from disk fallback (no claim IDs), use a sanitized claim hash as the filename.

### Report Format

```markdown
# Claim {claim_id} — Root Cause Analysis

**Claim:** {claim_text}
**Verdict:** {verdict} (confidence: {confidence}%)
**Source file:** `{source_file}`
**Root Cause:** `{category}`
**Improvement Target:** `{skill|context|retrieval|workflow|tooling|model|human-source}`

## Evidence Gathered

### K8s Job Logs
{Relevant excerpts showing what the agent read and reasoned about, or "Job logs unavailable — job may have been garbage-collected after 24h TTL."}

### MLflow Traces
{Trace summary: experiment, duration, spans, token usage — or "No matching MLflow traces found."}

### Strace Analysis
{What files the agent opened, what API calls it made — or "Strace data unavailable."}

### Source Artifacts
{What the original pipeline output and verification log showed}

## Root Cause Analysis

### Primary: {category}

{Detailed evidence-backed explanation of why the agent made this claim and why
this category fits better than the alternatives. Do not speculate about hidden
model state or training data.}

### Contributing Factors
- {Factor 1 — e.g., "Architecture context docs for rhoai-3.5 were not available"}
- {Factor 2 — e.g., "Similar component names across versions may have caused confusion"}

### Remediation
{What could prevent this type of error — e.g., "Ensure architecture context includes the target version before running strat-create. Consider adding a verification step that checks claims against source files before finalizing the strategy document."}

### Regression Test
{A concrete replay or assertion that would demonstrate the remediation works}
```

## Step 6: POST Explanations to Observatory

After writing disk reports, POST each machine-readable explanation created for
the explicit selected-run list from Step 2 to the immutable v2 API so it appears
with the exact verification history. Never glob all `*.explanation.json` files
from the shared artifact directory: they include immutable outputs from earlier
runs, and reposting them creates duplicate or stale explanation history.

Build a JSON payload with all explanations from this run:

```bash
cat <<'PAYLOAD' | curl -s -X POST "${observatory_url}/api/v2/claims/explanation-runs" \
  -H "Content-Type: application/json" -d @-
{
  "verification_run_id": 789,
  "explainer_revision": "github.com/example/skills@abc123:explain-claims",
  "repository_revision": "resolved repository commit",
  "model": "resolved model identity",
  "harness": "dashboard-jobs-api",
  "configuration_digest": "sha256:...",
  "category": "retrieval_failure",
  "improvement_target": "architecture-context retrieval",
  "explanation": "Execution evidence shows no retrieval of the required versioned source.",
  "contributing_factors": ["the retriever searched only the default version"],
  "alternative_explanations": ["the source may have been unavailable at execution time"],
  "remediation": "Require the claim's product version in retrieval queries.",
  "regression_test": "Replay and assert that the versioned source is read.",
  "human_review_required": false,
  "evidence": [
    {"evidence_type": "job_log", "uri": "k8s://job/example", "relationship": "supports"},
    {"evidence_type": "repository_file", "uri": "repo://architecture/dashboard.md", "relationship": "supports"}
  ]
}
PAYLOAD
```

### Constructing the payload

For each analyzed claim:
- **`verification_run_id`** — the exact immutable v2 run being explained.
- **`model`, `harness`, and `configuration_digest`** — the resolved execution
  identity used for revision- and configuration-aware comparisons.
- **`category`** — the root cause category assigned in Step 4 (e.g., `retrieval_failure`, `source_misinterpretation`).
- **`explanation`** — the primary analysis, improvement target, and regression test from Step 5. Keep it under 2000 characters.
- **`evidence`** — structured evidence records for each source actually used:
  - `evidence_type: "job_log"` with a `k8s://` URI
  - `evidence_type: "mlflow_trace"` with experiment/run URI
  - `evidence_type: "strace"` with artifact URI
  - `evidence_type: "artifact"` with digest and source locator
  - `evidence_type: "verification_log"` bound to the verification run
  - use `relationship: "supports"` or `"against"` for causal attribution

Only include sources that were actually found and used (not unavailable ones).

### Response

The API returns `{"id": N}`. Atomically add that value to the JSON artifact as
`observatory_run_id`. If the endpoint returns `404`, a legacy projection may be
submitted to `/api/claims/explanations` but cannot satisfy the structured gate.
For other failures, preserve the disk report and log it for retry.

## Step 7: Report Results

After processing all claims, output a summary:

```
## Explanation Summary

- **Claims analyzed:** 12
- **Root cause distribution:**
  | Category | Count | % |
  |----------|-------|---|
  | retrieval_failure | 5 | 42% |
  | source_misinterpretation | 3 | 25% |
  | context_gap | 2 | 17% |
  | model_reasoning_error | 1 | 8% |
  | unknown | 1 | 8% |

- **Evidence availability:**
  - Job logs found: 8/12
  - MLflow traces found: 10/12
  - Strace data found: 3/12

### All Analyzed Claims

| ID | Claim (truncated) | Verdict | Root Cause | Evidence Sources |
|---|---|---|---|---|
| 456 | "Component X uses mTLS on port 8443" | refuted | retrieval_failure | logs, mlflow |
| 789 | "Dashboard requires FIPS-validated TLS" | insufficient | context_gap | mlflow only |

### Patterns Detected
- {e.g., "4 of 5 failures involve missing version-specific architecture lookups, suggesting the retrieval instructions need a version gate"}
- {e.g., "All 3 misinterpretation cases involve the same source file strat-pipeline/RHAISTRAT-1676.md — the document may be ambiguously worded"}
```

Always end with detected patterns, improvement targets, and proposed regression
tests. These are the feedback outputs that allow the platform to improve skills,
context, retrieval, workflows, tools, models, policies, and human-owned sources.

$ARGUMENTS
