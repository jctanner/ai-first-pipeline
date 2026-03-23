---
name: bug-fix-attempt
description: Attempt to produce a fix for a bug
allowed-tools: Read, Write, Glob, Grep
---

# Bug Fix Attempt

Attempt to produce a fix for a Jira bug by editing midstream (opendatahub-io) repository clones, producing both a machine-readable JSON result and a human-readable markdown summary.

## Instructions

### Workspace Overview

You are working in an **isolated workspace** under `fix-workspaces/{KEY}/` that contains shallow clones of the relevant **midstream** (opendatahub-io) repositories. These are the repos where RHOAI fixes are contributed.

- **Edit files directly** in the cloned repos within your current working directory.
- **Read architecture docs** from `architecture-context/` for understanding component design — but **never edit** files in `architecture-context/`.
- The cloned repos use the **downstream name** as the directory name (e.g., `data-science-pipelines/` is a clone of `opendatahub-io/ai-pipelines`).

Your prompt will include a **Workspace Info** section listing:
- Which repos are cloned and their midstream origins
- Any upstream repos that exist above the midstream fork

### JSON Schema

Your primary output is a JSON file conforming to this schema:

```json
{
  "issue_key": "RHOAIENG-XXXXX",
  "root_cause_hypothesis": "The controller does not handle nil ConfigMap data, causing a nil pointer dereference when ...",
  "affected_files": [
    {
      "path": "pkg/controller/reconciler.go",
      "repository": "opendatahub-io/odh-model-controller",
      "change_description": "Add nil check before accessing ConfigMap data map"
    }
  ],
  "fix_description": "Add a nil guard on the ConfigMap.Data field before iterating over entries.",
  "patch": "diff --git a/pkg/controller/reconciler.go ...",
  "confidence": "medium",
  "risks": [
    "The nil ConfigMap case may be intentional in some deployment scenarios"
  ],
  "blockers": [
    "Could not verify against a live cluster"
  ],
  "recommendation": "ai-fixable",
  "target_repo": "opendatahub-io/odh-model-controller",
  "upstream_consideration": null,
  "self_corrections": [
    {
      "after_iteration": 2,
      "failure_trigger": "lint-error",
      "mistake_category": "unused-import",
      "what_went_wrong": "Added an import for 'fmt' that was not used in the final code",
      "what_was_changed": "Removed the unused fmt import",
      "files_modified": ["pkg/controller/reconciler.go"],
      "was_original_approach_wrong": false
    }
  ]
}
```

- `root_cause_hypothesis`: string explaining what's wrong and why
- `affected_files`: array of objects with `path`, `repository`, and `change_description`
- `fix_description`: string summarizing what the fix does
- `patch`: string containing the diff/patch in unified diff format (the phase runner will replace this with the real `git diff` from your edits)
- `confidence`: one of `"low"`, `"medium"`, `"high"`
- `risks`: array of strings describing what could go wrong
- `blockers`: array of strings describing reasons the fix might not work
- `recommendation`: one of:
  - `"ai-fixable"` — the AI produced a code fix
  - `"already-fixed"` — the bug is already fixed in the current codebase
  - `"not-a-bug"` — this is a feature request, enhancement, RFE, or by-design behavior
  - `"docs-only"` — the fix is a documentation change, not a code change
  - `"upstream-required"` — the fix must happen in an upstream repo outside the RHOAI midstream
  - `"insufficient-info"` — not enough information in the bug report to attempt a fix
  - `"ai-could-not-fix"` — the AI tried but could not produce a working fix
- `target_repo`: string — the midstream `org/repo` this patch targets (e.g., `"opendatahub-io/odh-dashboard"`)
- `upstream_consideration`: string or null — if the fix should be proposed upstream first, explain where and why (e.g., `"Fix should be proposed at kserve/kserve first as this is upstream of opendatahub-io/kserve"`). Set to `null` if not applicable.
- `self_corrections`: array (optional, retry only) — when retrying after validation failure, record what you got wrong. Each entry has:
  - `after_iteration`: integer — which iteration this correction follows (e.g., 2 means "corrected after iteration 1 failed")
  - `failure_trigger`: one of `"lint-error"`, `"build-error"`, `"test-failure"`, `"setup-failure"`
  - `mistake_category`: one of `"unused-import"`, `"missing-import"`, `"syntax-error"`, `"type-error"`, `"nil-handling"`, `"api-misuse"`, `"incomplete-change"`, `"wrong-file"`, `"test-expectation"`, `"formatting"`, `"logic-error"`, `"dependency-issue"`, `"other"`
  - `what_went_wrong`: string — free-text explanation of the mistake
  - `what_was_changed`: string — free-text description of the correction
  - `files_modified`: array of file paths changed in the correction
  - `was_original_approach_wrong`: boolean — `true` if the fundamental approach changed, `false` if it was a minor fix

### Steps

1. **Understand the bug:**
   - Read the component architecture doc(s) from `architecture-context/` (referenced in the context map)
   - Read the relevant source code in the **cloned midstream repos** in your current working directory
   - Identify the specific file(s) and function(s) likely involved

2. **Root cause analysis:**
   - Based on error output, logs, and code, hypothesize the root cause
   - Document the hypothesis in a structured format

3. **Implement the fix:**
   - **Edit files directly** in the cloned midstream repos in your working directory
   - If the fix requires changes across multiple files or repos, edit each file
   - If the component has a known upstream (provided in your prompt), note in `upstream_consideration` whether the fix should go upstream first and why
   - Set `target_repo` to the midstream `org/repo` (e.g., `opendatahub-io/odh-dashboard`)

4. **Self-review:**
   - Check for common pitfalls: nil pointer dereferences, missing error handling, race conditions, breaking API changes
   - Verify the fix doesn't introduce security vulnerabilities
   - Check if the fix respects the component's existing patterns and conventions

5. **Anticipate validation:**
   - If a Test Context section is provided in your prompt, review the lint and test commands that will be run after your fix
   - Ensure your changes pass the linting rules described (e.g., no unused imports, correct formatting, type annotations)
   - If validation feedback is provided (this is a retry after a failed validation), fix the specific errors reported in the feedback section
   - Pay attention to which commands are marked as `validated: true` — those are the ones that will actually run

5b. **Report self-corrections (retry only):**
   - If your prompt contains a `## Validation Feedback` section, this is a retry after a failed validation
   - Include a `self_corrections` array in your JSON output with one entry describing what you corrected
   - Set `after_iteration` to the iteration number shown in the feedback header (e.g., if the header says "Iteration 2", set `after_iteration` to 2)
   - Set `failure_trigger` based on what type of validation failed: `"lint-error"` for lint/formatting failures, `"build-error"` for compilation failures, `"test-failure"` for test assertion failures, `"setup-failure"` for environment setup failures
   - Set `mistake_category` to the best match from the enum (e.g., `"unused-import"` if you left an unused import, `"type-error"` for type mismatches, `"incomplete-change"` if you missed updating another call site)
   - Write clear `what_went_wrong` and `what_was_changed` descriptions
   - List the `files_modified` in this correction
   - Set `was_original_approach_wrong` to `true` only if you fundamentally changed your approach, `false` for minor fixes
   - If this is NOT a retry (no Validation Feedback section), do NOT include `self_corrections` in the JSON

6. **Choose the right recommendation:**
   - `"ai-fixable"` — you produced a working code fix. Use this when you edited files and believe the patch addresses the root cause.
   - `"already-fixed"` — after reading the current codebase, the bug appears to already be fixed in the midstream code. Explain in `fix_description` what code already handles the reported issue.
   - `"not-a-bug"` — the reported behavior is by design, a feature request, enhancement, or RFE. Explain in `fix_description` why this isn't a defect.
   - `"docs-only"` — the issue is a documentation gap, not a code defect. No code change is needed; describe the doc change in `fix_description`.
   - `"upstream-required"` — the fix must happen in an upstream repo (e.g., `kserve/kserve`, `kubeflow/training-operator`) that is above the RHOAI midstream. Set `upstream_consideration` to explain where and why.
   - `"insufficient-info"` — the bug report lacks enough detail (steps to reproduce, error messages, environment info) to identify the root cause. List what's missing in `blockers`.
   - `"ai-could-not-fix"` — you attempted a fix but could not produce a working solution. Explain what you tried and what blocked you in `blockers`.
   - In all cases, still provide a `root_cause_hypothesis` and `fix_description` with your best analysis.

### Output Format

Write **two files**:

1. **`issues/{KEY}.fix-attempt.json`** — the JSON object described above
2. **`issues/{KEY}.fix-attempt.md`** — a human-readable rendering:

```markdown
# Fix Attempt: {KEY}

## Target Repository

[midstream org/repo]

## Root Cause Hypothesis

[Explanation of what's wrong and why]

## Affected Files

| File | Repository | Change Description |
|------|-----------|-------------------|
| [path] | [repo] | [what changes] |

## Fix Description

[What the fix does and why it addresses the root cause]

## Patch

```diff
[The actual diff/patch]
```

## Confidence: [low / medium / high]

## Risks

- [What could go wrong with this fix]

## Blockers

- [Reasons the fix might not work: missing info, needs cluster testing, etc.]

## Upstream Consideration

[If applicable: where the fix should go upstream first and why. Otherwise: "N/A"]

## Recommendation: [ai-fixable / already-fixed / not-a-bug / docs-only / upstream-required / insufficient-info / ai-could-not-fix]

[Brief explanation of the recommendation]
```

### Important Rules

- **DO NOT edit** anything under `architecture-context/` — it is read-only reference material.
- **DO edit** files in the cloned midstream repos in your working directory.
- Read the actual source code before proposing changes. Do not guess at file contents.
- If you cannot find the relevant source code, document what you looked for and recommend `ai-could-not-fix`.
- The `issues/` directory path for output files is relative to the project base directory (provided in the Working Directory section), **not** your current working directory.
