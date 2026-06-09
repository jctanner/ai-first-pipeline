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

## Bug Report Quality

| Metric | Opus | Sonnet |
|--------|------|--------|
| Mean completeness score | 67.1 | **74.4** |
| Median score | 65.0 | **80.0** |
| Triaged "ai-fixable" | 30.8% | **51.3%** |
| Triaged "needs-enrichment" | 66.7% | 46.2% |

Sonnet scored higher on 33 of 39 issues (average +7.3 points). Opus scored higher on only 4 issues, all by 2-3 points.

### Score Distribution

| Score Range | Opus | Sonnet | Interpretation |
|-------------|------|--------|----------------|
| 85-100      | 7 (17.5%)  | 14 (35.9%) | Excellent — well-written, actionable |
| 65-84       | 13 (32.5%) | 16 (41.0%) | Good — most information present, minor gaps |
| 50-64       | 12 (30.0%) | 6 (15.4%)  | Fair — usable but missing important details |
| Below 50    | 8 (20.0%)  | 3 (7.7%)   | Poor — significant information gaps |

Sonnet shifts the distribution upward — nearly twice as many issues land in the "Excellent" bucket, and far fewer in "Fair" or "Poor". This is because Sonnet gives more credit for narrative descriptions and implicit information, while Opus demands more explicit detail.

### Systemic Weaknesses in Bug Reports

Both models agree on the weakest dimensions:

- **Environment info** is the weakest dimension: 62.5% scored 50 or below. OCP version, platform (AWS/GCP/bare metal), and architecture are routinely omitted.
- **Attachments/evidence** missing in 70% of issues. Most bugs lack inline logs, screenshots, or YAML artifacts.
- **Reproduction steps** vary wildly: 8 scored 100 but 5 scored 0.
- **Severity justification** weak: only 6 of 40 scored 100; 10 scored 0.

### Strengths

- Summary clarity generally good (32 of 40 scored 100)
- Component identification strong (25 of 40 scored 100)
- Expected-vs-actual well documented when present (24 of 40 scored 100)

---

## Issue Type Classification

| Classified Type | Opus | Sonnet |
|-----------------|------|--------|
| bug             | 25 (64.1%) | **32 (82.1%)** |
| enhancement     | 4 (10.3%) | 1 (2.6%) |
| task            | 3 (7.7%) | 3 (7.7%) |
| feature-request | 2 (5.1%) | 1 (2.6%) |
| test-gap        | 2 (5.1%) | 1 (2.6%) |
| configuration   | 2 (5.1%) | 0 (0%) |
| docs-update     | 1 (2.6%) | 1 (2.6%) |

Opus applies a wider taxonomy — classifying ambiguous issues as enhancement, configuration, or test-gap. Sonnet defaults to "bug" more often, which keeps more issues in the fix-attempt pipeline. The models disagreed on classification for 9 of 39 issues; in 7 of those 9, Sonnet called it a bug while Opus used a more specific category.

---

## Fix Attempt Results

Opus produced fix-attempts for 27 issues; Sonnet for 27. The remaining issues were skipped (active work status, insufficient info, or non-bug classification).

### Fix Recommendations

| Recommendation    | Opus | Sonnet |
|-------------------|------|--------|
| ai-fixable        | 22 (81.5%) | **25 (92.6%)** |
| already-fixed     | 2 (7.4%) | 1 (3.7%) |
| upstream-required | 1 (3.7%) | 0 (0%) |
| docs-only         | 1 (3.7%) | 1 (3.7%) |
| insufficient-info | 1 (3.7%) | 0 (0%) |

Sonnet attempts fixes on 3 more issues where Opus declined (flagging them as already-fixed, upstream-required, or insufficient-info).

### Confidence Levels

| Confidence | Opus | Sonnet |
|------------|------|--------|
| high       | 18 (66.7%) | **25 (92.6%)** |
| medium     | 8 (29.6%) | 2 (7.4%) |
| low        | 1 (3.7%) | 0 (0%) |

Sonnet is substantially more confident. Whether this reflects genuine capability or overconfidence depends on downstream validation.

### Patches and Self-Corrections

| Metric | Opus | Sonnet |
|--------|------|--------|
| Patches generated | 22 | 24 |
| Mean patch size | 115 lines | 120 lines |
| Issues with self-corrections | 7 | 5 |

Sonnet generated patches for 4 issues where Opus did not ([RHOAIENG-28830](https://redhat.atlassian.net/browse/RHOAIENG-28830), [RHOAIENG-44437](https://redhat.atlassian.net/browse/RHOAIENG-44437), [RHOAIENG-49166](https://redhat.atlassian.net/browse/RHOAIENG-49166), [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167)). Low self-correction counts on both models — most fixes passed on the first attempt.

### Target Repositories

| Repository | Fix Count |
|------------|-----------|
| opendatahub-io/opendatahub-operator (rhods-operator) | 16 (61.5%) |
| opendatahub-io/kube-auth-proxy | 3 |
| opendatahub-io/kubeflow | 1 |
| opendatahub-io/kueue | 1 |
| opendatahub-io/odh-model-controller | 1 |
| opendatahub-io/kserve | 1 |

Both models agreed on the target repository for all issues except [RHOAIENG-27943](https://redhat.atlassian.net/browse/RHOAIENG-27943) (Opus targeted rhods-operator, Sonnet targeted kserve).

---

## Context-Map Coverage

Opus produced context-maps for all 39 issues; Sonnet for 27 (69%).

| Rating | Opus (n=39) | Sonnet (n=27) |
|--------|-------------|---------------|
| full-context | 28 (71.8%) | 23 (85.2%) |
| partial-context | 5 (12.8%) | 3 (11.1%) |
| cross-component | 5 (12.8%) | 1 (3.7%) |
| no-context | 1 (2.6%) | 0 (0%) |

Opus identifies more cross-component dependencies (5 vs 1). Sonnet tends to rate cross-component issues as full-context or partial-context, potentially missing multi-repo interactions. Both models achieved near-complete coverage — 97.4% of Opus results and 100% of Sonnet results mapped to relevant source code with at least partial context.

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

## Bug Clusters

Both models identified the same clusters. Scores shown as Opus / Sonnet.

### Cluster A: Kueue/StatefulSet Integration (3 issues)

| Issue | Opus | Sonnet | Description |
|-------|------|--------|-------------|
| [RHOAIENG-52249](https://redhat.atlassian.net/browse/RHOAIENG-52249) | 88 | 95 | CopyStatefulSetFields ignores Kueue label immutability |
| [RHOAIENG-52235](https://redhat.atlassian.net/browse/RHOAIENG-52235) | 88 | 95 | Non-existent queue causes permanent stuck pod |
| [RHOAIENG-52223](https://redhat.atlassian.net/browse/RHOAIENG-52223) | 82 | 87.5 | SIGTERM during rolling update creates finalizer deadlock |

All high-severity. Systemic gap in Kueue's StatefulSet lifecycle management. Both models produced high-confidence fixes targeting different repos (kubeflow, rhods-operator, kueue).

### Cluster B: BYOIDC/Entra ID Authentication (3 issues)

| Issue | Opus | Sonnet | Description |
|-------|------|--------|-------------|
| [RHOAIENG-54751](https://redhat.atlassian.net/browse/RHOAIENG-54751) | 55 | 70 | access_token vs id_token mismatch |
| [RHOAIENG-54330](https://redhat.atlassian.net/browse/RHOAIENG-54330) | 57 | 73 | Same root cause, different approach |
| [RHOAIENG-50248](https://redhat.atlassian.net/browse/RHOAIENG-50248) | 65 | 88 | kube-auth-proxy crashloop from unknown flag |

Two are essentially duplicates with different fix strategies for the same token-forwarding problem in kube-auth-proxy. Sonnet scored these 15-23 points higher — the largest model gap of any cluster.

### Cluster C: Operator Resource Cleanup (5 issues)

| Issue | Opus | Sonnet | Description |
|-------|------|--------|-------------|
| [RHOAIENG-52933](https://redhat.atlassian.net/browse/RHOAIENG-52933) | 90 | 90 | cert-manager webhook not cleaned up |
| [RHOAIENG-49164](https://redhat.atlassian.net/browse/RHOAIENG-49164) | 57 | 63 | SMMR not removed on ServiceMesh disable |
| [RHOAIENG-49161](https://redhat.atlassian.net/browse/RHOAIENG-49161) | 68 | 72 | ModelMeshServing CR left after upgrade |
| [RHOAIENG-37563](https://redhat.atlassian.net/browse/RHOAIENG-37563) | 60 | 57.5 | Dual ownership infinite reconciliation loop |
| [RHOAIENG-48054](https://redhat.atlassian.net/browse/RHOAIENG-48054) | 50 | 55 | Race condition in DSCI/cleanup runnables |

Pattern: the operator's resource lifecycle management has systemic gaps. Models mostly agree on scores here (within 5 points).

### Cluster D: Non-OpenShift Platform Support (3 issues)

| Issue | Opus | Sonnet | Description |
|-------|------|--------|-------------|
| [RHOAIENG-53488](https://redhat.atlassian.net/browse/RHOAIENG-53488) | 63 | 65 | cert-manager Certificate missing on non-OCP |
| [RHOAIENG-52863](https://redhat.atlassian.net/browse/RHOAIENG-52863) | 70 | 80 | LWS ServiceMonitor fails without Prometheus |
| [RHOAIENG-41474](https://redhat.atlassian.net/browse/RHOAIENG-41474) | 60 | 82.5 | DestinationRule fails without Istio CRDs |

Operator assumes OCP-specific CRDs (ServiceMonitor, DestinationRule) exist on AKS/CoreWeave. Sonnet scored RHOAIENG-41474 22.5 points higher — Opus called it a "configuration" issue, Sonnet called it a "bug".

### Cluster E: False Ready Status (3 issues)

| Issue | Opus | Sonnet | Description |
|-------|------|--------|-------------|
| [RHOAIENG-34784](https://redhat.atlassian.net/browse/RHOAIENG-34784) | 85 | 82.5 | False Ready status during component deletion |
| [RHOAIENG-13921](https://redhat.atlassian.net/browse/RHOAIENG-13921) | 82 | 85 | Ready reported with failed ImageStreams |
| [RHOAIENG-44476](https://redhat.atlassian.net/browse/RHOAIENG-44476) | 85 | 92.5 | DSC v1/v2 migration silently drops components |

Operator incorrectly reports healthy/ready when components are degraded or deleted. Models closely agree on these well-documented issues.

---

## Overall Assessment

| Metric | Opus | Sonnet |
|--------|------|--------|
| End-to-end success rate (issue in, validated patch out) | 55% | 62% |
| Context-map coverage | 97.4% | 100% |
| Self-corrections triggered | 7 | 5 |
| High-confidence fixes | 66.7% | 92.6% |

**Main bottleneck:** Input quality. A Jira template enforcing OCP version, platform details, inline error logs, and specific reproduction commands would shift many "needs-enrichment" issues to "ai-fixable" without any pipeline changes.

**Highest-value bug clusters** for engineering attention are the Kueue/StatefulSet integration bugs (Cluster A) and the operator cleanup gaps (Cluster C) — both represent systemic patterns rather than isolated defects.

---

## Appendix: Model Disagreements

The 8 triage disagreements and 4 fix-recommendation disagreements listed below are the best candidates for human review.

### Triage Disagreements

In all 8 cases, Opus said "needs-enrichment" while Sonnet said "ai-fixable":

| Issue | Opus Score | Sonnet Score |
|-------|-----------|-------------|
| [RHOAIENG-41474](https://redhat.atlassian.net/browse/RHOAIENG-41474) | 60 | 82.5 |
| [RHOAIENG-49166](https://redhat.atlassian.net/browse/RHOAIENG-49166) | 78 | 80 |
| [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167) | 60 | 80 |
| [RHOAIENG-50248](https://redhat.atlassian.net/browse/RHOAIENG-50248) | 65 | 88 |
| [RHOAIENG-50513](https://redhat.atlassian.net/browse/RHOAIENG-50513) | 65 | 88 |
| [RHOAIENG-52543](https://redhat.atlassian.net/browse/RHOAIENG-52543) | 73 | 85 |
| [RHOAIENG-52863](https://redhat.atlassian.net/browse/RHOAIENG-52863) | 70 | 80 |
| [RHOAIENG-54376](https://redhat.atlassian.net/browse/RHOAIENG-54376) | 65 | 80 |

### Type Classification Disagreements

In 7 of 9 cases, Sonnet classified as "bug" while Opus used a more specific category:

| Issue | Opus | Sonnet |
|-------|------|--------|
| [RHOAIENG-13921](https://redhat.atlassian.net/browse/RHOAIENG-13921) | enhancement | bug |
| [RHOAIENG-28830](https://redhat.atlassian.net/browse/RHOAIENG-28830) | test-gap | bug |
| [RHOAIENG-41474](https://redhat.atlassian.net/browse/RHOAIENG-41474) | configuration | bug |
| [RHOAIENG-44437](https://redhat.atlassian.net/browse/RHOAIENG-44437) | configuration | bug |
| [RHOAIENG-49164](https://redhat.atlassian.net/browse/RHOAIENG-49164) | enhancement | bug |
| [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167) | enhancement | bug |
| [RHOAIENG-53488](https://redhat.atlassian.net/browse/RHOAIENG-53488) | feature-request | bug |

### Fix Recommendation Disagreements

| Issue | Opus | Sonnet |
|-------|------|--------|
| [RHOAIENG-28830](https://redhat.atlassian.net/browse/RHOAIENG-28830) | already-fixed | ai-fixable |
| [RHOAIENG-44437](https://redhat.atlassian.net/browse/RHOAIENG-44437) | insufficient-info | ai-fixable |
| [RHOAIENG-49167](https://redhat.atlassian.net/browse/RHOAIENG-49167) | upstream-required | ai-fixable |
| [RHOAIENG-27943](https://redhat.atlassian.net/browse/RHOAIENG-27943) | ai-fixable (rhods-operator) | ai-fixable (kserve) |

### When to Use Which Model

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

**Recommendation:** Use Sonnet for first-pass triage to maximize fix coverage, then use Opus as a second opinion on the highest-risk fixes (medium/low confidence, cross-component, or issues where the models disagree on type or target repo).
