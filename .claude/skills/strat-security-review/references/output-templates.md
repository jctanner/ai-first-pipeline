# Output Templates

## Table of Contents

- [File A: Full Review](#file-a-full-review)
  - [Compact Format (Light tier)](#compact-format-light-tier-short-circuit-pass)
  - [Full Format (multi-reviewer)](#full-format-multi-reviewer-consensus)
- [File B: Requirements File](#file-b-requirements-file)
  - [Compact Format (PASS)](#compact-format-pass-with-no-amendments)
  - [Full Format (risks/amendments)](#full-format-any-verdict-with-risks-or-amendments)

---

## File A: Full Review

Output path: `artifacts/security-reviews/<STRAT-KEY>-security-review.md`

### Compact Format (Light tier short-circuit PASS)

```markdown
---
strat_key: RHAISTRAT-NNN
review_date: "YYYY-MM-DD"
review_tier: "light"
review_method: "short-circuit"
verdict: "PASS"
risk_count:
  critical: 0
  high: 0
  medium: 0
  low: 0
requirements_file: "artifacts/security-requirements/RHAISTRAT-NNN-security-requirements.md"
---

# Security Review: [STRAT Title]

## Security Verdict: PASS

**Summary:** <1-2 sentences explaining why this change has minimal security surface and no risks identified.>
```

### Full Format (multi-reviewer consensus)

```markdown
---
strat_key: RHAISTRAT-NNN
review_date: "YYYY-MM-DD"
review_tier: "standard|deep"
review_method: "multi-reviewer-consensus"
reviewer_count: 3
verdict: "PASS|CONCERNS|FAIL"
risk_count:
  critical: N
  high: N
  medium: N
  low: 0
confidence_distribution:
  high_confidence: N
  medium_confidence: N
  low_confidence: N
architecture_context_consulted:
  - "rhods-operator.md"
  - "notebooks.md"
intermediate_files:
  threat_surface: "artifacts/security-reviews/RHAISTRAT-NNN-threat-surface.md"
  reviewer_1: "artifacts/security-reviews/RHAISTRAT-NNN-reviewer-1.md"
  reviewer_2: "artifacts/security-reviews/RHAISTRAT-NNN-reviewer-2.md"
  reviewer_3: "artifacts/security-reviews/RHAISTRAT-NNN-reviewer-3.md"
requirements_file: "artifacts/security-requirements/RHAISTRAT-NNN-security-requirements.md"
---

# Security Review: [STRAT Title]

## Security Verdict: [PASS | CONCERNS | FAIL]

**Summary:** <1-2 sentence summary of the overall security posture>

**Review method:** Multi-reviewer consensus (3 independent reviewers). Findings tagged with confidence level based on cross-reviewer agreement.

## Threat Surface Analysis

Summarize the threat surface inventory (from Phase 1). This section is deterministic — it is extracted from the STRAT, not analyzed.

- **Attack surfaces introduced/expanded:** <list from threat surface inventory>
- **Trust boundaries crossed:** <list from threat surface inventory>
- **Data flows created/modified:** <list from threat surface inventory>

## Existing Security Controls (Standard/Deep tier)

<Summarize what the architecture context says about the affected components' existing security posture. This establishes the baseline.>

## Security Risks

### RISK-001: [Risk Title]
- **Severity:** High (2/3 High, 1/3 Medium)
- **Confidence:** MEDIUM (2/3 reviewers)
- **Catalog Pattern:** AUTH-03
- **Category:** auth
- **Threat Surface Item:** "New RBAC / ServiceAccounts: ..."
- **STRAT Reference:** <union of all references from matched reviewers>
- **Relevance:** <merged explanation>
- **Impact:** <merged impact>
- **Recommended Mitigation:** <union of all mitigations>
- **Reviewer Agreement:** R1: High, R2: High, R3: not identified

### RISK-002: [Risk Title]
- **Severity:** Medium
- **Confidence:** LOW (1/3 reviewers) — human review recommended
- **Catalog Pattern:** CREATIVE-02
- **Category:** ml-ai
- **Threat Surface Item:** "..."
- **STRAT Reference:** ...
- **Relevance:** ...
- **Impact:** ...
- **Recommended Mitigation:** ...
- **Reviewer Agreement:** R1: not identified, R2: not identified, R3: Medium
- **Note:** Single-reviewer finding from creative exploration. May be a genuine concern or a false positive.

(If no Security Risks: "No security risks identified across all three reviewers.")

## NFR Gaps

- <gap description> (confidence: HIGH/MEDIUM/LOW)
- ...

(If none: omit this section.)

## Organizational Constraint Violations

<List violations with confidence tags>

(If none: "No organizational constraint violations detected.")

## Missing Context

<Union of missing context noted by any reviewer>

(If all reviewers had everything needed: "No missing context — review confidence is high.")

## Recommendation

- **PASS**: No Security Risks identified across all three reviewers
- **CONCERNS**: Security Risks identified with mitigations — confidence levels indicate reviewer agreement
- **FAIL**: Critical security issues with high reviewer consensus
```

---

## File B: Requirements File

Output path: `artifacts/security-requirements/<STRAT-KEY>-security-requirements.md`

### Compact Format (PASS with no amendments)

```markdown
---
strat_key: RHAISTRAT-NNN
review_date: "YYYY-MM-DD"
review_tier: "light|standard|deep"
review_method: "short-circuit|multi-reviewer-consensus"
verdict: "PASS"
risk_count:
  critical: 0
  high: 0
  medium: 0
  low: 0
full_review: "artifacts/security-reviews/RHAISTRAT-NNN-security-review.md"
---

# Security Requirements: [STRAT Title]

## Verdict: PASS

**Summary:** <1-2 sentences>

No security requirements to add.
```

### Full Format (any verdict with risks or amendments)

```markdown
---
strat_key: RHAISTRAT-NNN
review_date: "YYYY-MM-DD"
review_tier: "standard|deep"
review_method: "multi-reviewer-consensus"
verdict: "PASS|CONCERNS|FAIL"
risk_count:
  critical: N
  high: N
  medium: N
  low: 0
full_review: "artifacts/security-reviews/RHAISTRAT-NNN-security-review.md"
---

# Security Requirements: [STRAT Title]

## Verdict: [PASS | CONCERNS | FAIL]

**Summary:** <1-2 sentence summary>

## Required Amendments (Security Risk Mitigations)

These must be addressed before implementation. Only includes findings with MEDIUM or HIGH reviewer consensus.

1. **[Amendment title]** (RISK-001, HIGH confidence): <specific text addition/modification the STRAT needs>
2. **[Amendment title]** (RISK-002, MEDIUM confidence): <specific amendment>

If none: omit this section.

## Findings Requiring Human Review

These findings were identified by a single reviewer (LOW confidence). They may be genuine concerns or false positives. A human security architect should evaluate them.

1. **[Finding title]** (RISK-003, LOW confidence): <description, rationale, and recommended mitigation>

If none: omit this section.

## Recommended Amendments (NFR Additions)

Recommended for completeness but not blocking.

1. <amendment> (confidence: HIGH/MEDIUM/LOW)
2. ...

If none: omit this section.

## Organizational Constraint Violations

<List any violations with confidence tags>

If none: "No organizational constraint violations detected."
```
