# Token Usage & Cost Report

**Generated**: 2026-05-03
**Source**: Elasticsearch `mlflow-traces` index (9,260 traces across 1,000 issues)
**Total Spend**: $2,157.72
**Total Tokens**: 286,010,237

---

## Summary Statistics (per issue, summed across all traces)

| Metric | Total Tokens | Input Tokens | Output Tokens | Cost (USD) |
|--------|-------------|-------------|---------------|-----------|
| **Min** | 3,610 | 2,702 | 908 | $0.04 |
| **P25** | 47,681 | 38,866 | 8,335 | $0.40 |
| **Median** | 108,857 | 93,287 | 15,367 | $0.86 |
| **Mean** | 160,318 | 139,003 | 21,315 | $1.23 |
| **P75** | 256,244 | 221,454 | 33,617 | $1.95 |
| **P90** | 326,457 | 286,869 | 43,842 | $2.50 |
| **P95** | 369,542 | 323,224 | 48,510 | $2.85 |
| **Max** | 912,872 | 855,538 | 110,597 | $6.19 |
| **Std Dev** | 133,191 | 119,030 | 15,547 | $0.96 |

---

## Token Distribution (per issue)

```
         0-50K | ############################### 285
      50K-100K | ##################### 200
     100K-200K | ############ 115
     200K-400K | ######################################## 367
     400K-600K | ## 25
     600K-800K |  3
       800K-1M |  5
```

## Cost Distribution (per issue)

```
       $0-0.50 | ######################################## 353
       $0.50-1 | ################### 169
          $1-2 | ########################### 242
          $2-3 | ####################### 205
          $3-4 | ## 21
          $4-5 |  4
          $5-6 |  5
           $6+ |  1
```

---

## Breakdown by Category

All 1,000 issues fall into two categories: RHAIRFE (RFEs) and RHAISTRAT (Strategies). No RHOAIENG bug or epic traces are present in the current dataset.

### Cross-Category Comparison

| Category | Issues | Traces | Median Tokens | Median Cost | Total Cost | % of Spend |
|----------|--------|--------|--------------|------------|-----------|-----------|
| **RHAIRFE (RFEs)** | 545 | 2,655 | 48,862 | $0.42 | $272.89 | 22.2% |
| **RHAISTRAT (Strategies)** | 455 | 2,026 | 263,562 | $2.03 | $954.87 | 77.8% |

### RHAIRFE (RFEs) — 545 issues, 2,655 traces, $272.89 total

| Metric | Total Tokens | Input Tokens | Output Tokens | Cost (USD) |
|--------|-------------|-------------|---------------|-----------|
| **Min** | 3,610 | 2,702 | 908 | $0.04 |
| **P25** | 36,307 | 29,227 | 6,712 | $0.32 |
| **Median** | 48,862 | 40,830 | 8,656 | $0.42 |
| **Mean** | 60,559 | 50,651 | 9,908 | $0.50 |
| **P75** | 70,606 | 59,608 | 11,594 | $0.59 |
| **P90** | 102,859 | 90,688 | 14,997 | $0.81 |
| **P95** | 130,095 | 113,204 | 18,557 | $1.01 |
| **Max** | 466,547 | 396,838 | 82,409 | $3.73 |
| **Std Dev** | 45,070 | 39,083 | 6,736 | $0.35 |

```
Token Distribution (RFEs):
         0-50K | ############################## 285
      50K-100K | #################### 199
     100K-200K | ##### 51
     200K-400K |  9
     400K-600K |  1

Cost Distribution (RFEs):
       $0-0.50 | ############################## 353
       $0.50-1 | ############# 163
          $1-2 | ## 25
          $2-3 |  2
          $3-4 |  2
```

### RHAISTRAT (Strategies) — 455 issues, 2,026 traces, $954.87 total

| Metric | Total Tokens | Input Tokens | Output Tokens | Cost (USD) |
|--------|-------------|-------------|---------------|-----------|
| **Min** | 98,448 | 79,243 | 9,022 | $0.82 |
| **P25** | 218,591 | 192,955 | 26,838 | $1.65 |
| **Median** | 263,562 | 226,810 | 34,177 | $2.03 |
| **Mean** | 279,809 | 244,830 | 34,979 | $2.10 |
| **P75** | 316,639 | 277,493 | 42,495 | $2.40 |
| **P90** | 371,879 | 325,251 | 49,309 | $2.85 |
| **P95** | 425,432 | 377,960 | 53,720 | $3.10 |
| **Max** | 912,872 | 855,538 | 110,597 | $6.19 |
| **Std Dev** | 101,713 | 93,547 | 11,585 | $0.70 |

```
Token Distribution (Strategies):
      50K-100K |  1
     100K-200K | ##### 64
     200K-400K | ############################## 358
     400K-600K | ## 24
     600K-800K |  3
       800K-1M |  5

Cost Distribution (Strategies):
       $0.50-1 |  6
          $1-2 | ############################## 217
          $2-3 | ############################ 203
          $3-4 | ## 19
          $4-5 |  4
           $5+ |  6
```

---

## Top 3 Issues by Total Tokens

| Rank | Issue | Traces | Input Tokens | Output Tokens | Total Tokens | Cost (USD) |
|------|-------|--------|-------------|---------------|-------------|-----------|
| 1 | RHAISTRAT-17 | 36 | 855,538 | 57,334 | 912,872 | $5.71 |
| 2 | RHAISTRAT-19 | 36 | 831,154 | 53,325 | 884,479 | $5.49 |
| 3 | RHAISTRAT-13 | 35 | 818,046 | 59,738 | 877,784 | $5.58 |

## Top 3 Issues by Cost

| Rank | Issue | Traces | Input Tokens | Output Tokens | Total Tokens | Cost (USD) |
|------|-------|--------|-------------|---------------|-------------|-----------|
| 1 | RHAISTRAT-1 | 13 | 685,812 | 110,597 | 796,409 | $6.19 |
| 2 | RHAISTRAT-17 | 36 | 855,538 | 57,334 | 912,872 | $5.71 |
| 3 | RHAISTRAT-13 | 35 | 818,046 | 59,738 | 877,784 | $5.58 |

---

## Observations

- **Bimodal token distribution explained by category**: The two clusters map cleanly to issue type. The 0-100K cluster (485 issues) is almost entirely RFEs (median 49K tokens). The 200-400K cluster (367 issues) is strategies (median 264K tokens). The 100-200K dip is the gap between the two pipeline types.
- **Strategies dominate spend**: RHAISTRAT issues account for 77.8% of total cost ($955 of $1,228) despite being only 45.5% of issues. Each strategy invokes multiple review sub-skills (feasibility, testability, scope, architecture), driving 5x the median token usage vs. RFEs.
- **RFEs are cheap and predictable**: Tight distribution with std dev of $0.35 and 95% of RFEs costing under $1.01. The median RFE costs $0.42.
- **Right-skewed cost overall**: Mean ($1.23) is 43% above median ($0.86), pulled up by the strategy tail.
- **RHAISTRAT-1 is the costliest issue by dollar amount** ($6.19) despite having fewer total tokens than the top-3 by volume. It generated 110K output tokens (nearly 2x the next closest), and output tokens are priced higher. This issue was processed 13 times across Apr 20-26 during pipeline architecture iteration using the `strat-creator-fix` skill variant.
- **Only 6 issues exceeded $5**, and all are RHAISTRAT strategy issues.
- **No RHOAIENG bug traces** are present in the current Elasticsearch index — bug analysis phases either haven't been synced or haven't been run yet.
