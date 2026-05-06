# Corpus AB — Ground Truth Flags

Flagged during benchmark run 2026-05-05 (markov-run-7b2335ca / markov-run-dfac1c58).
Both modes were scored against these expected answers by a mode-blind sonnet judge.

---

## Bad Ground Truth (agents were correct, penalized unfairly)

### t3-009 — kube-auth-proxy is not a sidecar

**Question:** How does kube-auth-proxy interact with rhods-operator?

**Expected answer:** "Platform operator deploys kube-auth-proxy as sidecar in component pods"

**What's actually true:** kube-auth-proxy is deployed as a Deployment by rhods-operator's Gateway Controller. It is used by EnvoyFilter + ext_authz for authentication in the platform ingress stack. The source doc table says "Deployment (sidecar injection)" — the "(sidecar injection)" describes the auth injection pattern, not the pod topology. It also has an embedded kube-rbac-proxy entrypoint that will eventually be swapped with the actual kube-rbac-proxy project.

**Impact:** Both modes gave correct answers and were penalized. flat_files scored 3.4 (acc=2), arch_query scored 2.6 (acc=1).

**Fix:** Updated in corpus-AB-final.yaml. Expected answer should reference Deployment + EnvoyFilter ext_authz pattern.

---

### t3-016 — vllm-cpu and kserve-autogluon-server don't interact

**Question:** How does vllm-cpu interact with kserve-autogluon-server?

**Expected answer:** "vLLM runs as InferenceService runtime container"

**What's actually true:** These are independent KServe inference runtimes that serve different model types (LLMs vs AutoGluon tabular/time-series). They don't interact with each other — they both independently use KServe as their serving framework. The ground truth confuses "both use KServe" with "they interact with each other."

**Impact:** Both modes correctly identified no direct interaction and were penalized. flat_files scored 4.0 (acc=3), arch_query scored 3.2 (acc=1).

**Fix needed:** Expected answer should state they are independent peer runtimes with no direct interaction, both managed by KServe Controller.

---

### t4-005 — arch_query mode can't cite file paths

**Question:** Where is the platform summary for rhoai.next?

**Expected answer:** `architecture/rhoai.next/PLATFORM.md`

**What's actually true:** The ground truth is a file path. flat_files agents can discover and cite this path directly. arch_query agents access the same content via `arch-query platform` but the CLI doesn't expose the underlying file path — so the agent correctly described how to access it but was penalized for not naming a file it has no way to see.

**Impact:** flat_files scored 4.8 (correct), arch_query scored 3.0 (acc=2). The penalty is unfair to arch_query specifically — the question implicitly favors file-based access.

**Fix needed:** Either accept CLI access path as a valid answer for arch_query mode, or reclassify this question as flat_files-biased and exclude it from cross-mode comparison.

---

## Questionable Ground Truth (needs verification)

### t2-002 — does vllm-cpu actually use port 6379?

**Question:** What ports does vllm-cpu use?

**Expected answer:** "vllm-cpu uses ports: 50051, 6379, 8000."

**Both agents found:** 8000 (HTTP API) and 50051 (gRPC). Neither found 6379.

**Concern:** Port 6379 is Redis. If vllm-cpu uses Redis for caching, that may be an indirect dependency (a Redis instance it connects to) rather than a port vllm-cpu itself listens on. The source excerpt in the corpus only shows port 8000 endpoints — no mention of 6379. Both agents may be correct that vllm-cpu exposes only 8000 and 50051.

**Impact:** Both modes scored 3.8/3.6 (acc=3). If 6379 is not a vllm-cpu port, both should score higher.

**Fix needed:** Verify whether 6379 is a port vllm-cpu listens on, connects to, or neither.

---

## Infrastructure Issues (sparse checkout, not model errors)

### t4-001 — only 2 of 24 directories visible

**Question:** What architecture directories are available (including non-release)?

Both modes found only `rhoai-3.4-ea.2` and `rhoai.next` because the architecture-context repo was sparse-cloned with only those two paths. The other 22 directories exist in the full repo but weren't checked out.

**Impact:** flat_files scored 1.8, arch_query scored 2.0. Both answered correctly given the data available to them.

**Fix needed:** Either expand the sparse checkout to include all version directories, or mark this question as infrastructure-dependent and exclude from scoring.

### t4-004 — overlays not in sparse checkout

**Question:** What overlays modify the base architecture?

Both modes reported no overlays. The `overlays/` directory exists in the full repo but was not included in the sparse checkout.

**Impact:** flat_files scored 2.4, arch_query scored 2.6.

**Fix needed:** Same as t4-001 — expand sparse checkout or exclude from scoring.

---

## Score Impact Estimate

If the 3 bad ground truth questions (t3-009, t3-016, t4-005) and 2 infrastructure questions (t4-001, t4-004) were corrected or excluded:

- **flat_files** would gain ~0.1 on composite (t3-009 and t3-016 scores would increase; t4-001/t4-004 excluded)
- **arch_query** would gain ~0.2 on composite (larger penalties on t3-009, t3-016, t4-005)
- The **gap between modes would narrow** from 0.3 to ~0.2, with flat_files still ahead due to the legitimate false-claim pattern in arch_query
