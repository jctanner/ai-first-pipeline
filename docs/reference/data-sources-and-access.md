# Data Sources and Access Reference

This document catalogs every data source available in the AI-First Pipeline system, how to access it, and what fields are available. Use this as a reference when building queries, writing analysis scripts, or orienting new agents.

All services run in the `ai-pipeline` Kubernetes namespace. In-cluster URLs use `<service>.ai-pipeline.svc.cluster.local` or just `<service>` (short DNS). From the host, access is via `vagrant ssh -c "kubectl exec ..."` or the dashboard's external URL (`https://dashboard.local`).

---

## 1. Elasticsearch (Indexed Traces & Spans)

The fastest way to query pipeline execution data. Contains a mirror of MLflow traces and spans, synced via `make vagrant-sync-traces`.

**Access**: `http://elasticsearch:9200` (in-cluster)

### Index: `mlflow-traces`

One document per Claude Code trace (one agent invocation).

| Field | Type | Description |
|-------|------|-------------|
| `trace_id` | keyword | Unique trace identifier (e.g., `tr-746fda35...`) |
| `issue_keys` | keyword[] | Jira keys found in trace output (e.g., `["RHAIRFE-953", "RHAISTRAT-567"]`) |
| `status` | keyword | `OK` or `ERROR` |
| `start_time` | date | ISO 8601 timestamp |
| `duration_s` | float | Total execution time in seconds |
| `cost_usd` | float | Estimated API cost |
| `input_tokens` | integer | Prompt tokens consumed |
| `output_tokens` | integer | Completion tokens generated |
| `total_tokens` | integer | Sum of input + output tokens |
| `num_spans` | integer | Number of spans (tool calls, LLM calls) in the trace |
| `session_id` | keyword | Claude Code session ID |
| `user` | keyword | Unix user that ran the agent (e.g., `pipelineagent`) |
| `claude_code_version` | keyword | Claude Code CLI version |
| `prompt` | text | The initial prompt given to the agent |
| `response` | text | The agent's final response |

### Index: `mlflow-spans`

One document per span (individual unit of work within a trace: an LLM call, a tool invocation, etc.).

| Field | Type | Description |
|-------|------|-------------|
| `trace_id` | keyword | Parent trace ID |
| `span_id` | keyword | Unique span identifier |
| `parent_id` | keyword | Parent span ID (empty for root spans) |
| `name` | keyword | Span name (e.g., `ChatCompletion`, `Read`, `Bash`) |
| `span_type` | keyword | Category (e.g., `LLM`, `tool_Read`, `tool_Bash`, `tool_Write`) |
| `status` | keyword | `OK` or error status code |
| `start_time` | date | ISO 8601 timestamp |
| `duration_ms` | long | Execution time in milliseconds |
| `inputs` | text | JSON string of span inputs (up to 50KB, searchable) |
| `outputs` | text | JSON string of span outputs (up to 50KB, searchable) |
| `tool_name` | keyword | Tool name for tool spans |
| `issue_keys` | keyword[] | Denormalized from parent trace |
| `model` | keyword | Claude model used (for LLM spans) |
| `error` | text | Error message if span failed |

### Example Queries

```bash
# Traces for a specific issue (from host)
vagrant ssh -c 'ES=http://elasticsearch:9200; curl -s "$ES/mlflow-traces/_search?pretty" \
  -H "Content-Type: application/json" \
  -d "{\"query\": {\"term\": {\"issue_keys\": \"RHAIRFE-953\"}}}"'

# All failed traces
curl -s 'http://elasticsearch:9200/mlflow-traces/_search' \
  -H 'Content-Type: application/json' \
  -d '{"query": {"term": {"status": "ERROR"}}}'

# Spans that used the Bash tool, sorted by duration
curl -s 'http://elasticsearch:9200/mlflow-spans/_search' \
  -H 'Content-Type: application/json' \
  -d '{"query": {"term": {"span_type": "tool_Bash"}}, "sort": [{"duration_ms": "desc"}], "size": 20}'

# Full-text search across span inputs/outputs
curl -s 'http://elasticsearch:9200/mlflow-spans/_search' \
  -H 'Content-Type: application/json' \
  -d '{"query": {"multi_match": {"query": "permission denied", "fields": ["inputs", "outputs", "error"]}}}'

# Aggregate: total cost by issue
curl -s 'http://elasticsearch:9200/mlflow-traces/_search' \
  -H 'Content-Type: application/json' \
  -d '{"size": 0, "aggs": {"by_issue": {"terms": {"field": "issue_keys", "size": 100}, "aggs": {"total_cost": {"sum": {"field": "cost_usd"}}}}}}'

# Count of traces per day
curl -s 'http://elasticsearch:9200/mlflow-traces/_search' \
  -H 'Content-Type: application/json' \
  -d '{"size": 0, "aggs": {"per_day": {"date_histogram": {"field": "start_time", "calendar_interval": "day"}}}}'
```

### Syncing

```bash
make vagrant-sync-traces        # Incremental (only new traces since last sync)
make vagrant-sync-traces-full   # Delete and reindex everything
```

The sync script runs from the dashboard pod: `scripts/sync_mlflow_to_elastic.py`. It tracks a high-water mark (latest `start_time`) in Elasticsearch for incremental updates.

---

## 2. MLflow (Raw Traces & Runs)

The authoritative source of pipeline execution data. Elasticsearch mirrors this. Use MLflow directly only when you need data that hasn't been synced yet, or for the Runs API.

**Access**: `http://mlflow:5000` (in-cluster)  
**Storage**: SQLite at `/data/mlflow.db` (~2GB), artifacts at `/data/artifacts`  
**PVC**: `mlflow-data` (10Gi)

### Traces API

```bash
# List traces (paginated, max 100 per page)
curl 'http://mlflow:5000/api/2.0/mlflow/traces?experiment_ids=0&max_results=100'

# With server-side filtering (0.5s vs 18s full scan)
curl 'http://mlflow:5000/api/2.0/mlflow/traces?experiment_ids=0&max_results=100' \
  --data-urlencode 'filter=request_metadata."mlflow.traceOutputs" LIKE "%RHAIRFE-953%"'
```

Response contains `traces[]` array and `next_page_token` for pagination. Each trace has `request_id`, `timestamp_ms`, `execution_time_ms`, `status`, and `request_metadata[]` (key-value pairs containing cost, token usage, inputs/outputs).

### Runs API

Only 9 runs exist (from the ambient-runner's explicit `mlflow.start_run()` calls). Run name format: `{phase}-{ISSUE_KEY}-{runner}`.

```bash
curl -X POST 'http://mlflow:5000/api/2.0/mlflow/runs/search' \
  -H 'Content-Type: application/json' \
  -d '{"experiment_ids": ["0"], "max_results": 100}'
```

### Python Client

From within the cluster (e.g., dashboard pod):

```python
import mlflow
mlflow.set_tracking_uri("http://mlflow:5000")
client = mlflow.MlflowClient()

# Get a specific trace with all spans
trace = client.get_trace("tr-746fda35c8422225f6322f3425132d0d")
for span in trace.data.spans:
    print(span.name, span.span_id, span.attributes)
```

### Dashboard Proxy Endpoints

```bash
# Traces grouped by issue key
curl -k 'https://dashboard.local/api/mlflow/traces?grouped=1'

# Traces for a specific issue
curl -k 'https://dashboard.local/api/mlflow/traces?issue=RHAIRFE-953'

# All runs
curl -k 'https://dashboard.local/api/mlflow/runs'
```

---

## 3. Jira Emulator (Issues, Projects, Workflows)

Full Jira REST API v2/v3 emulator plus an MCP server. Contains all RHOAIENG bugs, RHAIRFE RFEs, and RHAISTRAT strategies.

**Access**: `https://jira-emulator:443` (in-cluster, HTTPS)  
**MCP SSE**: `http://jira-emulator:8081/sse`  
**Database**: SQLite at `/data/jira.db`  
**Projects**: `RHOAIENG` (bugs), `RHAIRFE` (RFEs), `RHAISTRAT` (strategies), `TEST`

### Key Endpoints

```bash
# Get a single issue
curl -k 'https://jira-emulator/rest/api/2/issue/RHOAIENG-37036'

# JQL search
curl -k 'https://jira-emulator/rest/api/2/search?jql=project=RHAIRFE+AND+status=Open&maxResults=50'

# List all issues in a project
curl -k 'https://jira-emulator/rest/api/2/search?jql=project=RHOAIENG&maxResults=1000'

# Get issue comments
curl -k 'https://jira-emulator/rest/api/2/issue/RHAIRFE-953/comment'

# List projects
curl -k 'https://jira-emulator/rest/api/2/project'

# List statuses, priorities, issue types
curl -k 'https://jira-emulator/rest/api/2/status'
curl -k 'https://jira-emulator/rest/api/2/priority'
curl -k 'https://jira-emulator/rest/api/2/issuetype'
```

### Issue Fields

Standard Jira fields: `key`, `summary`, `description`, `status`, `priority`, `issuetype`, `components`, `labels`, `assignee`, `reporter`, `created`, `updated`, `comment`, `issuelinks`, `attachment`, plus custom fields.

### MCP Tools (via SSE at port 8081)

| Tool | Parameters | Description |
|------|-----------|-------------|
| `getJiraIssue` | `issueIdOrKey` | Full issue JSON |
| `searchJiraIssuesUsingJql` | `jql`, `maxResults`, `fields` | JQL search |
| `createJiraIssue` | `projectKey`, `issueTypeName`, `summary`, ... | Create issue |
| `updateJiraIssue` | `issueIdOrKey`, `fields`, `comment` | Update issue |
| `transitionJiraIssue` | `issueIdOrKey`, `transitionName`, `comment` | Transition issue |
| `getJiraProjectMetadata` | `projectKey` | Project metadata |
| `attachFileToJiraIssue` | `issueIdOrKey`, `fileName`, `fileContent` | Upload attachment |

---

## 4. GitHub Emulator

GitHub-compatible REST API and Git Smart HTTP protocol for hosting repositories.

**Access**: `https://github-emulator:443` (in-cluster, HTTPS)  
**Database**: SQLAlchemy async  
**Features**: REST API v3, GraphQL API, Git clone/push/pull

### Key Endpoints

```bash
# List repositories
curl -k 'https://github-emulator/api/v3/repos'

# Get a repository
curl -k 'https://github-emulator/api/v3/repos/{owner}/{repo}'

# Git clone (from within cluster)
git clone https://github-emulator/{owner}/{repo}.git
```

---

## 5. Dashboard API

Aggregates data from multiple sources (filesystem, MLflow, K8s) into a single REST API. Also provides job management and file browsing.

**Access**: `http://pipeline-dashboard:5000` (in-cluster), `https://dashboard.local` (external)

### Data Endpoints

```bash
# All bug issues with phase outputs
curl -k 'https://dashboard.local/api/issues'

# All RFEs with reviews
curl -k 'https://dashboard.local/api/rfes'

# All strategies with reviews and security assessments
curl -k 'https://dashboard.local/api/strategies'

# Pipeline status
curl -k 'https://dashboard.local/api/pipeline/status'
```

### Job Management

```bash
# List all K8s jobs
curl -k 'https://dashboard.local/api/jobs'

# Filter by phase or status
curl -k 'https://dashboard.local/api/jobs?phase=bug-completeness&status=succeeded'

# Get specific job
curl -k 'https://dashboard.local/api/jobs/bug-completeness-rhoaieng-37036-opus-abc123'

# Stream job logs
curl -k 'https://dashboard.local/api/jobs/JOB_NAME/logs'

# Submit a new job
curl -k -X POST 'https://dashboard.local/api/jobs/submit' \
  -H 'Content-Type: application/json' \
  -d '{"command": "bug-completeness", "args": {"issue": "RHOAIENG-37036", "model": "opus"}}'
```

### File Browser

```bash
# List directory contents (allowed: artifacts, issues, workspace, logs, .context, tmp)
curl -k 'https://dashboard.local/api/files/list?path=/app/issues'

# Read a file
curl -k 'https://dashboard.local/api/files/read?path=/app/workspace/RHOAIENG-37036/claude-opus-4-6/completeness.json'
```

### Real-Time Event Stream (SSE)

```bash
# Subscribe to pipeline events
curl -k -N 'https://dashboard.local/api/events'
```

Event types: `manifest` (full pipeline state), `event` (individual phase events).
Fields: `type`, `issue_key`, `model`, `event`, `phase`, `timestamp`, `status`, `error`.

---

## 6. On-Disk Artifacts

Files produced by pipeline phases. Accessible via the dashboard file browser API or directly from pods/PVCs.

### Directory Layout

```
/app/
  issues/                                  # Raw Jira issue JSONs
    RHOAIENG-37036.json                    # Full Jira issue payload

  workspace/                               # Per-issue, per-model outputs
    RHOAIENG-37036/
      claude-opus-4-6/
        completeness.json                  # Bug quality score (0-100)
        context-map.json                   # Architecture mapping
        fix-attempt.json                   # AI-generated fix
        test-plan.json                     # Test plan
        write-test.json                    # Generated test code
        patch.diff                         # Code patch
        test-patch.diff                    # Test patch
        completeness.md                    # Human-readable version
        completeness.log                   # Agent execution log
        MEMORY.md                          # Agent memory from this run
        src/                               # Cloned midstream repo

  artifacts/
    rfe-tasks/                             # RFE documents (Markdown + YAML frontmatter)
      RHAIRFE-953.md
      RHAIRFE-953-comments.md
    rfe-reviews/                           # RFE review scores
      RHAIRFE-953-review.md
      RHAIRFE-953-feasibility.md
    rfe-originals/                         # Original Jira descriptions
      RHAIRFE-953.md
    strat-tasks/                           # Strategy documents
      RHAISTRAT-567.md
    strat-reviews/                         # Strategy reviews
      RHAISTRAT-567-review.md
    security-reviews/                      # Security threat assessments
      RHAISTRAT-567-security-review.md
    security-requirements/                 # Actionable security requirements
      RHAISTRAT-567-security-requirements.md
    epic-receipts/                         # Epic creation records
      RHAISTRAT-567.md

  .context/                                # Vendored dependencies (git-cloned, gitignored)
    architecture-context/                  # Sparse clone of opendatahub-io/architecture-context
      architecture/rhoai-*/                # RHOAI platform architecture docs (latest version)
    assess-rfe/                            # Clone of n1hility/assess-rfe (rubric scoring plugin)

  logs/
    activity.jsonl                         # Pipeline activity log (one JSON per line)
```

### Architecture Context & Vendored Dependencies (.context/)

The `.context/` directory is populated by the RFE skills (from the `jwforres/rfe-creator` repo) early in their lifecycle, before any review or strategy work begins. It contains two vendored dependencies:

**1. architecture-context** — Platform architecture inventory  
- **Source**: https://github.com/opendatahub-io/architecture-context  
- **Bootstrap script**: `scripts/fetch-architecture-context.sh` (in the rfe-creator skill repo)  
- **How it works**: The script auto-detects the latest RHOAI version via the GitHub API, then performs a shallow sparse clone to fetch only that version's docs:
  ```bash
  git clone --depth 1 --filter=blob:none --sparse \
    https://github.com/opendatahub-io/architecture-context .context/architecture-context
  git sparse-checkout set "architecture/$LATEST_VERSION"
  ```
- **Contents**: Component ownership, API surfaces, CRDs, integration patterns, and dependency maps for the OpenDataHub/RHOAI platform (PLATFORM.md + per-component docs)
- **Used by**: `/rfe.review` (feasibility assessment), `/strat.refine` (grounding strategy in actual components), `/strat.review` (architecture reviewer). NOT used during `/rfe.create` (RFEs describe business needs, not implementation).
- **Also used by**: Bug analysis `bug-context-map` phase for mapping bugs to architecture components.

**2. assess-rfe** — RFE quality rubric plugin  
- **Source**: https://github.com/n1hility/assess-rfe  
- **Bootstrap script**: `scripts/bootstrap-assess-rfe.sh`  
- **Used by**: `/rfe.review` and `/rfe.auto-fix` for rubric-based scoring of RFE quality (0-20 scale across 5 dimensions: what, why, open-to-how, not-a-task, right-sized)

Both are fetched on first use and cached. Subsequent runs pull updates. Can be skipped with `RFE_SKIP_BOOTSTRAP=1`. The data is read-only reference material — agents don't write to it.

### Phase Output JSON Schema

All phase outputs are validated against JSON Schema (defined in `lib/schemas.py`). Key schemas:

**completeness.json**: `overall_score` (0-100), `issue_type_assessment`, `triage_recommendation`, section scores for description, reproduction, environment, etc.

**context-map.json**: `component_mapping`, `upstream_repos`, `relevant_files`, `architecture_context`.

**fix-attempt.json**: `fix_description`, `files_changed`, `confidence`, `patch_available`.

**test-plan.json**: `test_scenarios`, `coverage_areas`, `prerequisites`.

**write-test.json**: `test_file_path`, `test_code`, `framework`, `dependencies`.

### Artifact Markdown Format

RFE and strategy artifacts use YAML frontmatter:

```markdown
---
rfe_id: RHAIRFE-953
title: "Feature Title"
status: open
priority: high
components: [dashboard]
---

# Body content in markdown...
```

### Activity Log (JSONL)

```json
{"issue_key": "RHOAIENG-37036", "event": "completed", "phase": "bug-completeness", "timestamp": "2026-04-30T12:34:56Z", "status": "success", "model": "opus", "duration_ms": 45000}
```

Event types: `started`, `completed`, `failed`, `skipped`, `pipeline_started`, `pipeline_completed`, `pipeline_failed`, `issue_started`, `issue_completed`.

---

## 7. Markovd (Workflow Engine)

Orchestrates multi-step pipeline workflows with gates and approvals.

**Access**: `http://markovd:8080` (in-cluster)  
**Database**: PostgreSQL at `markovd-postgres:5432` (db: `markovd`, user: `markovd`, password: `markovd`)  
**API Base**: `/api/v1/`  
**Health**: `GET /api/v1/health`

Workflow definitions are in `/markov.workflows/` (e.g., `rfe-pipeline-with-gates.yaml`, `batch-rfe-pipeline.yaml`).

---

## 8. Kubernetes Cluster State

The cluster itself is a data source for job status, pod health, and resource usage.

```bash
# All pods
kubectl get pods -n ai-pipeline -o wide

# All jobs with timestamps
kubectl get jobs -n ai-pipeline --sort-by=.metadata.creationTimestamp

# Job logs
kubectl logs -n ai-pipeline job/JOB_NAME

# PVC usage
kubectl get pvc -n ai-pipeline

# Service endpoints
kubectl get svc -n ai-pipeline

# Recent events
kubectl get events -n ai-pipeline --sort-by=.lastTimestamp
```

### Persistent Volume Claims

| PVC | Size | Mount | Contents |
|-----|------|-------|----------|
| `mlflow-data` | 10Gi | `/data` | SQLite DB + artifacts |
| `elasticsearch-data` | 20Gi | `/usr/share/elasticsearch/data` | ES indices |
| `jira-emulator-data` | varies | `/data` | SQLite DB + attachments |
| `github-emulator-data` | varies | `/data` | Repos + user data |
| `markovd-pgdata` | 5Gi | `/var/lib/postgresql/data` | PostgreSQL |
| `pipeline-storage` | varies | `/app/issues`, `/app/workspace`, etc. | All pipeline artifacts |

---

## 9. Skills Registry & Pipeline Configuration

The pipeline runs "skills" — agent instruction sets defined as `SKILL.md` files — against Jira issues. Skills come from multiple sources and are tracked in two configuration files.

### skills-registry/registry.yaml

The skills registry catalogs available skill plugins, their authors, source repos, and which skills each plugin provides. This is the authoritative reference for understanding what a "skill" is when you see one referenced in a job name or trace.

```bash
cat skills-registry/registry.yaml
```

**Registry**: `pipeline-staging` (staging registry for skills not yet published to opendatahub-io/skills-registry)

**Registered plugins**:

| Plugin | Author | Source Repo | Branch | Skills Provided |
|--------|--------|------------|--------|-----------------|
| `strat-creator` | ederign | ederign/strat-creator | main | strategy-create, strategy-refine, strategy-review, export-rubric, + 4 internal sub-skills |
| `strat-creator-fork` | jctanner-opendatahub-io | jctanner-opendatahub-io/eder-strat-creator | reorganize-scripts | Same 8 skills (marketplace-compatible fork) |
| `strat-creator-fix` | jctanner-opendatahub-io | jctanner-opendatahub-io/eder-strat-creator | concurrency_fixes | Same 8 skills (concurrency fixes) |

Each plugin entry tracks: version, category, author, GitHub source (owner/repo/branch), skills directory path, and a list of skills with their invocability (user-invocable vs. internal sub-skill).

### pipeline-skills.yaml

Maps skills to pipeline phases and defines how each skill is invoked at runtime.

```bash
cat pipeline-skills.yaml
```

**Skill sources** (4 external repos + local):

| Source | Repo | Local Path |
|--------|------|------------|
| `rfe-creator` | jwforres/rfe-creator (main) | `remote_skills/rfe-creator` |
| `strat-creator` | ederign/strat-creator (main) | `remote_skills/strat-creator` |
| `strat-creator-fork` | jctanner-opendatahub-io/eder-strat-creator (reorganize-scripts) | `remote_skills/strat-creator-fork` |
| `strat-creator-fix` | jctanner-opendatahub-io/eder-strat-creator (concurrency_fixes) | `remote_skills/strat-creator-fix` |
| (local) | this repo | `.claude/skills/` |

**Key fields per skill**: `name`, `source` (skill directory or repo), `invocation` (`templated` or `native`), `allowed_tools[]`, `mcp_servers[]`.

**Invocation methods**:
- **Templated** — SKILL.md content is extracted and injected directly into the agent prompt. Deterministic, batch-friendly. Used for bug analysis phases.
- **Native** — Agent uses Claude SDK skill discovery via the `Skill` tool. Used for RFE/strategy phases where agents need the full external repo context (CLAUDE.md, scripts, sub-skills).

**Skills by category** (38 total):

| Category | Skills | Source | Invocation |
|----------|--------|--------|------------|
| Bug Analysis | bug-completeness, bug-context-map, bug-fix-attempt, bug-test-plan, bug-write-test | local `.claude/skills/` | templated |
| Patch Validation | patch-validation | local `.claude/skills/` | native |
| RFE | rfe-create, rfe-review, rfe-split, rfe-submit, rfe-speedrun | rfe-creator | native |
| Strategy (from rfe-creator) | strat-create, strat-refine, strat-review | rfe-creator | native |
| Strategy (local) | strat-create-local, strat-submit, epic-create, strat-security-review | local `.claude/skills/` | native |
| Strategy (strat-creator) | strategy-create, strategy-refine, strategy-review | strat-creator | native |
| Strategy (fork) | strategy-create-fork, strategy-refine-fork, strategy-review-fork | strat-creator-fork | native |
| Strategy (fix) | strategy-create-fix, strategy-refine-fix, strategy-review-fix | strat-creator-fix | native |

When analyzing traces or jobs, the skill/phase name in the job name or trace metadata maps back to one of these entries. Multiple variants of the same skill (e.g., `strat-create` vs `strategy-create` vs `strategy-create-fix`) exist because the skills come from different authors and repos, each with their own approach.

### .env (credentials, gitignored)

Environment variables for Vertex AI, Jira, and MCP configuration. Not accessible to analysis agents but relevant for understanding what external services the pipeline connects to.

---

## Quick Reference: Choosing a Data Source

| Question | Best Source | Why |
|----------|------------|-----|
| How much did processing issue X cost? | Elasticsearch `mlflow-traces` | Fast keyword filter on `issue_keys` |
| What errors occurred in tool calls? | Elasticsearch `mlflow-spans` | Full-text search on `error` and `outputs` |
| What's the current status of issue X in Jira? | Jira emulator REST API | Live data |
| What phase outputs exist for issue X? | Dashboard `/api/files/list` | Lists workspace directory |
| What's the completeness score for issue X? | Dashboard `/api/issues` or filesystem | Pre-aggregated or raw JSON |
| How many traces ran yesterday? | Elasticsearch date histogram agg | Sub-second aggregation |
| What model was used for each span? | Elasticsearch `mlflow-spans` | `model` field on LLM spans |
| What's running right now? | Dashboard `/api/jobs` or `kubectl get pods` | Live K8s state |
| What did the agent actually do step-by-step? | Elasticsearch `mlflow-spans` | Ordered by `start_time`, shows each tool call |
| Are there patterns in agent failures? | Elasticsearch `mlflow-spans` | Filter `status != OK`, aggregate by `name` |
