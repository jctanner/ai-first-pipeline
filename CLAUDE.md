# AI-First Pipeline

Integration and deployment repository for the RHOAI AI-first engineering
pipeline. It contains the original Python CLI and Flask dashboard, plus the K3s
manifests and automation that assemble a larger set of independently developed
component services. The Python pipeline is still active; it is one execution
path in the platform, not the whole platform.

The broader platform defines, runs, observes, evaluates, and governs AI-native
software-engineering workflows against realistic but isolated Jira, GitHub,
GitLab, CI, and telemetry services. Its reference end-to-end scenario turns a
business request into reviewed planning artifacts and implementation work:

```text
RFE -> quality gate -> strategy -> review -> epics -> investigation/codegen
```

Because the environment can be reset and seeded, the same workflow can be
replayed with different skills, models, harnesses, runners, policies, and source
revisions. This makes the repository both an execution platform and a testbed
for comparing AI-assisted engineering practices.

The grand vision is a continuous-improvement loop. Workflow outputs and traces
are decomposed into claims, checked against versioned evidence, and attributed
to the layer responsible for a failure. Those findings should drive targeted
changes to skills, context, retrieval, workflows, models, tools, or policy and
then become regression cases for the next run:

```text
skills + context + models + policy
                 |
                 v
           workflow execution
                 |
                 v
       artifacts + traces + claims
                 |
                 v
      evidence-based verification
                 |
                 v
         root-cause attribution
                 |
                 v
 targeted improvement + regression replay
```

## Quick Reference

```bash
uv sync                                    # Install dependencies
python main.py <command> [options]          # Run a pipeline phase
python main.py dashboard --port 5000       # Launch web dashboard
make host-deploy-all                       # Build/deploy the complete K3s stack
make host-status                           # Inspect deployed services
checkouts/markovd/bin/markovd-cli projects sync ai-first-pipeline --wait
# See var/demos/end-to-end/README.md for the complete reference scenario
```

## Prerequisites

- Python 3.13+
- `uv` package manager
- Google Cloud credentials (Vertex AI)
- Jira access (REST API token)
- Podman or Docker (container image builds); Podman is required for patch validation
- K3s and kubectl (full component stack only)

## Environment

Create `.env` in the project root (gitignored):

```
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=global
ANTHROPIC_VERTEX_PROJECT_ID=<gcp-project-id>
JIRA_SERVER=https://issues.redhat.com
JIRA_USER=<email>
JIRA_TOKEN=<api-token>
ATLASSIAN_MCP_URL=http://127.0.0.1:8081/sse   # optional MCP server
```

## Commands

### Bug Analysis Pipeline
| Command | Description |
|---------|-------------|
| `bug-fetch` | Fetch RHOAIENG bugs from Jira into `issues/` |
| `bug-completeness` | Score bug quality (0-100) |
| `bug-context-map` | Map bugs to architecture context and repos |
| `bug-fix-attempt` | Attempt AI-generated code fixes |
| `bug-test-plan` | Generate test plans |
| `bug-write-test` | Write QE tests for opendatahub-tests |
| `bug-all` | Run phases 2-6 in dependency order |

### RFE Pipeline
| Command | Description |
|---------|-------------|
| `rfe-create` | Create RFE from problem statement |
| `rfe-review` | Review/score RFE with rubric |
| `rfe-split` | Split oversized RFE |
| `rfe-submit` | Submit RFE to RHAIRFE Jira project |
| `rfe-speedrun` / `rfe-all` | End-to-end RFE pipeline |

### Strategy Pipeline
| Command | Description |
|---------|-------------|
| `strat-create` | Create strategies from approved RFEs |
| `strat-refine` | Add HOW, dependencies, NFRs |
| `strat-review` | Adversarial review |
| `strat-submit` | Push to RHAISTRAT Jira tickets |
| `strat-security-review` | Security-focused threat assessment |
| `strat-all` | Run full strategy pipeline |

### Common Flags
- `--model {sonnet,opus,haiku}` - Claude model (default: opus). Bug phases accept multiple `--model` flags.
- `--max-concurrent N` - Parallel agent limit (default: 5)
- `--issue KEY` - Process specific issue(s); repeatable
- `--limit N` - Process first N issues
- `--force` - Regenerate existing outputs
- `--component NAME` - Filter by Jira component (bug phases)

## Project Structure

```
main.py                     # Entry point (CLI dispatcher)
pyproject.toml              # Dependencies (uv)
var/
  pipeline-skills.yaml      # Phase-to-skill mapping and invocation config
  skills-registry.yaml      # Staging registry for external skill plugins
  markov-workflows/          # Markov workflow definitions
.env                        # Credentials (gitignored)

src/
  cli/
    cli.py                  # Argument parsing
    phases.py               # Phase orchestrators, agent launcher, batch runner
    agent_runner.py          # Claude Agent SDK wrapper
    prompts.py              # Skill prompt extraction and injection
    skill_config.py         # pipeline-skills.yaml parser
    schemas.py              # JSON Schema definitions for phase outputs
    paths.py                # Workspace path utilities
    repo_mapping.py          # Upstream/midstream/downstream repo name resolution
    validation.py           # Podman container patch validation
  dashboard/
    webapp.py               # Flask dashboard (SSE activity feed)
    report_data.py          # Dashboard data loading
    rfe_data.py             # RFE artifact loading
    stats.py                # Aggregate statistics
    k8s_orchestrator.py     # K8s job management
    mlflow_client.py        # MLflow API client
    templates/              # Jinja2 HTML templates
    static/js/              # Frontend JavaScript

scripts/
  fetch_bugs.py             # Standalone Jira fetch
  attach_to_jira.py         # Attach artifacts to Jira tickets
  clean.sh                  # Reset workspaces and logs

deploy/
  k8s/                      # K3s resources for every deployed component
  scripts/                  # 19-step install/build/deploy automation
  dashboard/                # Container image for the local Flask dashboard
  pipeline-agent/           # Job image for the Python/SDK execution path
  golang-reverse-proxy/     # Host-facing *.local reverse proxy
  repos/                    # External component checkouts (gitignored)

.claude/skills/             # Local agent skill definitions (SKILL.md files)
  bug-completeness/         # Score bug quality
  bug-context-map/          # Map to architecture context
  bug-fix-attempt/          # Generate code fixes
  bug-test-plan/            # Design test plans
  bug-write-test/           # Write QE tests
  patch-validation/         # Validate patches in containers
  strat-security-review/    # Security threat assessment
  strat-submit/             # Push strategies to Jira

remote_skills/rfe-creator/  # External repo (gitignored) with RFE/strategy skills
.context/                   # External architecture context repos (gitignored)
```

`checkouts/` is deliberately not source-controlled here. The build scripts
expect sibling checkouts such as `github-emulator`, `jira-emulator`,
`gitlab-emulator`, `markov`, `markovd`, and `observatory` to be populated there.
Changes inside those directories belong to their component repositories, not
to this repository.

### Generated Directories (gitignored)
- `issues/` - Fetched Jira JSON and phase output files
- `workspace/` - Cloned midstream repos per issue + model-specific outputs
- `logs/` - Structured activity logs (`activity.jsonl`) and phase logs
- `artifacts/security-reviews/` - Full analytical security reviews (on-disk reference)
- `artifacts/security-requirements/` - Actionable security requirements (attached to Jira)

## Architecture

### Platform Capabilities

- **Workflow composition** - Markov workflows sequence skills and service API
  operations with conditions, fan-out, concurrency, reusable sub-workflows,
  facts, and quality gates.
- **Interchangeable execution** - Jobs can select Claude Code or OpenCode and
  SDK, shell, or `agentic-ci` runners rather than embedding one agent harness
  into the workflow definition.
- **Realistic isolation** - Jira and forge emulators support destructive,
  repeatable integration scenarios without changing production systems.
- **Governance** - Rubric labels and workflow gates demonstrate policy checks;
  the same mechanism can enforce human approval, security, evidence, test,
  budget, or repository policies.
- **Observability and evaluation** - MLflow, OpenTelemetry, strace,
  Elasticsearch, and Observatory connect job behavior, cost, artifacts, and
  claim verification to workflow outcomes.
- **Continuous improvement** - Verification findings are routed to the layer
  that should change, and historical scenarios become regression tests for
  skill, context, retrieval, workflow, model, harness, and policy revisions.
- **Provenance** - Jira issues, workflow and skill versions, model/harness
  choices, source revisions, traces, artifacts, and gate decisions can form an
  auditable lineage from intent to implementation.
- **Closed-loop delivery** - The service set can extend code generation into
  branches or pull requests, CI execution, failure diagnosis, repair, review,
  and outcome-driven evaluation.

The reference implementation is `var/demos/end-to-end/`. It resets Jira,
GitHub, Observatory, MLflow, artifact storage, and context storage; imports
repositories; seeds an RFE; and runs the RFE-to-strategy-to-epic-to-code chain.
Use its README and workflow definitions as the best example of how the
components are intended to work together.

### Improvement Feedback Loop

Observatory is intended to be the quality system for the platform, not only a
post-run hallucination dashboard. It extracts atomic claims from artifacts,
gathers evidence, records supported/refuted/insufficient/inconclusive verdicts,
and helps identify why a result failed. The corrective action depends on that
root cause:

| Finding | Improvement target |
|---------|--------------------|
| Skill ignored evidence that was available | Skill instructions and examples |
| Required evidence did not exist | Architecture or domain context |
| Retrieval selected irrelevant evidence | Indexing, queries, and retrieval policy |
| Workflow omitted validation or review | Markov workflow and gates |
| Agent lacked the required capability | Harness, runner, or tool policy |
| Source material was stale or contradictory | Human-owned documentation |
| Model failed despite sufficient evidence | Prompt, model choice, or escalation rule |
| Claim cannot be verified automatically | Human-review gate |

Prefer this attribution model when diagnosing poor output. Do not treat every
refuted or unsupported claim as a prompt defect. Preserve the originating issue,
artifact, workflow/skill revision, source revision, evidence, verifier, and
verdict so improvements can be evaluated against the same case.

Useful regression metrics include claim support/refutation rates, evidence
coverage, cross-verifier agreement, human-review rate, recurring regressions,
duration and cost, and downstream CI or acceptance outcomes. These metrics
should eventually participate in Markov gates so evidence quality can control
whether work advances.

### Component Inventory

| Component | Role | Source / deployment |
|-----------|------|---------------------|
| Python CLI and pipeline agent | Direct phase execution through Claude Agent SDK or OpenCode; patch validation and batch runs | `main.py`, `src/cli/`, `deploy/pipeline-agent/` |
| Pipeline dashboard | Reviews artifacts, launches Kubernetes Jobs, streams activity, and links to platform services | `src/dashboard/`, `deploy/dashboard/` |
| Markov | Declarative workflow CLI executed by workflow jobs | external `checkouts/markov/`; definitions in `var/markov-workflows/` |
| markovd | Workflow API/UI, run state, approval gates, and Kubernetes job orchestration | external `checkouts/markovd/`; PostgreSQL side service |
| Observatory | Collects CI artifacts/traces, extracts and verifies claims, and reports pipeline quality | external `checkouts/observatory/` |
| MLflow | Agent trace and experiment store | upstream MLflow image with persistent SQLite/artifacts |
| Elasticsearch | Search index populated from MLflow traces by sync jobs/scripts | upstream Elasticsearch image |
| GitHub emulator | GitHub REST/GraphQL, Git transport, web UI, and admin surface for isolated tests | external `checkouts/github-emulator/` |
| GitLab emulator | GitLab API/git/CI test surface | external `checkouts/gitlab-emulator/` |
| Jira emulator | Jira v2/v3 API, UI, snapshots, and MCP-compatible issue operations | external `checkouts/jira-emulator/` |
| GitLab Runner | Runs emulator CI jobs with the Kubernetes executor | upstream runner chart/image in `gitlab-runner` namespace |
| Ingress/TLS | Traefik, cert-manager internal CA, and Go `*.local` host proxy | `deploy/k8s/`, `deploy/golang-reverse-proxy/` |

The `checkouts/` directory can contain additional reference or dependency
checkouts (for example agent SDKs, agentic-ci, skill repos, and upstream tools).
Do not assume every directory there is a deployed service; the Kubernetes
manifests and `deploy/scripts/deploy-all.sh` are the authoritative deployment
inventory.

### Skill System

Skills are defined as `SKILL.md` files containing agent instructions. Two invocation methods:

- **Templated** - SKILL.md content injected directly into agent prompt (bug analysis phases). Deterministic and batch-friendly.
- **Native** - Agent uses SDK skill discovery via `Skill` tool. Used for RFE/strategy phases where agents need the full external repo context (CLAUDE.md, scripts, sub-skills).

Configuration lives in `var/pipeline-skills.yaml`, which maps each phase to its skill, source repo, invocation method, and allowed tools.

### Workspace Model

Each bug issue gets: `workspace/{ISSUE_KEY}/{model_id}/`
- `src/` - Cloned midstream (opendatahub-io) repo
- `{phase}.json` - Structured output (validated against JSON Schema)
- `{phase}.md` - Human-readable output
- `{phase}.log` - Agent execution log

Invalid outputs are renamed to `*.invalid` and don't block re-runs.

### Repo Mapping

Three-tier contribution model: upstream -> midstream (opendatahub-io) -> downstream (Red Hat).
Fixes always target midstream. `src/cli/repo_mapping.py` resolves names across tiers.

### Validation Loop

Fix attempts can be validated in Podman containers using `odh-tests-context` recipes. On failure, validation feedback is injected into a retry prompt for self-correction (configurable retries via `--validation-retries`).

### Dashboard

Flask app with PicoCSS + vanilla JS. In addition to artifact views for bugs,
RFEs, strategies, and epics, it submits and monitors Kubernetes Jobs, exposes
MLflow-backed run/trace data, provides admin operations, and streams activity
through Server-Sent Events (SSE). Launch locally with
`python main.py dashboard`.

### Concurrency

Phases run agents in parallel via asyncio semaphore. Default 5 concurrent agents. Activity events pushed to the dashboard for live monitoring.

## Key Conventions

- All phase outputs are validated against JSON Schema (draft 2020-12) defined in `src/cli/schemas.py`
- RFE/strategy artifacts use YAML frontmatter for structured metadata
- The `--model` flag determines the workspace subdirectory path for bug phases
- MCP servers (e.g., Atlassian) are configured per-phase in `var/pipeline-skills.yaml`
- Jira projects: `RHOAIENG` (bugs), `RHAIRFE` (RFEs), `RHAISTRAT` (strategies)

## Development Notes

- `src/cli/phases.py` is the largest module (~3,300 lines) containing all phase orchestration logic
- `src/dashboard/webapp.py` contains the Flask dashboard with Jinja2 templates
- The `.context/` directory holds git-cloned architecture docs; these are not checked in
- `remote_skills/rfe-creator/` is a separate git repo cloned into place; it has its own `CLAUDE.md`
- `checkouts/*` are separate, ignored repositories. Read and follow the
  component's own `AGENTS.md` or `CLAUDE.md` before changing one.
- `deploy/scripts/deploy-all.sh` and `deploy/k8s/*.yaml` define the current
  integrated stack; older design documents under `deploy/docs/` may describe
  superseded execution paths.
