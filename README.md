# Bug Bash Analyzer

AI-driven pipeline for triaging, analyzing, and fixing RHOAIENG Jira bugs using Claude agents.

The pipeline fetches open bugs from Jira, scores them for completeness, maps them to architecture context, attempts automated fixes against midstream (opendatahub-io) repository clones, validates patches with lint and tests, and generates test plans. A Flask dashboard provides a web UI for reviewing results.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Podman](https://podman.io/) (for patch validation containers)
- Git
- Vertex AI credentials (the Claude Agent SDK connects via Google Cloud)

### External data directories

The pipeline expects two symlinked directories in the project root:

- **`architecture-context/`** — architecture docs for RHOAI components (read-only reference for agents)
- **`odh-tests-context/`** — test context files (`.json` + `.md`) describing how to lint/test each repo in a container

These are gitignored and must be symlinked or populated separately.

## Setup

```bash
# Clone and enter the project
cd bug-bash

# Create virtualenv and install dependencies
uv sync

# Create .env with Vertex AI credentials
cat > .env <<'EOF'
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
ANTHROPIC_VERTEX_PROJECT_ID=<your-project-id>

# For Jira access (fetch phase + rfe-creator skills)
JIRA_SERVER=https://issues.redhat.com
JIRA_USER=<your-email>
JIRA_TOKEN=<your-jira-pat>
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
| `rfe-submit` | Submit or update RFEs in Jira |
| **Strategy management** | |
| `strat-create` | Create strategies from approved RFEs |
| `strat-refine` | Refine strategies with HOW, dependencies, and NFRs |
| `strat-review` | Adversarial review of refined strategies |
| **Reporting** | |
| `report` | Launch the Flask web dashboard |

### Common options

```
--model {sonnet,opus,haiku}   Claude model (default: opus)
--max-concurrent N            Parallel agent limit (default: 5)
--issue RHOAIENG-XXXXX        Process a single issue
--limit N                     Process only the first N issues
--force                       Regenerate existing outputs
--component NAME              Filter by Jira component (substring match)
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

# Review an RFE
python main.py rfe-review --issue RHAIRFE-1234

# Review a strategy
python main.py strat-review --issue RHAISTRAT-400

# Launch the dashboard
python main.py report --port 8080
```

## Pipeline Architecture

```
Jira (RHOAIENG)
     │
     ▼
┌──────────┐
│ 1. Fetch │  Download issue JSON to issues/
└────┬─────┘
     │
     ▼
┌──────────────┐   ┌──────────────┐
│2. Complete-  │   │ 3. Context   │   (run in parallel per issue)
│   ness       │   │    Map       │
└──────┬───────┘   └──────┬───────┘
       │                  │
       └────────┬─────────┘
                ▼
       ┌────────────────┐
       │ 4. Fix Attempt │  Clone midstream repos, generate patch
       └───────┬────────┘
               │
               ▼
       ┌────────────────┐
       │  Validation    │  Spin up podman container, run lint + tests
       │  Loop (0-N)    │  On failure: feed errors back to fix agent
       └───────┬────────┘
               │
               ▼
       ┌────────────────┐
       │ 5. Test Plan   │  Generate verification strategy
       └────────────────┘
```

Each issue flows through phases independently, sharing a concurrency pool. Phases 2 and 3 run in parallel since they're independent. Phase 4 waits for both, and phase 5 waits for phase 4.

## How It Works

### Agent skills

Each phase is driven by a Claude agent loaded with a **skill** (prompt template) from `.claude/skills/`:

| Skill | Agent tools | Purpose |
|-------|-------------|---------|
| `bug-completeness` | Read, Write, Glob, Grep | Score bug report quality, classify issue type, recommend triage |
| `bug-context-map` | Read, Write, Glob, Grep | Map bug to architecture docs and midstream repos |
| `bug-fix-attempt` | Read, Write, Glob, Grep | Analyze root cause, edit source code, produce patch |
| `patch-validation` | Read, Write, Glob, Grep, **Bash** | Run lint/tests in a podman container, report results |
| `bug-test-plan` | Read, Write, Glob, Grep | Design verification strategy for the fix |

Agents run via the [Claude Agent SDK](https://docs.anthropic.com/en/docs/agents/claude-agent-sdk), which launches independent Claude Code sessions with tool access.

### Fix attempt workflow

1. The orchestrator clones midstream repos into `fix-workspaces/{KEY}/`
2. The fix agent reads architecture docs, analyzes the bug, and edits source files
3. The orchestrator captures `git diff` from the workspace
4. If validation is enabled, a podman container is started using the recipe from `odh-tests-context`
5. The validation agent runs lint and tests via `podman exec`
6. On failure, errors are fed back to a fresh fix agent for retry (up to `--validation-retries` iterations)
7. Self-corrections from retries are captured for aggregate analysis

### Repo mapping

RHOAI uses a three-tier contribution flow: **upstream** (e.g., `kserve/kserve`) → **midstream** (e.g., `opendatahub-io/kserve`) → **downstream** (e.g., `red-hat-data-services/kserve`). Fixes target midstream. The `lib/repo_mapping.py` module handles name resolution between tiers and shallow-clones repos into workspaces.

## Output Files

All outputs land in `issues/` alongside the raw Jira JSON:

| File | Content |
|------|---------|
| `RHOAIENG-XXXXX.json` | Raw Jira issue data |
| `RHOAIENG-XXXXX.completeness.json` | Completeness score, dimensions, triage recommendation |
| `RHOAIENG-XXXXX.completeness.md` | Human-readable completeness report |
| `RHOAIENG-XXXXX.context-map.json` | Component mapping, context rating, relevant files |
| `RHOAIENG-XXXXX.context-map.md` | Human-readable context map |
| `RHOAIENG-XXXXX.fix-attempt.json` | Root cause, patch, recommendation, validation results, self-corrections |
| `RHOAIENG-XXXXX.fix-attempt.md` | Human-readable fix attempt report |
| `RHOAIENG-XXXXX.test-plan.json` | Unit/integration/regression test specifications |
| `RHOAIENG-XXXXX.test-plan.md` | Human-readable test plan |

Invalid outputs are renamed to `*.json.invalid` and won't block re-runs.

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
python main.py report
```

Opens a Flask web app at `http://localhost:5000` with:

- **Issues table** — sortable and filterable by status, triage, component, context, fix recommendation
- **Issue detail pages** — full Jira data alongside completeness scores, context maps, fix attempts with patches, validation results, self-corrections, and test plans
- **Activity feed** — live pipeline progress via SSE
- **Readiness view** — component-level validation readiness
- **Stats page** — aggregate statistics across all issues

## Project Structure

```
bug-bash/
├── main.py                  # Entry point
├── pyproject.toml           # Dependencies and project metadata
├── .env                     # Vertex AI and Jira credentials (gitignored)
├── lib/
│   ├── agent_runner.py      # Claude Agent SDK launcher
│   ├── cli.py               # Argument parsing
│   ├── phases.py            # Phase orchestrators and validation loop
│   ├── prompts.py           # Skill-based prompt builder
│   ├── repo_mapping.py      # Downstream/midstream/upstream name mapping
│   ├── report_data.py       # Data loading for the dashboard
│   ├── schemas.py           # JSON schema validation for phase outputs
│   ├── stats.py             # Aggregate statistics
│   ├── validation.py        # Container lifecycle and validation agent runner
│   └── webapp.py            # Flask dashboard
├── .claude/skills/          # Agent skill definitions (gitignored)
│   ├── bug-completeness/
│   ├── bug-context-map/
│   ├── bug-fix-attempt/
│   ├── bug-test-plan/
│   └── patch-validation/
├── architecture-context/    # Symlink to component architecture docs (gitignored)
├── odh-tests-context/       # Symlink to test context files (gitignored)
├── issues/                  # Jira data and phase outputs (gitignored)
├── fix-workspaces/          # Cloned midstream repos per issue (gitignored)
├── logs/                    # Agent logs and activity journal (gitignored)
│   ├── activity.jsonl       # Structured activity log
│   ├── completeness/
│   ├── context-map/
│   └── fix-attempt/
└── scripts/
    └── fetch_bugs.py        # Standalone Jira fetch script
```

## Aggregate Queries

The structured JSON outputs enable analysis across runs:

```bash
# Count fix recommendations
jq -r '.recommendation' issues/*.fix-attempt.json | sort | uniq -c | sort -rn

# Find high-confidence fixes
jq -r 'select(.confidence == "high") | .issue_key' issues/*.fix-attempt.json

# List self-correction categories across all issues
jq -r '.self_corrections[]?.mistake_category' issues/*.fix-attempt.json | sort | uniq -c | sort -rn

# Find issues where the fix agent changed its approach
jq -r 'select(.self_corrections[]?.was_original_approach_wrong == true) | .issue_key' issues/*.fix-attempt.json

# Average completeness scores
jq -s '[.[].overall_score] | add / length' issues/*.completeness.json
```
