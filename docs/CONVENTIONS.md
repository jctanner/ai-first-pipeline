# Skill Conventions

Comprehensive analysis of patterns, conventions, and inconsistencies across all 26 agent skills in the pipeline.

## Skill Inventory

### Local Skills (8) — `.claude/skills/`

| Skill | Invocation | Frontmatter Fields | User-Invocable |
|-------|-----------|-------------------|----------------|
| `bug-completeness` | templated | name, description, allowed-tools | no |
| `bug-context-map` | templated | name, description, allowed-tools | no |
| `bug-fix-attempt` | templated | name, description, allowed-tools | no |
| `bug-test-plan` | templated | name, description, allowed-tools | no |
| `bug-write-test` | templated | name, description, allowed-tools | no |
| `patch-validation` | native | name, description, allowed-tools | no |
| `strat-security-review` | native | name, description, user-invocable, allowed-tools | yes |
| `strat-submit` | native | name, description, user-invocable, allowed-tools | yes |

### Remote Skills (18) — `remote_skills/rfe-creator/.claude/skills/`

| Skill | Invocation | User-Invocable | Model | Context |
|-------|-----------|----------------|-------|---------|
| `rfe.create` | native | yes | (default) | — |
| `rfe.review` | native | yes | (default) | — |
| `rfe.split` | native | yes | (default) | — |
| `rfe.submit` | native | yes | (default) | — |
| `rfe.speedrun` | native | yes | (default) | — |
| `rfe.auto-fix` | native | yes | (default) | — |
| `assess-rfe` | native | yes* | (default) | — |
| `export-rubric` | native | yes* | (default) | — |
| `rfe-feasibility-review` | native | no | opus | — |
| `rfe-creator.update-deps` | native | yes | — | — |
| `strat.create` | native | yes | (default) | — |
| `strat.refine` | native | yes | (default) | fork |
| `strat.review` | native | yes | (default) | — |
| `strat.prioritize` | native | yes | (default) | — |
| `feasibility-review` | native | no | opus | fork |
| `testability-review` | native | no | opus | fork |
| `scope-review` | native | no | opus | fork |
| `architecture-review` | native | no | opus | fork |

*`assess-rfe` and `export-rubric` are from a vendored external plugin (`.context/assess-rfe/`), not authored in this project.

---

## Shared Conventions

### 1. YAML Frontmatter in SKILL.md

Every skill has a YAML frontmatter block with at minimum `name` and `description`. The following fields appear across skills:

| Field | Required | Values | Notes |
|-------|----------|--------|-------|
| `name` | yes | skill identifier | Dot-separated for remote skills (`rfe.create`), hyphenated for local (`bug-completeness`) |
| `description` | yes | free text | Single line for local skills, multi-line block scalar for some remote skills |
| `allowed-tools` | yes (local), varies (remote) | comma-separated tool names | Defines what tools the agent can use |
| `user-invocable` | no | `true`/`false` | Whether users can call directly via `/skill-name` |
| `model` | no | `opus` | Only set on sub-reviewer skills that must use a specific model |
| `context` | no | `fork` | Runs skill in isolated context (used by sub-reviewers and `strat.refine`) |
| `disable-model-invocation` | no | `true` | Only on `rfe-creator.update-deps` — pure shell script, no LLM needed |

### 2. Dual Output Format (JSON + Markdown)

All **bug analysis skills** produce two files per phase:

| Skill | JSON file | Markdown file |
|-------|-----------|---------------|
| `bug-completeness` | `completeness.json` | `completeness.md` |
| `bug-context-map` | `context-map.json` | `context-map.md` |
| `bug-fix-attempt` | `fix-attempt.json` | `fix-attempt.md` |
| `bug-test-plan` | `test-plan.json` | `test-plan.md` |
| `bug-write-test` | `write-test.json` | `write-test.md` |

**Convention:** JSON is the machine-readable primary output (validated against JSON Schema). Markdown is the human-readable rendering. Both are written to the output directory specified in the prompt header.

**RFE/strategy skills do NOT follow this pattern.** They use YAML frontmatter in markdown files as the structured format, managed via `scripts/frontmatter.py`. There is no separate JSON output.

**Security review** uses a single markdown file with YAML frontmatter (no JSON companion).

### 3. JSON Schema Definitions

Bug skills embed their full JSON schema as a code block inside the SKILL.md. The pipeline validates outputs against schemas defined in `lib/schemas.py`.

| Skill | Schema embedded in SKILL.md | Validated by `lib/schemas.py` |
|-------|---------------------------|-------------------------------|
| `bug-completeness` | yes | yes |
| `bug-context-map` | yes | yes |
| `bug-fix-attempt` | yes | yes |
| `bug-test-plan` | yes | yes |
| `bug-write-test` | yes | yes |
| `patch-validation` | yes | yes |
| RFE/strategy skills | no (use frontmatter schemas) | no (use `scripts/frontmatter.py`) |

**Inconsistency:** Bug skills define schemas in two places — SKILL.md (for the agent) and `lib/schemas.py` (for validation). These must be kept in sync manually.

### 4. Enum Conventions

#### Confidence Levels
Used by: `bug-fix-attempt`, `bug-write-test`
Values: `"low"`, `"medium"`, `"high"`

#### Recommendation Values (Bug Pipeline)
Used by: `bug-fix-attempt`
Values: `"ai-fixable"`, `"already-fixed"`, `"not-a-bug"`, `"docs-only"`, `"upstream-required"`, `"insufficient-info"`, `"ai-could-not-fix"`

#### Triage Recommendations
Used by: `bug-completeness`
Values: `"ai-fixable"`, `"needs-enrichment"`, `"needs-info"`

#### Context Ratings
Used by: `bug-context-map`
Values: `"full-context"`, `"partial-context"`, `"no-context"`, `"cross-component"`

#### Review Recommendations (RFE)
Used by: `rfe.review` (via frontmatter)
Values: `"submit"`, `"revise"`, `"split"`, `"reject"`

#### Feasibility Verdicts (RFE)
Used by: `rfe-feasibility-review`
Values: `"feasible"`, `"infeasible"`, `"indeterminate"`

#### Strategy Status (Frontmatter)
Used by: `strat.create`, `strat.refine`
Values: `"Draft"`, `"Refined"`, `"Reviewed"`

#### Security Review Verdict
Used by: `strat-security-review`
Values: `"PASS"`, `"CONCERNS"`, `"FAIL"`

#### Security Review Tier
Used by: `strat-security-review`
Values: `"light"`, `"standard"`, `"deep"`

#### Security Risk Severity
Used by: `strat-security-review`
Values: `"Critical"`, `"High"`, `"Medium"` (no Low — Low items are NFR Gaps, not Security Risks)

### 5. Output Directory Convention

**Bug skills:** Outputs are written to a directory specified in the prompt header (injected by the orchestrator). The agent does not choose the output path.

**RFE/strategy skills:** Outputs are written to well-known paths in the `artifacts/` directory (`artifacts/rfe-tasks/`, `artifacts/rfe-reviews/`, `artifacts/strat-tasks/`, `artifacts/strat-reviews/`).

**Security review:** Outputs are written to `security-reviews/` in the pipeline root.

### 6. Markdown Template Convention

Bug skills include the expected markdown output template inline in the SKILL.md, as a fenced code block showing the exact heading structure. This ensures consistent rendering across all issues.

RFE/strategy skills reference external template files via `${CLAUDE_SKILL_DIR}/rfe-template.md` or `${CLAUDE_SKILL_DIR}/strat-template.md`.

### 7. `$ARGUMENTS` Placeholder

All user-invocable native skills end with `$ARGUMENTS` on a line by itself. This is replaced at runtime with the user's arguments. Present in:
- All `rfe.*` and `strat.*` skills
- `strat-security-review`
- `strat-submit`
- `assess-rfe`

Not present in templated bug skills (they receive issue data via prompt header injection, not `$ARGUMENTS`).

---

## Divergent Patterns

### 8. Invocation Method Split

The pipeline uses two fundamentally different invocation methods:

| Method | Skills | How prompt is delivered | Agent context |
|--------|--------|------------------------|---------------|
| **Templated** | All `bug-*` skills | SKILL.md extracted by `lib/prompts.py`, injected with issue data into agent prompt | Minimal — only the skill prompt and issue data |
| **Native** | `patch-validation`, all `rfe.*`, all `strat.*`, `strat-security-review`, `strat-submit` | Agent discovers skills via SDK `Skill` tool | Full repo context — CLAUDE.md, scripts, sub-skills |

**Consequence:** Templated skills are self-contained — the SKILL.md must include everything the agent needs (schema, rubric, steps, template). Native skills can reference external files, scripts, and other skills.

### 9. Orchestrator vs Self-Contained Skills

Skills fall into two categories:

**Self-contained skills** — the agent does the work directly:
- All bug analysis skills (`bug-completeness`, `bug-context-map`, `bug-fix-attempt`, `bug-test-plan`, `bug-write-test`)
- `patch-validation`
- `strat.refine`
- `strat-security-review`
- `strat-submit`
- `rfe.create`
- `rfe.submit`
- Sub-reviewers (`feasibility-review`, `testability-review`, `scope-review`, `architecture-review`, `rfe-feasibility-review`)

**Orchestrator skills** — the agent launches sub-agents and coordinates:
- `rfe.review` — launches fetch, assess, feasibility, review, and revise agents
- `rfe.split` — launches split agents, then calls `/rfe.review`
- `rfe.auto-fix` — batches IDs and calls `/rfe.review` and `/rfe.split`
- `rfe.speedrun` — calls `/rfe.create`, `/rfe.auto-fix`, `/rfe.submit`
- `strat.review` — launches 4 forked sub-reviewer agents in parallel
- `assess-rfe` — launches scorer agents (up to 30 concurrent)

**Convention in orchestrators:** "Never read file contents into your context — only read frontmatter via `scripts/frontmatter.py read` and check file existence via Glob." This prevents context bloat in the coordinator.

### 10. State Persistence Patterns

**Bug pipeline:** No state persistence needed — the orchestrator (`lib/phases.py`) manages state externally. Skills are stateless.

**RFE/strategy pipeline:** Skills use `scripts/state.py` to persist state to `tmp/` files. This survives context compression in long-running sessions.

```bash
python3 scripts/state.py init <file> key=value ...
python3 scripts/state.py set <file> key=value ...
python3 scripts/state.py set-default <file> key=value ...  # won't overwrite
python3 scripts/state.py read <file>
python3 scripts/state.py write-ids <file> ID ...
python3 scripts/state.py read-ids <file>
python3 scripts/state.py timestamp
python3 scripts/state.py clean
```

Each skill uses distinct file prefixes: `autofix-`, `review-`, `split-`, `speedrun-`.

### 11. Frontmatter Management

**Bug pipeline:** Does not use frontmatter. Structured data is in JSON files.

**RFE/strategy pipeline:** All artifacts use YAML frontmatter managed by `scripts/frontmatter.py`:
- `schema` — print field names and allowed values
- `set` — update fields
- `read` — read validated frontmatter as JSON
- `rebuild-index` — regenerate `artifacts/rfes.md` index

**Convention:** "Never write YAML by hand" — always use the script to ensure schema compliance.

### 12. Jira Integration Patterns

| Pattern | Used by | How |
|---------|---------|-----|
| **MCP server** (read) | `strat-security-review`, `strat-submit`, `strat.create`, `rfe.review`, `assess-rfe` | `mcp__atlassian__getJiraIssue`, `mcp__atlassian__editJiraIssue`, etc. |
| **REST API scripts** (write) | `rfe.submit`, `rfe.split` | `scripts/submit.py`, `scripts/split_submit.py` — deterministic, not LLM-dependent |
| **REST API scripts** (read fallback) | `rfe.review`, `assess-rfe` | `scripts/fetch_issue.py`, `scripts/fetch_single.py` — when MCP unavailable |
| **Orchestrator fetch** | Bug pipeline | `lib/phases.py` fetches via REST API, no MCP |

**Convention for writes:** "All write operations use the Jira REST API directly via Python scripts... This ensures the exact sequence of Jira API calls is deterministic and not dependent on LLM tool-calling decisions."

**Exception:** `strat-submit` uses MCP (`mcp__atlassian__editJiraIssue`) for writes, not a script. This is inconsistent with the RFE pipeline's deterministic-write principle.

### 13. Architecture Context Usage

| Skill | Uses architecture context | Source |
|-------|--------------------------|--------|
| `bug-context-map` | yes | `architecture-context/` (symlink or `.context/`) |
| `bug-fix-attempt` | yes (read-only) | `architecture-context/` |
| `rfe.create` | **explicitly NO** | "Do NOT load architecture context. RFEs describe business needs" |
| `rfe-feasibility-review` | yes | `.context/architecture-context/` |
| `strat.refine` | yes | `.context/architecture-context/` |
| `strat.review` sub-reviewers | yes (architecture-review) | `.context/architecture-context/` |
| `strat-security-review` | yes (required for Standard/Deep) | `.context/architecture-context/` |

**Convention:** Architecture context is read-only reference material. Bug-fix-attempt explicitly states: "DO NOT edit anything under `architecture-context/`."

### 14. Tool Access Patterns

| Tool Combination | Skills |
|-----------------|--------|
| Read, Write, Glob, Grep | `bug-completeness`, `bug-context-map`, `bug-fix-attempt`, `bug-test-plan` |
| Read, Write, Edit, Glob, Grep, Bash | `bug-write-test` |
| Read, Write, Glob, Grep, Bash | `patch-validation`, `strat-security-review` |
| Read, Glob, Grep, Bash | `strat-submit` |
| Read, Write, Edit, Glob, Grep, Bash | `rfe.create`, `rfe.submit`, `strat.create` |
| Read, Write, Edit, Glob, Grep, Bash, Skill | `strat.review`, `rfe.speedrun` |
| Glob, Bash, Agent | `rfe.review` |
| Glob, Bash, Agent, Skill | `rfe.split` |
| Glob, Bash, Skill | `rfe.auto-fix` |
| Read, Grep, Glob | Sub-reviewers (`feasibility-review`, `scope-review`, `architecture-review`, `testability-review`) |
| Read, Write, Edit, Glob, Grep | `strat.refine` |

**Pattern:** Orchestrator skills (rfe.review, rfe.split, rfe.auto-fix) have Agent and/or Skill tools but NOT Read/Write — they delegate content handling to sub-agents. Sub-reviewer skills are read-only (Read, Grep, Glob) — they analyze but don't modify.

**Inconsistency:** `bug-write-test` includes `Edit` in its allowed-tools but other bug skills don't. The `strat-submit` local skill does not include `Edit` or `Write` while the RFE skills generally do.

### 15. `--headless` Flag Convention

Used by orchestrator skills for CI/batch mode:
- `rfe.create` — skip clarifying questions
- `rfe.review` — suppress end-of-run summary
- `rfe.split` — suppress end-of-run summary
- `rfe.auto-fix` — suppress summaries
- `rfe.speedrun` — pass through to sub-skills

**Convention:** When `--headless` is set, the skill stops after writing artifacts. "Do not output any summary. Resume the calling skill's next step immediately."

Not used in bug pipeline (the Python orchestrator controls interactivity).

### 16. Polling and Progress Patterns

Orchestrator skills use a consistent polling pattern:

```bash
python3 scripts/state.py write-ids tmp/rfe-poll-<phase>.txt <IDs>
python3 scripts/check_review_progress.py --phase <phase> --id-file tmp/rfe-poll-<phase>.txt
```

The progress script returns a `NEXT_POLL` interval. The orchestrator sleeps for that duration before polling again.

**Convention:** "Only output a status line when COMPLETED count changes." This prevents noisy progress output.

`assess-rfe` uses a different polling script (`check_progress.py`) with a fixed 30-second interval and a rolling pipeline of 30 concurrent agents.

### 17. Self-Correction and Retry Patterns

**Bug pipeline:** `bug-fix-attempt` has a structured `self_corrections` array in its JSON output. The orchestrator (`lib/phases.py`) manages the validation loop — running the fix agent, validating via `patch-validation`, and re-running with feedback injected as a `## Validation Feedback` section.

**RFE pipeline:** `rfe.review` has a built-in reassessment loop (max 2 cycles). `rfe.split` has a right-sizing self-correction loop (max 3 cycles). Both persist cycle counters to disk via `scripts/state.py set-default` to prevent re-entry after context compression.

**RFE auto-fix:** Has a retry queue (Step 4) that re-runs failed IDs once after the main batch completes.

### 18. Context Compression Resilience

RFE/strategy orchestrator skills have extensive anti-compression patterns:

1. **Persist all IDs to disk** — never rely on in-memory lists
2. **Re-read IDs from disk before each step** — "context compression may have corrupted in-memory lists"
3. **Use `set-default` for cycle counters** — "safe if compression causes re-entry — it won't reset an existing counter"
4. **Re-read config before checking flags** — "context compression may have lost them during agent execution"

Bug skills don't need this — their orchestrator (`lib/phases.py`) runs outside the agent context.

---

## Naming Conventions

### Skill Names
- **Local bug skills:** `bug-{phase}` (hyphenated, prefixed)
- **Local infrastructure skills:** `patch-validation`, `strat-security-review`, `strat-submit` (hyphenated)
- **Remote RFE skills:** `rfe.{action}` (dot-separated)
- **Remote strategy skills:** `strat.{action}` (dot-separated)
- **Remote sub-reviewers:** `{domain}-review` (hyphenated, no prefix)
- **Remote utility:** `rfe-creator.update-deps` (fully qualified), `export-rubric`, `assess-rfe`

### File Naming
- **Bug outputs:** `{phase}.json`, `{phase}.md` (no issue key in filename — disambiguated by directory)
- **RFE artifacts:** `{JIRA_KEY}.md` or `RFE-NNN.md` (pre-submission)
- **RFE reviews:** `{ID}-review.md`
- **Strategy artifacts:** `RHAISTRAT-NNN.md` or `STRAT-NNN.md`
- **Strategy reviews:** `{ID}-review.md`
- **Security reviews:** `{STRAT-KEY}-security-review.md`
- **Companion files:** `{ID}-comments.md`, `{ID}-removed-context.yaml`

### Jira Projects
- `RHOAIENG` — engineering bugs (bug pipeline)
- `RHAIRFE` — RFEs (RFE pipeline)
- `RHAISTRAT` — strategies (strategy pipeline)

---

## Structural Comparison

### Bug Skills vs RFE/Strategy Skills

| Aspect | Bug Skills | RFE/Strategy Skills |
|--------|-----------|-------------------|
| Invocation | Templated (prompt injection) | Native (SDK skill discovery) |
| Orchestration | External Python (`lib/phases.py`) | Internal skill orchestration (agent-launched sub-agents) |
| State management | Python code (external) | `scripts/state.py` + disk files |
| Structured output | JSON files + JSON Schema validation | YAML frontmatter + `scripts/frontmatter.py` |
| Human-readable output | Companion `.md` file | Same file (frontmatter + markdown body) |
| Schema source of truth | Duplicated: SKILL.md + `lib/schemas.py` | Single: `scripts/frontmatter.py schema` |
| Jira integration | Fetch via Python script | MCP (read) + Python scripts (write) |
| Interactivity | None (batch only) | `--headless` flag, `AskUserQuestion` tool |
| Architecture context path | `architecture-context/` (symlink) | `.context/architecture-context/` |
| Workspace model | `workspace/{KEY}/{model_id}/` | `artifacts/{type}/{ID}.md` |
| Concurrency control | Python asyncio semaphore | Agent tool (`run_in_background`) + polling scripts |
| Context compression resilience | Not needed (external orchestrator) | Extensive disk persistence patterns |

### Self-Contained Skills vs Orchestrators

| Aspect | Self-Contained | Orchestrator |
|--------|---------------|-------------|
| Content handling | Reads files, writes output directly | Delegates to sub-agents — "never read file contents into your context" |
| Tool access | Read, Write, Edit, Glob, Grep (± Bash) | Agent, Skill, Bash, Glob (no Read/Write) |
| Output | Writes files directly | Reads frontmatter/status from sub-agent outputs |
| Error handling | Agent reports in its JSON/frontmatter | Checks for missing files, writes error frontmatter |
| Parallelism | Sequential within the skill | Launches N agents in parallel, polls for completion |

### Sub-Reviewer Skills (Forked Context)

The four strategy sub-reviewers (`feasibility-review`, `testability-review`, `scope-review`, `architecture-review`) and `strat.refine` use `context: fork`, meaning they run in isolated contexts that don't see each other's output. This is intentional — "no reviewer sees another's output" to prevent groupthink.

Shared patterns across all four sub-reviewers:
- Read-only tools (Read, Grep, Glob)
- Fixed model (`model: opus`)
- Not user-invocable
- Same input structure (strategy artifacts + RFE artifacts + prior reviews)
- Same output structure (per-strategy assessment with verdict, key concerns, recommendation)
- Re-review awareness ("What concerns from the prior review were addressed?")

---

## Known Inconsistencies

1. **Schema duplication:** Bug skill JSON schemas exist in both SKILL.md (for the agent) and `lib/schemas.py` (for validation). Changes to one must be manually synced to the other.

2. **Architecture context path:** Bug skills reference `architecture-context/` (symlink at project root). RFE/strategy skills reference `.context/architecture-context/`. Both point to the same data but use different paths.

3. **Jira write method:** RFE pipeline uses deterministic Python scripts for writes. `strat-submit` uses MCP tool calls for writes. The stated principle ("deterministic, not LLM-dependent") is only applied to the RFE pipeline.

4. **Allowed-tools inconsistency:** `bug-write-test` has `Edit` in allowed-tools but other bug skills don't. This may be intentional (write-test needs to modify existing test files) but breaks the otherwise consistent tool set.

5. **Naming convention split:** Local skills use hyphens (`bug-completeness`), remote skills use dots (`rfe.create`). The `strat-security-review` and `strat-submit` local skills use hyphens while `strat.create`, `strat.refine`, `strat.review` remote skills use dots — both are strategy skills.

6. **Dashboard command:** `strat-submit` references `strat-refined` as a Jira label. The CLI uses `dashboard` but the SKILL.md and some code reference `report`.

7. **`user-invocable` field:** Present on native skills but absent from templated bug skills. Bug skills are never user-invocable (they're called by the Python orchestrator), so the absence is correct but implicit.

8. **Description format:** Local skills use single-line `description`. Some remote skills use multi-line block scalars (`description: >`). Both work but the style differs.

9. **Security review output path:** Writes to `security-reviews/` in the pipeline root, unlike other skills that write to `artifacts/` (RFE/strategy) or the workspace directory (bugs).

10. **Not-yet-implemented skill:** `strat.prioritize` is defined but explicitly not implemented. It exists as a placeholder with design notes.
