# Plan: Closed-Loop Hallucination Remediation Demo

## Goal

Demonstrate the larger ai-first-pipeline vision: agents produce RFE, STRAT, and EPIC planning artifacts; the platform extracts and verifies the claims in those artifacts; refuted or unsupported claims are traced back to their cause; fixes are made in the right repo; and the same end-to-end flow is rerun to prove the fix improved the output.

This is not a benchmark demo. The proof is the operational loop itself:

1. Run the real planning workflow.
2. Find hallucinations and unsupported claims in the generated artifacts.
3. Fix missing context, stale docs, ambiguous prompts, or broken claim skills.
4. Rerun the same workflow.
5. Compare before and after claim quality in Observatory.

## Current Status

As of 2026-07-14, the Claimify-aligned assurance subsystem is implemented and
deployed: generated artifacts can be segmented into traceable claim
occurrences, evaluated for extraction quality, verified against versioned
evidence, routed to explanations, gated by Markov, overridden with audit
provenance, and replayed through regression evaluation. Receipt evidence also
demonstrates no-op reuse and selective invalidation for skill and context
revisions.

This does not yet complete the larger closed-loop demo described below. The
remaining assurance work is tracked in the
[Claimify plan](claimify-aligned-claim-assurance-plan.md) and its linked pending
tasks. In particular, the regression judges must receive real case data, seven
missing staged outputs must be investigated, the long-running evaluation must
be reconciled after Markov's wait deadline, and source-artifact invalidation
must be demonstrated. The full planning-to-code workflow has intentionally not
been rerun twice because of its execution cost; whether that is required for
final acceptance remains an explicit decision.

## Why This Demo Exists

The project has the pieces for a local AI delivery control plane:

- `jira.local` for RFE, STRAT, EPIC, and follow-up fix tickets
- `github.local` and `gitlab.local` for source repos, skill repos, and PRs
- Dashboard jobs for running skills as Kubernetes jobs
- Markov/markovd for future orchestration of multi-step remediation loops
- architecture-context as the main grounding corpus
- Observatory for claim lifecycle and OTEL data
- MLflow for trace/run history
- strace and raw API bodies for forensic evidence

The demo should show these services working together as a self-improving planning system, not just as isolated observability tools.

## Demo RFE

Use a feature request that is concrete enough to drive real RFE/STRAT/EPIC output, but likely to trigger checkable architecture claims.

The demo RFE must target `opendatahub-io/odh-cli` (`rhai-cli`) as the code generation target. `odh-cli` is a Go CLI for RHOAI cluster management — currently has a `lint` subcommand that validates configs against a target version. It's moderately sized, has clear `cmd/`/`pkg/` structure, fast `go build`/`go test` feedback, and produces readable diffs — all good properties for a demo.

Three candidate RFEs are listed below. An external reviewer should select one (or propose a hybrid) based on which best satisfies the selection criteria at the end.

### Option A: `rhai-cli diagnose`

**Summary:** Add a diagnostic subcommand to rhai-cli that checks RHOAI deployment health

**Problem Statement:**

RHOAI administrators troubleshooting deployment issues must manually inspect multiple OpenShift resources — operator status, CRD conditions, component pod health, route availability, and certificate expiry. There is no single command that checks the health of an RHOAI deployment and reports actionable findings. Administrators end up running ad-hoc `oc get` and `oc describe` commands across namespaces, which is slow and error-prone.

**Desired Outcome:**

`rhai-cli diagnose` connects to an RHOAI cluster and runs a suite of health checks: operator deployment status, DSC/DSCI conditions, component readiness (dashboard, model controller, workbenches, pipelines, model registry), route accessibility, certificate validity, and version consistency. Output is a structured report with pass/fail/warning per check and remediation hints for failures.

**Why this generates checkable claims:**

Agents must make claims about RHOAI operator CRDs (DataScienceCluster, DSCInitialization), component deployment names, namespace conventions, health-check endpoints, and certificate chain structure. These are verifiable against `architecture-context` and `odh-cli`'s existing patterns.

### Option B: `rhai-cli resources`

**Summary:** Add a resource utilization subcommand to rhai-cli for RHOAI workloads

**Problem Statement:**

RHOAI administrators need to understand cluster capacity before approving notebook, pipeline, and model-serving workloads. Today they must inspect OpenShift Console, Prometheus, or run ad-hoc `oc` commands to understand CPU, memory, and GPU availability, running workload pressure, and namespace-level demand. This slows operational decisions and leads to over-provisioning or delayed approvals.

**Desired Outcome:**

`rhai-cli resources` queries the cluster for CPU, memory, and GPU utilization across RHOAI-managed namespaces. It shows current utilization vs. requested vs. allocatable capacity, breaks down by workload type (notebooks, pipelines, model servers), and flags namespaces approaching resource limits. Output is a structured table or JSON report.

**Why this generates checkable claims:**

Agents must make claims about Prometheus/Thanos metric availability, DCGM GPU metrics, Kubernetes resource quota APIs, RHOAI workload labels and selectors, and how `allocatable` vs. `requests` vs. `limits` vs. `usage` relate. Many of these will be plausible but unverifiable against `architecture-context` alone.

### Option C: `rhai-cli validate`

**Summary:** Add pre-flight validation for RHOAI workloads before submission

**Problem Statement:**

Data scientists submitting notebooks, pipelines, or model-serving configurations often discover problems only after the workload fails to schedule or crashes at runtime — wrong image tags, missing storage classes, insufficient resource requests, incompatible runtime versions, or references to nonexistent ConfigMaps. There is no pre-submission check that catches these issues before they consume cluster resources.

**Desired Outcome:**

`rhai-cli validate <workload-spec>` takes a notebook CR, pipeline run spec, or InferenceService manifest and checks it against the live cluster state: image availability, storage class existence, resource quota headroom, runtime version compatibility, and referenced secret/ConfigMap existence. Output is a pass/fail report with specific findings and fix suggestions, similar to how `lint` validates configurations but focused on workload submission readiness.

**Why this generates checkable claims:**

Agents must make claims about RHOAI CR schemas (Notebook, InferenceService, PipelineRun), storage class discovery, image pull policies, runtime version matrices, and workload-specific validation rules. The `lint` command's existing patterns provide a template, so agents will also make claims about how to extend that pattern — some of which will be wrong if `architecture-context` doesn't cover `odh-cli` internals well.

### RFE Selection Criteria

The reviewer should evaluate each option against:

1. **Claim density** — Does the RFE force agents to make many architecture claims that can be checked against `architecture-context` and source repos? More claims = more opportunities to demonstrate the remediation loop.
2. **Failure likelihood** — Will some claims likely be wrong or unsupported? Too easy (all claims trivially true) defeats the purpose. Too hard (agents can't produce anything useful) stalls the demo.
3. **Code generation feasibility** — Can `epic-code-gen` plausibly produce working Go code for this feature given `odh-cli`'s existing patterns? The demo needs at least a partial working PR, not just scaffolding.
4. **Epic decomposition fit** — Does the feature naturally decompose into 3-6 epics with some investigation gates? Too monolithic or too granular both hurt the DAG demo.
5. **Demo narrative clarity** — Can a non-expert audience follow what the feature does and why the hallucination matters? Simpler concepts win.
6. **Scope containment** — Can the feature be implemented without requiring a live RHOAI cluster during code generation? The agents work against source code and mocked/stubbed interfaces, not a running cluster.

## Workflow Structure

The production workflow is four stages:

```
A. RFE            B. Strategy           C. Epics (DAG)              D. Code PRs
─────────         ──────────────        ─────────────────           ──────────────
create RFE   →    create strategy  →    decompose into epics   →    codegen per epic
review            refine                investigate unknowns        4-reviewer gate
score             review                (dependency DAG             iterate if needed
submit            submit                 governs order)             open PR
```

**Stage C is a DAG, not a sequence.** `epic-creator` decomposes a strategy into multiple epics with dependency edges. `epic-investigator` runs on investigation-type epics first — its go/no-go verdicts gate downstream implementation epics. Implementation epics without investigation dependencies can proceed in parallel. The DAG determines execution order; the other three stages are linear.

**Claim analysis wraps around the whole thing.** After stages A–D complete, `extract-claims` → `verify-claims` → `explain-claims` runs against all generated artifacts. Refuted or unsupported claims produce remediation tickets and PRs. Then stages A–D rerun to prove the fixes improved output quality. This is the closed loop.

```
    ┌──────────────────────────────────────────────────────────┐
    │                                                          │
    │   A → B → C (DAG) → D                                   │
    │   │                  │                                   │
    │   └──── all artifacts ──→ extract → verify → explain     │
    │                                                  │       │
    │                              fix tickets + PRs ←─┘       │
    │                                     │                    │
    │                              apply fixes                 │
    │                                     │                    │
    └─────────────── rerun A → B → C → D ─┘                   │
                            │                                  │
                            └── compare claim delta ───────────┘
```

## Phases

### Repo Inventory

Eleven repos on `github.local` participate in this demo, grouped by role.

**Planning skill repos** — RFE → STRAT → EPIC lifecycle:

| Repo | Role | Key Skills | Upstream |
|------|------|------------|----------|
| `opendatahub-io/rfe-creator` | RFE lifecycle | `rfe.speedrun`, `rfe.submit` | `github.com/opendatahub-io/rfe-creator` |
| `opendatahub-io/strat-creator` | Strategy lifecycle | `strategy-create`, `strategy-refine`, `strategy-review` | `github.com/opendatahub-io/strat-creator` |
| `opendatahub-io/epic-creator` | Epic decomposition | `epic-decompose` — breaks a STRAT into implementation epics | `github.com/jwforres/epic-creator` (fork of `opendatahub-io/epic-creator`) |
| `opendatahub-io/epic-investigator` | Epic investigation | `epic-investigate` — resolves technical unknowns in investigation-type epics via 5-phase classify → investigate → validate → synthesize → publish loop | `github.com/jwforres/epic-investigator` |
| `opendatahub-io/epic-code-gen` | Code generation from epics | `epic-codegen` — spec/plan → TDD implementation → 4-reviewer review → iterate loop, produces a PR on the target repo | `github.com/ederign/epic-code-gen` |

**Quality and observability skill repos:**

| Repo | Role | Key Skills | Upstream |
|------|------|------------|----------|
| `opendatahub-io/skills` | Claim analysis and remediation | `extract-claims`, `verify-claims`, `explain-claims`, `fix-arch-docs`, `fix-skill-prompt` | Net-new on github.local (no upstream) |
| `opendatahub-io/agent-eval-harness` | Eval harness plugin | Installed via `pip install -e`, loaded via `claude --plugin-dir` | `github.com/opendatahub-io/agent-eval-harness` |
| `opendatahub-io/eval-datasets` | Eval configs and test cases | Contains `arch-context-accuracy/eval.yaml` and `claim-fix-validation/eval.yaml` | `github.com/opendatahub-io/eval-datasets` |

**Content repos** — read by agents as grounding material during skill execution:

| Repo | Role | Used By |
|------|------|---------|
| `opendatahub-io/architecture-context` | Main grounding corpus for architecture claims | `verify-claims`, `strategy-*`, `epic-*`, eval harness (via `--context-repo`) |
| `opendatahub-io/odh-cli` | Code generation target — Go CLI for RHOAI cluster management | `epic-code-gen` (clones as implementation target), `explain-claims` triage |
| `opendatahub-io/odh-dashboard` | Source repo for ground truth verification | `explain-claims` triage, `verify-claims` evidence |

**Pipeline repo** (not on github.local — runs the platform itself):

| Repo | Role |
|------|------|
| `jctanner.redhat/ai-first-pipeline` | Dashboard, K8s orchestrator, `run_eval.sh` entrypoint, local skills (`extract-claims`, `verify-claims`, `explain-claims`), `pipeline-agent` image |

**End-to-end flow through repos:**

```
rfe-creator          strat-creator        epic-creator         epic-investigator    epic-code-gen
  RFE ticket    →      STRAT ticket   →    EPIC tickets   →    Investigation    →   Code PR
  (RHAIRFE)            (RHAISTRAT)          (RHAIFIRST)         reports              on odh-cli
                                                                (go/no-go)

                              ↓ all artifacts feed into ↓

                    skills: extract-claims → verify-claims → explain-claims
                              ↓                                    ↓
                    Observatory (claim lifecycle)          RHAIFIRST fix tickets
                              ↓                                    ↓
                    skills: fix-arch-docs / fix-skill-prompt → PRs on github.local
```

**Relationship between local skills and github.local skills:**

The pipeline image bakes in local copies of `extract-claims`, `verify-claims`, and `explain-claims` under `.claude/skills/`. These are invoked via `"command": "extract-claims"` in dashboard job submissions. The `opendatahub-io/skills` repo on github.local holds the same skills plus remediation skills (`fix-arch-docs`, `fix-skill-prompt`). When invoked via FQN (`github.local/opendatahub-io/skills@main:extract-claims`), the agent clones the versioned repo instead of using the baked-in copy — this lets skill prompt fixes be tested by rerunning the same FQN.

For the demo: Phases 2-4 (RFE/STRAT/EPIC) use FQN from their respective skill repos. Phases 5-7 (claim analysis) can use either local `command` jobs or FQN from `opendatahub-io/skills`. Phase 9 (remediation PRs) requires FQN from `opendatahub-io/skills` since the remediation skills are only in that repo. The eval harness (`agent-eval-harness` + `eval-datasets`) is not on the main demo path — see the "Role Of agent-eval-harness" section below.

**All repos run on github.local.** Every repo in this demo — skill repos, content repos, and the code generation target — is imported into `github.local` under the `opendatahub-io` org. Agents clone from `github.local`, PRs are opened against `github.local`, and FQNs reference `github.local`. No agent job should hit public GitHub during the demo. This keeps the demo self-contained and makes it possible to run air-gapped or with modified branches.

**Current state on github.local (as of 2026-07-06):**

Existing repos (imported and populated):

- `opendatahub-io/rfe-creator` — imported from upstream
- `opendatahub-io/strat-creator` — imported from upstream
- `opendatahub-io/skills` — created locally with claim and remediation skills
- `opendatahub-io/agent-eval-harness` — imported from upstream, with local bug fixes (BUG-11 through BUG-17)
- `opendatahub-io/eval-datasets` — imported from upstream, with `arch-context-accuracy` eval config
- `opendatahub-io/architecture-context` — imported from upstream
- `opendatahub-io/odh-dashboard` — imported from upstream

Still need to import:

- `opendatahub-io/epic-creator` — from `github.com/jwforres/epic-creator`
- `opendatahub-io/epic-investigator` — from `github.com/jwforres/epic-investigator`
- `opendatahub-io/epic-code-gen` — from `github.com/ederign/epic-code-gen`
- `opendatahub-io/odh-cli` — from `github.com/opendatahub-io/odh-cli` (code generation target)

### Demo Workflow

The demo setup is a Markov directory-based workflow at `var/demos/end-to-end/`. It resets both `jira.local` and `github.local` to a clean state, imports all required repos, and optionally seeds a demo RFE ticket.

```
var/demos/end-to-end/
├── meta.yaml                 # entrypoint: main, namespace: ai-pipeline
├── vars.yaml                 # default variables, service URLs, and repo manifest
├── step_types.yaml           # agent_job step type (for future A→B→C→D steps)
├── rules.yaml                # empty (future: retry rules, quality gates)
├── README.md                 # usage docs
└── workflows/
    ├── main.yaml             # entrypoint: reset-jira → reset-github → seed-rfe
    ├── reset-jira.yaml       # POST /api/admin/reset, create RHAIFIRST project
    ├── reset-github.yaml     # for_each repo in vars.yaml: delete + import
    └── seed-rfe.yaml         # create demo RFE ticket in RHAIRFE
```

**Workflow structure:**

```
main
├── reset-jira          Wipe Jira, re-seed defaults, create RHAIFIRST, verify
├── reset-github        Ensure org, create skills repo, for_each repo: delete + import
│   └── import-repo     Per-repo: delete → import from upstream → poll until complete
└── seed-rfe            Create demo RFE ticket (gated on seed_rfe variable)
```

**Key variables** (override via `--var`):

| Variable | Default | Description |
|----------|---------|-------------|
| `github_base` | in-cluster FQDN | GitHub emulator URL |
| `jira_base` | in-cluster FQDN | Jira emulator URL |
| `org` | `opendatahub-io` | Target org on github.local |
| `github_token` | `""` | Real GitHub PAT for upstream clones |
| `seed_rfe` | `true` | Create demo RFE ticket after setup |

**Running the workflow:**

```bash
# Via markov CLI
markov run var/demos/end-to-end/

# Via markovd API
curl -s -X POST "https://markovd.local/api/v1/runs" \
  -H "Content-Type: application/json" \
  -d '{"workflow_name": "end-to-end", "vars": {"seed_rfe": true}}'

# Via Makefile
make demo-reset
```

The workflow uses `shell_exec` + `curl` for all API calls (consistent with existing Markov workflows), and `for_each` to fan out repo imports with concurrency 3.

### Phase 0: Prepare Services And Projects

Required local services:

- `jira.local`
- `github.local`
- `dashboard.local`
- `observatory.local`
- `mlflow.local`
- `markovd.local` (for workflow execution)
- Kubernetes namespace `ai-pipeline`

Required Jira projects (created by the `reset-jira` sub-workflow):

- `RHAIRFE` for feature requests (seeded by Jira emulator defaults)
- `RHAISTRAT` for strategies (seeded by Jira emulator defaults)
- `RHAIFIRST` for epics produced by `epic-creator` and remediation tickets (created via stub issue import — not in Jira emulator seed data)

All 11 repos from the inventory above should exist on github.local. Run `markov run var/demos/end-to-end/` to wipe and re-import everything from scratch.

### Phase 1: Select And Create The RFE

Select one of the three candidate RFEs (Option A: diagnose, Option B: resources, Option C: validate) or a hybrid. This is a gate — the choice determines what claims the rest of the demo exercises.

Create a `RHAIRFE` ticket using the selected RFE text.

Output:

- Selected RFE option (recorded for traceability)
- `RHAIRFE-N`

### Phase 2: Run RFE Skills

Run the RFE speedrun/review/submit path through the dashboard job API.

Expected outputs:

- refined RFE content in Jira
- RFE artifacts under `/app/artifacts/rfe-*`
- dashboard job records
- MLflow run/traces
- OTEL logs/traces in Observatory
- strace and raw API body artifacts

### Phase 3: Run STRAT Skills

Run strategy creation, refinement, and review against the RFE.

Expected outputs:

- `RHAISTRAT-N`
- strategy artifacts under `/app/artifacts/strat-*`
- strategy review artifacts
- the same observability evidence as Phase 2

### Phase 4: Epic Pipeline (DAG)

Three repos handle the STRAT → implementation path. This phase is a DAG, not a linear sequence: `epic-creator` produces multiple epics with typed dependency edges, `epic-investigator` resolves investigation epics first, and `epic-code-gen` runs on implementation epics whose dependencies are satisfied. Epics without investigation gates can proceed to code generation in parallel with ongoing investigations.

```
                          ┌─ investigation-1 ──→ go/no-go ─┐
STRAT ─→ epic-creator ──→├─ investigation-2 ──→ go/no-go ─├──→ epic-code-gen (per ready impl epic) ──→ PR
                          ├─ implementation-A (blocked by 1)┘
                          ├─ implementation-B (blocked by 2)┘
                          └─ implementation-C (no gate) ────────→ epic-code-gen ──→ PR
```

**Step 4a: Decompose strategy into epics**

Run `epic-decompose` from `epic-creator` against the strategy ticket. This breaks the STRAT into implementation epics — each one a scoped work unit with acceptance criteria, dependencies, and estimated effort. Some epics may be typed as "investigation" (technical unknowns that need resolution before implementation can proceed).

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/epic-creator@main:epic-decompose",
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

Expected outputs:

- EPIC tickets in Jira (e.g., `RHAIFIRST-1` through `RHAIFIRST-N`)
- Epic artifacts under `/app/artifacts/`
- Each epic typed as implementation or investigation

**Step 4b: Investigate technical unknowns**

Run `epic-investigate` from `epic-investigator` against any investigation-type epics. This runs a 5-phase loop per epic: classify questions → investigate (one agent per question, dispatched to the cheapest evidence tier) → adversarial validation → synthesize findings → publish go/no-go report.

Evidence tiers:

- **Tier 0 (Desk):** Source audits, docs, architecture-context, web research — sandbox-safe
- **Tier 1 (Local process):** Run binaries or probe libraries in sandbox — degrades to Tier 2 if sandbox can't handle it
- **Tier 2 (Deferred):** Requires containers/clusters — not executed, emits a runnable spec

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/epic-investigator@main:epic-investigate",
    "args": {
      "issue": "RHAIFIRST-N",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true
    }
  }'
```

Expected outputs:

- `investigation-report.md` attached to the epic
- Go/no-go status label on the epic
- Findings feed into sibling implementation epics

**Step 4c: Generate code from implementation epics**

Run `epic-codegen` from `epic-code-gen` against implementation epics that have a go status (or no investigation dependency). This runs a 4-phase pipeline: spec & plan (discovers patterns in target repo, generates TDD plan) → implementation (subagent clones target repo, writes failing tests, implements, verifies) → review (4 independent reviewers: architecture 30%, tests 30%, lint 20%, intent 20%; pass threshold: weighted avg >= 8.0, no dimension < 6.0) → iterate (up to 3 fix cycles if review fails).

```bash
curl -s -X POST "http://dashboard.local/api/jobs/submit" \
  -H "Content-Type: application/json" \
  -d '{
    "fqn": "github.local/opendatahub-io/epic-code-gen@main:epic-codegen",
    "args": {
      "issue": "RHAIFIRST-N",
      "model": "opus",
      "runner": "cli",
      "strace": true,
      "mlflow": true,
      "otel": true,
      "extra_kwargs": "target_repo=github.local/opendatahub-io/odh-cli"
    }
  }'
```

The `target_repo` tells `epic-code-gen` which repo to clone and open a PR against. For the demo this is always `odh-cli`. If the skill doesn't support `extra_kwargs` for this, the epic Jira ticket should carry a `target_repo` label or custom field set during Step 4a.

Expected outputs:

- PR on `github.local/opendatahub-io/odh-cli`
- Review scores from 4 independent reviewer agents
- Implementation artifacts with test evidence

**Claim analysis scope:** All three epic phases produce claim-bearing artifacts. The investigation reports contain architectural claims about what is/isn't feasible. The code generation phase produces implementation claims about API surfaces, dependencies, and component boundaries. All of these feed into Phase 5 extraction alongside the RFE and STRAT artifacts.

### Phase 5: Extract Claims

Run `extract-claims` against the generated artifacts.

Inputs:

- `RHAIRFE-N`
- `RHAISTRAT-N`
- EPIC keys (`RHAIFIRST-N`)

Expected outputs:

- claims JSON under `/app/artifacts/claims/`
- ingested claims in Observatory
- claim counts by artifact and type

The extraction phase should include claims from generated artifacts, not just final review summaries. The point is to evaluate the artifacts that downstream teams would consume.

### Phase 6: Verify Claims

Run `verify-claims` against the extracted claims.

Evidence sources:

- architecture-context
- original Jira RFE/STRAT/EPIC text
- source repos on `github.local`
- source artifacts in `/app/artifacts`

Expected verdicts:

- `supported`
- `refuted`
- `insufficient`
- `inconclusive`

Important distinction:

- `refuted` means available evidence contradicts the claim.
- `insufficient` means the claim may be true, but the available evidence cannot support it.

That distinction drives remediation routing.

### Phase 7: Explain Failures

Run `explain-claims` for refuted, insufficient, and inconclusive claims.

Evidence sources:

- verification logs
- original generated artifacts
- job logs
- MLflow traces
- OTEL logs/traces
- strace file access data
- raw API bodies where available

Root cause categories:

- `insufficient_context`: architecture-context or source docs lack needed coverage
- `stale_context`: docs exist but are outdated
- `source_misinterpretation`: the agent read relevant evidence but distorted it
- `context_confusion`: the agent mixed components, versions, or documents
- `training_data_hallucination`: the agent introduced plausible facts not grounded in accessed sources
- `claim_skill_gap`: extraction, verification, or explanation logic is wrong or too weak
- `artifact_bug`: the generated RFE/STRAT/EPIC artifact itself needs correction
- `unknown`: evidence is not enough to assign cause

### Phase 8: Route Fixes

Create `RHAIFIRST` remediation tickets from the explained claims.

Routing table:

| Root Cause | Fix Target | Example Fix |
|------------|------------|-------------|
| `insufficient_context` | `architecture-context` | Add missing RHOAI CRD, operator, or CLI dependency documentation |
| `stale_context` | `architecture-context` | Update component docs to match source repo |
| `source_misinterpretation` | skill prompt repo | Add citation and source-fidelity guardrails |
| `context_confusion` | architecture-context or skill prompt | Add disambiguation, version rules, or per-source citation rules |
| `training_data_hallucination` | skill prompt repo | Add stricter grounding instructions and claim verification gate |
| `claim_skill_gap` | claim skills repo | Fix extractor/verifier/explainer instructions or scripts |
| `artifact_bug` | generated Jira artifact or generating skill | Correct the artifact and improve the generator |

Each ticket should include:

- claim IDs
- original claim text
- verdict and confidence
- root cause category
- evidence paths
- proposed fix target
- rerun criteria

### Phase 9: Apply Fixes

Use remediation skills or manual PRs to fix the right repository.

Likely first-demo fixes:

- architecture-context: document RHOAI operator CRDs, `odh-cli` internal patterns, or component health-check conventions
- strat-creator: require per-source citations and prohibit unstated platform facts
- claim skills: improve classification when a claim is true in source code but unsupported by architecture-context

Fixes should land as PRs on `github.local`, not directly on upstream public repos.

### Phase 10: Rerun Stages A → B → C → D

Rerun the full workflow (RFE → STRAT → Epics DAG → Code PRs) after applying fixes.

Use the same original RFE and compare against the same major artifacts:

- original RFE run → fixed RFE run
- original STRAT run → fixed STRAT run
- original EPIC decomposition → fixed EPIC decomposition
- original code generation → fixed code generation (if the fix affects the target repo or epic content)

The rerun should use the fixed branch or updated repo for the relevant input:

- fixed architecture-context branch for context fixes
- fixed skill branch/FQN for prompt or claim-skill fixes
- same model and runner where possible

### Phase 11: Compare Before And After

Run claim extraction and verification again on the rerun artifacts.

Compare at three levels:

1. **Targeted claim comparison**
   - Did the claims tied to remediation tickets become supported?
   - Did unsupported claims disappear because the generated artifact stopped making them?
   - Did evidence quality improve?

2. **Artifact-level comparison**
   - total claims
   - supported/refuted/insufficient/inconclusive counts
   - claim types affected
   - new refuted claims introduced

3. **System-level comparison**
   - which repos required fixes
   - which skills produced better outputs
   - whether architecture-context coverage improved
   - whether the claim skills classified root causes more accurately

Success criteria:

- targeted refuted/insufficient claims become supported or disappear for a good reason
- no new high-confidence refuted claims appear in the same area
- generated strategy/epic artifacts cite architecture evidence more precisely
- Observatory shows a visible before/after improvement for the Jira issue
- MLflow, OTEL, strace, and raw API bodies provide enough evidence to explain what changed

## Role Of agent-eval-harness

`agent-eval-harness` is not on the main demo path.

It may still be useful for:

- nightly regression suites over known hallucination cases
- model comparison before changing model aliases
- prompt safety checks across a broader corpus
- measuring general skill quality over time

For this demo, the validation mechanism is the actual pipeline rerun plus claim delta in Observatory. The unit under test is the operational RFE/STRAT/EPIC flow, not a synthetic benchmark.

## Role Of Markov

The first demo can be run manually or scripted through dashboard API calls.

Markov/markovd is the natural next step:

- watch for completed generation jobs
- trigger claim extraction and verification
- route failure classes to remediation skills
- gate reruns on PR merge or branch availability
- stop the loop when targeted claims are fixed or when manual review is required

The plan should avoid depending on Markov for the first runnable demo, but it should make clear that Markov is the orchestration layer for turning this into a continuous self-improvement loop.

## What The Audience Sees

1. A realistic RFE enters Jira — a new `rhai-cli` subcommand targeting RHOAI cluster operations (selected from the candidate RFEs above).
2. Dashboard jobs produce RFE and STRAT artifacts — the planning phases.
3. `epic-creator` decomposes the strategy into implementation and investigation epics.
4. `epic-investigator` resolves technical unknowns — what RHOAI CRDs exist? What Go client libraries does `odh-cli` use? — and publishes go/no-go reports.
5. `epic-code-gen` takes an approved implementation epic, generates Go code against `odh-cli`, runs 4 independent reviewers, and opens a PR on `github.local`.
6. Observatory shows extracted claims from all artifacts — RFE, STRAT, investigation reports, and generated code.
7. Verification marks some claims supported, some insufficient, and maybe some refuted.
8. Explanation ties each failure to missing context, prompt overreach, source confusion, or claim-skill weakness.
9. RHAIFIRST remediation tickets appear for fixable failures.
10. PRs appear in `github.local` against architecture-context or skill repos.
11. The same workflow is rerun with fixes applied.
12. Observatory shows the before/after claim delta.
13. The demo closes with a concrete statement: "The system planned a feature, decomposed it into epics, investigated unknowns, generated code, found its own unsupported claims, fixed the right inputs, and produced better grounded artifacts on rerun."

## Open Questions

- Should architecture-context fixes be tested from a branch, or should the demo merge them into the local `main` branch before rerun?
- How should Observatory link before/after claims when wording changes: exact text, fuzzy match, source artifact section, or explicit remediation ticket references?
- Should remediation ticket creation be its own skill, or should `explain-claims` produce a triage manifest consumed by a separate `file-remediation-tickets` skill?
- How much of the first demo should be Markov-driven versus dashboard-driven?
- `epic-investigator` Tier 2 items (requiring containers/clusters) produce runnable specs but don't execute them. Should the demo include a manual Tier 2 execution step, or treat deferred items as out of scope?
