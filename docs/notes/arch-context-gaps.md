# Architecture-Context Improvement Report

**Date:** 2026-04-28
**Source repo:** https://github.com/opendatahub-io/architecture-context
**Corpus analyzed:** ~1,186 security reviews, ~831 RFE reviews, ~250 strategy reviews, 41,578 workflow steps, 80 strategy-refine jobs

---

## Critical: Infrastructure Issue

**80 strategy-refine jobs ran with ZERO architecture context** because of dangling symlinks in the repo:

- `current-ga` -> `rhoai-3.3` (doesn't exist)
- `future-ga` -> `rhoai-3.4` (doesn't exist)
- `latest-released` -> `rhoai-3.4-ea.1` (doesn't exist)

Only `rhoai-3.4-ea.2` exists on disk. These 80 RHAISTRAT jobs (182-377) produced degraded output and should be re-run once fixed.

---

## 1. Missing Components (no .md doc at all)

| Component | Evidence | Priority |
|-----------|----------|----------|
| **vllm-cuda** | 80 references across strat-reviews; most frequent single gap | P0 |
| **vllm-rocm** | 49 references; AMD inference runtime | P0 |
| **vllm-spyre** | 14 references; IBM Spyre accelerator | P1 |
| **AutoRAG backend** | UI plugin exists (port 8743), engine undocumented; 4 RFEs blocked | P1 |
| **AutoML backend** | UI plugin exists (port 8643), no backend docs; 2 RFEs blocked | P1 |
| **Docling** | Assumed shipped but not in 45-component inventory; 2 RFEs | P1 |
| **MCP Gateway / VirtualMCPServer CRD** | CRD not documented; 2 RFEs | P2 |
| **ITS / its-hub** | Inference-time scaling; not in inventory | P2 |
| **CLEAR / EvalHub Contrib** | Not in inventory | P2 |
| **LLM Compressor pipeline** | Referenced in RFEs, not documented | P2 |
| **Perses / Tempo / OpenTelemetry** | Referenced in security reviews, no context | P2 |
| **Limitador / Kuadrant AuthPolicy internals** | Security reviews couldn't assess | P2 |

143 combined strat-review references to undocumented vLLM variants alone. 15% of security reviews had `architecture_context_consulted: []` -- zero docs to work with.

---

## 2. Missing Sections in Existing Component Docs

93% of security reviews (229/245) flagged "Missing Context" even for well-documented components. The following standardized sections should be added to every component doc:

| Section Needed | Frequency Flagged | What to Document |
|---------------|-------------------|------------------|
| **RBAC specifics** | 98 mentions | Exact ClusterRole/Role permissions, verb mappings, namespace vs. cluster scope |
| **Input validation** | 93 mentions | Schema enforcement, webhook failurePolicy values, admission control |
| **TLS configuration** | 67 mentions | Inter-pod TLS, port-level encryption, FIPS cipher suites |
| **Credential handling** | 65 mentions | Delivery mechanism, rotation policy, storage backend |
| **Authentication flow** | 61 mentions | Header propagation, token forwarding per endpoint |
| **Injection surface** | 43 mentions | PromQL/SQL/log injection vectors, sanitization behavior |
| **NetworkPolicy posture** | 40 mentions | Default-deny or open, per-component policy coverage |
| **ServiceAccount scope** | 38 mentions | Exact SA permissions, namespace scoping |
| **FIPS compliance** | 36 mentions | Crypto library, TLS profile compliance |
| **Supply chain** | 28 mentions | Build pipeline, dependency pinning, image signing |
| **Multi-tenancy model** | 20 mentions | Single-tenant vs. multi-tenant intent per component |

---

## 3. Specific Factual Errors / Inconsistencies

| Issue | Details |
|-------|---------|
| **Port conflict: eval-hub** | Shows 8080 in its own doc vs. 8443 in PLATFORM.md |
| **Dashboard RBAC stale** | `rhods-dashboard` ClusterRole lacks `llminferenceservices` permissions (confirmed factual error in RHAISTRAT-42) |
| **Dashboard RBAC missing new CRDs** | No permissions listed for Kueue, MaaS, CONNLINK, TrainJob/PyTorchJob, LocalModelCache CRDs |
| **vllm-cpu missing endpoints** | `/v1/unload_lora_adapter` not in the 27 documented endpoints |
| **llm-d-inference-scheduler** | "LoRA affinity scoring" plugin referenced in strategies but not in documented plugin list |
| **eval-hub metric polarity** | higher-is-better vs. lower-is-better metadata not mentioned anywhere |
| **eval-hub-ui BFF layer** | Architecture doc confirms the plugin on port 8543 but does not state whether it runs a Node.js BFF or only serves static assets |

---

## 4. Cross-Product Scope Gap

The architecture-context covers RHOAI only. RFEs that span RHELAI and RHAIIS explicitly note: "the RHELAI and RHAIIS dimensions are outside the available architecture context." As the product portfolio grows, this becomes a larger blind spot.

---

## 5. GPU/Accelerator Coverage Gap

162 NVIDIA, 102 AMD, and 78 RDMA references across strategy reviews, but the architecture-context primarily documents CPU variants. Any strategy involving GPU inference, multi-GPU, or hardware-specific features hits a documentation wall.

---

## Recommended Action Priority

1. **Fix dangling symlinks** -- populate `rhoai-3.3`, `rhoai-3.4`, `rhoai-3.4-ea.1` or update symlinks to point to `rhoai-3.4-ea.2`. Re-run 80 affected strategy-refine jobs.
2. **Add vllm-cuda.md and vllm-rocm.md** -- highest-impact single additions (129 combined references).
3. **Add standardized "Security Posture" section** to all 48 existing component docs covering: RBAC, TLS, credentials, NetworkPolicy, multi-tenancy, supply chain.
4. **Add AutoRAG/AutoML backend docs** -- UI plugins exist but backend architecture is invisible.
5. **Fix port/RBAC inconsistencies** -- eval-hub port conflict, dashboard ClusterRole staleness.
6. **Document incoming components** -- Docling, MCP Gateway, CLEAR, ITS, LLM Compressor.
7. **Consider RHELAI/RHAIIS context** -- at minimum, document product boundary and cross-product integration points.

---

## 2026-05-03: Agent Usage Pattern Analysis

**Source**: Elasticsearch `mlflow-spans` index — 15,696 tool call spans (8,327 `tool_Read` + 7,369 `tool_Bash`) touching architecture-context across 2,000 traces and 919 unique issues. Data queried from the `ai-pipeline` cluster's Elasticsearch instance via `kubectl exec`.

This section analyzes *how agents consume* architecture-context, not just what's missing from it. The findings below complement the content gaps documented above with quantified usage patterns.

### Corpus Stats

- 71 markdown files, 22,154 lines, 1.3MB total
- `PLATFORM.md`: 870 lines (the single most-read file)
- Typical component doc: 280-415 lines
- 45+ component docs in `rhoai-3.4-ea.2/`, 4 overlay docs

### Navigation Overhead

**54% of all architecture-context tool calls are navigation, not reading content.**

| Metric | Value |
|--------|-------|
| Total Read spans (content consumption) | 8,327 |
| Total Bash spans (navigation: `ls`, `find`, `grep` for filenames) | 7,369 |
| Navigation as % of all tool calls | 54.1% (mean), 50.0% (median) |
| Traces with >50% navigation | 777 / 2,000 (39%) |
| Traces with ONLY navigation (0 successful reads) | 399 / 2,000 (20%) |

One in five traces that attempt to use architecture-context **never successfully read a single file**. These agents spend all their tool calls navigating broken symlinks, trying non-existent paths like `components/`, or failing to locate the version directory, then proceed without architecture context.

### The 6-Step Access Pattern

Every trace follows a nearly identical sequence. Sampled from 3 representative traces:

```
1. Bash: ls .context/architecture-context/          // check existence
2. Bash: ls architecture/ | grep rhoai              // find version directory
   (often tries newest/, current-ga/ first — broken symlinks → retry)
3. Read: PLATFORM.md                                // read full 870-line inventory
4. Bash: ls rhoai-3.4-ea.2/ | grep -i <component>  // find relevant docs
5. Read: 2-5 component docs (~300 lines each)       // read full docs
6. Bash: ls overlays/ ; Read overlays               // check modifications
```

Steps 1-2 and 4 are pure discovery overhead. Step 3 reads 870 lines every time, though agents typically need only the component inventory table and the functional domains table.

### Files Read Per Trace

| Metric | Value |
|--------|-------|
| Min | 1 |
| P25 | 4 |
| Median | 5 |
| Mean | 5.2 |
| P75 | 7 |
| P90 | 8 |
| Max | 16 |

Distribution: 1-2 files (165 traces), 3-5 files (769), 6-10 files (645), 11-20 files (27).

### Most-Read Files

Top 10 files by read frequency (sampled from 500 Read spans):

| File | Reads | Lines |
|------|-------|-------|
| `PLATFORM.md` | 97 | 870 |
| `odh-dashboard.md` | 53 | 415 |
| `0001-kfp-sdk-2.16-in-rhoai-3.4.md` (overlay) | 50 | — |
| `kserve.md` | 32 | 336 |
| `notebooks.md` | 19 | 300 |
| `rhods-operator.md` | 19 | 342 |
| `RHOAI-Build-Config.md` | 14 | — |
| `vllm-cpu.md` | 14 | 288 |
| `llama-stack-distribution.md` | 13 | 283 |
| `trainer.md` | 12 | 317 |

`PLATFORM.md` is read in ~19% of all sampled Read spans. `odh-dashboard.md` is the most-read component doc.

### Component Search Terms

When agents run `ls | grep` to find relevant component docs, these are the most common search terms:

```
 21x  rhoai           (finding the version directory)
  8x  vllm
  6x  kueue           (no doc exists — always fails)
  3x  trusty
  3x  dash / dashboard
  3x  model
  2x  notebook, eval, instruct, codeflare
```

Agents searching for `kueue` (6 times) never find a doc — it's managed by the `rhods-operator` but has no standalone component doc, so the search always fails silently.

### What Agents Extract vs. What They Read

A typical component doc like `kserve.md` (336 lines) contains:
- Metadata block (~20 lines)
- Purpose section (~15 lines of prose)
- Architecture components table (~15 lines)
- CRDs table (~15 lines) — **frequently extracted**
- HTTP endpoints table (~10 lines) — **frequently extracted**
- Dependencies list (~10 lines) — **frequently extracted**
- Configuration details (~100 lines)
- Build/deployment details (~80 lines)
- Detailed prose (~70 lines)

Agents typically extract the CRDs, ports, dependencies, and purpose — roughly **50-60 lines of structured data** out of a 300+ line document. The remaining ~250 lines (configuration details, build info, detailed prose) are read but rarely referenced in the agent's output.

### Estimated Token Cost

- Median trace reads PLATFORM.md (870 lines) + 4 component docs (~300 lines each) + overlay checks = **~2,100 lines of content**
- At roughly 1.5 tokens per line of markdown, that's **~30-40K input tokens per trace** consumed by architecture-context alone
- Across 8,327 Read spans, the estimated total architecture-context input token consumption is **~25-35M tokens** (roughly 10-12% of the pipeline's total 286M input tokens)
- Navigation Bash spans add additional token overhead from `ls` output, error messages, and retries

### Implications for Format

The current format — a directory of auto-generated markdown files — forces every agent into the same expensive discovery loop. The data suggests three specific optimizations:

1. **Eliminate navigation** — A structured index file (JSON/YAML) mapping component names to key facts (CRDs, ports, dependencies, API groups) would replace steps 1-4 of the access pattern with a single Read. Agents would only read full component docs when they need prose-level detail.

2. **Reduce PLATFORM.md reads** — PLATFORM.md is 870 lines but agents primarily need the component inventory table and functional domains table (~80 lines). A condensed version or a machine-readable component list would cut 90% of the most-frequently-read file.

3. **Fix the `components/` convention** — 53 Bash errors came from agents trying `rhoai-3.4-ea.2/components/` (a subdirectory that doesn't exist). Component docs live directly in the version directory. A `components/` symlink or a note in the README would eliminate this.
