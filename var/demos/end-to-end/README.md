# End-to-End Demo — Markov Workflow

Markov directory-based workflow for the closed-loop hallucination remediation demo. Resets all local services (Jira, GitHub, Observatory, MLflow) to a clean state, clears pipeline volumes, imports all required repos, seeds a demo RFE ticket, and runs the full RFE-to-strategy pipeline.

See `docs/plans/closed-loop-hallucination-remediation-demo-plan.md` for the full demo plan.

## Prerequisites

- Markov/markovd running in the `ai-pipeline` namespace
- All local services running: `jira.local`, `github.local`, `dashboard.local`, `observatory.local`, `mlflow.local`
- `pipeline-secrets` K8s secret configured

## Usage

### Via markovd (recommended)

Submit through the markovd UI or API:

```bash
curl -s -X POST "https://markovd.local/api/v1/runs" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_name": "end-to-end",
    "vars": {"seed_rfe": true}
  }'
```

### Via markov CLI

```bash
# Full reset + pipeline (default)
markov run var/demos/end-to-end/

# Reset only, skip pipeline
markov run var/demos/end-to-end/ --var run_pipeline=false

# Skip RFE seeding (and pipeline)
markov run var/demos/end-to-end/ --var seed_rfe=false --var run_pipeline=false

# With GitHub token for rate-limited upstream repos
markov run var/demos/end-to-end/ --var github_token=ghp_xxx

# Override service URLs (e.g., from outside the cluster)
markov run var/demos/end-to-end/ \
  --var github_base=https://github.local \
  --var jira_base=https://jira.local
```

### Via Makefile

```bash
make demo-reset              # Full reset via markov
make vagrant-demo-reset      # Full reset via vagrant ssh
```

## Variables

All variables are defined in `vars.yaml`. The `repos` list defines which repos to import from upstream.

| Variable | Default | Description |
|----------|---------|-------------|
| `github_base` | in-cluster FQDN | GitHub emulator URL |
| `jira_base` | in-cluster FQDN | Jira emulator URL |
| `observatory_base` | in-cluster FQDN | Observatory URL |
| `dashboard_base` | in-cluster FQDN | Pipeline dashboard URL |
| `org` | `opendatahub-io` | Target org on github.local |
| `github_token` | `""` | Real GitHub PAT for upstream clones (optional) |
| `github_api_token` | `""` | Bootstrapped at runtime by `reset-github` |
| `seed_rfe` | `true` | Create a demo RFE ticket after setup |
| `run_pipeline` | `true` | Run the RFE-to-strategy pipeline after setup |
| `rfe_issue` | `RHAIRFE-1` | RFE ticket to process (created by `seed-rfe`) |
| `repos` | 10 entries | List of `{name, upstream}` repos to import |

The `skills` repo (no upstream) is handled as a dedicated step in `reset-github.yaml`.

## Workflow Structure

```
main
├── reset-jira          Reset database, create RHAIFIRST project, verify
├── reset-github        Bootstrap token, ensure org, create skills repo, for_each repo: delete + import
│   └── import-repo     Per-repo: delete (authed) → import from upstream (admin) → poll until complete
├── reset-services      Wipe observatory, clear MLflow, clear artifacts + .context volumes
├── seed-rfe            Create demo RFE ticket (when seed_rfe=true)
└── run-pipeline        RFE-to-strategy pipeline (when run_pipeline=true)
    ├── run-skill        rfe-speedrun on RHAIRFE-1 (submit + poll)
    ├── add label        strat-creator-3.6 on RHAIRFE-1
    ├── run-skill        strat-create on RHAIRFE-1 (submit + poll)
    ├── discover strat   query Jira Cloners link → RHAISTRAT-*
    ├── run-skill        strat-refine on RHAISTRAT-* (submit + poll)
    └── run-skill        strat-review on RHAISTRAT-* (submit + poll)
```

## Step Types

Defined in `step_types/` (one file per type):

| Type | Base | Description |
|------|------|-------------|
| `jira_api` | `http_request` | Jira REST API with basic auth (`admin:admin`) |
| `github_api` | `http_request` | GitHub API with token auth (`{{ github_api_token }}`) |
| `github_admin_api` | `http_request` | GitHub admin endpoints (unauthenticated) |
| `observatory_api` | `http_request` | Observatory API |
| `dashboard_api` | `http_request` | Pipeline dashboard API |
| `agent_job` | `http_request` | Submit skill job via dashboard API (strace + otel + mlflow on by default) |

## Files

| File | Description |
|------|-------------|
| `meta.yaml` | Entrypoint and namespace |
| `vars.yaml` | Default variables and repo manifest |
| `step_types/jira_api.yaml` | Jira API step type |
| `step_types/github_api.yaml` | GitHub API step type (token auth) |
| `step_types/github_admin_api.yaml` | GitHub admin API step type (no auth) |
| `step_types/observatory_api.yaml` | Observatory API step type |
| `step_types/dashboard_api.yaml` | Pipeline dashboard API step type |
| `step_types/agent_job.yaml` | Dashboard-submitted skill job step type |
| `rules.yaml` | Empty (future: import retry rules, quality gates) |
| `workflows/main.yaml` | Entrypoint workflow |
| `workflows/reset-jira.yaml` | Jira reset and project creation |
| `workflows/reset-github.yaml` | GitHub repo deletion and import |
| `workflows/reset-services.yaml` | Observatory, MLflow, and volume reset |
| `workflows/seed-rfe.yaml` | Demo RFE ticket creation |
| `workflows/run-pipeline.yaml` | RFE-to-strategy pipeline |
| `workflows/run-skill.yaml` | Reusable submit + poll wrapper for agent jobs |
