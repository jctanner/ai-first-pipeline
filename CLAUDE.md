# AI-First Pipeline

AI-driven pipeline for triaging, analyzing, and fixing RHOAI (Red Hat OpenShift AI) engineering bugs, managing RFEs, and developing strategies. Uses Claude Agent SDK on Vertex AI to orchestrate multi-phase workflows against Jira.

## Quick Reference

```bash
uv sync                                    # Install dependencies
python main.py <command> [options]          # Run a pipeline phase
python main.py dashboard --port 5000       # Launch web dashboard
```

## Prerequisites

- Python 3.13+
- `uv` package manager
- Google Cloud credentials (Vertex AI)
- Jira access (REST API token)
- Podman (for patch validation only)

## Environment

Create `.env` in the project root (gitignored):

```
CLAUDE_CODE_USE_VERTEX=1
CLOUD_ML_REGION=us-east5
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
pipeline-skills.yaml        # Phase-to-skill mapping and invocation config
.env                        # Credentials (gitignored)

lib/
  cli.py                    # Argument parsing
  phases.py                 # Phase orchestrators, agent launcher, batch runner
  agent_runner.py            # Claude Agent SDK wrapper
  prompts.py                # Skill prompt extraction and injection
  skill_config.py           # pipeline-skills.yaml parser
  schemas.py                # JSON Schema definitions for phase outputs
  paths.py                  # Workspace path utilities
  repo_mapping.py            # Upstream/midstream/downstream repo name resolution
  validation.py             # Podman container patch validation
  webapp.py                 # Flask dashboard (SSE activity feed)
  report_data.py            # Dashboard data loading
  rfe_data.py               # RFE artifact loading
  stats.py                  # Aggregate statistics

scripts/
  fetch_bugs.py             # Standalone Jira fetch
  attach_to_jira.py         # Attach artifacts to Jira tickets
  clean.sh                  # Reset workspaces and logs

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

### Generated Directories (gitignored)
- `issues/` - Fetched Jira JSON and phase output files
- `workspace/` - Cloned midstream repos per issue + model-specific outputs
- `logs/` - Structured activity logs (`activity.jsonl`) and phase logs
- `artifacts/security-reviews/` - Full analytical security reviews (on-disk reference)
- `artifacts/security-requirements/` - Actionable security requirements (attached to Jira)

## Architecture

### Skill System

Skills are defined as `SKILL.md` files containing agent instructions. Two invocation methods:

- **Templated** - SKILL.md content injected directly into agent prompt (bug analysis phases). Deterministic and batch-friendly.
- **Native** - Agent uses SDK skill discovery via `Skill` tool. Used for RFE/strategy phases where agents need the full external repo context (CLAUDE.md, scripts, sub-skills).

Configuration lives in `pipeline-skills.yaml`, which maps each phase to its skill, source repo, invocation method, and allowed tools.

### Workspace Model

Each bug issue gets: `workspace/{ISSUE_KEY}/{model_id}/`
- `src/` - Cloned midstream (opendatahub-io) repo
- `{phase}.json` - Structured output (validated against JSON Schema)
- `{phase}.md` - Human-readable output
- `{phase}.log` - Agent execution log

Invalid outputs are renamed to `*.invalid` and don't block re-runs.

### Repo Mapping

Three-tier contribution model: upstream -> midstream (opendatahub-io) -> downstream (Red Hat).
Fixes always target midstream. `lib/repo_mapping.py` resolves names across tiers.

### Validation Loop

Fix attempts can be validated in Podman containers using `odh-tests-context` recipes. On failure, validation feedback is injected into a retry prompt for self-correction (configurable retries via `--validation-retries`).

### Dashboard

Flask app with PicoCSS + vanilla JS. Tabs for bugs, RFEs, and strategies. Real-time activity feed via Server-Sent Events (SSE). Launch with `python main.py dashboard`.

### Concurrency

Phases run agents in parallel via asyncio semaphore. Default 5 concurrent agents. Activity events pushed to the dashboard for live monitoring.

## Key Conventions

- All phase outputs are validated against JSON Schema (draft 2020-12) defined in `lib/schemas.py`
- RFE/strategy artifacts use YAML frontmatter for structured metadata
- The `--model` flag determines the workspace subdirectory path for bug phases
- MCP servers (e.g., Atlassian) are configured per-phase in `pipeline-skills.yaml`
- Jira projects: `RHOAIENG` (bugs), `RHAIRFE` (RFEs), `RHAISTRAT` (strategies)

## Development Notes

- `lib/phases.py` is the largest module (~3,300 lines) containing all phase orchestration logic
- `lib/webapp.py` (~180KB) contains inline Jinja2 templates via DictLoader
- The `.context/` directory holds git-cloned architecture docs; these are not checked in
- `remote_skills/rfe-creator/` is a separate git repo cloned into place; it has its own `CLAUDE.md`
