# Plan: Skill Factory Demo

## Problem

We need a demo that shows the full agentic SDLC platform in action — not just "AI wrote code" but a closed-loop system that creates, tests, evaluates, and iterates on its own capabilities. Every service in the stack should be visible and playing its role.

## Concept

The `opendatahub-io/architecture-decision-records` repo is stale and unmaintained. The `opendatahub-io/architecture-context` repo and the individual component repos (with their commit histories) contain the ground truth about what actually happened architecturally — but nobody has written it up as ADRs.

The demo imports both repos into github.local, then uses a Markov workflow to autonomously rebuild the ADR repo. Along the way, the agents create the skills they need to do the work — commit log parsers, architectural signal detectors, ADR drafters, cross-referencers — and test and iterate on those skills until they meet a quality bar. The skills are the means, not the end; the rebuilt ADR repo is the deliverable.

## Two-Layer Workflow

The demo has two interleaved loops: an **outer loop** that produces ADRs, and an **inner loop** that produces the skills needed to do that work.

```
Jira Ticket: "Rebuild ADRs for component X"
     |
     v
[1. setup]     ── Create org + repos on github.local if missing,
     |            import upstream content (idempotent)
     |
     v
[2. scope]     ── Pull ticket, identify target component + time window
     |
     v
[3. discover]  ── Scan commit logs + architecture-context for architectural shifts
     |
     |   ┌─────────────────────────────────────────────────┐
     |   │  INNER LOOP (skill factory)                     │
     |   │                                                 │
     |   │  Need a skill? (e.g., commit-signal-detector)     │
     |   │       |                                         │
     |   │  [a. generate]  ── Create SKILL.md in           │
     |   │       |            adr-skills/.claude/skills/   │
     |   │       |                                         │
     |   │  [b. test]      ── Build test corpus + CI       │
     |   │       |            on GitLab                    │
     |   │  [c. ci]        ── GitLab Runner executes       │
     |   │       |                                         │
     |   │  [d. eval]      ── Score correctness,           │
     |   │       |            determinism, coverage        │
     |   │  [e. gate]      ── Pass? Graduate skill.        │
     |   │       |            Fail? Revise + loop.         │
     |   │                                                 │
     |   └─────────────────────────────────────────────────┘
     |
     v
[4. draft]     ── Using graduated skills, draft ADR documents
     |
     v
[5. claims]    ── Extract claims from drafted ADRs, verify against
     |            source material, explain any refuted claims
     |
     v
[6. submit]    ── Open PR on github.local against the ADR repo
     |
     v
[7. review]    ── Independent reviewer agent evaluates the PR
     |            (claim verdicts included as review context)
     |
     v
[8. gate]      ── Approved + claims clean? Merge.
     |            Rejected or refuted claims? Feed back to [4].
     |
     v
[9. report]    ── Update Jira, log metrics to MLflow
```

## Skill Consumption (how graduated skills reach subsequent agents)

The pattern mirrors `strat-pipeline` on gitlab.local: CI jobs clone a skills repo at runtime, and Claude Code's native SDK skill discovery finds `.claude/skills/` automatically. The difference is that Markov triggers the pipelines via GitLab API instead of schedules.

### The flow

1. **Inner loop graduates a skill** — the `adr-author` agent pushes the new `SKILL.md` to `github.local/opendatahub-io/adr-skills` under `.claude/skills/{skill-name}/`

2. **Markov triggers a GitLab CI pipeline** — when the outer loop needs to run a phase that uses skills (draft, review), Markov calls the GitLab API to trigger a pipeline on `gitlab.local/opendatahub-io/adr-skill-tests` (or a dedicated runner repo):
   ```
   POST /api/v4/projects/:id/trigger/pipeline
   { "ref": "main", "variables": { "PHASE": "draft", "COMPONENT": "model-serving" } }
   ```

3. **The CI job clones `adr-skills` from github.local** — same pattern as `strat-pipeline` cloning `strat-creator`:
   ```yaml
   .pipeline-setup:
     before_script:
       - git clone --depth 1 https://github-emulator.ai-pipeline.svc.cluster.local/opendatahub-io/adr-skills.git /tmp/adr-skills
   ```

4. **Claude Code runs with `cwd` pointed at the cloned skills repo** — the agent discovers all graduated skills via `.claude/skills/` and can invoke them with `/{skill-name}`. The `CLAUDE.md` in `adr-skills` provides repo-level context.

5. **Markov polls the pipeline status** — waits for the CI job to complete, then reads the artifacts (ADR drafts, review results) to decide the next phase.

### Why this works

- **No deployment step** — skills become available the moment they're pushed to github.local. The next CI job clones the latest version.
- **Isolation** — each CI job gets a fresh clone, so a broken skill revision can't corrupt other runs. Rolling back is just a git revert on `adr-skills`.
- **Visibility** — every skill invocation happens inside a GitLab pipeline, so the audience can click into the job log and see exactly which skills were called and what they produced.
- **Markov controls timing** — instead of schedules or manual triggers, Markov decides when to fire each pipeline based on the workflow state (inner loop graduated? trigger draft. PR rejected? trigger revision).

### Observability integration

Every GitLab CI job must wire in the same three observability layers that the dashboard's agent runner uses (`scripts/run_skill.sh`, `k8s_orchestrator.py`). This gives the demo audience full visibility into what each agent does, and feeds metrics back into the evaluation gates.

**Strace** — syscall-level tracing of the Claude process tree:

- Set `ENABLE_STRACE=1` in the job environment
- The runner pod needs `SYS_PTRACE` capability in its security context (configured via the GitLab Runner's Kubernetes executor `cap_add` setting)
- Strace wraps the Claude invocation: `strace -ffttv -s 1024 -o ${STRACE_DIR}/${JOB_TAG} claude ...`
- Output lands in an artifacts directory: `/app/artifacts/strace/{SKILL}-{COMPONENT}/`
- Useful for debugging agent hangs, unexpected subprocess spawning, and file I/O patterns

**OpenTelemetry** — traces, metrics, and logs exported to Observatory:

- Environment variables set in `.skill-base`:
  ```yaml
  ENABLE_OTEL: "1"
  CLAUDE_CODE_ENABLE_TELEMETRY: "1"
  CLAUDE_CODE_ENHANCED_TELEMETRY_BETA: "1"
  OTEL_EXPORTER_OTLP_PROTOCOL: "http/json"
  OTEL_EXPORTER_OTLP_ENDPOINT: "http://observatory.ai-pipeline.svc.cluster.local:8000/otel"
  OTEL_METRICS_EXPORTER: "otlp"
  OTEL_LOGS_EXPORTER: "otlp"
  OTEL_TRACES_EXPORTER: "otlp"
  OTEL_LOG_USER_PROMPTS: "1"
  OTEL_LOG_TOOL_DETAILS: "1"
  OTEL_LOG_TOOL_CONTENT: "1"
  OTEL_LOG_RAW_API_BODIES: "file:/app/artifacts/apibodies/${JOB_TAG}"
  ```
- Claude Code auto-detects these and exports spans to Observatory
- Raw API request/response bodies are dumped to the artifacts volume for post-hoc analysis
- Observatory indexes traces into Elasticsearch, making them searchable on observatory.local

**MLflow** — experiment tracking for skill iterations and ADR quality:

- Environment variables:
  ```yaml
  MLFLOW_TRACKING_URI: "http://mlflow.ai-pipeline.svc.cluster.local:5000"
  MLFLOW_EXPERIMENT_NAME: "adr-pipeline/${PHASE}/${COMPONENT}"
  ```
- Before Claude invocation, run `mlflow autolog claude` to install hooks that capture conversation events, token usage, tool calls, and cost
- Each skill test iteration and each ADR draft becomes an MLflow run, so the audience can compare iterations side-by-side on mlflow.local
- Key metrics logged: `duration_ms`, `cost_usd`, `num_turns`, token counts, tool usage per tool, `is_error`
- The inner loop's gate criteria (correctness, determinism, edge coverage) are logged as MLflow metrics so threshold comparisons are queryable

### GitLab CI job structure

```yaml
# .gitlab-ci.yml in the runner repo on gitlab.local
stages:
  - execute

.skill-base:
  tags: [k8s-incluster]
  variables:
    SKILLS_REPO: "https://github-emulator.ai-pipeline.svc.cluster.local/opendatahub-io/adr-skills.git"
    ADR_REPO: "https://github-emulator.ai-pipeline.svc.cluster.local/opendatahub-io/architecture-decision-records.git"
    CONTEXT_REPO: "https://github-emulator.ai-pipeline.svc.cluster.local/opendatahub-io/architecture-context.git"
    GIT_SSL_CAINFO: "/etc/gitlab-runner/certs/ca.crt"
    # Observability
    ENABLE_STRACE: "1"
    ENABLE_OTEL: "1"
    CLAUDE_CODE_ENABLE_TELEMETRY: "1"
    CLAUDE_CODE_ENHANCED_TELEMETRY_BETA: "1"
    OTEL_EXPORTER_OTLP_PROTOCOL: "http/json"
    OTEL_EXPORTER_OTLP_ENDPOINT: "http://observatory.ai-pipeline.svc.cluster.local:8000/otel"
    OTEL_METRICS_EXPORTER: "otlp"
    OTEL_LOGS_EXPORTER: "otlp"
    OTEL_TRACES_EXPORTER: "otlp"
    OTEL_LOG_USER_PROMPTS: "1"
    OTEL_LOG_TOOL_DETAILS: "1"
    OTEL_LOG_TOOL_CONTENT: "1"
    MLFLOW_TRACKING_URI: "http://mlflow.ai-pipeline.svc.cluster.local:5000"
  before_script:
    - git clone --depth 1 "$SKILLS_REPO" /tmp/adr-skills
    - git clone --depth 1 "$CONTEXT_REPO" /tmp/architecture-context
    - git clone "$ADR_REPO" /tmp/adr-repo
    - export JOB_TAG="${PHASE}-${COMPONENT}"
    - export OTEL_LOG_RAW_API_BODIES="file:/app/artifacts/apibodies/${JOB_TAG}"
    - mkdir -p /app/artifacts/strace /app/artifacts/apibodies/${JOB_TAG}
    - mlflow autolog claude

draft-adr:
  extends: .skill-base
  stage: execute
  variables:
    MLFLOW_EXPERIMENT_NAME: "adr-pipeline/draft/${COMPONENT}"
  rules:
    - if: $PHASE == "draft"
  script:
    - cd /tmp/adr-skills
    - |
      if [ "$ENABLE_STRACE" = "1" ]; then
        STRACE_CMD="strace -ffttv -s 1024 -o /app/artifacts/strace/${JOB_TAG}"
      fi
    - ${STRACE_CMD:-} claude --skill /commit-signal-detector "$COMPONENT"
    - ${STRACE_CMD:-} claude --skill /adr-drafter "$COMPONENT"
    - cd /tmp/adr-repo && git push origin "adr/$COMPONENT"
  artifacts:
    paths:
      - /app/artifacts/strace/
      - /app/artifacts/apibodies/

review-adr:
  extends: .skill-base
  stage: execute
  variables:
    MLFLOW_EXPERIMENT_NAME: "adr-pipeline/review/${COMPONENT}"
  rules:
    - if: $PHASE == "review"
  script:
    - cd /tmp/adr-skills
    - |
      if [ "$ENABLE_STRACE" = "1" ]; then
        STRACE_CMD="strace -ffttv -s 1024 -o /app/artifacts/strace/${JOB_TAG}"
      fi
    - ${STRACE_CMD:-} claude --skill /adr-reviewer "$PR_URL"
  artifacts:
    paths:
      - /app/artifacts/strace/
      - /app/artifacts/apibodies/

# Claim analysis — runs after draft, before PR submission
# Markov triggers with PHASE=claims after draft-adr completes
claims-analyze:
  extends: .skill-base
  stage: execute
  variables:
    MLFLOW_EXPERIMENT_NAME: "adr-pipeline/claims/${COMPONENT}"
    OBSERVATORY_URL: "http://observatory.ai-pipeline.svc.cluster.local:8000"
  rules:
    - if: $PHASE == "claims"
  script:
    - cd /tmp/adr-skills
    - |
      if [ "$ENABLE_STRACE" = "1" ]; then
        STRACE_CMD="strace -ffttv -s 1024 -o /app/artifacts/strace/${JOB_TAG}"
      fi
    # Step 1: Extract claims from drafted ADRs
    - ${STRACE_CMD:-} claude --skill /adr-claim-extractor "$COMPONENT"
    # Step 2: Verify claims against commit history + architecture-context
    - ${STRACE_CMD:-} claude --skill /adr-claim-verifier "$COMPONENT"
    # Step 3: Explain any refuted/insufficient claims using OTEL + strace forensics
    - ${STRACE_CMD:-} claude --skill /adr-claim-explainer "$COMPONENT"
  artifacts:
    paths:
      - /app/artifacts/strace/
      - /app/artifacts/apibodies/
      - /app/artifacts/claims/
      - /app/artifacts/verification/
      - /app/artifacts/explanations/
```

## Example Skills the Agents Would Build

| Skill | Purpose | Test corpus |
|-------|---------|-------------|
| `commit-signal-detector` | Parse a commit log for signals of architectural shifts (new dependencies, API changes, component splits/merges, config restructuring) | 10-15 commits, labeled "architectural" or "not architectural" |
| `adr-drafter` | Given an architectural change summary + context docs, produce a well-formed ADR (status, context, decision, consequences) | 5 known architectural changes with hand-written reference ADRs |
| `context-cross-referencer` | Find relevant sections in architecture-context docs for a given commit range | Commit ranges mapped to expected architecture-context file paths |
| `adr-reviewer` | Review a draft ADR for completeness, accuracy against source material, and ADR format compliance | Draft ADRs with known issues (missing consequences, wrong dates, unsupported claims) |
| `adr-claim-extractor` | Extract verifiable factual claims from a drafted ADR document (dates, component names, dependency relationships, behavioral assertions) | 3-5 ADR drafts with hand-labeled expected claims |
| `adr-claim-verifier` | Verify extracted claims against commit history, architecture-context docs, and source repo state | Claims with known verdicts (supported/refuted) and ground-truth evidence |
| `adr-claim-explainer` | For refuted/insufficient claims, trace WHY the drafter made the claim using OTEL traces, strace output, and MLflow run data | Refuted claims with known root causes (hallucination, source confusion, stale data) |

### Claim analysis skills — how they differ from the existing pipeline skills

The project already has `extract-claims`, `verify-claims`, and `explain-claims` skills (in `.claude/skills/`), but those are purpose-built for the strat-pipeline: they parse strategy documents, verify against RHOAI architecture-context via `arch-query`, and classify root causes specific to strategy reviews (source confusion between proposals and platform state, etc.).

The ADR claim skills need to be different in several ways:

| Concern | Strat-pipeline skills | ADR skills (to be created) |
|---------|----------------------|----------------------------|
| **Source material** | Strategy `.md` files with YAML frontmatter | ADR documents (status, context, decision, consequences sections) |
| **Claim types** | factual, architectural, security, scope, attribution | temporal (dates/ordering), causal (why a decision was made), dependency (component relationships), behavioral (what changed) |
| **Verification evidence** | `arch-query` CLI + architecture-context docs + NFR checklist | Commit logs, PR descriptions, architecture-context docs, source repo file state at specific commits |
| **Ground truth** | Architecture-context is authoritative for current platform state | Commit history is authoritative — a claim like "kserve was split from KFServing in Q3 2022" can be verified against actual commits |
| **Explanation forensics** | K8s job logs, MLflow traces, strace | Same data sources, but root cause categories differ — ADR hallucinations are more likely temporal (wrong dates) or causal (inventing reasons for decisions) than security-related |

The inner loop creates these skills the same way it creates any other: generate SKILL.md → test against a corpus → evaluate → gate → graduate. The test corpus for claim skills comes from the ADR drafts produced in earlier outer-loop iterations — once the drafter has produced even one ADR, the claim extractor has input to work with.

## Phase 5: Claim Analysis

After the drafter produces ADR documents (phase 4) and before submitting PRs (phase 6), the workflow runs the graduated claim analysis skills to catch hallucinations early. This is a three-step pipeline within a single Markov phase.

### Step 1: Extract claims (`adr-claim-extractor`)

The extractor reads each drafted ADR and produces a `.claims.json` file containing atomic, verifiable statements. For ADRs, the interesting claim types are:

- **temporal** — "This change was introduced in RHOAI 2.8" (verifiable against commit dates)
- **causal** — "The team split kserve into a separate repo because of release cadence conflicts" (verifiable against PR descriptions and commit messages)
- **dependency** — "model-mesh depends on kserve's storage-initializer" (verifiable against import graphs and deployment manifests)
- **behavioral** — "After this change, inference requests are routed through the mesh instead of directly to pods" (verifiable against code diffs)

The skill POSTs extracted claims to Observatory via `POST /api/claims/ingest`, making them immediately visible on observatory.local.

### Step 2: Verify claims (`adr-claim-verifier`)

The verifier fetches pending claims from Observatory (`GET /api/hallucinations/claims?verdict=pending`) and evaluates each against:

1. **Commit history** — `git log --all --oneline --grep="keyword"` on the component repos cloned during setup
2. **Architecture-context docs** — the `architecture-context` repo imported to github.local
3. **Source repo file state** — `git show {commit}:{path}` to check what actually existed at a claimed point in time

Each claim gets a verdict (`supported`/`refuted`/`insufficient`/`inconclusive`) with a confidence score, written to Observatory via `POST /api/claims/verdicts`.

### Step 3: Explain refuted claims (`adr-claim-explainer`)

For refuted and insufficient claims, the explainer does forensic analysis using the observability data from the draft phase's CI job:

- **OTEL traces** — what tool calls did the drafter make? Did it actually read the relevant commit log or did it skip it?
- **Strace output** — what files did the process open? (Proves whether the agent had access to evidence)
- **MLflow run data** — token counts, duration, number of turns (low input tokens + high output may indicate hallucination)
- **Raw API bodies** — the actual LLM request/response pairs from `/app/artifacts/apibodies/`

Each explanation gets a root cause category and is posted to Observatory via `POST /api/claims/explanations`.

### How this feeds back into the outer loop gate

Phase 8 (gate) checks claim verdicts as part of the merge decision:

- **Zero refuted claims with confidence ≥ 80%** — required for merge. Any high-confidence refutation means the ADR contains a hallucinated fact.
- **Insufficient claims ≤ 20% of total** — if too many claims can't be verified, the ADR lacks grounding. The drafter needs to add citations.
- **Explanation patterns** — if multiple claims share the same root cause (e.g., `training_data_hallucination` for temporal claims), the feedback to phase 4 includes specific remediation: "Do not state dates without verifying against `git log --format=%ai`"

When the gate rejects, the claim verdicts and explanations are injected into the re-draft prompt so the drafter can address specific issues rather than regenerating from scratch.

## Gate Criteria

**Inner loop (skill quality):**

| Metric | Threshold | How measured |
|--------|-----------|--------------|
| **Correctness** | 100% of corpus | Skill output matches expected output per test case |
| **Determinism** | >= 4/5 identical | Run skill 5x on same input, compare structural equivalence |
| **Edge coverage** | 100% of corpus | Every test case gets a valid response |

**Outer loop (ADR quality):**

| Metric | Threshold | How measured |
|--------|-----------|--------------|
| **PR review** | Approved | Independent reviewer agent accepts the ADR |
| **Format compliance** | Pass | ADR follows the standard template (status, context, decision, consequences) |
| **Source traceability** | All claims cited | Every factual claim in the ADR links back to a commit or architecture-context section |
| **Claim accuracy** | 0 refuted (≥80% confidence) | `adr-claim-verifier` verdicts via Observatory API |
| **Claim grounding** | ≤20% insufficient | Ratio of insufficient verdicts to total extracted claims |

Max iterations capped at 5 per loop to prevent runaway.

## Services Involved

| Service | Role in demo |
|---------|-------------|
| **Jira** (jira.local) | Ticket per component: "Rebuild ADRs for X." Status updates per iteration |
| **GitHub** (github.local) | Hosts repos: `adr-skills` (skills in `.claude/skills/`), `architecture-decision-records` (target), `architecture-context` (reference) |
| **GitLab** (gitlab.local) | Hosts `adr-skill-tests` repo (test corpus, `.gitlab-ci.yml`, eval scripts) |
| **GitLab Runner** | Executes skill tests as k8s pods |
| **Markov** (markov.local) | Orchestrates both loops, enforces gates |
| **MLflow** (mlflow.local) | Logs each skill iteration + ADR iteration as experiment runs |
| **Observatory** (observatory.local) | Claim lifecycle: ingest extracted claims, store verdicts from verification, store root cause explanations. Frontend shows per-ADR claim accuracy and hallucination patterns |
| **Elasticsearch** | Indexes traces for searchability across iterations |
| **Dashboard** (dashboard.local) | Live activity feed, links to all artifacts |

## What the Audience Sees

1. A Jira ticket: "Rebuild architecture decision records for the Model Serving component"
2. Markov workflow starts — visible on markov.local
3. Setup phase runs: `opendatahub-io` org appears on github.local, repos get imported (audience sees repos populating in real time)
4. Agent scans commit logs across model-serving repos, identifies 3 architectural shifts
5. Agent needs a commit-signal-detector skill — inner loop kicks off:
   - `SKILL.md` appears in `adr-skills/.claude/skills/commit-signal-detector/` on github.local
   - Test pipeline fires on gitlab.local — first run scores 70%
   - Agent revises, pushes again — second run scores 100%, skill graduates
6. Same inner loop runs for `adr-claim-extractor`, `adr-claim-verifier`, `adr-claim-explainer` — each graduates after meeting corpus thresholds
7. Agent uses the graduated skills + adr-drafter to write 3 ADR documents
8. Claim analysis runs automatically:
   - `adr-claim-extractor` pulls 27 claims from the 3 drafts — visible on observatory.local as they're ingested
   - `adr-claim-verifier` checks each against commit history and architecture-context — 24 supported, 2 refuted, 1 insufficient
   - `adr-claim-explainer` traces the 2 refuted claims: one was a hallucinated date (training data), one confused two similarly-named components (context confusion)
   - Audience sees the full claim lifecycle on observatory.local: extraction → verdict → root cause
9. Gate rejects: 2 refuted claims with ≥80% confidence. Claim verdicts + explanations are fed back to the drafter
10. Drafter revises the 2 affected ADRs, fixing the date and component reference. Re-run: 0 refuted claims
11. PRs appear on github.local against the ADR repo
12. Reviewer agent comments on PR #1: "Missing consequences section, context doesn't reference the Knative deprecation" — claim verdicts are included as review context
13. Author agent revises, pushes updated commit — reviewer approves
14. PRs merge, Jira ticket updated, MLflow shows skill iterations + claim accuracy across ADR revisions
15. Total elapsed: ~15 minutes, fully autonomous

## Scope Control

To keep the demo focused and convergent:

- **One component** — pick a single RHOAI component (e.g., Model Serving, Dashboard, DSP) rather than the full project
- **Time window** — limit commit history to a specific range (e.g., last 6 months) to bound the number of potential ADRs
- **ADR cap** — target 2-3 ADRs per demo run, not an exhaustive rebuild

## Repo Layout

**GitHub (github.local):**
```
opendatahub-io/
  architecture-decision-records/    # Target — PRs land here
  architecture-context/             # Reference — read-only
  adr-skills/                       # Skills created by the workflow
    CLAUDE.md                       # Repo-level agent instructions
    .claude/
      skills/
        commit-signal-detector/
          SKILL.md
        adr-drafter/
          SKILL.md
        context-cross-referencer/
          SKILL.md
        adr-reviewer/
          SKILL.md
        adr-claim-extractor/
          SKILL.md
        adr-claim-verifier/
          SKILL.md
        adr-claim-explainer/
          SKILL.md
```

The `adr-skills` repo follows the standard Claude Code skill convention — each skill is a directory under `.claude/skills/` containing a `SKILL.md` file. The repo's `CLAUDE.md` provides repo-level context (what the skills are for, how they relate to the ADR rebuild workflow, coding conventions). This means any Claude agent that clones the repo can discover and invoke the skills natively via the SDK `Skill` tool.

**GitLab (gitlab.local):**
```
opendatahub-io/
  adr-skill-tests/                  # CI pipelines that validate skills
    commit-signal-detector/
      .gitlab-ci.yml
      corpus/                       # Input/output test pairs
      eval/                         # Scoring scripts
    adr-drafter/
      .gitlab-ci.yml
      corpus/
      eval/
```

Skills are developed and versioned on GitHub. The CI/CD pipelines that validate them live on GitLab. The GitLab pipeline clones `adr-skills` from github.local and invokes each skill against its test corpus.

## Idempotency

Every phase writes its output to a known path and checks for existing output before running. The workflow can be stopped and restarted at any gate boundary. Re-running a completed phase with `--force` regenerates it; without `--force`, it skips. Graduated skills persist across restarts — the inner loop only fires for skills that haven't yet met the quality bar.

The demo is additive — it creates new orgs, repos, skills, and experiments alongside whatever already exists in the stack. It does not require or perform any data wipes.

## Phase 1: Setup (repo import)

The workflow's first phase handles all repo provisioning on github.local. This is part of the workflow, not a separate deploy step — the demo is fully self-contained from a single Jira ticket.

### What phase 1 does (idempotent)

1. **Create org** — `POST /api/v3/orgs` to create `opendatahub-io` on github.local (skip if exists)
2. **Create repos** — `POST /api/v3/orgs/opendatahub-io/repos` for each repo (skip if exists)
3. **Import content** — `git clone --bare` from real GitHub, `git push --mirror` to emulator (skip if emulator repo is non-empty, checked via `git ls-remote`)

### What gets imported

| Repo | Role | Clone strategy |
|------|------|---------------|
| `architecture-decision-records` | Target — PRs land here | Full clone (small repo, need file content as baseline) |
| `architecture-context` | Reference — read-only | Full clone (agents need the doc content) |
| Component repos (e.g., `odh-dashboard`, `kserve`, `data-science-pipelines`) | Source — commit history | Blobless clone (`--filter=blob:none`) — commit graph and messages without file content |
| `adr-skills` | Skills created by the workflow | No upstream; `auto_init: true`, then seed with `CLAUDE.md` and `.claude/skills/` directory structure |

### Agent users

The setup phase creates two GitHub users with distinct roles, each with their own API token. This gives the demo a visible separation of concerns — the author and reviewer are independent actors, not the same identity talking to itself.

| User | Role | What it does |
|------|------|-------------|
| `adr-author` | Author agent | Creates skills, drafts ADRs, opens PRs, pushes revisions |
| `adr-reviewer` | Reviewer agent | Reviews PRs, posts comments, approves or requests changes, merges |

Both users are created via the emulator's admin bootstrap API (`POST /admin/users`, `POST /admin/tokens`) and added as collaborators to the relevant repos. The setup phase skips creation if the users already exist (idempotent).

```
POST /admin/users     {"login": "adr-author",   "password": "...", "name": "ADR Author",   "email": "author@adr-pipeline.local"}
POST /admin/users     {"login": "adr-reviewer", "password": "...", "name": "ADR Reviewer", "email": "reviewer@adr-pipeline.local"}
POST /admin/tokens    {"login": "adr-author",   "name": "workflow", "scopes": ["repo"]}
POST /admin/tokens    {"login": "adr-reviewer", "name": "workflow", "scopes": ["repo"]}
```

Git commits from the author agent use `adr-author` as the committer. PR reviews and merge commits come from `adr-reviewer`. The audience sees two distinct actors collaborating on github.local — PRs show the author's commits and the reviewer's comments, just like a real team.

### Auth and TLS

The workflow agent runs inside the cluster as a pipeline job pod, so it can reach `github-emulator.ai-pipeline.svc.cluster.local` directly. For git push over HTTPS, the pod needs the internal CA cert — mounted from the `internal-ca-cert` ConfigMap via `GIT_SSL_CAINFO` (same pattern as the GitLab Runner pods). Each agent operation uses the appropriate user's token for API calls and git credential.

### Why this belongs in the workflow

- The demo is one command: file ticket, start workflow, walk away
- The setup phase is idempotent — re-running the workflow doesn't re-import or re-create existing users
- Different Jira tickets can request different component sets without needing separate deploy scripts
- The audience sees the platform bootstrapping itself as step 1

## Seed Material Needed

- **Component repo list** — which repos to import for commit history (can reuse `repo_mapping.py`)
- **`adr-skills` seed content** — initial `CLAUDE.md` and empty `.claude/skills/` directory committed to the repo during setup
- **GitLab CI template** — skeleton with `.gitlab-ci.yml` wired to clone `adr-skills` from github.local and run eval
- **Rules engine config** — threshold definitions for both inner and outer loop gates
- **Markov workflow definition** — `var/markov-workflows/skill-factory-adr-rebuild.yaml`

## Open Questions

- How does the test corpus get generated — agent-written from the commit data, human-curated, or bootstrapped by a separate agent?
- Should graduated skills be registered in `var/skills-registry.yaml` automatically, or just stored on github.local?
- How does the GitLab CI pipeline authenticate to github.local to clone skills — shared CA cert in a k8s secret (same as gitlab-runner), or a git credential helper?
- Which component repos are worth importing for the demo? A focused set (3-5 repos for one component) is better than importing everything.
