---
name: bug-completeness
description: Score bug report completeness (0-100)
allowed-tools: Read, Write, Glob, Grep
---

# Bug Completeness Scoring

Evaluate the completeness of a Jira bug report by scoring it against a weighted rubric, producing both a machine-readable JSON result and a human-readable markdown summary.

## Instructions

### JSON Schema

Your primary output is a JSON file conforming to this schema:

```json
{
  "issue_key": "RHOAIENG-XXXXX",
  "overall_score": 75,
  "dimensions": [
    {
      "name": "Summary clarity",
      "weight": 10,
      "score": 100,
      "weighted_score": 10.0,
      "justification": "Specific: component + symptom + trigger"
    }
  ],
  "missing_information": [
    "No reproduction steps provided",
    "OCP version not specified"
  ],
  "triage_recommendation": "ai-fixable",
  "issue_type_assessment": {
    "classified_type": "bug",
    "confidence": "high",
    "justification": "Describes a regression in existing functionality with clear error output"
  }
}
```

- `overall_score`: integer 0-100, the sum of all `weighted_score` values
- `dimensions`: array of exactly 9 objects (one per rubric row)
  - `name`: dimension name exactly as listed in the rubric
  - `weight`: integer percentage (10, 15, 20, etc.)
  - `score`: one of 0, 50, or 100
  - `weighted_score`: `weight * score / 100` (a float)
  - `justification`: brief reason for the score
- `missing_information`: array of strings listing specific items the reporter should add
- `triage_recommendation`: one of `"ai-fixable"`, `"needs-enrichment"`, or `"needs-info"`
  - `ai-fixable`: overall_score >= 80
  - `needs-enrichment`: overall_score 40-79
  - `needs-info`: overall_score < 40
- `issue_type_assessment`: object evaluating what the issue actually is (independent of how it was filed)
  - `classified_type`: one of `"bug"`, `"feature-request"`, `"enhancement"`, `"task"`, `"epic"`, `"docs-update"`, `"support-request"`, `"configuration"`, `"test-gap"`
  - `confidence`: one of `"low"`, `"medium"`, `"high"`
  - `justification`: brief explanation of why this classification was chosen

### Issue Type Classification Guide

Many issues filed as bugs are actually something else. Evaluate the issue content (not the Jira issue type) and classify it:

| Type | Description | Signals |
|------|-------------|---------|
| `bug` | Defect or regression in existing functionality | "used to work", error output, crash, incorrect behavior vs documented behavior |
| `feature-request` | Request for new functionality that never existed | "it would be nice", "we need support for", no prior working state described |
| `enhancement` | Improvement to existing functionality | "should also", "better UX", "extend to support", existing feature works but could be better |
| `task` | Operational or maintenance work | Dependency update, CI/CD change, cleanup, refactoring |
| `epic` | Large effort that should be broken into sub-tasks | Multiple distinct deliverables described, spans components or releases |
| `docs-update` | Documentation is missing, wrong, or outdated | "docs say X but Y", "no documentation for", "README is outdated" |
| `support-request` | User needs help, not a code change | "how do I", misconfiguration by user, misunderstanding of expected behavior |
| `configuration` | Misconfiguration or missing config, not a code defect | Wrong environment variable, missing RBAC, incorrect CR spec |
| `test-gap` | Missing test coverage, not a product defect | "no tests for", flaky test, test infrastructure issue |

### Scoring Rubric

| Dimension | Weight | 0 (Missing) | 50 (Partial) | 100 (Complete) |
|-----------|--------|-------------|---------------|----------------|
| Summary clarity | 10% | Vague or generic title | Has component name but unclear symptom | Specific: component + symptom + trigger |
| Description quality | 15% | Empty or single sentence | Some context but missing key details | Full narrative: what, where, when, impact |
| Reproduction steps | 20% | None provided | Vague steps ("deploy and check") | Numbered steps with specific commands/configs |
| Environment info | 10% | No version/platform info | Partial (e.g., "RHOAI 3.4" but no OCP version) | Full: RHOAI version, OCP version, platform (AWS/GCP/bare metal), architecture |
| Expected vs actual | 10% | Not stated | One of the two is stated | Both clearly described |
| Error output / logs | 15% | None | Partial stack trace or screenshot | Full error output, relevant log snippets, pod/container identified |
| Component identification | 10% | No component/label | Has Jira component but not specific enough | Specific repo, operator, controller, or service identified |
| Severity justification | 5% | Priority set with no rationale | Priority set, impact implied | Explicit impact statement (user-facing, data loss, security, etc.) |
| Attachments / evidence | 5% | None | Screenshot only | Logs, screenshots, yamls, or reproduction scripts |

### Steps

1. Read the issue data provided in the prompt header.
2. For each of the 9 dimensions, assign a score of 0, 50, or 100 based on the rubric.
3. Compute the weighted score for each dimension: `weight * score / 100`.
4. Sum all weighted scores to get the overall score.
5. **Classify the actual issue type** — read the issue content carefully and determine what type of work this really represents, regardless of how it was filed in Jira. Many "bugs" are actually feature requests, enhancements, or configuration issues.
6. List any missing information that would improve the report.
7. Determine the triage recommendation based on the overall score.

### Output Format

Write **two files** in the `issues/` directory:

1. **`issues/{KEY}.completeness.json`** — the JSON object described above
2. **`issues/{KEY}.completeness.md`** — a human-readable rendering:

```markdown
# Completeness Analysis: {KEY}

## Overall Score: {overall_score}/100

## Per-Dimension Scores

| Dimension | Weight | Score | Weighted | Justification |
|-----------|--------|-------|----------|---------------|
| Summary clarity | 10% | [0/50/100] | [weighted] | [brief reason] |
| ... | ... | ... | ... | ... |

## Missing Information

- [item 1]
- [item 2]

## Issue Type Assessment

**Classified type:** [bug / feature-request / enhancement / task / epic / docs-update / support-request / configuration / test-gap]
**Confidence:** [low / medium / high]
**Justification:** [why this classification was chosen]

## Triage Recommendation

[ai-fixable / needs-enrichment / needs-info]: [brief explanation]
```

Be rigorous and consistent. Read the issue data carefully before scoring.
