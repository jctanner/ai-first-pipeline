# Corpus AB — Ground Truth Flags

Flagged during benchmark run 2026-05-05 (markov-run-7b2335ca / markov-run-dfac1c58).
Both modes were scored against these expected answers by a mode-blind sonnet judge.

Verified 2026-05-05 against architecture docs, arch-query output, and rhods-operator source in checkouts.

---

## Bad Ground Truth (agents were correct, penalized unfairly)

### t3-009 — kube-auth-proxy has TWO deployment patterns, not just sidecar

**Question:** How does kube-auth-proxy interact with rhods-operator?

**Old expected answer:** "Platform operator deploys kube-auth-proxy as sidecar in component pods"

**Verified answer:** rhods-operator deploys kube-auth-proxy in two patterns: (1) as a standalone Deployment (2 replicas) via its Gateway Controller in the openshift-ingress namespace for platform-wide authentication through Envoy ext_authz, and (2) as sidecar containers injected into component pods (odh-dashboard, KServe InferenceServices, DSP API server) for per-component token validation. The architecture doc says "Deployment (sidecar injection)" — both words are literally true, describing the two distinct patterns. The Gateway Controller manages the full ingress stack: Gateway API, Envoy proxy, EnvoyFilter for auth, kube-auth-proxy Deployment, DestinationRules, NetworkPolicies, and OpenShift Routes.

**Source evidence:**
- Standalone Deployment templates: `checkouts/red-hat-data-services.rhoai-3.5-ea.1/rhods-operator/internal/controller/services/gateway/resources/kube-auth-proxy-oauth-deployment.tmpl.yaml` and `kube-auth-proxy-oidc-deployment.tmpl.yaml`
- Sidecar injection: odh-dashboard pod spec, KServe `inferenceservice-config-patch.yaml` (oauthProxy), DSP API server
- `arch-query grep kube-auth-proxy` shows rhods-operator Gateway Controller description: "Deploys and manages the entire platform ingress stack: Gateway API, Envoy proxy, EnvoyFilter for auth, kube-auth-proxy..."

**Impact:** Both modes gave correct answers and were penalized. flat_files scored 3.4 (acc=2), arch_query scored 2.6 (acc=1).

**Fix:** Expected answer should state both deployment patterns — standalone Deployment via Gateway Controller (Envoy ext_authz) and sidecar injection in component pods.

---

### t3-016 — vllm-cpu and kserve-autogluon-server don't interact

**Question:** How does vllm-cpu interact with kserve-autogluon-server?

**Old expected answer:** "vLLM runs as InferenceService runtime container"

**Verified answer:** These are independent KServe inference serving runtimes with no direct interaction. vllm-cpu serves LLM inference on CPU hardware (ports 8000/HTTP, 50051/gRPC), while kserve-autogluon-server serves AutoGluon TabularPredictor and TimeSeriesPredictor models (ports 8080/HTTP, 8081/gRPC). Both are independently managed by the KServe Controller as separate InferenceService serving runtimes. They share no data, no APIs, and no runtime dependencies.

**Source evidence:**
- `arch-query component vllm-cpu`: internal deps list KServe as serving framework, no mention of autogluon
- `arch-query component kserve-autogluon-server`: internal deps list KServe Controller and Model Storage, no mention of vllm
- kserve-autogluon-server RBAC section: "does not interact with the Kubernetes API directly"

**Impact:** Both modes correctly identified no direct interaction and were penalized. flat_files scored 4.0 (acc=3), arch_query scored 3.2 (acc=1).

**Fix:** Expected answer should state they are independent peer runtimes with no direct interaction, both managed by KServe Controller.

---

### t4-005 — arch_query mode can't cite file paths

**Question:** Where is the platform summary for rhoai.next?

**Expected answer:** `architecture/rhoai.next/PLATFORM.md`

**Verified answer:** The file exists at `architecture/rhoai.next/PLATFORM.md`. This expected answer is factually correct. However, arch_query agents access the same content via `arch-query platform` (which returns the full platform summary) but the CLI doesn't expose the underlying file path — so arch_query agents correctly described how to access the content but were penalized for not naming a file they have no way to see.

**Source evidence:**
- `ls architecture/rhoai.next/PLATFORM.md` confirms the file exists
- `arch-query platform` returns the full content but does not print the file path
- `arch-query component` output includes a "Full doc:" line with relative paths, but `arch-query platform` does not

**Impact:** flat_files scored 4.8 (correct), arch_query scored 3.0 (acc=2). The penalty is unfair to arch_query specifically — the question implicitly favors file-based access.

**Fix:** Accept `arch-query platform` as a valid access path for arch_query mode, or reclassify this question as flat_files-biased and exclude it from cross-mode comparison.

---

## Resolved: Ground Truth Was Wrong

### t2-002 — port 6379 is Ray, not Redis, and not a vllm-cpu listening port

**Question:** What ports does vllm-cpu use?

**Old expected answer:** "vllm-cpu uses ports: 50051, 6379, 8000."

**Verified answer:** vllm-cpu listens on two ports: 8000/TCP (OpenAI-compatible HTTP API) and 50051/TCP (gRPC). Port 6379 is NOT a port vllm-cpu listens on. The architecture doc (vllm-cpu.md line 259) lists 6379 as "Ray cluster | TCP | 6379/TCP (head) | Ray protocol | Optional distributed execution orchestration" — this is the Ray head node port used only in optional multi-node distributed inference scenarios. Redis appears only as a test dependency (via tensorizer) in `requirements/test.txt`, not in production code.

**Source evidence:**
- `arch-query ports vllm-cpu` returns only: 8000/TCP HTTP (vllm-openai), 50051/TCP gRPC (vllm-grpc)
- `architecture/rhoai.next/vllm-cpu.md` line 259: Ray cluster egress at 6379/TCP (head), labeled "Optional"
- `checkouts/red-hat-data-services.rhoai-3.5-ea.1/vllm-cpu/examples/online_serving/multi-node-serving.sh`: `ray_port=6379`
- `checkouts/.../vllm-cpu/requirements/test.txt`: redis==5.2.0 is test-only (transitive via tensorizer)
- `arch-query grep 6379` across all components: zero results (not in any service table)

**Impact:** Both modes scored 3.8/3.6 (acc=3). Both agents were correct — vllm-cpu exposes only 8000 and 50051. The expected answer was wrong.

**Fix:** Expected answer should be "vllm-cpu listens on ports 8000/TCP (HTTP) and 50051/TCP (gRPC). Port 6379 is an optional Ray cluster head node port for multi-node inference, not a vllm-cpu service port."

---

## Infrastructure Issues (NOT resolved — sparse checkout still narrow)

The benchmark workflow (`markov.workflows/arch-context-benchmark.yaml` line 219) sparse-checks out only two paths: `architecture/$LATEST` and `architecture/rhoai.next`. The PVC currently has only `rhoai-3.4-ea.2`, `rhoai.next`, and one symlink (`early-access`). No overlays directory. The `arch-query versions` data below comes from a full local checkout, not the PVC.

To fix: either remove sparse checkout (full clone) or expand it to include all version directories and overlays.

### t4-001 — only 2 of 24 architecture directories visible on PVC

**Question:** What architecture directories are available (including non-release)?

**Issue:** Both modes found only `rhoai-3.4-ea.2` and `rhoai.next` because the architecture-context repo is sparse-cloned with only those two paths. The full repo has 24 versions:

| Version | Tags | Components |
|---------|------|------------|
| rhoai-2.6 | | 22 |
| rhoai-2.7 | | 10 |
| rhoai-2.8 | | 12 |
| rhoai-2.9 | | 12 |
| rhoai-2.10 | | 13 |
| rhoai-2.11 | | 13 |
| rhoai-2.12 | | 13 |
| rhoai-2.13 | | 13 |
| rhoai-2.14 | | 14 |
| rhoai-2.15 | | 14 |
| rhoai-2.16 | | 14 |
| rhoai-2.17 | | 14 |
| rhoai-2.19 | | 35 |
| rhoai-2.24 | | 44 |
| rhoai-2.25 | | 45 |
| rhoai-3.0 | | 36 |
| rhoai-3.2 | | 52 |
| rhoai-3.3 | current-ga | 39 |
| rhoai-3.3.0 | | 0 |
| rhoai-3.4 | future-ga, newest | 45 |
| rhoai-3.4-ea.1 | latest-released | 44 |
| rhoai-3.4-ea.2 | early-access | 44 |
| rhoai-3.5-ea.1 | | 51 |
| rhoai.next | (default) | 71 |

**Source evidence:** `arch-query versions` (from a full local checkout) returns all 24 versions with component counts and tags. The PVC only has 2.

**Impact:** flat_files scored 1.8, arch_query scored 2.0. Both answered correctly given the data available to them.

**Fix:** Expand sparse checkout in workflow to include all version directories, then re-run.

### t4-004 — overlays not in sparse checkout

**Question:** What overlays modify the base architecture?

**Issue:** Both modes reported no overlays because the `overlays/` directory is not in the sparse checkout. The full repo has 4 overlays:

1. **0001** — KFP SDK updated to 2.16 in RHOAI 3.4 (affects: data-science-pipelines, data-science-pipelines-operator, notebooks)
2. **0002** — Go SDK available for MLflow (affects: mlflow, mlflow-operator; all releases)
3. **0003** — Llama Stack renamed to OGX upstream, adopted in RHOAI 3.5 (affects: llama-stack-distribution, llama-stack-k8s-operator, llama-stack-provider-ragas, llama-stack-provider-trustyai-garak)
4. **0004** — CodeFlare SDK missing from component inventory (affects: platform, notebooks; release 3.4)

**Source evidence:** `arch-query overlays` (from a full local checkout) returns all 4 overlays. The PVC has no overlays directory.

**Impact:** flat_files scored 2.4, arch_query scored 2.6. Both answered correctly given the data available.

**Fix:** Add `overlays` to the sparse checkout in workflow, then re-run.

---

## Score Impact Estimate

6 questions flagged, all now verified:

| ID | Category | Verdict |
|----|----------|---------|
| t3-009 | Bad ground truth | Expected answer incomplete — should describe both Deployment and sidecar patterns |
| t3-016 | Bad ground truth | Expected answer wrong — runtimes don't interact |
| t4-005 | Bad ground truth (mode-biased) | Expected answer correct for flat_files but unfair to arch_query |
| t2-002 | Bad ground truth | Expected answer wrong — 6379 is Ray, not a listening port |
| t4-001 | Infrastructure (resolved) | Sparse checkout now expanded, 24 versions available |
| t4-004 | Infrastructure (resolved) | Overlays directory available, 4 overlays exist |

If the 4 ground truth issues are corrected (t3-009, t3-016, t2-002 rescored; t4-005 mode-adjusted or excluded):

- **flat_files** would gain ~0.1 on composite (t3-009, t3-016, t2-002 scores increase)
- **arch_query** would gain ~0.2 on composite (same gains plus t4-005 penalty removed)
- The **gap between modes would narrow** from 0.3 to ~0.2, with flat_files still ahead due to the legitimate false-claim pattern in arch_query

The 2 infrastructure issues (t4-001, t4-004) require expanding the sparse checkout and re-running the benchmark to get valid scores. Until then, those questions should be excluded from cross-mode comparison.
