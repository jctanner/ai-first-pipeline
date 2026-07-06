# Plan: Observability Demo — RFE-to-Strategy with Claim Analysis

## Goal

Demonstrate the full pipeline observability stack — from RFE creation through strategy generation to claim extraction, verification, and remediation — using the existing dashboard agent runner and Observatory. Unlike the skill-factory demo (which focuses on agents building their own skills), this demo focuses on **tracing, evaluating, and improving** agent output quality through the claim analysis loop.

The demo is a linear pipeline with a feedback tail: steps 1–4 produce artifacts, steps 5–7 analyze those artifacts for hallucinations, and step 8 turns refuted claims into actionable fixes for architecture-context docs and skill prompts.

## Context

The pipeline already has all the pieces — RFE skills (`opendatahub-io/rfe-creator`), strategy skills (`opendatahub-io/strat-creator`), claim analysis skills (`extract-claims`, `verify-claims`, `explain-claims`), and the observability stack (strace, OTEL, MLflow, Observatory). This demo wires them into a single end-to-end flow and shows that the platform can detect its own mistakes and file tickets to fix them.

## Prerequisites

- K8s stack running (all services healthy)
- Architecture-context repo available at `/app/.context/architecture-context` in agent pods
- Jira emulator running with RHAIRFE, RHAISTRAT, and RHAIFIRST projects created
- Dashboard API reachable at `dashboard.local`

### Import skill repos to github.local

The github-emulator exposes a GitHub v3 API with token-based auth. Repos must be imported before agent jobs can clone them via FQN.

**Step 1: Create user and token**

The emulator has unauthenticated bootstrap endpoints at `/api/v3/admin/users` and `/api/v3/admin/tokens`:

```bash
# Create the repo owner
curl -s -X POST "http://github.local/api/v3/admin/users" \
  -H "Content-Type: application/json" \
  -d '{"login": "opendatahub-io", "email": "opendatahub-io@example.com", "password": "password123"}'

# Create a personal access token (returns raw token — save it)
curl -s -X POST "http://github.local/api/v3/admin/tokens" \
  -H "Content-Type: application/json" \
  -d '{"login": "opendatahub-io", "name": "demo", "scopes": ["repo", "user", "admin:org"]}'
# → {"token": "ghp_..."}
```

**Step 2: Create and populate the repo**

```bash
ODH_TOKEN="ghp_..."  # from step 1

# Create empty repo on github.local
curl -s -X POST "http://github.local/api/v3/user/repos" \
  -H "Content-Type: application/json" \
  -H "Authorization: token ${ODH_TOKEN}" \
  -d '{"name": "rfe-creator", "description": "RFE creation and strategy skills", "auto_init": true}'

# Clone from upstream, unshallow, and push to github.local
git clone https://github.com/opendatahub-io/rfe-creator.git /tmp/rfe-creator
cd /tmp/rfe-creator
git remote add local "http://x-access-token:${ODH_TOKEN}@github.local/opendatahub-io/rfe-creator.git"
git push local main --force
```

Repeat for `opendatahub-io/strat-creator` when Phase 3 requires it. Note: shallow clones are rejected by the emulator's git-http backend — always `git fetch --unshallow` before pushing.

## Phases

### Phase 1: Create RHAIRFE ticket

Create an RFE ticket on jira.local for a concrete RHOAI feature:

> **Summary:** Add cluster resource utilization data to the RHOAI Dashboard
>
> **Problem statement:** Administrators using the RHOAI Dashboard have no visibility into cluster-level resource utilization (CPU, memory, GPU allocation) from within the dashboard UI. They must switch to the OpenShift console or run CLI commands to check capacity before approving notebook or serving requests. This context-switching slows decisions and increases the risk of over-provisioning.
>
> **Business justification:** In customer interviews conducted during RHOAI 2.x adoption (Q1 2026), 7 of 10 enterprise accounts (financial services and healthcare segments) cited lack of resource visibility as the #1 barrier to expanding RHOAI usage beyond pilot teams. Three accounts (combined ARR: $2.4M) have delayed renewal decisions pending a dashboard-integrated capacity view, as their platform teams refuse to grant data scientists access to the OpenShift console for security reasons. Competitor platforms (SageMaker, Vertex AI) surface resource metrics natively, and this gap was cited in 4 competitive loss reports in Q4 2025.
>
> **Desired outcome:** The RHOAI Dashboard should display a cluster resources panel showing current utilization metrics (CPU/memory/GPU used vs available, node count, running workloads) sourced from Prometheus/Thanos, so admins can make capacity decisions without leaving the dashboard.

The business justification is required — without it, the RFE speedrun's rubric scoring will fail the WHY criteria and the RFE won't get the `rfe-creator-autofix-rubric-pass` label needed for strategy creation.

This can be created via the Jira emulator API:

```bash
curl -s -X POST "http://jira.local/rest/api/2/issue" \
  -H "Content-Type: application/json" \
  -u "${JIRA_USER}:${JIRA_TOKEN}" \
  -d '{
    "fields": {
      "project": {"key": "RHAIRFE"},
      "issuetype": {"name": "Feature Request"},
      "summary": "Add cluster resource utilization data to the RHOAI Dashboard",
      "description": "h2. Problem Statement\n\nAdministrators using the RHOAI Dashboard have no visibility into cluster-level resource utilization (CPU, memory, GPU allocation) from within the dashboard UI. They must switch to the OpenShift console or run CLI commands to check capacity before approving notebook or serving requests. This context-switching slows decisions and increases the risk of over-provisioning.\n\nh2. Business Justification\n\nIn customer interviews conducted during RHOAI 2.x adoption (Q1 2026), 7 of 10 enterprise accounts (financial services and healthcare segments) cited lack of resource visibility as the #1 barrier to expanding RHOAI usage beyond pilot teams. Three accounts (combined ARR: $2.4M) have delayed renewal decisions pending a dashboard-integrated capacity view, as their platform teams refuse to grant data scientists access to the OpenShift console for security reasons. Competitor platforms (SageMaker, Vertex AI) surface resource metrics natively, and this gap was cited in 4 competitive loss reports in Q4 2025.\n\nh2. Desired Outcome\n\nThe RHOAI Dashboard should display a cluster resources panel showing current utilization metrics (CPU/memory/GPU used vs available, node count, running workloads) sourced from Prometheus/Thanos, so admins can make capacity decisions without leaving the dashboard."
    }
  }'
```

**Output:** A Jira issue key (e.g., `RHAIRFE-1`). Save this — all subsequent phases reference it.

### Phase 2: Run RFE speedrun via dashboard agent runner

Use the dashboard's job submission API to run the `opendatahub-io/rfe-creator` RFE speedrun skill, which handles review, scoring, and refinement in a single invocation. The K8s job pod gets strace, OTEL, and MLflow wired in automatically by `k8s_orchestrator.py`.

Use the `fqn` field (not `command`) so the job manifest is self-contained — the FQN tells the agent container which repo to clone, which branch to use, and which skill to invoke, without relying on the local `pipeline-skills.yaml` registry.

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/rfe-creator@main:rfe.speedrun",
    "args": {
      "issue": "RHAIRFE-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'
```

**What's captured:**
- OTEL traces → Observatory (`http://observatory.ai-pipeline.svc.cluster.local:8000/otel`)
- Raw API bodies → `/app/artifacts/apibodies/{job-tag}/`
- Strace output → `/app/artifacts/strace/{job-tag}/`
- MLflow run → `opendatahub-io/rfe-creator/claude-code/opus/cli` experiment
- RFE artifacts → `/app/artifacts/rfe-tasks/`

### Phase 2b: Submit the RFE

The speedrun reviews, scores, and revises the RFE but may not submit it — e.g., if it fails the WHY criteria (business justification needs human input). Run `rfe.submit` explicitly to push the RFE to Jira regardless:

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/rfe-creator@main:rfe.submit",
    "args": {
      "issue": "RHAIRFE-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'
```

**Output:** The RFE is updated on jira.local with the refined content from the speedrun.

**Label gates for strategy creation:** The `strategy-create` skill requires two labels on the RFE before it will process it:

1. **Version gate:** `strat-creator-3.5` or `strat-creator-3.6` (or a matching Target Version field)
2. **Quality gate:** `rfe-creator-autofix-rubric-pass` or `tech-reviewed`

The speedrun's auto-fix phase assigns these labels based on rubric scoring. If the RFE fails a rubric dimension (e.g., WHY — business justification), it gets `rfe-creator-needs-attention` instead of `rfe-creator-autofix-rubric-pass`, and strategy creation will skip it.

To pass the quality gate, the RFE description must include business justification (customer evidence, revenue impact, or segment-level reasoning). If the initial problem statement lacks this, update the Jira ticket description to add it, then re-run the speedrun so the auto-fix agent can score it as passing.

### Phase 3: Run strategy skills via dashboard agent runner

Once the RFE submit completes, import `opendatahub-io/strat-creator` to github.local (same process as the prerequisites — create user, token, repo, push) and run the strategy skills.

**Pre-step: Add required labels**

Before running strategy-create, ensure the RFE has the required labels. Add `strat-creator-3.6` (version gate) and `tech-reviewed` (quality gate) if the speedrun didn't produce `rfe-creator-autofix-rubric-pass`:

```bash
curl -s -X PUT "http://jira.local/rest/api/2/issue/RHAIRFE-1" \
  -H "Content-Type: application/json" \
  -u "${JIRA_USER}:${JIRA_TOKEN}" \
  -d '{"update": {"labels": [{"add": "strat-creator-3.6"}, {"add": "tech-reviewed"}]}}'
```

**Step 3a: Strategy creation**

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/strat-creator@main:strategy-create",
    "args": {
      "issue": "RHAIRFE-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'
```

**Step 3b: Strategy refine**

The strategy creation step produces a RHAISTRAT ticket (e.g., `RHAISTRAT-1`) with a stub containing the Business Need. The refine step adds the HOW — technical approach, dependencies, impacted components, and non-functional requirements.

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/strat-creator@main:strategy-refine",
    "args": {
      "issue": "RHAISTRAT-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'
```

**Step 3c: Strategy review**

Once the strategy is refined, run review to score it.

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/strat-creator@main:strategy-review",
    "args": {
      "issue": "RHAISTRAT-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'
```

**What's captured:** Same observability data as phase 2, plus strategy artifacts in `/app/artifacts/strat-pipeline/` and `/app/artifacts/strat-tasks/`.

### Phase 4: Verify observability data landed

Before running claim analysis, confirm data reached each backend:

| Check | How | Expected |
|-------|-----|----------|
| OTEL traces visible | `curl observatory.local/api/hallucinations/summary` | Responds (0 claims — extraction hasn't run yet) |
| MLflow experiments logged | `curl mlflow.local/api/2.0/mlflow/experiments/search -d '{"max_results": 10}'` | Experiments for each FQN/harness/model/runner combo |
| Strace files present | `kubectl exec -n ai-pipeline deploy/pipeline-dashboard -- ls /app/artifacts/strace/` | One directory per phase (e.g., `rfe.speedrun-RHAIRFE-1`, `strategy-create-RHAIRFE-1`) |
| API bodies dumped | `kubectl exec -n ai-pipeline deploy/pipeline-dashboard -- ls /app/artifacts/apibodies/` | Same directories as strace |
| Strategy artifact exists | `kubectl exec -n ai-pipeline deploy/pipeline-dashboard -- ls /app/artifacts/strat-tasks/` | `RHAISTRAT-1.md` |
| All jobs completed | `curl dashboard.local/api/jobs` | All jobs show `status: completed` with strace/mlflow/otel=true |

This is a manual gate — verify before proceeding.

### Phase 5: Extract claims → Observatory

> **Lesson learned:** In this demo run, Phases 5-7 used `"command": "extract-claims"` etc., which invokes the skills as local commands. In a production demo, these should use `"fqn": "github.local/opendatahub-io/skills@main:extract-claims"` so the job manifests are self-contained and the skills are versioned in git. This requires importing `opendatahub-io/skills` to github.local first (see Phase 8d prerequisites). The FQN approach also means skill prompt fixes in Phase 8d can be tested by re-running the same FQN against the updated repo.

Run the `extract-claims` skill against the strategy and RFE artifacts produced in phases 2–3.

```bash
# Local command (used in this demo run):
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "extract-claims",
    "args": {
      "issue": "RHAISTRAT-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'

# Preferred (FQN — requires importing opendatahub-io/skills to github.local):
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/skills@main:extract-claims",
    "args": {
      "issue": "RHAISTRAT-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'
```

**What happens:**
1. Skill finds strategy `.md` files in `/app/artifacts/strat-tasks/` and `/app/artifacts/strat-reviews/` matching the issue key
2. Extracts atomic verifiable claims (factual, architectural, security, scope, attribution)
3. Writes `.claims.json` alongside each source file in `/app/artifacts/claims/strat-tasks/` and `/app/artifacts/claims/strat-reviews/`
4. POSTs each claims file to `POST observatory.local/api/claims/ingest`
5. Claims appear immediately on observatory.local's hallucinations dashboard (25 claims in our run: 18 from the strategy, 7 from the review)

### Phase 6: Verify claims → Observatory

Run the `verify-claims` skill to evaluate each extracted claim against architecture-context docs and source material.

```bash
# Local command (used in this demo run):
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "verify-claims",
    "args": {
      "issue": "RHAISTRAT-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'

# Preferred (FQN):
# "fqn": "github.local/opendatahub-io/skills@main:verify-claims"
```

**What happens:**
1. Skill fetches pending claims from `GET observatory.local/api/hallucinations/claims?jira_key=RHAISTRAT-1&verdict=pending`
2. For each claim, queries architecture-context via `arch-query` and reads raw docs
3. Produces verdicts: `supported`, `refuted`, `insufficient`, or `inconclusive`
4. Writes verification logs to `/app/artifacts/verification/{claim_id}.md`
5. POSTs verdicts to `POST observatory.local/api/claims/verdicts`
6. Observatory updates claim status — refuted claims are highlighted in the UI

### Phase 7: Explain refuted claims → Observatory

Run the `explain-claims` skill to do forensic analysis on refuted and insufficient claims.

```bash
# Local command (used in this demo run):
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "command": "explain-claims",
    "args": {
      "issue": "RHAISTRAT-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'

# Preferred (FQN):
# "fqn": "github.local/opendatahub-io/skills@main:explain-claims"
```

**What happens:**
1. Skill fetches refuted/insufficient claims from Observatory
2. Gathers forensic evidence from multiple sources:
   - K8s job logs (what files the agent read, what it reasoned about)
   - MLflow traces (token usage, duration, span count)
   - Strace output (what syscalls/files the process touched)
   - Raw API bodies (actual LLM request/response pairs)
3. Assigns root cause category per claim:
   - `training_data_hallucination` — agent invented facts not in any source
   - `source_misinterpretation` — agent read the source but distorted it
   - `context_confusion` — agent mixed up components or versions
   - `insufficient_context` — architecture-context docs lack coverage
   - `compound_error` — built on another wrong claim
4. Writes explanation reports to `/app/artifacts/explanations/{claim_id}.md`
5. POSTs explanations to `POST observatory.local/api/claims/explanations`

### Phase 8: Triage refuted claims → Jira tickets → PRs

This is the feedback tail — the demo's payoff. Filter refuted claims by root cause to identify what's actually fixable, then file Jira tickets and open PRs.

**Step 8a: Filter to fixable issues**

Not all refuted claims are actionable. The triage filters:

| Root cause | Fixable? | Fix target |
|------------|----------|------------|
| `insufficient_context` | Yes | architecture-context repo — add missing component docs or update stale ones |
| `source_misinterpretation` | Yes | skill prompts — the skill's instructions are ambiguous, causing agents to misread sources |
| `training_data_hallucination` | Sometimes | skill prompts — add explicit guardrails ("do not state facts not found in source material") |
| `context_confusion` | Sometimes | architecture-context overlays — clarify component naming or add disambiguation |
| `compound_error` | No | Resolves when upstream claim is fixed |

Query Observatory for the filtered set:

```bash
# Get explanations, filtered to fixable categories
curl -s "observatory.local/api/hallucinations/explanations?category=insufficient_context"
curl -s "observatory.local/api/hallucinations/explanations?category=source_misinterpretation"
```

**8a Results (from demo run):**

Observatory returned 7 explained claims for RHAISTRAT-1: 1 refuted, 5 insufficient, 1 inconclusive. After cross-referencing against the actual source repos (now imported to github.local), the triage identified **3 fixable issues**:

| # | Claims | Root Cause | Verdict | Fix Target | Description |
|---|--------|------------|---------|------------|-------------|
| 1 | 9 | `insufficient_context` (reclassified from `training_data_hallucination`) | insufficient | architecture-context | odh-dashboard.md omits `@tanstack/react-query` from external dependencies — verified present in `frontend/package.json` at `^4.44.0`. The agent was RIGHT but the docs don't back it up. |
| 2 | 10, 11, 16, 17 | `training_data_hallucination` → fixable as `insufficient_context` | insufficient | architecture-context | Strategy referenced specific Prometheus metrics (DCGM_FI_DEV_GPU_UTIL, kube_pod_resource_request, node_cpu_seconds_total, node_memory_MemAvailable_bytes) that aren't documented in architecture-context. These are standard K8s/NVIDIA metrics the agent pulled from training data. Fix: add a monitoring metrics section to architecture-context. |
| 3 | 25 | `source_misinterpretation` | refuted | strat-creator skill prompts | Agent conflated PLATFORM.md (monitoring namespace) with odh-dashboard.md (Thanos querier) into a single attribution. Fix: add per-source-document citation guardrail to strategy skill prompts. |

**Not filed (lower priority):**
- Claim 5 (Thanos port 9091 vs 9092): `context_confusion` — architecture-context documents BOTH ports for different hops (9092 for Dashboard→Thanos, 9091 for Thanos→Prometheus internal). The agent picked the wrong hop's port. This resolves if fix #3 (source citation guardrail) is applied.

**Key lesson:** Cross-referencing against actual source repos (odh-dashboard's `package.json`) revealed that explain-claims' root cause classification was wrong for claim 9 — the agent was correct, but architecture-context lacked coverage. The imported repos on github.local are essential for ground-truth validation during triage.

**Step 8b: File Jira tickets**

For each fixable refuted claim, create a Jira ticket describing the problem and fix:

- **architecture-context gaps** → file in RHAIFIRST with the specific component and version that needs docs
- **skill prompt issues** → file in RHAIFIRST against the skill repo (rfe-creator or strat-creator) with the ambiguous instruction and a proposed fix

**Prerequisite:** Create the RHAIFIRST project first — the Jira emulator doesn't auto-create projects on issue creation. Use the admin config import:

```bash
cat > /tmp/rhaifirst-config.json << 'EOF'
{
  "version": "1.0",
  "project": {
    "key": "RHAIFIRST",
    "name": "Red Hat AI First Pipeline",
    "description": "Fixes identified by the claim analysis pipeline",
    "issue_types": ["Bug", "Task", "Story"]
  }
}
EOF

curl -s -X POST "http://jira.local/api/admin/import/project-config" \
  -u "admin:admin" \
  -F "file=@/tmp/rhaifirst-config.json;type=application/json"
```

**8b Results (from demo run):**

Filed 3 tickets in RHAIFIRST, one per fixable issue from the 8a triage:

| Ticket | Summary | Fix Target | Claims |
|--------|---------|------------|--------|
| RHAIFIRST-1 | odh-dashboard.md missing React Query dependency | architecture-context | 9 |
| RHAIFIRST-2 | missing Prometheus/GPU monitoring metric names | architecture-context | 10, 11, 16, 17 |
| RHAIFIRST-3 | agent conflates source documents in architectural citations | strat-creator skill prompts | 25 (+ related: 5) |

Each ticket includes: the problem, root cause category, Observatory claim IDs, evidence sources, and a specific fix description.

**Step 8c: Validate fixes with agent-eval-harness (before opening PRs)**

Before committing architecture-context or skill prompt fixes, use the [agent-eval-harness](https://github.com/opendatahub-io/agent-eval-harness) to verify that the proposed changes actually correct the model's reasoning. This turns the fix from "we think this will help" into "we proved it does."

**Concept:** Build an eval dataset from the refuted/insufficient claims, run `verify-claims` against the BEFORE architecture-context (expecting failures), apply the fix, re-run against the AFTER architecture-context (expecting passes), and compare.

**Prerequisites: Import agent-eval-harness to github.local**

```bash
curl -s -X POST http://github.local/api/v3/admin/repos/import \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://github.com/opendatahub-io/agent-eval-harness",
    "owner": "opendatahub-io"
  }'
```

**Building the eval dataset**

Each test case maps to one claim from the 8a triage. The dataset structure follows the harness convention:

```
eval/dataset/cases/
├── case-001-react-query/
│   ├── input.yaml          # claim text, source file, jira key
│   └── reference.md        # expected verdict + evidence after fix
├── case-002-dcgm-metrics/
│   ├── input.yaml
│   └── reference.md
├── case-003-cpu-metrics/
│   ├── input.yaml
│   └── reference.md
├── case-004-gpu-alloc-metrics/
│   ├── input.yaml
│   └── reference.md
├── case-005-memory-metrics/
│   ├── input.yaml
│   └── reference.md
└── case-006-source-attribution/
    ├── input.yaml
    └── reference.md
```

Each `input.yaml` contains:

```yaml
claim_id: 9
claim_text: "The odh-dashboard frontend already uses React Query for client-side caching in the codebase."
claim_type: architectural
source_file: strat-tasks/RHAISTRAT-1.md
jira_key: RHAISTRAT-1
expected_verdict_before: insufficient    # what verify-claims should say with current arch-context
expected_verdict_after: supported         # what it should say after the fix
fix_ticket: RHAIFIRST-1
```

Each `reference.md` contains the expected verdict and evidence summary after the fix is applied.

**eval.yaml for claim verification validation**

```yaml
name: claim-fix-validation
description: Validate that architecture-context fixes correct claim verification verdicts
skill: verify-claims

execution:
  mode: case
  arguments: "--headless {jira_key} --claim-id {claim_id}"
  env:
    OBSERVATORY_URL: http://observatory.local
    JIRA_SERVER: http://jira.local

runner:
  type: cli
  command: >
    python main.py verify-claims
    --issue {jira_key}
    --model {model}

models:
  skill: claude-opus-4-6
  judge: claude-opus-4-6

dataset:
  path: eval/dataset/cases
  schema: |
    Each case directory contains:
    - input.yaml: claim_id, claim_text, claim_type, source_file,
      jira_key, expected_verdict_before, expected_verdict_after, fix_ticket
    - reference.md: Expected verdict and evidence summary after fix

outputs:
  - path: artifacts/verification
    schema: |
      One markdown file per claim: {claim_id}.md with verdict,
      confidence, and evidence_summary.

traces:
  metrics: true
  stdout: true

judges:
  - name: verdict_correct
    description: |
      Check that the claim received the expected verdict.
    check: |
      import yaml
      expected = outputs["annotations"].get("expected_verdict_after", "supported")
      content = outputs["main_content"]
      verdict_match = expected.lower() in content.lower()
      if not verdict_match:
          return False, f"Expected verdict '{expected}' not found in output"
      return True, f"Verdict matches expected: {expected}"

  - name: evidence_quality
    description: |
      Evaluate whether the verification evidence is specific and
      grounded in architecture-context documentation.
    prompt: |
      The claim was: {claim_text}
      The expected verdict is: {expected_verdict_after}

      Does the verification output cite specific architecture-context
      documentation? Is the evidence concrete (file paths, section names,
      quoted text) rather than vague? Score 1-5.

  - name: no_hallucinated_evidence
    description: |
      Check that the verification doesn't cite documents or sections
      that don't exist.
    prompt: |
      Review the verification output. Does it reference specific files
      or sections in architecture-context? Could any of these references
      be fabricated? Score 1-5 where 5 means all references appear genuine.

thresholds:
  verdict_correct:
    min_pass_rate: 0.8        # 80% of claims should get the right verdict after fix
  evidence_quality:
    min_mean: 3.5
```

**Running the A/B comparison**

1. **BEFORE run** — baseline with current architecture-context (claims should stay insufficient/refuted):
   ```bash
   /eval-run --model opus --run-id before-fix
   ```

2. **Apply the fix** — merge the architecture-context PR from step 8d (or apply changes to a branch):
   ```bash
   # In the architecture-context clone, apply fixes from RHAIFIRST-1 and RHAIFIRST-2
   ```

3. **AFTER run** — with fixed architecture-context (claims should flip to supported):
   ```bash
   /eval-run --model opus --run-id after-fix --baseline before-fix
   ```

4. **Compare** — the `--baseline` flag produces a regression report showing:
   - Which claims changed verdict (expected: insufficient → supported)
   - Whether evidence quality improved
   - Any regressions (claims that were supported before but broke)

5. **Log to MLflow** — track the before/after as experiment runs:
   ```bash
   /eval-mlflow --run-id before-fix --action log-results
   /eval-mlflow --run-id after-fix --action log-results
   ```

**What this proves:**
- The architecture-context fix is sufficient to change the model's verdict
- The model doesn't introduce new hallucinations when given better context
- The fix can be quantified (e.g., "4 of 5 insufficient claims flipped to supported")
- Results are logged in MLflow for audit trail

**Skill prompt fixes (RHAIFIRST-3)** follow the same pattern but testing `strategy-refine` instead of `verify-claims`:
- BEFORE: strategy output contains conflated source citations
- AFTER: strategy output with per-document citations (after adding guardrails to SKILL.md)

**Step 8d: Open PRs to fix (automated via agent jobs)**

Fix PRs target the imported forks on github.local, not upstream. The demo shows the platform improving its own inputs (architecture-context), tools (skill prompts), and analysis pipeline (claim skills) based on what it learned from its own mistakes.

**Prerequisites: Create opendatahub-io/skills on github.local**

The `opendatahub-io/skills` repo does not exist upstream — it is a net-new project created on github.local to hold the claim analysis skills and remediation skills. It was seeded with the claim skills from the ai-first-pipeline repo and the remediation skills created during this demo.

```bash
# Create the repo
curl -s -X POST "http://github.local/api/v3/user/repos" \
  -H "Content-Type: application/json" \
  -H "Authorization: token ${ODH_TOKEN}" \
  -d '{"name": "skills", "description": "Shared agent skills for claim analysis and remediation", "auto_init": true}'
```

Then clone, add skill files, and push. The repo structure:

```
.claude/skills/
├── extract-claims/          # Extract verifiable claims from artifacts → Observatory
│   └── SKILL.md
├── verify-claims/           # Evaluate claims against arch docs → verdicts
│   └── SKILL.md
├── explain-claims/          # Root-cause analysis on refuted claims
│   ├── SKILL.md
│   └── scripts/
│       └── gather-evidence.py
├── fix-arch-docs/           # Fix architecture-context doc gaps → PR
│   ├── SKILL.md
│   └── scripts/
│       ├── gather-context.py   # Jira ticket + Observatory + ground truth checks
│       └── open-pr.py          # branch → commit → push → PR via GitHub API
└── fix-skill-prompt/        # Fix skill prompt guardrails → PR
    ├── SKILL.md
    └── scripts/
        ├── gather-context.py   # Jira ticket + Observatory + target repo resolution
        └── open-pr.py          # branch → commit → push → PR via GitHub API
```

This makes all skills addressable via FQN: `github.local/opendatahub-io/skills@main:<skill-name>`.

**Skill design pattern:** Each skill's deterministic work (API queries, repo resolution, git operations) is handled by Python scripts in `scripts/`. The SKILL.md focuses the agent on judgment calls — reading docs, deciding what to change, and writing the fix. This follows the same pattern as `explain-claims/scripts/gather-evidence.py`.

**Remediation skills and their FQNs:**

| Skill | FQN | Purpose |
|-------|-----|---------|
| `fix-arch-docs` | `github.local/opendatahub-io/skills@main:fix-arch-docs` | Reads RHAIFIRST ticket, clones architecture-context, adds/updates docs, opens PR |
| `fix-skill-prompt` | `github.local/opendatahub-io/skills@main:fix-skill-prompt` | Reads RHAIFIRST ticket, resolves target skill repo, adds guardrails to SKILL.md, opens PR |

**Fix categories and target repos:**

| Fix Type | Target Repo on github.local | Remediation Skill |
|----------|----------------------------|-------------------|
| architecture-context gaps | `opendatahub-io/architecture-context` | `fix-arch-docs` |
| strat-creator prompt issues | `opendatahub-io/strat-creator` | `fix-skill-prompt` |
| rfe-creator prompt issues | `opendatahub-io/rfe-creator` | `fix-skill-prompt` |
| claim skill issues | `opendatahub-io/skills` | `fix-skill-prompt` |

**For architecture-context fixes (RHAIFIRST-1, RHAIFIRST-2):**

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/skills@main:fix-arch-docs",
    "args": {
      "issue": "RHAIFIRST-1",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true,
      "extra_kwargs": "--github-token ${ODH_TOKEN}"
    }
  }'
```

The skill's `scripts/gather-context.py` fetches the Jira ticket, queries Observatory for related claims, verifies ground truth against source repos (e.g., checking `package.json` to confirm a dependency exists), and outputs a JSON manifest. The agent then clones architecture-context, makes the doc fix, and `scripts/open-pr.py` handles branch/commit/push/PR creation.

**For strategy/RFE skill prompt fixes (RHAIFIRST-3):**

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/skills@main:fix-skill-prompt",
    "args": {
      "issue": "RHAIFIRST-3",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true,
      "extra_kwargs": "--github-token ${ODH_TOKEN}"
    }
  }'
```

The skill's `scripts/gather-context.py` resolves the target repo from ticket labels (e.g., `strat-creator` label → `opendatahub-io/strat-creator`) and identifies which SKILL.md files to edit. The agent reads the current SKILL.md, adds guardrails based on the root cause category (citation requirements for `source_misinterpretation`, source fidelity rules for `training_data_hallucination`), and `scripts/open-pr.py` opens the PR.

**For claim skill fixes:**

Same as skill prompt fixes but targeting `opendatahub-io/skills` itself. After the PR merges, re-run the affected phase using the FQN (`github.local/opendatahub-io/skills@main:<skill>`) to verify the fix.

## Services Involved

| Service | Role in demo |
|---------|-------------|
| **Jira** (jira.local) | Source RFE ticket (RHAIRFE), strategy ticket (RHAISTRAT), follow-up fix tickets (RHAIFIRST) |
| **GitHub** (github.local) | Hosts imported forks of `rfe-creator`, `strat-creator`, `skills`, `architecture-context`, `opendatahub-operator`, and `odh-dashboard`; skill prompt fixes and doc fixes land as PRs here |
| **Dashboard** (dashboard.local) | Job submission API (`POST /api/jobs/submit`), job monitoring, activity feed |
| **Observatory** (observatory.local) | Claim lifecycle: ingest → verdicts → explanations. Frontend shows per-issue accuracy and hallucination patterns |
| **MLflow** (mlflow.local) | Experiment runs per skill invocation — duration, cost, token usage, tool counts |
| **Elasticsearch** | OTEL trace indexing for cross-job search |

## What the Audience Sees

1. Jira ticket filed: "Add cluster resource utilization data to the RHOAI Dashboard"
2. Dashboard shows K8s job pods launching in sequence — RFE review, strategy creation, strategy review
3. During execution: OTEL traces stream into Observatory, MLflow experiments populate, strace files accumulate
4. Claim extraction runs — 35 claims appear on observatory.local, categorized by type
5. Verification runs — observatory.local lights up: 28 supported (green), 4 refuted (red), 3 insufficient (yellow)
6. Explanation runs — each red claim gets a root cause: 2 are `insufficient_context` (architecture-context gaps), 1 is `source_misinterpretation` (skill prompt ambiguity), 1 is `training_data_hallucination`
7. Triage: 3 fixable issues → 3 Jira tickets filed automatically
8. PRs appear on github.local: one adds monitoring docs to `odh-dashboard.md` in architecture-context, one clarifies a strat-creator prompt
9. Full claim lifecycle visible on observatory.local — click any claim to see extraction → verdict → explanation → fix ticket → PR

## Differences from Skill Factory Demo

| Aspect | Skill Factory Demo | Observability Demo |
|--------|-------------------|-------------------|
| **Focus** | Agents creating and iterating on skills | Tracing and evaluating agent output quality |
| **Skills used** | Agent-created (inner loop) | Pre-existing (`rfe-creator`, `strat-creator`, claim skills) |
| **Orchestration** | Markov workflow with gates | Sequential dashboard API calls (can be scripted or manual) |
| **Feedback loop** | Skill quality → revise SKILL.md → retest | Claim accuracy → fix architecture-context or skill prompts |
| **Primary service** | GitLab CI (skill testing) | Observatory (claim lifecycle) |
| **Complexity** | High (two nested loops) | Medium (linear pipeline + feedback tail) |
| **Duration** | ~15 minutes | ~10 minutes |

## Open Questions

- Do we need to import specific component repos to github.local for the strategy creation to have source material, or is architecture-context sufficient? (TBD — will find out during first run)
