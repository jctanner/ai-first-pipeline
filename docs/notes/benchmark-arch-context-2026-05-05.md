# Architecture-Context A/B Benchmark Report

**Date:** 2026-05-05
**Run:** markov-run-7b2335ca (completed), markov-run-dfac1c58 (agent jobs)
**Corpus:** corpus-AB-final.yaml v1.0 — 60 questions across 4 tiers
**Agent model:** opus | **Judge model:** sonnet
**Platform:** Markov on k3s, concurrency 5

---

## Executive Summary

**flat_files wins on quality (4.5 vs 4.2), arch_query wins on cost ($5.23 vs $10.95).**

- flat_files outperforms arch_query in every tier, with the largest gap at Tier 2 (cross-component questions): 4.5 vs 4.0
- The quality advantage comes from **grounding** — flat_files agents cite source documents with near-perfect precision (5.0 avg in tiers 1-3), while arch_query agents average 3.6-4.4
- arch_query costs **52% less** per answer ($0.09 vs $0.18) because it consumes 60% fewer input tokens — the CLI returns focused excerpts instead of full files
- Total benchmark cost: **$26.72** for 240 agent jobs (120 answers + 120 judgments)
- Zero failures across all 240 jobs

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
| **flat_files** | **4.5** | 4.6 | **5.0** | 4.3 | 4.0 |
| **arch_query** | 4.2 | 4.2 | 3.9 | 4.4 | 3.9 |
| **Delta** | **+0.3** | +0.4 | **+1.1** | -0.1 | +0.1 |

### Per Tier

| Tier | flat_files | arch_query | Delta | Winner | False Claims (flat / arch) |
|------|-----------|-----------|-------|--------|---------------------------|
| Tier 1 (lookup) | **4.6** | 4.5 | +0.1 | flat_files | 0 / 0 |
| Tier 2 (cross-component) | **4.5** | 4.0 | +0.5 | flat_files | 1 / 30 |
| Tier 3 (multi-doc) | **4.6** | 4.3 | +0.3 | flat_files | 1 / 11 |
| Tier 4 (unanswerable) | **4.1** | 3.8 | +0.3 | flat_files | 4 / 3 |

### Per Tier — Full Dimension Breakdown

**Tier 1 — Single-file lookup (12 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 4.9 | 4.8 | +0.1 |
| Grounding | **5.0** | 4.4 | **+0.6** |
| Scope awareness | 4.3 | 4.6 | -0.3 |
| Gap acknowledgment | 4.0 | 4.0 | 0.0 |

**Tier 2 — Cross-component (20 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 4.6 | 4.2 | +0.4 |
| Grounding | **5.0** | 3.6 | **+1.4** |
| Scope awareness | 4.3 | 4.3 | 0.0 |
| Gap acknowledgment | 4.0 | 4.0 | 0.0 |

**Tier 3 — Multi-doc reasoning (18 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 4.7 | 4.2 | +0.5 |
| Grounding | **5.0** | 4.4 | **+0.6** |
| Scope awareness | 4.6 | 4.5 | +0.1 |
| Gap acknowledgment | 4.0 | 4.0 | 0.0 |

**Tier 4 — Unanswerable / gaps (10 questions)**

| Dimension | flat_files | arch_query | Delta |
|-----------|-----------|-----------|-------|
| Accuracy | 4.1 | 3.6 | +0.5 |
| Grounding | 4.2 | 4.3 | -0.1 |
| Scope awareness | 4.1 | 4.0 | +0.1 |
| Gap acknowledgment | 3.8 | 3.7 | +0.1 |

---

## Cost & Efficiency

### Per Skill

| Skill | Jobs | Total Cost | Avg Cost | Avg Input Tokens | Avg Output Tokens | Avg Duration | Avg Turns |
|-------|------|-----------|----------|-----------------|-------------------|-------------|-----------|
| answer/flat_files | 60 | $10.95 | $0.18 | 30,954 | 1,112 | 62s | 15.4 |
| answer/arch_query | 60 | $5.23 | $0.09 | 12,368 | 1,010 | 48s | 13.1 |
| judge | 120 | $10.53 | $0.09 | 10,323 | 3,787 | 69s | 7.0 |
| **Total** | **240** | **$26.72** | **$0.11** | **15,992** | **2,424** | | |

### Answer Mode Comparison

| Metric | flat_files | arch_query | Ratio |
|--------|-----------|-----------|-------|
| Total cost | $10.95 | $5.23 | 2.1x |
| Avg cost/answer | $0.18 | $0.09 | 2.0x |
| Avg input tokens | 30,954 | 12,368 | 2.5x |
| Avg output tokens | 1,112 | 1,010 | 1.1x |
| Avg duration | 62s | 48s | 1.3x |
| Avg turns (tool calls) | 15.4 | 13.1 | 1.2x |

### Aggregate Totals

| Metric | Value |
|--------|-------|
| Total tokens consumed | 4,420,100 |
| Total input tokens | 3,838,216 |
| Total output tokens | 581,884 |
| Total cost | $26.72 |
| Wall-clock time (concurrency 5) | ~95 min |
| Most expensive single job | $0.46 |
| Cheapest single job | $0.04 |

---

## Analysis

### Why flat_files wins on quality

The dominant factor is **grounding**. flat_files agents score 5.0 (perfect) on grounding in tiers 1-3, while arch_query agents average 3.6-4.4. When agents read raw files with Read/Glob/Grep, they can cite exact file paths and quote verbatim passages. The arch-query CLI returns structured excerpts that lose the original document context, making precise citation harder.

The grounding gap is largest at **Tier 2** (cross-component, +1.4 delta) where answers must synthesize multiple documents. flat_files agents naturally discover related content while browsing the directory tree; arch_query agents must formulate the right queries and may miss adjacent context.

**False claims** tell the same story: arch_query produced 30 false claims in Tier 2 alone vs 1 for flat_files. The CLI's focused excerpts apparently encourage agents to over-extrapolate from incomplete context.

### Why arch_query wins on cost

arch_query uses **60% fewer input tokens** per answer (12,368 vs 30,954). The CLI returns targeted excerpts rather than full files, so the agent's context window stays lean. This translates directly to 52% lower cost per answer ($0.09 vs $0.18).

arch_query is also **23% faster** (48s vs 62s avg) and uses **15% fewer tool calls** (13.1 vs 15.4 turns). The CLI answers in 1-2 Bash calls what flat_files achieves through many Read/Glob/Grep iterations.

Output tokens are nearly identical (~1,100 per answer) — both modes produce similar-length answers.

### Tier 4 convergence

On unanswerable questions (Tier 4), both modes struggle similarly. Neither has strong signals for "this information doesn't exist," and both produce some false claims (4 flat_files, 3 arch_query). Gap acknowledgment scores are the weakest dimension for both modes (3.7-3.8).

### Error Analysis

**flat_files — 6 questions with issues.** The dominant failure mode is the **sparse-checkout blindspot**. The architecture-context repo was sparse-cloned with only `rhoai-3.4-ea.2` and `rhoai.next`. When questions asked about content outside that checkout (all version directories, overlays), agents couldn't see the files and confidently declared they didn't exist. When files are present, grounding is near-perfect; when files are absent, agents assert absence rather than acknowledging uncertainty.

| Question | Score | Issue |
|----------|-------|-------|
| t4-001 | 1.8 | Found 2 of 24 version directories (only sparse-checked-out ones), claimed others don't exist |
| t4-004 | 2.4 | Claimed no overlays exist — files were outside sparse checkout |
| t3-009 | 3.4 | Misidentified kube-auth-proxy as Deployment instead of sidecar; cited right files, wrong conclusion |
| t2-002 | 3.8 | Found 2 of 3 ports, missed port 6379 |
| t2-008 | 3.8 | Semantic error: said mlflow "consumes" MLflowConfig when it "manages" it |
| t2-009 | 4.2 | Counted 5 API groups while listing 6 |

**arch_query — 18 questions with issues.** Three failure patterns:

1. **Over-extrapolation (false claims).** The CLI returns focused excerpts, and agents fill gaps with plausible but unverifiable details. t2-019 had 10 false claims, t2-016 had 6, t2-020 had 5 — all with correct core answers but fabricated architectural specifics.

2. **Weak grounding.** Agents cite "arch-query commands" generically instead of specific file paths and sections. Judges consistently score this 3/5 on grounding vs flat_files' typical 5/5.

3. **Same sparse-checkout blindspot.** t4-001 and t4-004 fail identically to flat_files — the underlying data is incomplete regardless of access method.

| Question | Score | False Claims | Issue |
|----------|-------|-------------|-------|
| t4-001 | 2.0 | 1 | Found 2 of 24 version directories (sparse checkout) |
| t3-009 | 2.6 | 1 | Same kube-auth-proxy sidecar misidentification as flat_files |
| t4-004 | 2.6 | 1 | Same overlay blindspot as flat_files |
| t4-005 | 3.0 | 0 | Asked for file path, gave CLI access method instead |
| t2-019 | 3.2 | 10 | Correct core purpose, 10 unsupported architecture assertions |
| t3-016 | 3.2 | 1 | Said vLLM and kserve don't interact; they do (vLLM runs inside kserve) |
| t2-001 | 3.4 | 2 | Found 5 of 7 ports, missed 8443 and 9081 |
| t2-003 | 3.4 | 2 | Found 8 of 12 ports, missed 4, added 2 not in ground truth |
| t2-002 | 3.6 | 0 | Missed port 6379 (same as flat_files) |
| t3-014 | 3.6 | 2 | Added Envoy ext_proc mechanism not in source |
| t2-004 | 3.8 | 0 | Found 4 of 5 ports, missed 3001 |
| t4-002 | 3.8 | 1 | Counted 71 component docs instead of 70 (included metadata file) |
| t2-016 | 3.8 | 6 | Correct core answer, 6 unsupported implementation details |

**Summary:** flat_files fails rarely but catastrophically (sparse checkout gaps). arch_query fails more often but more subtly (over-extrapolation, vague citations). Both share the same data-availability blindspot on Tier 4 questions that probe content outside the sparse checkout.

---

## Recommendation

**Use flat_files as the default for production workloads where answer quality matters.** The 0.3-point composite advantage and dramatically better grounding (fewer false claims, more precise citations) justify the 2x cost premium for tasks like bug analysis, RFE review, and strategy generation where incorrect information is costly.

**Consider arch_query for high-volume, cost-sensitive workloads** where approximate answers are acceptable — screening, triage, or first-pass filtering where a human reviews the output. At $0.09/answer vs $0.18, the savings compound at scale.

**Potential hybrid approach:** Use arch_query for initial discovery (identify relevant documents), then flat_files for deep analysis of those specific files. This would combine arch_query's token efficiency with flat_files' grounding precision. Not tested in this benchmark but a natural next step.
