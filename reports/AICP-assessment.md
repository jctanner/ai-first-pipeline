# AI Core Platform — Pipeline Assessment

- **Date:** 2026-03-25
- **Scope:** 40 Jira issues tagged "AI Core Platform" component
- **Models:** claude-opus-4-6, claude-sonnet-4-5
- **Phases:** completeness, context-map, fix-attempt, test-plan, write-test

---

## Pipeline Phases

Each issue is processed through five sequential phases. All phases run independently on both `claude-opus-4-6` and `claude-sonnet-4-5`, producing separate results per model for comparison (see [Appendix: Opus vs Sonnet Model Comparison](#appendix-opus-vs-sonnet-model-comparison)).

1. **Completeness** — Scores the bug report's quality (0-100) across nine dimensions (summary clarity, reproduction steps, environment info, etc.). Triages the issue as `ai-fixable`, `needs-enrichment`, or other categories. Also reclassifies the issue type (bug, enhancement, configuration, etc.).
2. **Context-map** — Maps the bug to available architecture documentation and source code checkouts. For each component mentioned in the issue, the agent searches the `architecture-context/` directory for matching docs and source trees, then rates context availability as `full-context`, `partial-context`, `cross-component`, or `no-context`. Also scores context helpfulness on three dimensions: coverage (does the context cover the bug's area?), depth (is it detailed enough?), and freshness (does it match the affected version?). Identifies repos and files that are available vs. missing.
3. **Fix-attempt** — Using the completeness analysis and context-map as inputs, the agent clones the target repository, diagnoses the root cause, and generates a patch. The patch is validated (lint, build, tests) with up to two self-correction iterations if validation fails. Outputs a confidence rating and recommendation (`ai-fixable`, `already-fixed`, `upstream-required`, `insufficient-info`).
4. **Test-plan** — Generates a structured test plan covering the bug's scenario: positive and negative cases, edge cases, and regression checks.
5. **Write-test** — Produces executable QE test code (Go/Python depending on the target repo's test framework) based on the test plan.

---

## Bug Report Quality (Opus)

> Sections below show `claude-opus-4-6` results. See [Appendix](#appendix-opus-vs-sonnet-model-comparison) for side-by-side Sonnet comparison.

- **Mean completeness score:** 64.5/100 (median 63.5)
- **60% triaged as "needs-enrichment"** before effective action can be taken
- **30% triaged as "ai-fixable"** as-is
- ~25% of issues filed as "bugs" were reclassified as enhancements, tasks, or configuration issues

### Score Distribution

| Score Range | Count | Percentage | Interpretation |
|-------------|-------|------------|----------------|
| 85-100      | 7     | 17.5%      | Excellent — well-written, actionable |
| 65-84       | 13    | 32.5%      | Good — most information present, minor gaps |
| 50-64       | 12    | 30.0%      | Fair — usable but missing important details |
| Below 50    | 8     | 20.0%      | Poor — significant information gaps |

### Systemic Weaknesses in Bug Reports

- **Environment info** is the weakest dimension: 62.5% scored 50 or below. OCP version, platform (AWS/GCP/bare metal), and architecture are routinely omitted.
- **Attachments/evidence** missing in 70% of issues. Most bugs lack inline logs, screenshots, or YAML artifacts.
- **Reproduction steps** vary wildly: 8 scored 100 but 5 scored 0.
- **Severity justification** weak: only 6 of 40 scored 100; 10 scored 0.

### Strengths

- Summary clarity generally good (32 of 40 scored 100)
- Component identification strong (25 of 40 scored 100)
- Expected-vs-actual well documented when present (24 of 40 scored 100)

---

## Issue Type Classification (Opus)

| Classified Type     | Count | Percentage |
|---------------------|-------|------------|
| bug                 | 27    | 67.5%      |
| enhancement         | 4     | 10.0%      |
| task                | 3     | 7.5%       |
| feature-request     | 2     | 5.0%       |
| test-gap            | 2     | 5.0%       |
| configuration       | 2     | 5.0%       |
| docs-update         | 1     | 2.5%       |

---

## Fix Attempt Results (Opus)

26 of 40 issues received fix-attempts. 14 were skipped (active work status, insufficient info, or non-bug classification).

### Fix Recommendations

| Recommendation     | Count | Percentage |
|--------------------|-------|------------|
| ai-fixable         | 22    | 84.6%      |
| already-fixed      | 2     | 7.7%       |
| upstream-required  | 1     | 3.8%       |
| docs-only          | 1     | 3.8%       |
| insufficient-info  | 1     | 3.8%       |

### Confidence Levels

| Confidence | Count | Percentage |
|------------|-------|------------|
| high       | 18    | 69.2%      |
| medium     | 7     | 26.9%      |
| low        | 1     | 3.8%       |

### Validation

- 19 of 22 ai-fixable patches passed validation on final iteration
- 5 required automatic self-correction (lint, dependency, or test failures caught and fixed)
- 3 had no validation run

### Target Repositories

| Repository | Fix Count |
|------------|-----------|
| opendatahub-io/opendatahub-operator (rhods-operator) | 16 (61.5%) |
| opendatahub-io/kube-auth-proxy | 3 |
| opendatahub-io/kubeflow | 1 |
| opendatahub-io/kueue | 1 |
| opendatahub-io/odh-model-controller | 1 |
| opendatahub-io/kserve | 1 |

---

## Context-Map Coverage (Opus)

| Rating | Count | Percentage |
|--------|-------|------------|
| full-context | 27 | 67.5% |
| partial-context | 7 | 17.5% |
| cross-component | 5 | 12.5% |
| no-context | 1 | 2.5% |

97.5% of issues mapped to relevant source code with at least partial context.

### Most Frequent Components

| Component | Appearances |
|-----------|-------------|
| rhods-operator | 34 (85%) |
| kserve | 7 |
| kube-auth-proxy | 5 |
| kueue | 5 |
| odh-dashboard | 4 |
| notebooks/kubeflow | 4 |

---

## Bug Clusters (Opus)

### Cluster A: Kueue/StatefulSet Integration (3 issues)

- [RHOAIENG-52249](https://redhat.atlassian.net/browse/RHOAIENG-52249) (score 88) — CopyStatefulSetFields ignores Kueue label immutability
- [RHOAIENG-52235](https://redhat.atlassian.net/browse/RHOAIENG-52235) (score 88) — non-existent queue causes permanent stuck pod
- [RHOAIENG-52223](https://redhat.atlassian.net/browse/RHOAIENG-52223) (score 82) — SIGTERM during rolling update creates finalizer deadlock

All high-severity. Systemic gap in Kueue's StatefulSet lifecycle management. All received high-confidence fixes targeting different repos (kubeflow, rhods-operator, kueue).

### Cluster B: BYOIDC/Entra ID Authentication (3 issues)

- [RHOAIENG-54751](https://redhat.atlassian.net/browse/RHOAIENG-54751) (score 55) — access_token vs id_token mismatch
- [RHOAIENG-54330](https://redhat.atlassian.net/browse/RHOAIENG-54330) (score 57) — same root cause, different approach
- [RHOAIENG-50248](https://redhat.atlassian.net/browse/RHOAIENG-50248) (score 65) — kube-auth-proxy crashloop from unknown flag

Two are essentially duplicates with different fix strategies for the same token-forwarding problem in kube-auth-proxy.

### Cluster C: Operator Resource Cleanup (5 issues)

- [RHOAIENG-52933](https://redhat.atlassian.net/browse/RHOAIENG-52933) (score 90) — cert-manager webhook not cleaned up
- [RHOAIENG-49164](https://redhat.atlassian.net/browse/RHOAIENG-49164) (score 57) — SMMR not removed on ServiceMesh disable
- [RHOAIENG-49161](https://redhat.atlassian.net/browse/RHOAIENG-49161) (score 68) — ModelMeshServing CR left after upgrade
- [RHOAIENG-37563](https://redhat.atlassian.net/browse/RHOAIENG-37563) (score 60) — dual ownership infinite reconciliation loop
- [RHOAIENG-48054](https://redhat.atlassian.net/browse/RHOAIENG-48054) (score 50) — race condition in DSCI/cleanup runnables

Pattern: the operator's resource lifecycle management has systemic gaps.

### Cluster D: Non-OpenShift Platform Support (3 issues)

- [RHOAIENG-53488](https://redhat.atlassian.net/browse/RHOAIENG-53488) (score 63) — cert-manager Certificate missing on non-OCP
- [RHOAIENG-52863](https://redhat.atlassian.net/browse/RHOAIENG-52863) (score 70) — LWS ServiceMonitor fails without Prometheus
- [RHOAIENG-41474](https://redhat.atlassian.net/browse/RHOAIENG-41474) (score 60) — DestinationRule fails without Istio CRDs

Operator assumes OCP-specific CRDs (ServiceMonitor, DestinationRule) exist on AKS/CoreWeave.

### Cluster E: False Ready Status (3 issues)

- [RHOAIENG-34784](https://redhat.atlassian.net/browse/RHOAIENG-34784) (score 85) — false Ready status during component deletion
- [RHOAIENG-13921](https://redhat.atlassian.net/browse/RHOAIENG-13921) (score 82) — Ready reported with failed ImageStreams
- [RHOAIENG-44476](https://redhat.atlassian.net/browse/RHOAIENG-44476) (score 85) — DSC v1/v2 migration silently drops components

Operator incorrectly reports healthy/ready when components are degraded or deleted.

---

## Overall Assessment

**End-to-end success rate:** 55% (issue in, validated patch out). Solid given the input quality.

**Pipeline effectiveness:**
- Context-map phase works well (97.5% coverage)
- Fix validation loop catches errors (5 self-corrections)
- High confidence on fixes that do pass (69.2%)

**Main bottleneck:** Input quality. A Jira template enforcing OCP version, platform details, inline error logs, and specific reproduction commands would shift many "needs-enrichment" issues to "ai-fixable" without any pipeline changes.

**Highest-value bug clusters** for engineering attention are the Kueue/StatefulSet integration bugs (Cluster A) and the operator cleanup gaps (Cluster C) — both represent systemic patterns rather than isolated defects.

---

## Appendix: Opus vs Sonnet Model Comparison

**Sample:** 39 AI Core Platform issues processed by both `claude-opus-4-6` and `claude-sonnet-4-5`.

### Completeness Scores

| Metric | Opus | Sonnet | Delta |
|--------|------|--------|-------|
| Mean score | 66.2 | 73.6 | **+7.4** |
| Median score | 65.0 | 80.0 | +15.0 |
| Min score | 27 | 30 | +3 |
| Max score | 90 | 95 | +5 |

Sonnet scored higher on **33 of 39** issues, tied on 2, and Opus scored higher on only 4 ([RHOAIENG-32503](https://redhat.atlassian.net/browse/RHOAIENG-32503), [RHOAIENG-34784](https://redhat.atlassian.net/browse/RHOAIENG-34784), [RHOAIENG-37563](https://redhat.atlassian.net/browse/RHOAIENG-37563), [RHOAIENG-52190](https://redhat.atlassian.net/browse/RHOAIENG-52190) — all by 2-3 points).

**Largest gaps favoring Sonnet:**

| Issue | Opus | Sonnet | Gap |
|-------|------|--------|-----|
| [RHOAIENG-50248](https://redhat.atlassian.net/browse/RHOAIENG-50248) | 65 | 88 | +23 |
| [RHOAIENG-50513](https://redhat.atlassian.net/browse/RHOAIENG-50513) | 65 | 88 | +23 |
| [RHOAIENG-41474](https://redhat.atlassian.net/browse/RHOAIENG-41474) | 60 | 82.5 | +22.5 |
| [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167) | 60 | 80 | +20 |
| [RHOAIENG-54330](https://redhat.atlassian.net/browse/RHOAIENG-54330) | 57 | 73 | +16 |
| [RHOAIENG-54751](https://redhat.atlassian.net/browse/RHOAIENG-54751) | 55 | 70 | +15 |
| [RHOAIENG-54376](https://redhat.atlassian.net/browse/RHOAIENG-54376) | 65 | 80 | +15 |
| [RHOAIENG-54558](https://redhat.atlassian.net/browse/RHOAIENG-54558) | 80 | 93 | +13 |

**Interpretation:** Sonnet is a more generous grader. It tends to give more credit for narrative descriptions and implicit information. Opus demands more explicit detail. The practical effect: Sonnet triages more issues as "ai-fixable" (see below), which may be either more aggressive or more realistic depending on whether its fixes actually hold up.

### Triage Recommendations

| Recommendation | Opus | Sonnet |
|----------------|------|--------|
| ai-fixable | 12 (30.8%) | 20 (51.3%) |
| needs-enrichment | 24 (61.5%) | 16 (41.0%) |
| other | 3 (7.7%) | 3 (7.7%) |

Models agreed on 31 of 39 issues. In all 8 disagreements, **Opus said "needs-enrichment" while Sonnet said "ai-fixable"**:
[RHOAIENG-41474](https://redhat.atlassian.net/browse/RHOAIENG-41474), [RHOAIENG-49166](https://redhat.atlassian.net/browse/RHOAIENG-49166), [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167), [RHOAIENG-50248](https://redhat.atlassian.net/browse/RHOAIENG-50248), [RHOAIENG-50513](https://redhat.atlassian.net/browse/RHOAIENG-50513), [RHOAIENG-52543](https://redhat.atlassian.net/browse/RHOAIENG-52543), [RHOAIENG-52863](https://redhat.atlassian.net/browse/RHOAIENG-52863), [RHOAIENG-54376](https://redhat.atlassian.net/browse/RHOAIENG-54376).

This directly follows from Sonnet's higher completeness scores pushing issues above the ai-fixable threshold.

### Issue Type Classification

Models agreed on classification for 30 of 39 issues. The 9 disagreements all involve **Opus using a more specific category** while **Sonnet defaults to "bug"**:

| Issue | Opus | Sonnet |
|-------|------|--------|
| [RHOAIENG-13921](https://redhat.atlassian.net/browse/RHOAIENG-13921) | enhancement | bug |
| [RHOAIENG-28830](https://redhat.atlassian.net/browse/RHOAIENG-28830) | test-gap | bug |
| [RHOAIENG-41474](https://redhat.atlassian.net/browse/RHOAIENG-41474) | configuration | bug |
| [RHOAIENG-44437](https://redhat.atlassian.net/browse/RHOAIENG-44437) | configuration | bug |
| [RHOAIENG-49164](https://redhat.atlassian.net/browse/RHOAIENG-49164) | enhancement | bug |
| [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167) | enhancement | bug |
| [RHOAIENG-53488](https://redhat.atlassian.net/browse/RHOAIENG-53488) | feature-request | bug |
| [RHOAIENG-54301](https://redhat.atlassian.net/browse/RHOAIENG-54301) | test-gap | (agreed) |
| [RHOAIENG-45892](https://redhat.atlassian.net/browse/RHOAIENG-45892) | feature-request | feature-request |

Opus applies a wider taxonomy (enhancement, configuration, test-gap, feature-request). Sonnet tends to classify ambiguous issues as "bug" — a more conservative approach that keeps everything in the fix-attempt pipeline rather than filtering it out.

### Fix-Attempt Confidence

Of the 27 issues where both models produced fix-attempts:

| Confidence | Opus | Sonnet |
|------------|------|--------|
| high | 18 (66.7%) | 25 (92.6%) |
| medium | 8 (29.6%) | 2 (7.4%) |
| low | 1 (3.7%) | 0 (0%) |

Sonnet is substantially more confident in its fixes. Whether this reflects genuine capability or overconfidence depends on validation pass rates (see below).

### Fix Recommendation Disagreements

4 issues had different fix recommendations:

| Issue | Opus | Sonnet |
|-------|------|--------|
| [RHOAIENG-28830](https://redhat.atlassian.net/browse/RHOAIENG-28830) | already-fixed | ai-fixable |
| [RHOAIENG-44437](https://redhat.atlassian.net/browse/RHOAIENG-44437) | insufficient-info | ai-fixable |
| [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167) | upstream-required | ai-fixable |
| [RHOAIENG-27943](https://redhat.atlassian.net/browse/RHOAIENG-27943) | ai-fixable (rhods-operator) | ai-fixable (kserve) |

Opus is more conservative — flagging issues as already-fixed, insufficient-info, or upstream-required where Sonnet attempts a fix. [RHOAIENG-27943](https://redhat.atlassian.net/browse/RHOAIENG-27943) is notable: both say ai-fixable but disagree on which repository to target (the only repo disagreement across all 39 issues).

### Patch Size and Self-Corrections

**Patches generated:** Opus produced patches for 22 issues, Sonnet for 24. Sonnet generated patches for 4 issues where Opus did not ([RHOAIENG-28830](https://redhat.atlassian.net/browse/RHOAIENG-28830), [RHOAIENG-44437](https://redhat.atlassian.net/browse/RHOAIENG-44437), [RHOAIENG-49166](https://redhat.atlassian.net/browse/RHOAIENG-49166), [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167)).

**Self-corrections:** Opus self-corrected on 7 issues (max 2 iterations on [RHOAIENG-52249](https://redhat.atlassian.net/browse/RHOAIENG-52249)). Sonnet self-corrected on 5 issues. Low self-correction counts on both models — most fixes passed on the first attempt.

**Mean patch size (where both produced patches):**
- Opus: 115 lines
- Sonnet: 120 lines
- No meaningful size difference.

### Context-Map Coverage

Sonnet had context-map results for only 28 of 39 issues (vs. all 39 for Opus). Where both have ratings:

| Rating | Opus | Sonnet |
|--------|------|--------|
| full-context | 20 | 22 |
| partial-context | 3 | 3 |
| cross-component | 5 | 1 |

Opus identifies more cross-component dependencies. Sonnet tends to rate the same issues as either full-context or partial-context rather than cross-component, potentially missing multi-repo interactions.

### Summary: When to Use Which Model

**Opus strengths:**
- More nuanced issue classification (distinguishes enhancement/configuration/test-gap from bug)
- More conservative confidence — fewer false positives
- Better at identifying cross-component dependencies
- More demanding completeness scoring encourages better bug reports

**Sonnet strengths:**
- Higher throughput — attempts fixes on more issues
- More generous scoring means fewer issues stuck in "needs-enrichment"
- Produces patches even for ambiguous issues
- Faster context-map phase completion

**Recommendation:** Use Sonnet for first-pass triage to maximize fix coverage, then use Opus as a second opinion on the highest-risk fixes (medium/low confidence, cross-component, or issues where Sonnet and Opus disagree on type or target repo). The 8 triage disagreements and 4 fix-recommendation disagreements are the best candidates for human review.
