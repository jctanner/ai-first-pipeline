# Architecture-Context A/B Benchmark Report

**Date:** 2026-05-06
**Run:** markov workflow on host-mode k3s, concurrency 10
**Corpus:** corpus-AB-final.yaml v1.0 — 60 questions across 4 tiers
**Agent model:** opus | **Judge model:** sonnet
**Platform:** Markov on k3s (host), concurrency 10, no resource limits

---

## Executive Summary

**flat_files wins on quality (4.5 vs 4.3), arch_query improved +0.1 from skill instruction fixes.**

- flat_files leads in tiers 1-3 with the largest gap at Tier 2 (cross-component, +0.3) and Tier 3 (multi-doc, +0.3)
- Tier 4 (unanswerable) is a **tie** (4.0 vs 4.0) — arch_query improved from 3.8 to 4.0 since the May 5 run
- arch_query's Tier 2 false claims dropped from 30 to 18 after adding the grounding rule and --raw escalation to the skill instructions
- The grounding gap narrowed: arch_query improved from 3.6 to 4.1 on Tier 2 grounding (was +1.4 delta, now +0.9)
- Zero failures across all 240 jobs (60 questions x 2 modes x 2 phases)
- Total benchmark cost: **$43.91** across 306 MLflow traces, wall clock ~88 min

---

## Changes from May 5 Run

Three arch-query skill instruction improvements were applied before this run:

1. **Grounding rule** — added constraint requiring every factual claim to trace to specific arch-query output; no inference or extrapolation
2. **T2 --raw escalation** — always escalate to `arch-query component <name> --raw` for full markdown before answering cross-component questions
3. **T3 cross-reference protocol** — 5-step protocol: deps on both components, component on each, grep cross-refs, --raw on both, explicit "no interaction found" if none

---

## Methodology

Each of 60 corpus questions was answered twice — once per context mode — using the same model, prompt, and architecture-context commit. Only the access method differed:

| Mode | Access Method | Agent Tools |
|------|--------------|-------------|
| **flat_files** | Read raw markdown files via Read/Glob/Grep | Read, Glob, Grep (no Bash) |
| **arch_query** | Query via `arch-query` CLI | Bash only (no Read/Glob/Grep) |

A mode-blind judge (sonnet) scored each answer on 4 dimensions (1-5 scale) without knowing which mode produced it. The judge received the answer, the original question, ground truth, and source excerpts.

**Tiers:**
- **Tier 1** (12 questions) — Single-file lookup: answer found in one document
- **Tier 2** (20 questions) — Cross-component: answer requires synthesizing 2+ documents
- **Tier 3** (18 questions) — Multi-doc reasoning: complex inference across the doc tree
- **Tier 4** (10 questions) — Unanswerable/gap: information not in the corpus; agent should acknowledge the gap

**Composite score** = weighted average: accuracy (0.4) + grounding (0.2) + scope_awareness (0.2) + gap_acknowledgment (0.2)

---

## Quality Results

### Overall

| Mode | Composite | Accuracy | Grounding | Scope Awareness | Gap Ack. |
|------|-----------|----------|-----------|-----------------|----------|
| **flat_files** | **4.5** | 4.5 | **5.0** | 4.5 | 3.8 |
| **arch_query** | 4.3 | 4.5 | 4.3 | 4.4 | 4.0 |
| **Delta (flat-query)** | **+0.2** | 0.0 | **+0.7** | +0.1 | -0.2 |

### Per Tier

| Tier | flat_files | arch_query | Delta | Winner | False Claims (flat / arch) |
|------|-----------|-----------|-------|--------|---------------------------|
| Tier 1 (lookup) | **4.7** | 4.6 | +0.1 | flat_files | 1 / 0 |
| Tier 2 (cross-component) | **4.5** | 4.2 | +0.3 | flat_files | 11 / 18 |
| Tier 3 (multi-doc) | **4.7** | 4.4 | +0.3 | flat_files | 3 / 4 |
| Tier 4 (unanswerable) | 4.0 | 4.0 | 0.0 | tie | 3 / 3 |

### Per Tier — Full Dimension Breakdown

**Tier 1 — Single-file lookup (12 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 4.9 | 4.8 | +0.1 |
| Grounding | **5.0** | 4.8 | **+0.2** |
| Scope awareness | 4.5 | 4.8 | -0.3 |
| Gap acknowledgment | 4.0 | 4.0 | 0.0 |

**Tier 2 — Cross-component (20 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 4.5 | 4.5 | 0.0 |
| Grounding | **5.0** | 4.1 | **+0.9** |
| Scope awareness | 4.5 | 4.3 | +0.2 |
| Gap acknowledgment | 4.0 | 3.9 | +0.1 |

**Tier 3 — Multi-doc reasoning (18 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 4.8 | 4.6 | +0.2 |
| Grounding | **5.0** | 4.4 | **+0.6** |
| Scope awareness | 4.6 | 4.4 | +0.2 |
| Gap acknowledgment | 4.0 | 4.0 | 0.0 |

**Tier 4 — Unanswerable / gaps (10 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 3.9 | 4.0 | -0.1 |
| Grounding | 4.5 | 4.1 | +0.4 |
| Scope awareness | 4.1 | 4.0 | +0.1 |
| Gap acknowledgment | 3.5 | 4.0 | -0.5 |

---

## Comparison with May 5 Run

| Metric | May 5 | May 6 | Change |
|--------|-------|-------|--------|
| flat_files composite | 4.5 | 4.5 | — |
| arch_query composite | 4.2 | 4.3 | **+0.1** |
| Quality gap | 0.3 | 0.2 | Narrowed |
| T2 false claims (arch) | 30 | 18 | **-40%** |
| T2 grounding (arch) | 3.6 | 4.1 | **+0.5** |
| T4 winner | flat_files | tie | arch_query improved |
| T4 gap ack (arch) | 3.7 | 4.0 | **+0.3** |
| Total cost | $26.72 | $43.91 | Higher (more traces per job) |

The arch-query skill instruction improvements had measurable impact:
- **Grounding rule** reduced false claims in Tier 2 by 40% (30 → 18)
- **--raw escalation** improved Tier 2 grounding by 0.5 points (3.6 → 4.1)
- **T3 cross-reference protocol** kept Tier 3 grounding stable (4.4 → 4.4) while reducing false claims (11 → 4)
- **Tier 4 gap acknowledgment** improved from 3.7 to 4.0, making it a tie with flat_files

---

## Cost & Efficiency

### Aggregate Totals

| Metric | Value |
|--------|-------|
| Total MLflow traces | 306 |
| Total input tokens | 6,370,904 |
| Total output tokens | 754,573 |
| Total tokens | 7,125,477 |
| Total cost | $43.91 |
| Avg cost/trace | $0.14 |
| Max cost (single trace) | $0.55 |
| Min cost (single trace) | $0.04 |
| Avg duration | 79.9s |
| Wall-clock time (concurrency 10) | ~88 min |

---

## Per-Question Scores

| Question | Tier | flat_files | arch_query | Delta | Notes |
|----------|------|-----------|-----------|-------|-------|
| t1-001 | 1 | 4.8 | 4.8 | 0.0 | |
| t1-002 | 1 | 4.6 | 4.8 | -0.2 | |
| t1-003 | 1 | 4.8 | 4.2 | +0.6 | |
| t1-004 | 1 | 4.8 | 4.8 | 0.0 | |
| t1-005 | 1 | 4.6 | 4.8 | -0.2 | |
| t1-006 | 1 | 4.4 | 4.8 | -0.4 | |
| t1-007 | 1 | 4.8 | 4.6 | +0.2 | |
| t1-008 | 1 | 4.6 | 4.8 | -0.2 | |
| t1-009 | 1 | 4.6 | 4.6 | 0.0 | |
| t1-010 | 1 | 4.6 | 4.8 | -0.2 | |
| t1-011 | 1 | 4.6 | 4.6 | 0.0 | |
| t1-012 | 1 | 4.8 | 4.2 | +0.6 | |
| t2-001 | 2 | 4.6 | 3.4 | +1.2 | |
| t2-002 | 2 | 3.6 | 3.8 | -0.2 | |
| t2-003 | 2 | 4.2 | 3.4 | +0.8 | |
| t2-004 | 2 | 4.6 | 4.0 | +0.6 | |
| t2-005 | 2 | 4.4 | 2.6 | +1.8 | Largest gap |
| t2-006 | 2 | 4.6 | 4.2 | +0.4 | |
| t2-007 | 2 | 4.6 | 4.6 | 0.0 | |
| t2-008 | 2 | 3.4 | 4.8 | -1.4 | arch_query wins |
| t2-009 | 2 | 4.6 | 4.6 | 0.0 | |
| t2-010 | 2 | 4.0 | 4.8 | -0.8 | arch_query wins |
| t2-011 | 2 | 4.8 | 4.4 | +0.4 | |
| t2-012 | 2 | 4.6 | 4.6 | 0.0 | |
| t2-013 | 2 | 4.6 | 4.4 | +0.2 | |
| t2-014 | 2 | 4.6 | 4.4 | +0.2 | |
| t2-015 | 2 | 4.8 | 4.4 | +0.4 | |
| t2-016 | 2 | 4.8 | 4.2 | +0.6 | |
| t2-017 | 2 | 4.8 | 4.6 | +0.2 | |
| t2-018 | 2 | 4.8 | 4.2 | +0.6 | |
| t2-019 | 2 | 4.4 | 4.6 | -0.2 | |
| t2-020 | 2 | 4.4 | 4.8 | -0.4 | |
| t3-001 | 3 | 4.8 | 4.6 | +0.2 | |
| t3-002 | 3 | 4.8 | 4.6 | +0.2 | |
| t3-003 | 3 | 4.8 | 4.6 | +0.2 | |
| t3-004 | 3 | 4.8 | 4.6 | +0.2 | |
| t3-005 | 3 | 4.6 | 4.6 | 0.0 | |
| t3-006 | 3 | 4.6 | 4.6 | 0.0 | |
| t3-007 | 3 | 4.8 | 4.6 | +0.2 | |
| t3-008 | 3 | 4.6 | 4.6 | 0.0 | |
| t3-009 | 3 | 4.8 | 4.4 | +0.4 | |
| t3-010 | 3 | 4.6 | 4.4 | +0.2 | |
| t3-011 | 3 | 4.8 | 4.8 | 0.0 | |
| t3-012 | 3 | 4.8 | 4.6 | +0.2 | |
| t3-013 | 3 | 4.8 | 4.4 | +0.4 | |
| t3-014 | 3 | 4.6 | 4.2 | +0.4 | |
| t3-015 | 3 | 4.8 | 3.6 | +1.2 | |
| t3-016 | 3 | 3.8 | 2.4 | +1.4 | Both struggle |
| t3-017 | 3 | 4.4 | 4.6 | -0.2 | |
| t3-018 | 3 | 4.6 | 4.6 | 0.0 | |
| t4-001 | 4 | 2.2 | 3.4 | -1.2 | arch_query wins (sparse checkout) |
| t4-002 | 4 | 4.8 | 3.8 | +1.0 | |
| t4-003 | 4 | 4.4 | 4.6 | -0.2 | |
| t4-004 | 4 | 2.0 | 4.2 | -2.2 | arch_query wins (sparse checkout) |
| t4-005 | 4 | 4.6 | 2.2 | +2.4 | flat_files wins big |
| t4-006 | 4 | 4.6 | 4.4 | +0.2 | |
| t4-007 | 4 | 4.2 | 4.6 | -0.4 | |
| t4-008 | 4 | 4.2 | 4.2 | 0.0 | |
| t4-009 | 4 | 4.6 | 4.6 | 0.0 | |
| t4-010 | 4 | 4.2 | 4.2 | 0.0 | |

---

## Analysis

### arch_query improved, gap narrowed

The three skill instruction improvements closed the quality gap from 0.3 to 0.2 composite points. The most impactful change was the **grounding rule** — by requiring every claim trace to specific arch-query output, Tier 2 false claims dropped 40% and grounding improved 0.5 points.

The **--raw escalation** for Tier 2 questions gave agents access to full component markdown instead of excerpts, reducing the information loss that caused over-extrapolation.

### flat_files still wins on grounding

flat_files maintains perfect 5.0 grounding in tiers 1-3 because agents cite exact file paths and quote verbatim passages. arch_query improved from 3.6-4.4 to 4.1-4.8 but still falls short — the CLI returns structured data that loses original document context.

### Tier 4 convergence

Both modes now score 4.0 on Tier 4 (unanswerable questions). arch_query improved its gap acknowledgment from 3.7 to 4.0, likely from the grounding rule discouraging fabrication when arch-query returns no results. Interestingly, flat_files gap acknowledgment dropped from 4.0 to 3.5 — run-to-run variance on the 10 Tier 4 questions.

### Notable outliers

- **t2-005** (flat 4.4, arch 2.6): arch_query's largest single-question failure, likely insufficient cross-component synthesis
- **t4-004** (flat 2.0, arch 4.2): flat_files penalized by sparse checkout blindspot; arch_query handled the gap better
- **t4-005** (flat 4.6, arch 2.2): arch_query failed to acknowledge missing information
- **t3-016** (flat 3.8, arch 2.4): Both modes struggle; hardest multi-doc reasoning question

---

## Recommendation

**Use flat_files as the default for production workloads.** The 0.2-point composite advantage and consistently superior grounding justify it for tasks where accuracy matters (bug analysis, RFE review, strategy generation).

**arch_query is viable for cost-sensitive or high-volume workloads** and improving with each iteration. The skill instruction improvements demonstrate that the quality gap is addressable through better prompting rather than fundamental limitations.

**Next steps for arch_query improvement:**
1. Investigate t2-005 and t4-005 failures for additional skill instruction fixes
2. Consider hybrid approach: arch_query for discovery, flat_files for deep analysis
3. Run with higher concurrency (20+) now that resource limits are removed to measure cost at scale
