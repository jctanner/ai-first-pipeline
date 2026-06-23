# Architecture-Context Bugs & Gaps

**Generated**: 2026-05-03
**Source**: Elasticsearch `mlflow-spans` and `mlflow-traces` indices (9,260 traces, 102K+ spans)
**Scope**: Issues where agents encountered errors or flagged missing information in `.context/architecture-context/`

---

## 1. Broken Symlinks (Structural Bug)

The `fetch-architecture-context.sh` bootstrap script performs a sparse checkout of a single version directory (`rhoai-3.4-ea.2`). The upstream repo contains symlinks for convenience aliases (`current-ga`, `newest`, etc.), but their targets were not included in the sparse checkout. The symlinks exist on disk but resolve to nothing.

### Current State

| Symlink | Target | Status |
|---------|--------|--------|
| `early-access` | `rhoai-3.4-ea.2` | OK |
| `current-ga` | `rhoai-3.3` | **BROKEN** — target not cloned |
| `latest-released` | `rhoai-3.4-ea.1` | **BROKEN** — target not cloned |
| `newest` | `rhoai-3.4` | **BROKEN** — target not cloned |
| `future-ga` | `rhoai-3.4` | **BROKEN** — target not cloned |

### Impact

- **142 "file not found" errors across 121 unique issues** (26.6% of all RHAISTRAT issues)
- Agents tried the broken paths in this frequency:

| Path Attempted | Failures |
|----------------|----------|
| `architecture/rhoai-3.4-ea.2/components/` (subdirectory) | 53 |
| `architecture/newest/` | 33 |
| `architecture/current-ga/` | 30 |
| `architecture/latest-released/` | 12 |
| `architecture/rhoai-3.4/` | 4 |
| `architecture/future-ga/` | 2 |

Note: The 53 failures on `rhoai-3.4-ea.2/components/` indicate agents tried a `components/` subdirectory that doesn't exist — the component docs live directly in the version directory, not in a `components/` subfolder.

### Suggested Fix

Either expand the sparse checkout to include all symlink targets, or have the bootstrap script resolve symlinks and replace them with copies/additional sparse-checkout paths after cloning.

---

## 2. Components Missing from the Inventory

Agents flagged these components/technologies as absent from `PLATFORM.md` (the 45-component RHOAI inventory) or lacking dedicated component docs. Findings are extracted from LLM span outputs across 42 spans in 46 issues.

### Components Referenced in Strategies but Not in Architecture Context

| Component | Issues | Category |
|-----------|--------|----------|
| **InstructLab** | RHAISTRAT-829, RHAIRFE-54 | RHEL AI component, not RHOAI — but strategies reference it without disambiguation |
| **SDG Hub** | RHAISTRAT-71, RHAISTRAT-726 | Not in the 45-component inventory; SDG framework extension points undocumented |
| **CodeFlare SDK** | RHAIRFE-1572 | Absent from 3.4-ea.2 inventory; overlay `0004` acknowledges this gap |
| **ai-gateway-payload-processing** | RHAISTRAT-433, RHAISTRAT-443 | No component doc exists for this repository |
| **Kagenti** | RHAISTRAT-413 | Not in architecture context |
| **Docling** | RHAISTRAT-413 | Not in architecture context |
| **AlertmanagerConfig CRD** | RHAISTRAT-410 | Absent from entire context; `rhods-operator` has no RBAC for it |
| **BBR/vSR** | RHAIRFE-1407, RHAISTRAT-443 | Not in RHOAI architecture inventory |
| **vLLM-Omni** | RHAIRFE-1711 | Not in component inventory |
| **ITS/its-hub** | RHAISTRAT-33, RHAIRFE-1085 | Not in 3.4 architecture inventory |
| **RHAIIS tooling** | RHAISTRAT-658 | Architecture docs cover OCP-based RHOAI only; RHAIIS deployment tooling undocumented |
| **Node Feature Discovery (NFD)** | RHAISTRAT-252 | Referenced in strategy dependencies but not in architecture analysis |
| **Limitador** | RHAISTRAT-525 | Custom integration pattern not documented |

### Interpretation

These fall into three buckets:

1. **Wrong product scope** (InstructLab, RHAIIS) — These belong to RHEL AI or other products. Architecture-context only covers RHOAI. Agents need clearer guidance on product boundaries.
2. **Genuinely missing** (SDG Hub, ai-gateway-payload-processing, Kagenti, Docling, AlertmanagerConfig) — Components that exist in the codebase or are referenced in RFEs but have no architecture doc.
3. **Known gaps with overlays** (CodeFlare SDK) — Already tracked via overlay `0004-codeflare-sdk-missing-from-component-inventory.md`, but the component doc itself is still absent.

---

## 3. Undocumented APIs, Behaviors, and Concepts

Agents found features, APIs, or architectural concepts referenced in strategies that are not covered in the corresponding component docs.

| What's Missing | Component Doc | Issues | Detail |
|----------------|---------------|--------|--------|
| `trustyai_eval` / `trustyai_safety` metric families | `trustyai-explainability.md` | RHAISTRAT-662 | Metric families not documented; strategy assumes their existence |
| OGX post-training API | `llama-stack-distribution.md` | RHAISTRAT-808 | API exists upstream but not in RHOAI distribution config |
| Argo workflow scheduling mechanisms | `argo-workflows.md` | RHAISTRAT-680 | Strategy proposes Argo mechanisms not documented in platform architecture |
| `autolog()` integration patterns | `mlflow.md` | RHAISTRAT-141 | Flagged as open question, absent from acceptance criteria |
| Environment Card concept | `eval-hub.md` | RHAISTRAT-210 | Referenced 8+ times in strategy, absent from eval-hub v0.2.0 docs |
| kfp-driver internal behavior | `data-science-pipelines.md` | RHAISTRAT-153 | Not documented; must be validated empirically |
| `odh-model-controller` Jobs RBAC | `odh-model-controller.md` | RHAISTRAT-124 | ClusterRole covers configmaps, secrets, services, pods, routes — but not Jobs |
| Per-tool-call span metadata | (observability) | RHAISTRAT-455 | Granularity not documented; flagged as "needs validation" |
| Subscription-manager cert signing | (platform) | RHAISTRAT-122 | Different auth model not documented in platform architecture |

---

## 4. Summary

| Category | Count | Impact |
|----------|-------|--------|
| Broken symlink path errors | 142 spans / 121 issues | Agents fail to read architecture docs via convenience aliases, fall back to direct paths or proceed without context |
| Missing component docs | 13 components / 46 issues | Strategies referencing undocumented components cannot be fully validated against architecture |
| Undocumented APIs/behaviors | 9 findings | Strategies make assumptions about component capabilities that can't be verified from docs |

### Recommended Actions

1. **Fix sparse checkout** — Expand `fetch-architecture-context.sh` to include symlink targets or resolve them post-clone. This eliminates 142 errors across 121 issues.
2. **Add a `components/` directory note** — 53 errors came from agents looking for `rhoai-3.4-ea.2/components/`. A `README.md` or directory structure convention note would prevent this.
3. **Triage missing components** — Determine which of the 13 missing components should have docs (genuinely in RHOAI scope) vs. which are out-of-scope (RHEL AI, upstream-only).
4. **Update component docs for undocumented APIs** — The 9 API/behavior gaps represent real documentation debt that affects strategy review quality.
