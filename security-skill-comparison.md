# Security Review Skill Comparison

Comparison of two security review skills for the strategy pipeline: the standalone `strat-security-review` (local skill in this project) and Ugo's `security-review` (designed as a forked sub-reviewer for `strat.review`).

## What They Are

**`strat-security-review`** (`.claude/skills/strat-security-review/SKILL.md`) — A standalone skill invoked separately from the pipeline (`/strat.security-review RHAISTRAT-400`). Fetches the STRAT directly from Jira, writes its own output file to `security-reviews/`, and attaches it to the Jira ticket. Full-featured, self-contained review with its own tiering system, frontmatter schema, verdict format (PASS/CONCERNS/FAIL), and detailed output structure.

**Ugo's `security-review`** (`tmp/UGO-SKILL.md`) — A forked sub-reviewer designed to run inside `strat.review` alongside feasibility, testability, scope, and architecture. Has `context: fork`, `user-invocable: false`, `model: sonnet`, reads from local `artifacts/strat-tasks/` (not Jira), and outputs a section that the orchestrator merges into the combined review file.

## Key Differences

| Dimension | strat-security-review | Ugo's security-review |
|-----------|----------------------|----------------------|
| **Invocation** | Standalone skill, user-invocable | Forked sub-reviewer, not user-invocable |
| **Data source** | Fetches from Jira via MCP | Reads local artifacts |
| **Output** | Separate file in `security-reviews/` + Jira attachment | Section merged into `artifacts/strat-reviews/{id}-review.md` |
| **Verdicts** | PASS / CONCERNS / FAIL | approve / revise / reject (matches other forks) |
| **Severity levels** | Critical / High / Medium (Low = NFR Gap) | Critical / Important / Minor |
| **Model** | Inherits (opus) | Explicitly sonnet |
| **Tiering** | Light / Standard / Deep with explicit criteria table | Same tiers, slightly less formal criteria |
| **RHOAI-specific** | Explicit organizational requirements table (FIPS, Gateway API, secrets policy, etc.) | Auth patterns listed but no formal requirements table |
| **NFR escalation** | NFR Gaps never drive CONCERNS | 5+ NFR Gaps can upgrade to `revise` |
| **ML/AI threats** | Not covered | Explicit dimension (data poisoning, prompt injection, model artifact access) |
| **Multi-tenant** | Covered under Auth & Data Protection | Explicit standalone dimension |
| **Re-review** | Not handled (standalone runs are fresh) | Explicit re-review protocol (reads prior `## Security` section only, avoids anchoring) |
| **Output format** | Full structured markdown with frontmatter, threat surface analysis, existing controls, amendments, missing context | Compact — findings list, optional acceptance criteria, verdict |

## Strengths of Each

### strat-security-review

- Organizational requirements table codifies tribal knowledge (FIPS, upstream-first, approved auth patterns, secrets policy)
- Existing security controls section prevents redundant findings by establishing what's already in place
- Missing context section gives feedback to STRAT authors and the pipeline itself
- STRAT amendments section produces directly actionable output
- Standalone operation means it can run independently of the review cycle
- Jira attachment integration

### Ugo's security-review

- ML/AI-specific threat dimension is a real gap — model poisoning, prompt injection, inference endpoint auth are relevant for an AI platform
- Multi-tenant isolation as a first-class dimension is cleaner than burying it in other categories
- NFR escalation rule (5+ gaps -> revise) is a smart heuristic — catches strategies where the author didn't think about security at all
- Re-review protocol is well-designed — reads only its own prior section to avoid anchoring
- Lighter output format fits the forked reviewer pattern (the orchestrator synthesizes)
- Runs on sonnet — cheaper for batch runs

## Recommendation

These aren't competing — they serve different purposes and should both exist.

### 1. Add Ugo's as a fifth fork in `strat.review`

It's already designed for this (`context: fork`, `user-invocable: false`). Every `/strat.review` run would automatically get a security perspective alongside feasibility, testability, scope, and architecture. The orchestrator needs a small update to invoke `security-review` and add `reviewers.security` to the frontmatter. This gives security coverage as part of the standard review loop, running on sonnet for cost efficiency.

### 2. Keep strat-security-review as the standalone deep-dive

The standalone skill is the one to run when you specifically want a thorough security review with Jira integration, organizational requirements checking, and a full report attached to the ticket. It operates independently and produces a richer artifact.

### 3. Port from Ugo's into strat-security-review

- **ML/AI-specific threats** dimension — genuine gap for an AI platform product
- **5+ NFR Gap escalation** rule — useful heuristic that catches systematically security-unaware strategies

### 4. Port from strat-security-review into Ugo's

- **Organizational requirements table** — the FIPS, Gateway API, secrets policy, and upstream-first constraints are enforced in practice and should be checked even in the lightweight fork
