# Architecture-Context A/B Benchmark — Implementation Plan

**Generated**: 2026-05-05
**Source**: `docs/arch-context-testing.md` (corpus tiers, judge rubric, MLflow structure)
**Reference**: `docs/arch-query-design.md` (arch-query CLI design, fallback detection)
**Integration**: Markov workflows + Claude Agent SDK

---

## Goal

Determine whether agents perform better when they consume architecture context as **raw flat files** from the architecture-context repo, or when they use the **`arch-query` CLI**.

The benchmark runs the same Tier 1–4 architecture question corpus in paired mode — `flat_files` vs `arch_query` — holding model, prompt, judge, and architecture-context commit constant. Only the access method differs.

---

## Architecture Overview

```
ES (mlflow-spans)
  │  extract scripts
  v
corpus.yaml (200 questions + ground truth)
  │
  │  markov run / local runner
  │
  ├──── context_mode=flat_files ────────────────────┐
  │  bench-answer-flat skill (x200, concurrency 5)  │
  │  allowed: Read, Glob, Grep on $ARCH_CONTEXT_DIR │
  │  answers/flat_files/{id}.json                    │
  │                                                  │
  ├──── context_mode=arch_query ────────────────────┐│
  │  bench-answer-query skill (x200, concurrency 5) ││
  │  allowed: Bash (arch-query only)                 ││
  │  answers/arch_query/{id}.json                    ││
  │                                                  ││
  ├──── judge (x400, concurrency 5) ────────────────┤│
  │  bench-judge skill (same for both modes)         ││
  │  judgments/{context_mode}/{id}.json              ││
  │                                                  ││
  v                                                  vv
aggregate_benchmark.py
  │  per-mode scores, cross-mode comparison, behavior metrics
  │  benchmark-summary.json + benchmark-summary.yaml
  v
quality gate (per-tier minimums per mode)
  │
  v
MLflow experiment: arch-context-access-benchmark
  │  paired runs: one per context_mode
```

---

## New Files

```
var/benchmarks/arch-context/
  corpus.yaml                              # Curated question corpus (~200 questions)
  raw/                                     # Intermediate ES extraction output (gitignored)

.claude/skills/
  bench-answer-flat/SKILL.md               # Answer agent: flat file access (Read/Glob/Grep)
  bench-answer-query/SKILL.md              # Answer agent: arch-query access (Bash only)
  bench-judge/SKILL.md                     # Judge agent (Read only, sonnet model)

scripts/
  extract_corpus_tier4.py                  # ES: failed path lookups → navigation questions
  extract_corpus_tier12.py                 # ES: absent components + successful reads
  extract_corpus_tier3.py                  # ES: architecture review cross-component queries
  build_corpus.py                          # Merge, dedup, normalize → corpus.yaml
  aggregate_benchmark.py                   # Per-mode scores, comparison, behavior metrics
  run_benchmark.py                         # Local runner (no K8s required)
  log_benchmark_to_mlflow.py               # MLflow experiment logging

markov.workflows/
  arch-context-benchmark.yaml              # Markov workflow for K8s paired-mode execution
```

## Modified Files

- `lib/schemas.py` — add `BENCH_ANSWER_SCHEMA`, `BENCH_JUDGE_SCHEMA`
- `pipeline-skills.yaml` — register `bench-answer-flat`, `bench-answer-query`, `bench-judge`
- `deploy/pipeline-agent/Dockerfile` — multi-stage build adds arch-query binary

---

## Component Details

### 1. Corpus Extraction Scripts

Follow the pattern of `scripts/sync_mlflow_to_elastic.py` (same ES client, env var config, CLI args).

**`scripts/extract_corpus_tier4.py`** — Queries `mlflow-spans` for `tool_Bash` spans with `architecture-context` in inputs and error patterns (`No such file`, `DIR NOT FOUND`, `cannot access`) in outputs. Normalizes paths (strip `./`, resolve symlinks, extract component name), deduplicates by `(component, error_type)`. Writes JSONL to `var/benchmarks/arch-context/raw/tier4-extracted.jsonl`.

**`scripts/extract_corpus_tier12.py`** — Two queries:
1. LLM spans with "absent from" / "not in the architecture" phrases → Tier 1 existence questions
2. `tool_Read` spans on architecture-context files without errors → Tier 2 fact-extraction questions

Deduplicates by `(component, fact_type)` to avoid redundant questions.

**`scripts/extract_corpus_tier3.py`** — Queries `tool_Skill` spans matching `architecture-review`, extracts claim-verification pairs from outputs → Tier 3 cross-component integration questions.

**`scripts/build_corpus.py`** — Reads all `raw/*.jsonl`, normalizes, deduplicates (>80% token overlap → keep most specific), validates `source_files` exist in `references/architecture-context/`, extracts `source_excerpt` (max 500 chars), assigns sequential IDs (`t1-001`, `t2-001`...), writes `corpus.yaml`.

Deduplication strategies (from design doc recommendations):
- Path normalization for Tier 4 (strip `./`, resolve symlinks)
- Component-name grouping for Tier 4 (different paths to same component = one question)
- `(component, fact)` dedup for Tier 2 (avoid many identical port/endpoint questions)

---

### 2. Corpus Format

The corpus is shared across both access modes. Questions are architecture questions — the access method is a runtime parameter, not a corpus concern.

```yaml
# var/benchmarks/arch-context/corpus.yaml
version: "1.0"
architecture_context_commit: "abc123"
generated_date: "2026-05-05"
target_version: "rhoai-3.4-ea.2"

questions:
  - id: "t1-001"
    tier: 1
    category: "inventory-lookup"
    question: "Is InstructLab a RHOAI component?"
    expected_answer: "No. InstructLab is a RHEL AI component."
    expected_answerable: false
    source_files: ["architecture/rhoai-3.4-ea.2/PLATFORM.md"]
    source_excerpt: "Component Count: 45 ... [InstructLab not listed]"
    tags: ["product-scope", "negative"]

  - id: "t2-001"
    tier: 2
    category: "fact-extraction"
    question: "What port does vLLM expose metrics on?"
    expected_answer: "Port 8000"
    expected_answerable: true
    source_files: ["architecture/rhoai-3.4-ea.2/vllm-cpu.md"]
    source_excerpt: "Metrics endpoint on port 8000..."
    tags: ["port", "metrics"]

  # ... ~200 total questions
```

**Schema per question:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique ID: `t{tier}-{seq}` (e.g., `t1-001`) |
| `tier` | integer (1-4) | yes | Evaluation tier |
| `category` | enum | yes | `inventory-lookup`, `fact-extraction`, `cross-component-integration`, `navigation` |
| `question` | string | yes | Question text |
| `expected_answer` | string | yes | Ground truth or "Not documented in architecture-context" |
| `expected_answerable` | boolean | yes | Whether the question is answerable from the docs |
| `source_files` | list[string] | yes | Relative paths within architecture-context |
| `source_excerpt` | string | yes | Relevant text from source file(s), max 500 chars |
| `tags` | list[string] | no | Freeform tags for filtering/grouping |

---

### 3. Paired Answer Skills

Two skill variants with different tool access. Both receive the same prompt structure and must produce the same output schema. The only difference is *how* the agent accesses architecture context.

#### 3a. `bench-answer-flat` — Flat File Access

**File**: `.claude/skills/bench-answer-flat/SKILL.md`

```yaml
---
name: bench-answer-flat
description: Answer architecture question using flat file access (Read/Glob/Grep)
allowed-tools: Read, Glob, Grep
---
```

**Instructions:**
- Agent receives `$QUESTION`, `$QUESTION_ID`, `$ARCH_CONTEXT_DIR`, `$OUTPUT_DIR`
- Use Read, Glob, Grep to explore `$ARCH_CONTEXT_DIR` and answer the question
- Navigate directory structure, read markdown docs, search for content
- If information is not documented, explicitly state "Not documented in the architecture-context"
- Cite specific file paths relative to architecture-context root
- Write result to `$OUTPUT_DIR/bench-answer.json`

#### 3b. `bench-answer-query` — arch-query Access

**File**: `.claude/skills/bench-answer-query/SKILL.md`

```yaml
---
name: bench-answer-query
description: Answer architecture question using arch-query CLI
allowed-tools: Bash
---
```

**Instructions:**
- Agent receives `$QUESTION`, `$QUESTION_ID`, `$ARCH_QUERY_BIN`, `$OUTPUT_DIR`
- Use `arch-query` subcommands to answer the question. Available subcommands:
  - `arch-query search <term>` — find components by name/purpose
  - `arch-query component <name>` — component fact sheet (CRDs, ports, deps)
  - `arch-query component <name> --raw` — full markdown doc
  - `arch-query exists <name>` — check if component exists in RHOAI inventory
  - `arch-query list` / `arch-query list --names-only` — list all components
  - `arch-query deps <name>` — dependency graph (forward + reverse)
  - `arch-query crds [component]` — CRD index
  - `arch-query ports [component]` — port index
  - `arch-query platform` — condensed platform summary
  - `arch-query overlays` — active overlays
  - `arch-query versions` — available versions with aliases
  - `arch-query diff <component> <ver-a> <ver-b>` — structured diff
  - `arch-query diff --all <ver-a> <ver-b>` — platform-wide diff
  - `arch-query grep <term>` — deep search across all parsed fields
  - `arch-query --version <ver> <subcommand>` — query a specific version
- Do NOT use Read, Glob, or Grep on architecture-context files directly
- Do NOT use `ls`, `cat`, `grep`, or `find` on the architecture-context directory
- Only use Bash to invoke `arch-query`
- If information is not found via arch-query, state "Not documented in the architecture-context"
- Write result to `$OUTPUT_DIR/bench-answer.json`

#### Shared Output Schema

Both skills produce identical JSON (`BENCH_ANSWER_SCHEMA` in `lib/schemas.py`):

```json
{
  "question_id": "t1-001",
  "question": "Is InstructLab a RHOAI component?",
  "answer": "No. InstructLab is not listed in the RHOAI component inventory.",
  "answerable": false,
  "sources_cited": [
    {
      "source": "arch-query exists InstructLab",
      "excerpt": "Not found in RHOAI component inventory."
    }
  ],
  "confidence": "high"
}
```

The `sources_cited[].source` field is flexible: for flat_files mode it contains a file path (`architecture/rhoai-3.4-ea.2/PLATFORM.md`), for arch_query mode it contains the command used (`arch-query exists InstructLab`). The `excerpt` field contains the relevant text from either source.

---

### 4. Judge Skill

**File**: `.claude/skills/bench-judge/SKILL.md`

One judge skill serves both modes. The judge is blind to access method — it evaluates answer quality against ground truth regardless of how the answer was obtained.

Uses **sonnet** model (different from the opus benchmark agent — avoids self-evaluation bias).

**Input**: question, agent answer (full JSON), ground truth answer, expected_answerable flag, source excerpts from corpus.

**Rubric dimensions** (1-5 each, from `docs/arch-context-testing.md`):
- **Accuracy** (weight 0.4): Does the answer match the docs?
- **Grounding** (weight 0.2): Does it cite specific sources?
- **Scope Awareness** (weight 0.2): Does it distinguish product boundaries?
- **Gap Acknowledgment** (weight 0.2): Does it handle missing info honestly?

**Additional counts** (integers, not scored):
- **`false_claims`**: Number of architecture assertions in the answer that are not supported by the ground truth or source docs
- **`missed_gaps`**: Number of known gaps (from corpus `expected_answerable=false` or `tags`) that the agent failed to surface

Composite: `(accuracy * 0.4) + (grounding * 0.2) + (scope * 0.2) + (gap * 0.2)`. Pass threshold: 3.0.

**Output schema** (`BENCH_JUDGE_SCHEMA` in `lib/schemas.py`):

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
    "accuracy": "Answer correctly identifies InstructLab as RHEL AI, not RHOAI ...",
    "grounding": "Cites arch-query exists output but not underlying doc ...",
    "scope_awareness": "Correctly distinguishes RHOAI from RHEL AI ...",
    "gap_acknowledgment": "N/A — question was answerable"
  }
}
```

---

### 5. Mode Enforcement & Fallback Detection

The A/B comparison is only valid if agents actually use their assigned access method. Mode enforcement operates at two levels:

#### Tool-Level Enforcement

| Mode | Allowed Tools | Blocked |
|------|--------------|---------|
| `flat_files` | Read, Glob, Grep | Bash |
| `arch_query` | Bash | Read, Glob, Grep |

The `allowed-tools` frontmatter in each SKILL.md controls this. The agent SDK enforces tool restrictions — the agent literally cannot call blocked tools.

#### Post-Run Fallback Detection

Even with Bash allowed in `arch_query` mode, an agent could use Bash to run `cat`, `ls`, or `grep` directly on architecture-context files instead of using `arch-query`. The aggregation script detects this:

1. Parse the agent's execution log for Bash tool calls
2. For each Bash call in `arch_query` mode, check if the command:
   - Contains paths matching `architecture-context/` or `$ARCH_CONTEXT_DIR`
   - Uses `cat`, `ls`, `find`, `grep`, `head`, `tail` on those paths
   - Does NOT start with `arch-query`
3. Flag `fallback_to_filesystem: true` on the answer record
4. Count `bash_navigation_calls` (non-arch-query Bash calls targeting architecture-context)

Fallback does not invalidate the run — it is logged as a behavior metric. A high fallback rate across questions indicates the skill prompt needs strengthening or arch-query is missing a capability the agent needs.

Reference: `docs/arch-query-design.md` lines 469-495 describe the fallback detection pattern and the 20% threshold for investigation.

---

### 6. Output Path Structure & Cache Keys

All outputs are keyed by `context_mode` to prevent cross-contamination between paired runs:

```
results/
  answers/
    flat_files/
      t1-001.json
      t1-002.json
      ...
    arch_query/
      t1-001.json
      t1-002.json
      ...
  judgments/
    flat_files/
      t1-001.json
      ...
    arch_query/
      t1-001.json
      ...
  benchmark-summary.json
  benchmark-summary.yaml
```

**Full cache key** (determines whether an existing result can be reused):

```
(question_id, context_mode, prompt_version, model, corpus_version,
 arch_context_commit, arch_query_version)
```

`arch_query_version` is null for `flat_files` mode. The `prompt_version` field is a hash of the SKILL.md content, so skill prompt changes invalidate cached results.

---

### 7. Metrics

#### Outcome Metrics (per question, from judge)

| Metric | Type | Source |
|--------|------|--------|
| `accuracy` | 1-5 | Judge rubric |
| `grounding` | 1-5 | Judge rubric |
| `scope_awareness` | 1-5 | Judge rubric |
| `gap_acknowledgment` | 1-5 | Judge rubric |
| `composite_score` | 1.0-5.0 | Weighted composite |
| `false_claims` | integer | Judge count |
| `missed_gaps` | integer | Judge count |

#### Behavior/Cost Metrics (per question, from agent traces)

| Metric | Type | Source |
|--------|------|--------|
| `total_tool_calls` | integer | Agent log: count all tool invocations |
| `arch_file_reads` | integer | Agent log: count Read/Glob/Grep calls on architecture-context paths |
| `bash_navigation_calls` | integer | Agent log: count Bash calls that are not `arch-query` but target architecture-context |
| `arch_query_calls` | integer | Agent log: count Bash calls starting with `arch-query` |
| `fallback_to_filesystem` | boolean | True if `bash_navigation_calls > 0` in `arch_query` mode |
| `arch_context_tokens_est` | integer | Estimated from tool call output lengths (architecture-context content only) |
| `latency_seconds` | float | Wall time from agent start to JSON output |
| `cost_estimate_usd` | float | From agent SDK token counts × model pricing |

---

### 8. Markov Workflow

**File**: `markov.workflows/arch-context-benchmark.yaml`

Follows the pattern of `markov.workflows/rfe-pipeline-with-gates.yaml`. The workflow runs both modes sequentially (flat_files first, then arch_query), then judges all answers, aggregates, and gates.

**Variables:**

```yaml
vars:
  corpus_path: "/app/artifacts/var/benchmarks/arch-context/corpus.yaml"
  arch_context_dir: "/app/.context/architecture-context"
  arch_query_bin: "/usr/local/bin/arch-query"
  results_dir: "/app/artifacts/var/benchmarks/arch-context/results"
  model: opus
  judge_model: sonnet
  mlflow_enabled: false
  context_modes: ["flat_files", "arch_query"]
```

**Rules (quality gate):**

| Rule | Salience | Condition | Action |
|------|----------|-----------|--------|
| `tier4_minimum_met` | 200 | Either mode's Tier 4 avg < 2.5 | pause — cascade concern |
| `any_tier_below_minimum` | 150 | Any mode's any tier avg < 2.0 | pause |
| `all_tiers_minimum_met` | 100 | All pass | continue |

**Workflow structure:**

```
main
  ├── load_corpus
  ├── record_context_version
  ├── run_paired_benchmarks (for_each: context_modes)
  │     └── run_single_mode
  │           ├── benchmark_all (for_each: questions, concurrency 5)
  │           │     └── benchmark-question
  │           │           ├── check_existing_answer
  │           │           └── run_benchmark_agent (bench-answer-flat or bench-answer-query)
  │           └── judge_all (for_each: questions, concurrency 5)
  │                 └── judge-answer
  │                       ├── check_existing_judgment
  │                       ├── load_answer
  │                       └── run_judge_agent (bench-judge)
  ├── aggregate_results
  ├── load_aggregates + set_tier_scores
  ├── benchmark_quality_gate
  └── mlflow_log (conditional)
```

The `run_paired_benchmarks` step fans out over `context_modes`. Each mode runs its full answer+judge cycle before the next mode starts (sequential between modes, parallel within each mode's questions). This ensures flat_files results are complete before arch_query starts, though the modes are independent and could run concurrently if capacity allows.

The `run_benchmark_agent` step selects the skill based on `context_mode`:
- `flat_files` → `bench-answer-flat`
- `arch_query` → `bench-answer-query`

Output paths include `context_mode`: `answers/{{ context_mode }}/{{ question_id }}.json`.

---

### 9. Aggregation Script

**File**: `scripts/aggregate_benchmark.py`

Pure Python (no LLM). Reads all `answers/{mode}/*.json` and `judgments/{mode}/*.json`, computes per-mode scores, then produces a cross-mode comparison.

**Output** (`benchmark-summary.json` and `benchmark-summary.yaml`):

```json
{
  "arch_context_commit": "abc123",
  "run_date": "2026-05-05T14:30:00Z",
  "corpus_version": "1.0",
  "agent_model": "claude-opus-4-6",
  "judge_model": "claude-sonnet-4-5",
  "prompt_version": "a1b2c3",

  "per_mode": {
    "flat_files": {
      "total_questions": 200,
      "total_answered": 198,
      "total_judged": 198,
      "composite_avg": 3.1,
      "per_tier": {
        "tier_1": {
          "count": 50,
          "composite_avg": 3.5,
          "accuracy_avg": 3.8,
          "grounding_avg": 3.2,
          "scope_awareness_avg": 3.6,
          "gap_acknowledgment_avg": 3.4,
          "false_claims_total": 3,
          "missed_gaps_total": 2
        }
      },
      "behavior": {
        "total_tool_calls_avg": 12.4,
        "arch_file_reads_avg": 8.2,
        "arch_query_calls_avg": 0,
        "bash_navigation_calls_avg": 0,
        "fallback_count": 0,
        "arch_context_tokens_est_avg": 28500,
        "latency_seconds_avg": 45.2,
        "cost_estimate_usd_total": 62.00
      }
    },
    "arch_query": {
      "...same structure..."
    }
  },

  "comparison": {
    "per_tier": {
      "tier_1": {
        "composite_delta": 0.3,
        "accuracy_delta": 0.2,
        "grounding_delta": 0.5,
        "scope_awareness_delta": 0.1,
        "gap_acknowledgment_delta": 0.1,
        "winner": "arch_query"
      }
    },
    "behavior_deltas": {
      "total_tool_calls_delta": -8.1,
      "arch_context_tokens_est_delta": -24000,
      "latency_seconds_delta": -22.5,
      "cost_estimate_usd_delta": -38.00,
      "fallback_rate": 0.05
    },
    "verdict": {
      "quality_winner": "arch_query",
      "quality_margin": 0.3,
      "efficiency_winner": "arch_query",
      "token_reduction_pct": 84,
      "cost_reduction_pct": 55,
      "summary": "arch_query matches or exceeds flat_files on answer quality (+0.3 composite) while reducing context tokens by 84% and cost by 55%. Fallback rate 5% (10/200 questions)."
    }
  },

  "per_question": ["..."],
  "failures": ["..."]
}
```

The `comparison` section is the primary output. It answers the question directly: which mode produces better answers, and at what cost?

The `verdict` is computed mechanically:
- `quality_winner`: mode with higher composite_avg (or "tie" if delta < 0.1)
- `efficiency_winner`: mode with lower cost_estimate_usd_total
- `token_reduction_pct`: `(flat_tokens - query_tokens) / flat_tokens * 100`
- `fallback_rate`: `fallback_count / total_questions` in arch_query mode

---

### 10. Local Runner

**File**: `scripts/run_benchmark.py`

For development without K8s. Uses `lib/agent_runner.run_agent()` directly with asyncio semaphore.

```bash
# Run both modes (default)
python scripts/run_benchmark.py \
  --corpus var/benchmarks/arch-context/corpus.yaml \
  --arch-context-dir references/architecture-context \
  --arch-query-bin /path/to/arch-query \
  --model opus \
  --judge-model sonnet \
  --output-dir var/benchmarks/arch-context/results/$(date +%Y%m%d) \
  [--mlflow] \
  [--concurrency 3] \
  [--tier 4]

# Run a single mode
python scripts/run_benchmark.py \
  --mode flat_files \
  ...

python scripts/run_benchmark.py \
  --mode arch_query \
  ...
```

The `--mode` flag controls which access mode to run. Without it, both modes run sequentially (flat_files then arch_query). The `--tier` flag filters to a single tier for development.

---

### 11. MLflow Integration

**File**: `scripts/log_benchmark_to_mlflow.py`

One experiment, two paired runs per benchmark execution.

- **Experiment**: `arch-context-access-benchmark`

**Shared params** (same across both runs in a pair):

| Param | Value |
|-------|-------|
| `corpus_version` | From `corpus.yaml` header |
| `architecture_context_commit` | `git rev-parse HEAD` in arch-context dir |
| `agent_model` | e.g., `claude-opus-4-6` |
| `judge_model` | e.g., `claude-sonnet-4-5` |
| `agent_prompt_version` | Hash of SKILL.md content |

**Differing params** (one run per mode):

| Param | `flat_files` run | `arch_query` run |
|-------|------------------|------------------|
| `context_mode` | `flat_files` | `arch_query` |
| `arch_query_version` | null | `git rev-parse HEAD` in arch-query repo |
| `context_source` | `filesystem` | `arch-query CLI` |

**Run names**: `flat_files-{commit_short}-{date}`, `arch_query-{commit_short}-{date}`

**Metrics per run**: `composite_avg`, `tier{1-4}_avg`, per-dimension per-tier averages, `false_claims_total`, `missed_gaps_total`, `total_tool_calls_avg`, `arch_context_tokens_est_avg`, `latency_seconds_avg`, `cost_estimate_usd_total`, `fallback_rate` (arch_query only).

**Artifacts**: `benchmark-summary.json` (includes comparison section).

---

### 12. What the Benchmark Needs from arch-query

arch-query exists at `/home/jtanner/workspace/github/jctanner.redhat/odh.architecture-context/src/arch-query/` and already implements 13 subcommands. The benchmark depends on these capabilities:

| Tier | Questions Need | arch-query Subcommands Used |
|------|---------------|----------------------------|
| Tier 1 (Inventory) | Component existence checks | `exists`, `list`, `search` |
| Tier 2 (Facts) | Port, CRD, dependency extraction | `component`, `crds`, `ports`, `deps` |
| Tier 3 (Integration) | Cross-component reasoning | `deps`, `component` (multiple), `grep`, `diff` |
| Tier 4 (Navigation) | Version discovery, directory structure | `versions`, `list`, `platform` |

**Current arch-query gaps relevant to the benchmark:**
- No `--json` output flag — agents parse human-readable tabwriter output. Not a blocker (agents handle text well in traces), but structured output would improve grounding scores.
- No usage logging — the benchmark extracts behavior metrics from agent execution logs, not from arch-query itself. If arch-query adds usage logging later (as described in `docs/arch-query-design.md` line 471), the aggregation script can incorporate it.
- No cache — each `arch-query` call re-parses markdown. Acceptable for benchmark (200 questions × ~3 calls each = ~600 invocations), but noticeable in latency metrics.

The benchmark does not implement arch-query or depend on any changes to it. It uses arch-query as-is.

---

### 13. Container Setup

The benchmark runs in K8s pods using the `pipeline-agent` image. Two things must be available inside the container:

#### arch-query Binary

Built via **multi-stage Dockerfile** (`deploy/pipeline-agent/Dockerfile`):

```dockerfile
# Stage 1: Build arch-query
FROM golang:1.24-bookworm AS arch-query-builder
WORKDIR /build
RUN git clone --depth 1 https://github.com/opendatahub-io/architecture-context.git && \
    cd architecture-context/src/arch-query && \
    go build -o /build/arch-query .

# Stage 2: Copy into final image
COPY --from=arch-query-builder /build/arch-query /usr/local/bin/arch-query
```

This bakes the binary into the image at build time. The binary is ~15MB (static Go), adds no runtime dependencies, and the Go toolchain is discarded in the build stage. To update arch-query, rebuild the image.

At runtime, arch-query requires `--base-dir` pointing to the architecture docs. The workflow var `arch_query_base_dir` provides this: `/app/.context/architecture-context/architecture`. The `ARCH_QUERY_BIN` var passed to the skill includes the `--base-dir` flag so the agent uses it as a prefix.

#### Architecture-Context Docs

Cloned at runtime by the workflow's `setup_context` step (same sparse-checkout pattern as `checkouts/rfe-creator/scripts/fetch-architecture-context.sh`):

1. Sparse clone from `opendatahub-io/architecture-context` into `/app/.context/architecture-context/` (on the `pipeline-context` PVC)
2. Sparse-checkout set to `architecture/$LATEST` and `architecture/rhoai.next`
3. Commit SHA recorded as `arch_context_version` for cache keying and MLflow tags

The `pipeline-context` PVC is mounted at `/app/.context` in all agent_job pods. The setup step runs once in the main workflow before any benchmark agents, so all pods see the same clone.

If architecture-context is already present on the PVC (from a previous workflow run or manual population), the setup step pulls updates rather than re-cloning.

---

## Implementation Order

| Phase | Work | Dependencies | Testable With |
|-------|------|-------------|---------------|
| 1 | Corpus extraction scripts | ES access | Run against production ES, inspect JSONL |
| 2 | Schemas + skill registration | None | Schema unit tests |
| 3 | SKILL.md files (bench-answer-flat, bench-answer-query, bench-judge) | Phase 2 | `claude -p` with 5 sample questions per mode |
| 4 | Local runner + aggregation | Phases 2-3, hand-written 10-question corpus | `run_benchmark.py --tier 1 --concurrency 1` |
| 5 | MLflow logging | Phase 4 | Check experiment in MLflow UI |
| 6 | Markov workflow | Phases 2-4, K8s cluster | `markov run --dry-run`, then live 5-question subset |

Each phase is independently testable. Phase 1 requires ES access. Phases 2-4 can run locally with a hand-written 10-question corpus. Phase 6 requires K8s.

---

## Cost Estimate

200 questions × 2 modes × (1 answer agent + 1 judge) = 800 Claude API calls per full benchmark run.

| Component | Model | Calls | Est. Cost/Call | Total |
|-----------|-------|-------|---------------|-------|
| bench-answer-flat | Opus | 200 | ~$0.30 | ~$60 |
| bench-answer-query | Opus | 200 | ~$0.20 | ~$40 |
| bench-judge | Sonnet | 400 | ~$0.05 | ~$20 |
| **Total per run** | | **800** | | **~$120** |

arch_query answers are estimated cheaper per-call because the agent consumes fewer context tokens (~50 lines per `arch-query component` vs ~300 lines per full doc read).

The `--mode`, `--tier`, and Markov `--var` overrides allow running subsets during development.

---

## Verification

- **Corpus extraction**: Run each `extract_corpus_*.py` against ES, verify JSONL output has expected fields and no duplicates after `build_corpus.py`
- **Skills**: Test each skill variant with `claude -p` against 5 sample questions, validate output JSON against `BENCH_ANSWER_SCHEMA`
- **Mode enforcement**: Run bench-answer-query on 5 questions, verify no Read/Glob/Grep spans appear in agent logs; run bench-answer-flat, verify no Bash spans
- **Fallback detection**: Manually inject a `cat architecture-context/...` call into an arch_query mode log, verify aggregation flags `fallback_to_filesystem: true`
- **Local runner**: `python scripts/run_benchmark.py --corpus var/benchmarks/arch-context/corpus.yaml --tier 1 --concurrency 1` with both modes
- **Aggregation**: Verify per-mode averages match hand-calculated values; verify comparison deltas are correct
- **Markov**: `markov run markov.workflows/arch-context-benchmark.yaml --dry-run` for YAML validation, then live paired run with 5-question subset
- **MLflow**: Check experiment `arch-context-access-benchmark` has two paired runs with correct shared/differing params
- **Quality gate**: Manually set a tier avg to 1.5 in summary YAML, verify gate pauses

---

## Key Risks

| Risk | Mitigation |
|------|-----------|
| Agent in arch_query mode falls back to filesystem | Tool-level enforcement (Bash only, no Read/Glob/Grep) + post-run fallback detection from agent logs |
| Agent in arch_query mode uses Bash to `cat`/`grep` arch-context files directly | Skill prompt explicitly prohibits it; fallback detection flags `bash_navigation_calls > 0`; metric logged but run not invalidated |
| arch-query doesn't cover a question type (e.g., Tier 3 cross-component) | Agent can compose multiple `arch-query` calls; `component --raw` provides full doc as escape hatch; compare tool_calls count to see where arch-query is insufficient |
| Judge bias toward one mode's citation style | Judge is blind to access method — receives answer text and ground truth only, no mode label |
| Paired runs not comparable due to different prompt versions | Cache key includes `prompt_version` (hash of SKILL.md); both skills share identical answer instructions, differing only in tool access |
| Cost doubles vs single-mode benchmark | `--mode` flag allows running one mode at a time; `--tier` flag for subset runs |
| arch-query latency inflates arch_query mode's latency_seconds | Separate `arch_query_calls` count from quality metrics; latency is a behavior metric, not a quality metric |
