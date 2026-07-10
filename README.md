# AI-First Pipeline

AI-driven pipeline for triaging, analyzing, and fixing RHOAI (Red Hat OpenShift AI) engineering bugs, managing RFEs, and developing strategies using Claude agents.

The pipeline orchestrates Claude Agent SDK sessions to fetch Jira issues, score bug completeness, map bugs to architecture context, attempt automated code fixes against midstream repos, validate patches in containers, generate test plans, create and review RFEs, and develop implementation strategies. A Flask dashboard provides a web UI for reviewing results across all pipelines.

```mermaid
graph TB
    subgraph host["Host Machine"]
        proxy["Go Reverse Proxy<br/>*.local TLS routing"]
    end

    subgraph k3s["K3s Cluster"]
        direction TB

        subgraph core["Core Services"]
            dashboard["Pipeline Dashboard<br/>dashboard.local"]
            markov["Markov<br/>markov.local<br/>Workflow Engine"]
            mlflow["MLflow<br/>mlflow.local<br/>Experiment Tracking"]
            es["Elasticsearch<br/>Trace Indexing"]
            observatory["Observatory<br/>observatory.local<br/>Claim Verification"]
        end

        subgraph emulators["Service Emulators"]
            github["GitHub Emulator<br/>github.local"]
            gitlab["GitLab Emulator<br/>gitlab.local"]
            jira["Jira Emulator<br/>jira.local"]
            runner["GitLab Runner<br/>K8s Executor"]
        end

        subgraph infra["Infrastructure"]
            certmgr["cert-manager<br/>Internal CA"]
            traefik["Traefik<br/>Ingress Controller"]
        end

        jobs["Pipeline Agent Jobs<br/>Claude SDK"]
    end

    proxy --> traefik
    traefik --> dashboard & mlflow & markov & observatory
    traefik --> github & gitlab & jira
    runner --> gitlab
    dashboard --> jira & mlflow
    jobs --> jira & github
    mlflow --> es
    certmgr -.->|TLS certs| traefik
```

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Podman](https://podman.io/) (for patch validation containers)
- Git
- Vertex AI credentials (the Claude Agent SDK connects via Google Cloud)
- K3s (for the full deployment stack; optional for CLI-only usage)

### External data directories

The pipeline uses a `.context/` directory (gitignored) for external reference data:

- **`.context/architecture-context/`** — architecture docs for RHOAI components (read-only reference for agents)
- **`.context/odh-tests-context/`** — test context files (`.json` + `.md`) describing how to lint/test each repo in a container

RFE and strategy skills live in an external repo:

- **`remote_skills/rfe-creator/`** — cloned repo with RFE/strategy skill definitions, scripts, and its own `CLAUDE.md`

These are gitignored and must be cloned or populated separately.

## Setup

```bash
# Clone and enter the project
git clone git@github.com:jctanner/ai-first-pipeline.git
cd ai-first-pipeline

# Create virtualenv and install dependencies
uv sync

# Create .env with Vertex AI credentials
cat > .env <<'EOF'
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=global
ANTHROPIC_VERTEX_PROJECT_ID=<your-project-id>

# For Jira access (fetch phase + rfe-creator skills)
JIRA_SERVER=https://issues.redhat.com
JIRA_USER=<your-email>
JIRA_TOKEN=<your-jira-pat>

# Optional: Atlassian MCP server for enhanced Jira integration
# ATLASSIAN_MCP_URL=http://127.0.0.1:8081/sse
EOF
```

## Usage

```bash
python main.py <command> [options]
```

### Commands

| Command | Description |
|---------|-------------|
| **Bug analysis** | |
| `bug-fetch` | Fetch open RHOAIENG bugs from Jira into `issues/` |
| `bug-completeness` | Score each bug's report quality (0-100) and classify issue type |
| `bug-context-map` | Map each bug to available architecture context and repos |
| `bug-fix-attempt` | Clone midstream repos and attempt AI-generated fixes |
| `bug-test-plan` | Generate test plans based on fix attempts |
| `bug-write-test` | Write QE tests for opendatahub-tests |
| `bug-all` | Run all bug analysis phases per-issue with dependency ordering |
| **RFE management** | |
| `rfe-create` | Write a new RFE from a problem statement or idea |
| `rfe-review` | Review and improve an RFE (rubric scoring, feasibility, auto-revision) |
| `rfe-split` | Split an oversized RFE into smaller, right-sized RFEs |
| `rfe-submit` | Submit or update RFEs in Jira (RHAIRFE project) |
| `rfe-speedrun` / `rfe-all` | End-to-end RFE pipeline: create/fetch, review, auto-fix, submit |
| **Strategy management** | |
| `strat-create` | Create strategies from approved RFEs |
| `strat-refine` | Refine strategies with HOW, dependencies, and NFRs |
| `strat-review` | Adversarial review of refined strategies |
| `strat-submit` | Push refined strategy content to RHAISTRAT Jira tickets |
| `strat-security-review` | Security-focused threat assessment of strategies |
| `strat-all` | Run full strategy pipeline (refine, review, submit, security-review) |
| **Dashboard** | |
| `dashboard` | Launch the Flask web dashboard |

### Common options

```
--model {sonnet,opus,haiku}   Claude model (default: opus); repeatable for bug phases
--max-concurrent N            Parallel agent limit (default: 5)
--issue KEY                   Process a specific issue (e.g., RHOAIENG-37036, RHAIRFE-1234); repeatable
--limit N                     Process only the first N issues
--force                       Regenerate existing outputs
--component NAME              Filter by Jira component (substring match, bug phases)
```

### Examples

```bash
# Score completeness for a single bug
python main.py bug-completeness --issue RHOAIENG-13921

# Run fix attempts for all ai-fixable bugs, max 3 at a time
python main.py bug-fix-attempt --triage ai-fixable --max-concurrent 3

# Re-run issues that previously couldn't be fixed
python main.py bug-fix-attempt --recommendation ai-could-not-fix

# Run fix attempt with no post-fix validation
python main.py bug-fix-attempt --issue RHOAIENG-13921 --skip-validation

# Full bug pipeline for 10 issues using haiku
python main.py bug-all --limit 10 --model haiku

# End-to-end RFE pipeline
python main.py rfe-speedrun --issue RHAIRFE-1234

# Review a strategy
python main.py strat-review --issue RHAISTRAT-400

# Security review of a strategy
python main.py strat-security-review --issue RHAISTRAT-400

# Launch the dashboard
python main.py dashboard --port 8080
```

## Pipeline Architecture

### Bug Analysis Pipeline

```
Jira (RHOAIENG)
     |
     v
+-----------+
| 1. Fetch  |  Download issue JSON to issues/
+-----+-----+
      |
      v
+--------------+   +--------------+
|2. Complete-  |   | 3. Context   |   (run in parallel per issue)
|   ness       |   |    Map       |
+------+-------+   +------+-------+
       |                  |
       +--------+---------+
                v
       +----------------+
       | 4. Fix Attempt |  Clone midstream repos, generate patch
       +-------+--------+
               |
               v
       +----------------+
       |  Validation    |  Spin up podman container, run lint + tests
       |  Loop (0-N)    |  On failure: feed errors back to fix agent
       +-------+--------+
               |
               v
       +----------------+     +----------------+
       | 5. Test Plan   |     | 6. Write Test  |
       +----------------+     +----------------+
```

Each issue flows through phases independently, sharing a concurrency pool. Phases 2 and 3 run in parallel since they're independent. Phase 4 waits for both, and phases 5-6 wait for phase 4.

### RFE Pipeline

```
Problem statement / Jira (RHAIRFE)
     |
     v
+-----------+     +-----------+     +-----------+     +-----------+
|  Create   | --> |  Review   | --> |  Split    | --> |  Submit   |
|  (draft)  |     | (rubric)  |     | (if needed)|    | (to Jira) |
+-----------+     +-----------+     +-----------+     +-----------+

rfe-speedrun / rfe-all runs the full sequence automatically.
```

### Strategy Pipeline

```
Approved RFEs (RHAIRFE) --> Jira (RHAISTRAT)
     |
     v
+-----------+     +-----------+     +-----------+     +-----------------+
|  Create   | --> |  Refine   | --> |  Review   | --> | Security Review |
|  (draft)  |     | (HOW/NFR) |     | (adversarial)|  | (threat model)  |
+-----------+     +-----------+     +-----------+     +-----------------+
                                         |
                                         v
                                    +-----------+
                                    |  Submit   |
                                    | (to Jira) |
                                    +-----------+

strat-all runs refine, review, submit, and security-review in sequence.
```

## How It Works

### Skill system

Each phase is driven by a Claude agent loaded with a **skill** — instructions defined in a `SKILL.md` file. Skills are invoked in two ways:

- **Templated** — SKILL.md content is extracted and injected into the agent prompt. Used for bug analysis phases. Deterministic and batch-friendly.
- **Native** — Agent discovers skills via SDK `Skill` tool. Used for RFE/strategy phases where the agent needs full repo context (CLAUDE.md, scripts, sub-skills).

Skill-to-phase mapping is configured in `var/pipeline-skills.yaml`.

| Skill | Source | Invoke | Agent tools | Purpose |
|-------|--------|--------|-------------|---------|
| `bug-completeness` | local | templated | Read, Write, Glob, Grep | Score bug quality, classify type, recommend triage |
| `bug-context-map` | local | templated | Read, Write, Glob, Grep | Map bug to architecture docs and repos |
| `bug-fix-attempt` | local | templated | Read, Write, Glob, Grep | Analyze root cause, edit source, produce patch |
| `bug-test-plan` | local | templated | Read, Write, Glob, Grep | Design verification strategy |
| `bug-write-test` | local | templated | Read, Write, Glob, Grep | Write QE tests for opendatahub-tests |
| `patch-validation` | local | native | Read, Write, Glob, Grep, Bash | Run lint/tests in podman, report results |
| `strat-security-review` | local | native | Read, Write, Glob, Grep, Bash | Security threat assessment |
| `strat-submit` | local | native | Read, Glob, Grep, Bash | Push strategies to RHAISTRAT Jira |
| `rfe.*` skills | rfe-creator | native | Read, Write, Edit, Glob, Grep, Bash | RFE lifecycle (create, review, split, submit) |
| `strat.*` skills | rfe-creator | native | Read, Write, Edit, Glob, Grep, Bash | Strategy lifecycle (create, refine, review) |

### Fix attempt workflow

1. The orchestrator clones midstream repos into `workspace/{KEY}/{model_id}/src/`
2. The fix agent reads architecture docs, analyzes the bug, and edits source files
3. The orchestrator captures `git diff` from the workspace
4. If validation is enabled, a podman container is started using the recipe from `odh-tests-context`
5. The validation agent runs lint and tests via `podman exec`
6. On failure, errors are fed back to a fresh fix agent for retry (up to `--validation-retries` iterations)
7. Self-corrections from retries are captured for aggregate analysis

### Repo mapping

RHOAI uses a three-tier contribution flow: **upstream** (e.g., `kserve/kserve`) -> **midstream** (e.g., `opendatahub-io/kserve`) -> **downstream** (e.g., `red-hat-data-services/kserve`). Fixes target midstream. The `src/cli/repo_mapping.py` module handles name resolution between tiers and shallow-clones repos into workspaces.

## Output Files

### Bug outputs

Bug phase outputs are stored per-issue in `workspace/{KEY}/{model_id}/`:

| File | Content |
|------|---------|
| `completeness.json` | Completeness score, dimensions, triage recommendation |
| `completeness.md` | Human-readable completeness report |
| `context-map.json` | Component mapping, context rating, relevant files |
| `context-map.md` | Human-readable context map |
| `fix-attempt.json` | Root cause, patch, recommendation, validation results, self-corrections |
| `fix-attempt.md` | Human-readable fix attempt report |
| `test-plan.json` | Unit/integration/regression test specifications |
| `test-plan.md` | Human-readable test plan |

Raw Jira issue JSON is stored in `issues/{KEY}.json`.

Invalid outputs are renamed to `*.invalid` and won't block re-runs.

### RFE/Strategy outputs

RFE and strategy artifacts use YAML frontmatter and are managed by the `rfe-creator` skill repo. Security reviews are written to `security-reviews/`.

### Fix attempt recommendations

| Value | Meaning |
|-------|---------|
| `ai-fixable` | Working code fix produced |
| `already-fixed` | Bug is already resolved in current code |
| `not-a-bug` | Feature request, enhancement, or by-design behavior |
| `docs-only` | Documentation change, not a code fix |
| `upstream-required` | Fix must go to an upstream repo first |
| `insufficient-info` | Bug report lacks detail to attempt a fix |
| `ai-could-not-fix` | AI attempted but failed to produce a fix |

## Dashboard

```bash
python main.py dashboard
```

Opens a Flask web app at `http://localhost:5000` with:

- **Multi-tab view** — All Issues, Bugs, RFEs, Strategies, Epics
- **Issue detail pages** — full Jira data alongside completeness scores, context maps, fix attempts with patches, validation results, self-corrections, and test plans
- **RFE detail pages** — task content, reviews, and tabbed sections
- **Strategy detail pages** — metadata, review summaries, and tabbed content
- **K8s Jobs page** — submit, monitor, and inspect pipeline jobs running in the cluster
- **Activity feed** — live pipeline progress via SSE
- **Stats page** — aggregate statistics across all issues
- **Admin panel** — service configuration and management
- **File browser** — browse generated artifacts on disk

When deployed in the K3s stack, the dashboard is available at `https://dashboard.local` with navbar links to all cluster services (MLflow, Markov, GitHub, GitLab, Jira, Observatory).

## K8s Deployment Stack

The project includes a full K3s-based deployment stack for running the pipeline and its supporting services in a single-node Kubernetes cluster.

### Deployed Services

| Service | Namespace | URL | Purpose |
|---------|-----------|-----|---------|
| Pipeline Dashboard | ai-pipeline | `https://dashboard.local` | Web UI for bugs, RFEs, strategies, jobs |
| GitHub Emulator | ai-pipeline | `https://github.local` | Git hosting and GitHub API emulation |
| GitLab Emulator | ai-pipeline | `https://gitlab.local` | GitLab API emulation with CI/CD pipelines |
| Jira Emulator | ai-pipeline | `https://jira.local` | Jira REST API emulation for ticket management |
| GitLab Runner | gitlab-runner | — | In-cluster CI runner (Kubernetes executor) |
| MLflow | ai-pipeline | `https://mlflow.local` | Experiment tracking and agent trace logging |
| Markov (markovd) | ai-pipeline | `https://markov.local` | Workflow engine for multi-phase pipelines |
| Elasticsearch | ai-pipeline | — | Trace indexing and search |
| Observatory | ai-pipeline | `https://observatory.local` | Claim extraction and verification |
| Go Reverse Proxy | ai-pipeline | — | Routes `*.local` hostnames to internal services via TLS |

### Infrastructure

- **K3s** — lightweight Kubernetes (single-node)
- **cert-manager** — automatic TLS certificate provisioning with an internal CA
- **Traefik** — ingress controller for internal routing
- **Go reverse proxy** — routes `*.local` DNS names from the host to cluster services with TLS passthrough

### Deployment

```bash
# Full stack deployment (19 steps)
make host-deploy-all

# Or step by step
make host-install-k3s
make host-images          # Build all container images
make host-deploy-all      # Apply k8s manifests, wait for readiness
```

### Makefile Targets

The Makefile provides targets for both Vagrant VM (`vagrant-*`) and bare-metal host (`host-*`) deployment:

| Target Group | Examples | Purpose |
|-------------|----------|---------|
| `host-deploy-*` | `host-deploy-all`, `host-deploy-dashboard` | Deploy services |
| `host-rebuild-*` | `host-rebuild-dashboard`, `host-rebuild-gitlab` | Build image + restart deployment |
| `host-logs-*` | `host-logs-dashboard`, `host-logs-gitlab` | Tail service logs |
| `host-images` | | Build all container images |
| `host-status` | | Cluster pod/service status |
| `host-es-sync` | | Sync MLflow traces to Elasticsearch |
| `host-backup` / `host-restore` | | Backup and restore all service data |
| `host-deploy-gitlab-runner` | | Deploy GitLab Runner with k8s executor |

### Backup and Restore

```bash
make host-backup                    # Backup all service data
make host-backup-full               # Include workspace and context PVCs
make host-restore BACKUP=<path>     # Restore from a backup
make host-list-backups              # List available backups
```

## Project Structure

```
ai-first-pipeline/
├── main.py                  # Entry point (CLI dispatcher)
├── pyproject.toml           # Dependencies and project metadata
├── Makefile                 # Build, deploy, and operational targets
├── var/
│   ├── pipeline-skills.yaml # Phase-to-skill mapping and invocation config
│   ├── skills-registry.yaml # Staging registry for external skill plugins
│   └── markov-workflows/    # Markov workflow definitions (batch RFE, strategy, etc.)
├── .env                     # Vertex AI and Jira credentials (gitignored)
├── CLAUDE.md                # Claude Code project context
├── src/
│   ├── cli/
│   │   ├── agent_runner.py  # Claude Agent SDK launcher
│   │   ├── cli.py           # Argument parsing
│   │   ├── paths.py         # Workspace path utilities
│   │   ├── phases.py        # Phase orchestrators, batch runner, validation loop
│   │   ├── prompts.py       # Skill prompt extraction and injection
│   │   ├── repo_mapping.py  # Upstream/midstream/downstream name mapping
│   │   ├── schemas.py       # JSON Schema validation for phase outputs
│   │   ├── skill_config.py  # pipeline-skills.yaml parser
│   │   └── validation.py    # Container lifecycle and validation agent runner
│   └── dashboard/
│       ├── webapp.py        # Flask dashboard (PicoCSS, SSE activity feed)
│       ├── report_data.py   # Dashboard data loading (bugs)
│       ├── rfe_data.py      # Dashboard data loading (RFEs)
│       ├── stats.py         # Aggregate statistics
│       ├── k8s_orchestrator.py # K8s job submission and monitoring
│       ├── mlflow_client.py # MLflow API client
│       ├── templates/       # Jinja2 HTML templates
│       └── static/js/       # Frontend JavaScript
├── deploy/
│   ├── k8s/                 # Kubernetes manifests (namespace, certs, services, deployments)
│   ├── scripts/             # Build and deployment automation (19-step deploy-all.sh)
│   ├── golang-reverse-proxy/  # Go reverse proxy for *.local TLS routing
│   └── repos/               # Cloned emulator and service repos (gitignored)
│       ├── github-emulator/ # GitHub API emulator
│       ├── jira-emulator/   # Jira API emulator
│       └── gitlab-emulator/ # GitLab API emulator with CI/CD
├── .claude/skills/          # Local agent skill definitions
│   ├── bug-completeness/    # Score bug quality, classify type
│   ├── bug-context-map/     # Map bug to architecture docs and repos
│   ├── bug-fix-attempt/     # Analyze root cause, edit source, produce patch
│   ├── bug-test-plan/       # Design verification strategy
│   ├── bug-write-test/      # Write QE tests for opendatahub-tests
│   ├── patch-validation/    # Run lint/tests in containers
│   ├── strat-security-review/ # Security threat assessment
│   ├── strat-submit/        # Push strategies to Jira
│   ├── extract-claims/      # Observatory: extract verifiable claims
│   ├── verify-claims/       # Observatory: verify claims against evidence
│   ├── explain-claims/      # Observatory: explain claim verification results
│   └── doc-*/               # Documentation generation skills
├── remote_skills/           # External skill repos (gitignored)
│   └── rfe-creator/         # RFE/strategy skills, scripts, CLAUDE.md
├── .context/                # External context data (gitignored)
│   ├── architecture-context/  # RHOAI component architecture docs
│   └── odh-tests-context/     # Test recipes for container validation
├── scripts/
│   ├── fetch_bugs.py        # Standalone Jira fetch script
│   ├── attach_to_jira.py    # Attach artifacts to Jira tickets
│   └── clean.sh             # Reset workspaces and logs
├── docs/                    # Architecture docs, plans, notes, reference, bugs
├── bugs/                    # Bug analysis notes and summaries
├── artifacts/               # Security reviews and requirements (gitignored)
├── issues/                  # Fetched Jira JSON (gitignored)
├── workspace/               # Cloned repos and phase outputs per issue (gitignored)
└── logs/                    # Activity logs and phase logs (gitignored)
    └── activity.jsonl       # Structured event feed for dashboard SSE
```

## Service Emulators

The deployment stack includes local emulators for GitHub, GitLab, and Jira so the pipeline can run end-to-end without depending on external services. Each emulator lives in `deploy/repos/` and is built into a container image deployed to the cluster.

| Emulator | URL | API | Purpose |
|----------|-----|-----|---------|
| **GitHub Emulator** | `https://github.local` | GitHub REST API | Git hosting, pull requests, issues, `gh` CLI workflows |
| **GitLab Emulator** | `https://gitlab.local` | GitLab REST API | Git hosting, CI/CD pipelines, merge requests, `glab` CLI workflows |
| **Jira Emulator** | `https://jira.local` | Jira REST API v2/v3 | Issue tracking, project management, MCP server for Claude integration |

The Jira emulator includes a built-in MCP (Model Context Protocol) server, enabling Claude agents to interact with Jira tickets directly during pipeline runs.

The GitLab emulator supports CI/CD pipeline execution via an in-cluster **GitLab Runner** (Kubernetes executor) that polls for jobs and runs them as pods in the `gitlab-runner` namespace.

Each emulator runs on SQLite — no external database required. Data persists on PVCs within the cluster.

## Markov Workflows

The pipeline integrates with [Markov](https://markov.local), a workflow engine that orchestrates multi-phase pipelines as declarative YAML definitions. Workflow definitions live in `var/markov-workflows/`:

| Workflow | Purpose |
|----------|---------|
| `batch-rfe-pipeline.yaml` | Batch RFE processing (create, review, submit) |
| `batch-rfe-to-strategy.yaml` | Convert batch of RFEs to strategies |
| `rfe-to-strategy.yaml` | Single RFE to strategy conversion |
| `rfe-pipeline-with-gates.yaml` | RFE pipeline with approval gates |
| `arch-context-benchmark.yaml` | Architecture context quality benchmarking |

## Observatory

The Observatory service extracts verifiable claims from pipeline artifacts (RFEs, strategies, security reviews) and checks them against evidence. It runs as a cluster service and has dedicated skills:

- **extract-claims** — parse artifacts into discrete, testable claims
- **verify-claims** — check each claim against source material and codebase evidence
- **explain-claims** — produce human-readable verification summaries

## Jira Projects

| Project | Purpose |
|---------|---------|
| `RHOAIENG` | Engineering bugs |
| `RHAIRFE` | Requests for Enhancement |
| `RHAISTRAT` | Implementation strategies |

## Documentation

See [docs/README.md](docs/README.md) for the full documentation index covering architecture, deployment, plans, reference material, notes, and the agentic work ledger methodology.
