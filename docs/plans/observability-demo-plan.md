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
| OTEL traces visible | `curl observatory.local/api/traces/summary` | Shows trace spans from the phase jobs (nonzero span count) |
| MLflow experiments logged | `curl mlflow.local/api/2.0/mlflow/experiments/search -d '{"max_results": 10}'` | Experiments for each FQN/harness/model/runner combo |
| Strace files present | `kubectl exec -n ai-pipeline deploy/pipeline-dashboard -- ls /app/artifacts/strace/` | One directory per phase (e.g., `rfe.speedrun-RHAIRFE-1`, `strategy-create-RHAIRFE-1`) |
| API bodies dumped | `kubectl exec -n ai-pipeline deploy/pipeline-dashboard -- ls /app/artifacts/apibodies/` | Same directories as strace |
| Strategy artifact exists | `kubectl exec -n ai-pipeline deploy/pipeline-dashboard -- ls /app/artifacts/strat-tasks/` | `RHAISTRAT-1.md` |
| All jobs completed | `curl dashboard.local/api/jobs` | All jobs show `status: completed` with strace/mlflow/otel=true |

This is a manual gate — verify before proceeding.

### Phase 5: Extract claims → Observatory

> **Note:** Phases 5-7 use `"command": "extract-claims"` etc., which invokes the skills as local commands from the pipeline agent image. Once `opendatahub-io/skills` is created on github.local (see Phase 8d prerequisites), these can be switched to FQN form (`"fqn": "github.local/opendatahub-io/skills@main:extract-claims"`) so the job manifests are self-contained and skill prompt fixes can be tested by re-running the same FQN against the updated repo. However, `opendatahub-io/skills` does not exist until Phase 8d creates it — do NOT use the FQN form in Phases 5-7 without creating the repo first.

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

**Prerequisites: Import agent-eval-harness and eval-datasets to github.local**

The agent-eval-harness and eval-datasets repos should already be on github.local from the `arch-context-accuracy` eval work. If not:

```bash
curl -s -X POST http://github.local/api/v3/admin/repos/import \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/opendatahub-io/agent-eval-harness", "owner": "opendatahub-io"}'

curl -s -X POST http://github.local/api/v3/admin/repos/import \
  -H "Content-Type: application/json" \
  -d '{"url": "https://github.com/opendatahub-io/eval-datasets", "owner": "opendatahub-io"}'
```

**Lessons from the arch-context-accuracy eval (2026-07-06)**

The `arch-context-accuracy` eval in `eval-datasets` was the first end-to-end eval run. It validated that an agent can answer architecture questions using architecture-context docs without hallucinating. Key lessons that inform this phase:

1. **`dataset.path` is relative to the eval.yaml file's directory**, not the repo root. The harness's `resolve_path` in `agent_eval/config.py` prepends the config file's parent directory. If the eval.yaml is at `claim-fix-validation/eval.yaml`, then `dataset/cases` resolves to `claim-fix-validation/dataset/cases/`.

2. **Judge prompt template variables**: `score.py` populates `outputs["input"]` from `input.yaml` and `outputs["stdout"]` from execution output. To reference input fields in judge prompts, use `{{ outputs["input"]["question"] }}`, NOT `{{ outputs["question"] }}`. The latter renders empty because input.yaml fields are nested under `outputs["input"]`, not at the top level.

3. **Judge prompt wording must be extremely specific about failure criteria.** The `arch-context-accuracy` no-hallucination judge initially scored 1.0 (pass) on a case where it identified hallucination in its own rationale — because the prompt said "reasonable inference" was acceptable. The fix was to enumerate explicit fail conditions (specific dependency names, version numbers, port numbers, etc.) and add "when uncertain, score 0."

4. **Use model aliases (`opus`, `sonnet`) not full Vertex IDs.** The harness has a `VERTEX_MODEL_ALIASES` map in `score.py` that resolves aliases to the correct Vertex model IDs (`opus` → `claude-opus-4-6`, `sonnet` → `claude-sonnet-4-6`). Full model IDs like `claude-sonnet-4-6-20250514` do NOT work on Vertex.

5. **Known harness bugs add ~60s of agent friction per run.** BUG-11 (preflight marks fresh state as stale — agent uses `--clean --force`) and BUG-14 (agent must manually discover eval venv python for scoring). These are documented in `docs/bugs/eval-job-143610-bugs.md`.

6. **The dashboard Evals page is the best way to run and monitor evals.** The evals tab at `/evals` has a submit form with select-with-toggle fields for harness/dataset/context repos, live log polling in the detail modal, and a re-run button that pre-fills the form. Use it instead of raw CLI commands for the demo.

**Building the eval dataset**

Each test case maps to one claim from the 8a triage. The dataset lives in `eval-datasets` alongside `arch-context-accuracy`:

```
claim-fix-validation/
├── eval.yaml
└── dataset/
    └── cases/
        ├── case-001-react-query/
        │   └── input.yaml
        ├── case-002-dcgm-metrics/
        │   └── input.yaml
        ├── case-003-cpu-metrics/
        │   └── input.yaml
        ├── case-004-gpu-alloc-metrics/
        │   └── input.yaml
        ├── case-005-memory-metrics/
        │   └── input.yaml
        └── case-006-source-attribution/
            └── input.yaml
```

Each `input.yaml` contains:

```yaml
claim_id: 9
claim_text: "The odh-dashboard frontend already uses React Query for client-side caching in the codebase."
claim_type: architectural
source_file: strat-tasks/RHAISTRAT-1.md
jira_key: RHAISTRAT-1
expected_verdict_before: insufficient
expected_verdict_after: supported
fix_ticket: RHAIFIRST-1
```

**eval.yaml for claim verification validation**

```yaml
skill: claim-fix-validation

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
  skill: opus
  judge: sonnet

dataset:
  path: dataset/cases

judges:
  - name: verdict-correct
    check: |
      expected = outputs["input"].get("expected_verdict_after", "supported")
      stdout = outputs.get("stdout", "")
      if expected.lower() in stdout.lower():
          return True, f"Verdict matches expected: {expected}"
      return False, f"Expected verdict '{expected}' not found in output"

  - name: evidence-quality
    prompt: |
      You are evaluating whether an AI agent's claim verification is well-evidenced.

      ## Claim
      {{ outputs["input"]["claim_text"] }}

      ## Expected Verdict
      {{ outputs["input"]["expected_verdict_after"] }}

      ## Agent's Verification Output
      {{ outputs["stdout"] }}

      ## Scoring Rules

      Score 1 (pass) ONLY when ALL of these are true:
      - The output cites at least one specific architecture-context file by name
      - The output quotes or closely paraphrases the relevant section
      - The evidence directly supports or refutes the claim

      Score 0 (fail) if ANY of these are true:
      - The output contains no specific file paths or section names from architecture-context
      - The output makes vague references like "the docs mention" without citing which doc
      - The verdict is stated without supporting evidence

      Return a JSON object: {"score": 0 or 1, "reasoning": "brief explanation"}

  - name: no-hallucinated-evidence
    prompt: |
      You are a strict evidence auditor. Check whether an AI agent fabricated
      any references in its claim verification output.

      ## Agent's Verification Output
      {{ outputs["stdout"] }}

      ## Scoring Rules

      Score 0 (fail) if the output references ANY of these that you cannot
      verify exist in a typical architecture-context repo:
      - File paths that look invented (e.g., specific version numbers in paths)
      - Section headings that seem fabricated
      - Quoted text that appears made up rather than extracted

      Score 1 (pass) ONLY when all cited files, sections, and quotes appear
      to be genuine references to architecture documentation.

      When uncertain whether a reference is real, score 0. False negatives
      (missing a fabricated reference) are worse than false positives.

      Return a JSON object: {"score": 0 or 1, "reasoning": "brief explanation"}

thresholds:
  verdict-correct:
    min_pass_rate: 0.8
  evidence-quality:
    min_mean: 0.7
  no-hallucinated-evidence:
    min_mean: 0.8
```

**Running the A/B comparison via the Evals dashboard**

Submit both runs from the dashboard Evals page at `/evals`. The FQN for this eval is `github.local/opendatahub-io/eval-datasets@main:claim-fix-validation`.

1. **BEFORE run** — baseline with current architecture-context. Submit with Context Ref = `main`. Claims should stay insufficient/refuted.

2. **Apply the fix** — merge the architecture-context PR from step 8d to a branch (e.g., `fix/monitoring-docs`).

3. **AFTER run** — submit with Context Ref = `fix/monitoring-docs`. Use the BEFORE run's run-id as the Baseline Run ID field. Claims should flip to supported.

4. **Compare** — the `--baseline` flag produces a regression report showing:
   - Which claims changed verdict (expected: insufficient → supported)
   - Whether evidence quality improved
   - Any regressions (claims that were supported before but broke)

5. **Verify MLflow** — eval jobs with `mlflow: true` automatically log results to MLflow. Confirm both runs appear:
   ```bash
   curl -s "mlflow.local/api/2.0/mlflow/experiments/search" \
     -d '{"max_results": 10}' | python3 -m json.tool
   ```
   Both the BEFORE and AFTER runs should appear as separate MLflow runs under the same experiment, with metrics (judge scores, duration, token usage) logged automatically.

**What this proves:**
- The architecture-context fix is sufficient to change the model's verdict
- The model doesn't introduce new hallucinations when given better context
- The fix can be quantified (e.g., "4 of 5 insufficient claims flipped to supported")
- Results are logged in MLflow automatically for audit trail

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

**GitHub token for PRs:** The remediation skills need a GitHub token to push branches and open PRs on github.local. The dashboard's `extra_kwargs` forwards `key=value` tokens as `--extra-vars` to the entrypoint. Pass the token in that format:

```bash
"extra_kwargs": "github_token=YOUR_TOKEN_HERE"
```

The skill scripts then receive it via `--extra-vars github_token=...` and use it for git push and PR creation. Replace `YOUR_TOKEN_HERE` with the actual token from the github.local setup (Phase 0 prerequisites).

**For architecture-context fixes (RHAIFIRST-1, RHAIFIRST-2):**

```bash
ODH_TOKEN="ghp_..."  # from prerequisites

curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d "{
    \"fqn\": \"github.local/opendatahub-io/skills@main:fix-arch-docs\",
    \"args\": {
      \"issue\": \"RHAIFIRST-1\",
      \"model\": \"opus\",
      \"runner\": \"cli\",
      \"strace\": true,
      \"mlflow\": true,
      \"otel\": true,
      \"extra_kwargs\": \"github_token=${ODH_TOKEN}\"
    }
  }"
```

The skill's `scripts/gather-context.py` fetches the Jira ticket, queries Observatory for related claims, verifies ground truth against source repos (e.g., checking `package.json` to confirm a dependency exists), and outputs a JSON manifest. The agent then clones architecture-context, makes the doc fix, and `scripts/open-pr.py` handles branch/commit/push/PR creation using the token from `--extra-vars`.

**For strategy/RFE skill prompt fixes (RHAIFIRST-3):**

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d "{
    \"fqn\": \"github.local/opendatahub-io/skills@main:fix-skill-prompt\",
    \"args\": {
      \"issue\": \"RHAIFIRST-3\",
      \"model\": \"opus\",
      \"runner\": \"cli\",
      \"strace\": true,
      \"mlflow\": true,
      \"otel\": true,
      \"extra_kwargs\": \"github_token=${ODH_TOKEN}\"
    }
  }"
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
