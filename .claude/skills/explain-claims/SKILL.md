---
name: explain-claims
description: Investigate WHY an agent made a claim using pod logs, MLflow traces, strace output, and source artifacts
allowed-tools: Read, Write, Glob, Grep, Bash
user-invocable: true
---

# Explain Claims

Perform forensic analysis on verified claims to determine WHY an agent made each claim. Uses K8s job logs, MLflow traces, strace output, and source artifacts to identify root causes — training data hallucination, source misinterpretation, context confusion, or insufficient context.

## Inputs

This skill accepts inputs as positional arguments and/or kwargs in a `## Inputs` section appended to the prompt:

- **Issue key** (positional, e.g. `RHAISTRAT-1676`) — explain claims linked to this Jira key
- **claim_id** (kwarg, e.g. `123`) — explain a specific claim by ID
- **verdict_filter** (kwarg, e.g. `refuted,insufficient`) — only explain claims with these verdicts (default: `refuted,insufficient,inconclusive`)
- **limit** (kwarg, e.g. `10`) — max claims to process (default: 20)
- **`--force`** — re-explain claims that already have explanation files

Example prompt with kwargs:
```
/explain-claims --headless RHAISTRAT-1676

## Inputs
- verdict_filter: refuted
- limit: 5
```

## Step 1: Index All Evidence Sources

Run the evidence-gathering script to discover all available data sources for the issue. This script does NOT read the evidence — it produces a JSON manifest of pointers (file paths, job names, trace IDs, API URLs).

Locate the script relative to this SKILL.md file:

```bash
SKILL_DIR=$(dirname "$(find /app/.claude/skills/explain-claims -name SKILL.md -type f 2>/dev/null | head -1)" 2>/dev/null || echo ".claude/skills/explain-claims")
python3 "${SKILL_DIR}/scripts/gather-evidence.py" "${ISSUE_KEY}" 2>/dev/null
```

Save the JSON output — it is your evidence index for all subsequent steps. The manifest contains:

- **`evidence_sources.k8s_jobs`** — matching jobs with `has_logs` boolean and `log_cmd` to fetch logs
- **`evidence_sources.mlflow_traces`** — traces with `trace_id`, token counts, duration, and `url`
- **`evidence_sources.strace`** — directories with `file_count` and `total_mb`
- **`evidence_sources.artifacts`** — file paths grouped by type (`pipeline_output`, `claims_json`, `verification_log`, `existing_explanation`)
- **`evidence_sources.observatory`** — claims with `id`, `claim_text`, `verdict`, and per-claim `url`

**Before proceeding**, report the summary counts. If the script is not found, fall back to manual discovery (see Appendix).

## Step 2: Select Claims to Explain

From the manifest's `evidence_sources.observatory.claims`, filter to claims needing explanation:

- If `claim_id` kwarg was provided, select only that claim
- Otherwise filter by `verdict_filter` (default: refuted, insufficient, inconclusive)
- Apply `limit` (default: 20)
- Skip claims that already have files in `evidence_sources.artifacts` with `type: existing_explanation` unless `--force`

Report the number of claims selected and their verdict distribution.

## Step 3: Gather Forensic Evidence

For each selected claim, use the manifest to read evidence from every available source. **Use every source the manifest says is available — do not skip any.**

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

For each trace in the manifest, note the `input_tokens`, `output_tokens`, `num_spans`, `duration_ms`, and `model`. High output tokens with low input may indicate hallucination. Low `num_spans` may indicate the agent didn't search for evidence.

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

**`training_data_hallucination`** — The claim contains specific facts (version numbers, API details, component behaviors) that do not appear in ANY source the agent accessed. Job logs show no file reads or searches that could have produced this information. The agent appears to have generated plausible-sounding but fabricated details from its training data.

**`source_misinterpretation`** — The agent DID read a relevant source document, but the claim distorts, overstates, or misquotes what the source says. The verification log shows a specific contradiction between the claim and the source. Job logs confirm the agent read the relevant file.

**`context_confusion`** — The claim conflates information from two different components, versions, or documents. Job logs show the agent read multiple files and mixed their contents. Common when similar component names exist across RHOAI versions (e.g., mixing 3.4 and 3.5 details).

**`insufficient_context`** — The claim addresses a topic where no authoritative source was available to the agent. Architecture context docs don't cover this component or version. The agent made a reasonable inference from limited data but got it wrong. The claim is plausible but unverifiable.

**`compound_error`** — The claim is built on another claim that is also wrong, creating a chain of errors. Other refuted claims from the same source file are prerequisites for this claim's truth.

**`unknown`** — Insufficient forensic evidence to determine the cause. Job logs and strace are unavailable, and the claim text alone doesn't reveal the mechanism. Use this sparingly.

### Analysis Guidelines

- Check whether the claim's distinctive facts appear in any file the agent read (from job logs or strace). If not → likely `training_data_hallucination`.
- Compare the claim text against the verification log's `evidence_detail`. If the verifier found a source that contradicts the claim AND the agent read that source → `source_misinterpretation`.
- If the claim mentions component X but the evidence is about component Y → `context_confusion`.
- If no architecture context exists for the topic → `insufficient_context`.
- Always identify contributing factors beyond the primary category.

## Step 5: Write Explanation Reports

For each claim, write a markdown report to:

```
{artifacts_dir}/explanations/{claim_id}.md
```

Create parent directories with `mkdir -p`.

If working from disk fallback (no claim IDs), use a sanitized claim hash as the filename.

### Report Format

```markdown
# Claim {claim_id} — Root Cause Analysis

**Claim:** {claim_text}
**Verdict:** {verdict} (confidence: {confidence}%)
**Source file:** `{source_file}`
**Root Cause:** `{category}`

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

{Detailed explanation of WHY the agent made this claim. Be specific — cite evidence from the sections above. For example: "The agent read architecture/rhoai-3.4/dashboard.md which describes OAuth2 proxy integration. However, the claim states 'dashboard uses mTLS for all service communication' — a detail that appears nowhere in the source document. The agent appears to have generated this detail from training data about common Kubernetes security patterns."}

### Contributing Factors
- {Factor 1 — e.g., "Architecture context docs for rhoai-3.5 were not available"}
- {Factor 2 — e.g., "Similar component names across versions may have caused confusion"}

### Remediation
{What could prevent this type of error — e.g., "Ensure architecture context includes the target version before running strat-create. Consider adding a verification step that checks claims against source files before finalizing the strategy document."}
```

## Step 6: POST Explanations to Observatory

After writing disk reports, POST explanations to the Observatory API so they appear in the frontend.

Build a JSON payload with all explanations from this run:

```bash
cat <<'PAYLOAD' | curl -s -X POST "${observatory_url}/api/claims/explanations" \
  -H "Content-Type: application/json" -d @-
{
  "explanations": [
    {
      "claim_id": 456,
      "category": "training_data_hallucination",
      "explanation": "The agent read architecture/rhoai-3.4/dashboard.md but the claim states 'dashboard uses mTLS for all service communication' — a detail that appears nowhere in the source. Generated from training data.",
      "sources_used": [
        {"type": "job_log", "path": "strat-create-rhaistrat-1676-opus-0610-143022"},
        {"type": "artifact", "path": "strat-pipeline/RHAISTRAT-1676.md"},
        {"type": "verification_log", "path": "verification/456.md"}
      ]
    }
  ]
}
PAYLOAD
```

### Constructing the payload

For each analyzed claim:
- **`claim_id`** — the numeric ID from the Observatory (from Step 1 fetch). Skip claims from disk fallback that have no ID.
- **`category`** — the root cause category assigned in Step 4 (e.g., `training_data_hallucination`, `source_misinterpretation`).
- **`explanation`** — the "Root Cause Analysis > Primary" section text from the Step 5 report. Keep it under 2000 characters.
- **`sources_used`** — list of `{type, path}` objects for each evidence source actually used:
  - `type: "job_log"` — K8s job name
  - `type: "mlflow_trace"` — experiment/run path
  - `type: "strace"` — strace file path
  - `type: "artifact"` — source artifact file path
  - `type: "verification_log"` — verification log path

Only include sources that were actually found and used (not unavailable ones).

### Response

The API returns `{"stored": N, "skipped": M}`. Log the result. If the API is unreachable, log a warning and continue — the disk reports from Step 5 are the durable fallback.

## Step 7: Report Results

After processing all claims, output a summary:

```
## Explanation Summary

- **Claims analyzed:** 12
- **Root cause distribution:**
  | Category | Count | % |
  |----------|-------|---|
  | training_data_hallucination | 5 | 42% |
  | source_misinterpretation | 3 | 25% |
  | insufficient_context | 2 | 17% |
  | context_confusion | 1 | 8% |
  | unknown | 1 | 8% |

- **Evidence availability:**
  - Job logs found: 8/12
  - MLflow traces found: 10/12
  - Strace data found: 3/12

### All Analyzed Claims

| ID | Claim (truncated) | Verdict | Root Cause | Evidence Sources |
|---|---|---|---|---|
| 456 | "Component X uses mTLS on port 8443" | refuted | training_data_hallucination | logs, mlflow |
| 789 | "Dashboard requires FIPS-validated TLS" | insufficient | insufficient_context | mlflow only |

### Patterns Detected
- {e.g., "4 of 5 hallucinations involve security-specific claims about components in rhoai-3.5, suggesting the model's training data contains outdated security patterns for these components"}
- {e.g., "All 3 misinterpretation cases involve the same source file strat-pipeline/RHAISTRAT-1676.md — the document may be ambiguously worded"}
```

Always end with detected patterns — these are the most actionable output for improving the pipeline.
