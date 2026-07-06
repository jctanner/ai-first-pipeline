# AI-First Pipeline Documentation

## Architecture

System design, component docs, and diagrams.

- [agent-parallelism.md](architecture/agent-parallelism.md) — Two-layer parallelism: orchestrator + agent self-parallelism
- [agent-runner.md](architecture/agent-runner.md) — Pipeline job lifecycle from dashboard to K8s execution
- [cli-runner.md](architecture/cli-runner.md) — CLI runner mode proposal (SDK limitations workaround)

### Diagrams

Mermaid `.mmd` files — render on GitHub or paste into [Mermaid Live Editor](https://mermaid.live/).

- [architecture-overview.mmd](architecture/diagrams/architecture-overview.mmd) — High-level system architecture
- [architecture-infrastructure.mmd](architecture/diagrams/architecture-infrastructure.mmd) — K3s cluster, storage, services, secrets
- [architecture-jobs-runners.mmd](architecture/diagrams/architecture-jobs-runners.mmd) — K8s Jobs, agent runners, skill config
- [architecture-data-flow.mmd](architecture/diagrams/architecture-data-flow.mmd) — Data pipeline from bug fetch to dashboard
- [pipeline-execution-flow.mmd](architecture/diagrams/pipeline-execution-flow.mmd) — End-to-end execution sequence
- [architecture.mmd](architecture/diagrams/architecture.mmd) — Legacy single-diagram view (replaced by above)

## Deployment

- [README.md](deployment/README.md) — K3s deployment quick start, .env setup, troubleshooting

## Plans

Planning and strategy documents.

- [local-cluster-plan.md](plans/local-cluster-plan.md) — Move k3s from Vagrant VM to host at /data
- [new-frontend-plan.md](plans/new-frontend-plan.md) — Dashboard redesign for bugs/RFEs/strategies
- [arch-context-testing-plan.md](plans/arch-context-testing-plan.md) — A/B benchmark: flat_files vs arch_query
- [validation-loop-plan.md](plans/validation-loop-plan.md) — Post-fix validation loop with odh-tests-context
- [agent-runner-v2-plan.md](plans/agent-runner-v2-plan.md) — Pluggable runner system + MLflow for agentic-ci
- [dynamic-skill-fqn-plan.md](plans/dynamic-skill-fqn-plan.md) — Dynamic skill resolution via URI-style FQNs
- [agentic-ci-optional-runner-plan.md](plans/agentic-ci-optional-runner-plan.md) — Optional agentic-ci runner in pipeline agent image
- [skill-factory-demo-plan.md](plans/skill-factory-demo-plan.md) — Closed-loop skill generation demo using full service stack
- [observability-demo-plan.md](plans/observability-demo-plan.md) — RFE-to-strategy pipeline with claim analysis and remediation
- [evals-dashboard-plan.md](plans/evals-dashboard-plan.md) — Add Evals page to dashboard for agent-eval-harness runs with A/B context comparison

## Reference

Stable reference material.

- [CONVENTIONS.md](reference/CONVENTIONS.md) — Agent skill analysis: parallelism, idempotency, consistency
- [arch-query-design.md](reference/arch-query-design.md) — arch-query CLI design document
- [arch-context-testing.md](reference/arch-context-testing.md) — Benchmark corpus tiers, judge rubric, MLflow structure
- [data-sources-and-access.md](reference/data-sources-and-access.md) — Pipeline data sources, field mappings, access methods
- [mlflow-basics.md](reference/mlflow-basics.md) — MLflow evaluations with Claude via Vertex API
- [mlflow-claude.md](reference/mlflow-claude.md) — Claude Code tracing via MLflow autolog

## Bugs

Tracked issues and investigations.

- [opencode-mlflow-issue.md](bugs/opencode-mlflow-issue.md) — OpenCode MLflow trace parity with Claude Code
- [opencode-sdk-noop.md](bugs/opencode-sdk-noop.md) — OpenCode SDK silently drops prompts
- [eval-job-143610-bugs.md](bugs/eval-job-143610-bugs.md) — 16 bugs from first eval harness run (dataset config, harness, pipeline)

## Notes

Research, investigations, and dated analysis reports.

- [arch-context-bugs-2026-05-03.md](notes/arch-context-bugs-2026-05-03.md) — Broken symlinks blocking ~26.6% of RHAISTRAT issues
- [arch-context-consumption-problem.md](notes/arch-context-consumption-problem.md) — Agents waste 54% of tool calls on navigation
- [arch-context-consumption-problem-chatgpt.md](notes/arch-context-consumption-problem-chatgpt.md) — YAML index layer recommendation
- [arch-context-consumption-problem-chatgpt-2.md](notes/arch-context-consumption-problem-chatgpt-2.md) — arch-query validation
- [arch-context-corpus-generation.md](notes/arch-context-corpus-generation.md) — Extracting benchmark questions from Elasticsearch
- [arch-context-gaps-2026-05-03.md](notes/arch-context-gaps-2026-05-03.md) — Missing components causing RFE validation failures
- [arch-context-gaps.md](notes/arch-context-gaps.md) — Missing component docs and infrastructure blockers
- [benchmark-arch-context-2026-05-05.md](notes/benchmark-arch-context-2026-05-05.md) — Benchmark results: flat_files vs arch_query
- [benchmark-arch-context-2026-05-06.md](notes/benchmark-arch-context-2026-05-06.md) — Follow-up benchmark with instruction fixes
- [claude-mcp-behavior.md](notes/claude-mcp-behavior.md) — MCP tools not exposed via `claude --print`
- [claude-sdk-mlflow-integration.md](notes/claude-sdk-mlflow-integration.md) — SDK has no built-in MLflow; hooks available
- [token-usage-report-2026-05-03.md](notes/token-usage-report-2026-05-03.md) — Cost analysis: median $0.86/issue, $2.16K total
- [agent-parallelism-testing.md](notes/agent-parallelism-testing.md) — Layer 2 agent self-parallelism test notes
- [AICP-assessment.md](notes/AICP-assessment.md) — AI Core Platform pipeline assessment

## Reference (top-level)

- [vertex-claude-runtime.md](vertex-claude-runtime.md) — Vertex AI Claude runtime wiring

## Ledger

- [agentic_work_ledger.md](ledger/agentic_work_ledger.md) — Filesystem-native project management methodology for AI agents
