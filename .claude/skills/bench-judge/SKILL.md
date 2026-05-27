---
name: bench-judge
description: Score a benchmark agent's answer against ground truth using a 4-dimension rubric
allowed-tools: Read, Write
---

# Benchmark Answer Judge

Score the quality of an agent's answer to an architecture-context question by comparing it against the provided ground truth. Produce a machine-readable JSON judgment and a human-readable markdown summary.

You are a judge, not an answerer. Do NOT attempt to answer the question yourself or consult any architecture files. Evaluate ONLY whether the agent's answer matches the ground truth provided to you.

## Instructions

### Inputs

You will receive the following in the prompt:

- `QUESTION` — the architecture question that was asked
- `AGENT_ANSWER_PATH` — path to the agent's answer JSON file (read it)
- `EXPECTED_ANSWER` — the ground truth answer
- `EXPECTED_ANSWERABLE` — whether the question is answerable from the docs (`true` or `false`)
- `SOURCE_EXCERPT` — the relevant text from the architecture-context source files
- `OUTPUT_DIR` — directory to write your output files

### Steps

1. Read the agent's answer JSON from `AGENT_ANSWER_PATH`.
2. Compare the agent's answer against `EXPECTED_ANSWER` and `SOURCE_EXCERPT`.
3. Score each rubric dimension (see below).
4. Count `false_claims` and `missed_gaps` (see below).
5. Compute the composite score.
6. Write both output files to `OUTPUT_DIR`.

### JSON Schema

Your primary output is a JSON file conforming to this schema.

**STRICT SCHEMA RULE:** The JSON must contain ONLY the exact keys shown below — no extra fields at any level. The schema uses `additionalProperties: false` and any extra key will cause validation failure.

```json
{
  "question_id": "t1-001",
  "scores": {
    "accuracy": 5,
    "grounding": 4,
    "scope_awareness": 5,
    "gap_acknowledgment": 4
  },
  "composite_score": 4.6,
  "pass": true,
  "false_claims": 0,
  "missed_gaps": 0,
  "justifications": {
    "accuracy": "Answer correctly states InstructLab is not an RHOAI component, matching ground truth.",
    "grounding": "Cites PLATFORM.md but does not reference a specific section or line.",
    "scope_awareness": "Correctly distinguishes RHOAI from RHEL AI and notes InstructLab belongs to RHEL AI.",
    "gap_acknowledgment": "Not applicable — question was answerable from the docs."
  }
}
```

Field definitions:

- `question_id`: string — the corpus question ID (from the agent's answer JSON)
- `scores`: object with exactly 4 integer fields (1-5 each):
  - `accuracy` — factual correctness against ground truth
  - `grounding` — citation quality
  - `scope_awareness` — product boundary awareness
  - `gap_acknowledgment` — honesty about missing information
- `composite_score`: number (1.0-5.0) — weighted composite (see formula below)
- `pass`: boolean — `true` if `composite_score >= 3.0`
- `false_claims`: integer — count of architecture assertions NOT supported by ground truth or source excerpt
- `missed_gaps`: integer — count of known gaps the agent should have flagged but did not (only applicable when `EXPECTED_ANSWERABLE` is `false`)
- `justifications`: object with exactly 4 string fields — one sentence explaining each score

### Scoring Rubric

Score each dimension on a 1-5 integer scale. Compare the agent's answer against the provided ground truth, NOT against your own knowledge.

#### 1. Accuracy (weight: 0.4)

Does the agent's answer match the ground truth?

| Score | Criteria |
|-------|----------|
| **5** | All facts correct, matches ground truth exactly |
| **4** | Minor imprecision (e.g., slightly different wording) but no wrong facts |
| **3** | Mostly correct with one factual error |
| **2** | Multiple factual errors |
| **1** | Answer is substantially wrong or contradicts the ground truth |

#### 2. Grounding (weight: 0.2)

Does the agent cite specific sources?

| Score | Criteria |
|-------|----------|
| **5** | Cites specific file path AND relevant section or content |
| **4** | Cites file path but not specific section |
| **3** | References "the architecture docs" or "arch-query" generically |
| **2** | No citation, but answer is consistent with the docs |
| **1** | Makes claims with no basis in available docs |

#### 3. Scope Awareness (weight: 0.2)

Does the agent distinguish product boundaries?

| Score | Criteria |
|-------|----------|
| **5** | Identifies which product/project a component belongs to (RHOAI vs RHEL AI vs upstream-only) |
| **4** | Correct scope but does not explicitly state it |
| **3** | Ambiguous on scope |
| **2** | Conflates RHOAI with adjacent products |
| **1** | Attributes non-RHOAI components to RHOAI or vice versa |

When the question does not involve product scope distinctions, default to 4 ("correct scope, not explicitly stated") unless the agent introduces a scope error.

#### 4. Gap Acknowledgment (weight: 0.2)

Does the agent handle missing information honestly?

| Score | Criteria |
|-------|----------|
| **5** | Explicitly states "not documented" when the answer is not in the docs |
| **4** | Hedges but clearly communicates uncertainty ("may not be documented", "I could not find") |
| **3** | Silently skips the gap without addressing it |
| **2** | Fabricates a partial answer for undocumented content |
| **1** | Fabricates a confident answer for undocumented content |

When `EXPECTED_ANSWERABLE` is `true` and the agent answers the question accurately, score this dimension based on how the agent handles any subsidiary gaps or limitations (default to 4 if not applicable).

### Composite Score

```
composite = (accuracy * 0.4) + (grounding * 0.2) + (scope_awareness * 0.2) + (gap_acknowledgment * 0.2)
```

Round to one decimal place. The `pass` field is `true` when `composite_score >= 3.0`.

### False Claims Count

Count the number of distinct architecture assertions in the agent's answer that are NOT supported by the ground truth (`EXPECTED_ANSWER`) or the source excerpt (`SOURCE_EXCERPT`).

An "architecture assertion" is a specific claim about a component's behavior, API, port, CRD, dependency, or capability. General hedging ("this may be the case") does not count as an assertion.

Examples:
- Agent says "vLLM exposes metrics on port 9090" but ground truth says port 8000 → 1 false claim
- Agent says port 8000 (accurate) but also claims "metrics include GPU utilization counters" with no basis in the source → 1 false claim
- Agent says "not documented" for something that is actually documented → 0 false claims (this is an accuracy error, not a false claim)

### Missed Gaps Count

Only applicable when `EXPECTED_ANSWERABLE` is `false`. Count the number of known gaps (documented in the ground truth as not present in architecture-context) that the agent failed to surface.

When `EXPECTED_ANSWERABLE` is `true`, set `missed_gaps` to 0.

Examples:
- Ground truth says "trustyai_eval metrics are not documented" and the agent says "TrustyAI has comprehensive metrics" without noting the gap → 1 missed gap
- Ground truth says component is not in RHOAI inventory and agent says "not found" → 0 missed gaps

### Output Format

Write **two files** in `OUTPUT_DIR`:

1. **`{question_id}.json`** — the JSON object described above
2. **`{question_id}.md`** — a human-readable rendering:

```markdown
# Judgment: {question_id}

## Question
{the question text}

## Agent Answer
{the agent's answer text}

## Ground Truth
{the expected answer}

## Scores

| Dimension | Score | Weight | Weighted | Justification |
|-----------|-------|--------|----------|---------------|
| Accuracy | {1-5} | 0.4 | {weighted} | {justification} |
| Grounding | {1-5} | 0.2 | {weighted} | {justification} |
| Scope Awareness | {1-5} | 0.2 | {weighted} | {justification} |
| Gap Acknowledgment | {1-5} | 0.2 | {weighted} | {justification} |

**Composite Score: {composite}/5.0 — {PASS/FAIL}**

## Claim Analysis

- False claims: {count}
- Missed gaps: {count}
```
