# Skill Review: test-plan (Multi-Skill Repository)

**Reviewed:** 2026-04-30
**Repository:** `to-review/test-plan/`
**Skills found:** 16 skills + 1 shared resource directory (`test-plan-common`)
**Overall status:** WARN — functional but has packaging, consistency, and size issues

## Summary

| Check | Verdict | Notes |
|-------|---------|-------|
| 1. SKILL.md Structure | WARN | 16/17 dirs have SKILL.md; `test-plan-common` is shared resource only |
| 2. Naming Conventions | PASS | Dot-separated namespacing is consistent and intentional |
| 3. Frontmatter Fields | WARN | Mixed `allowedTools` vs `allowed-tools` field names across skills |
| 4. Description Quality | PASS | All descriptions are specific and actionable |
| 5. Size / Progressive Disclosure | WARN | `test-plan.case-implement` is 1049 lines (2x over 500-line limit) |
| 6. Variable Substitution | PASS | Only valid variables used (`${CLAUDE_SKILL_DIR}`, `$ARGUMENTS`) |
| 7. File References | WARN | `test-plan.score` hardcodes paths into `test-plan.review`'s directory |
| 8. External Script Detection | WARN | 11 skills share repo-root scripts via 2-hop symlink chain |
| 9. Runtime Dependencies | WARN | 11 skills depend on `uv`, shared symlinked scripts, and repo-root `pyproject.toml` |
| 10. `context: fork` Impact | INFO | 6 skills use `context: fork` correctly as non-user-invocable sub-agents |
| 11. Script Path Portability | PASS | All SKILL.md script refs use `${CLAUDE_SKILL_DIR}/scripts/` |
| 12. Shared Artifact Safety | INFO | Skills write to shared feature-dir artifacts with clear pipeline ordering |
| 13. Marketplace Compatibility | WARN | Symlink chain to repo-root scripts prevents standalone install |

---

## Check 1: SKILL.md Structure

17 directories found under `.claude/skills/`:

| Directory | SKILL.md | Frontmatter | YAML Valid |
|-----------|----------|-------------|------------|
| test-plan.analyze.endpoints | Yes | Yes | Yes |
| test-plan.analyze.infra | Yes | Yes | Yes |
| test-plan.analyze.placement | Yes | Yes | Yes |
| test-plan.analyze.risks | Yes | Yes | Yes |
| test-plan.case-implement | Yes | Yes | Yes |
| test-plan-common | **No** | N/A | N/A |
| test-plan.create | Yes | Yes | Yes |
| test-plan.create-cases | Yes | Yes | Yes |
| test-plan.create.test-function | Yes | Yes | Yes |
| test-plan.merge | Yes | Yes | Yes |
| test-plan.publish | Yes | Yes | Yes |
| test-plan.resolve-feedback | Yes | Yes | Yes |
| test-plan.resolve-gaps | Yes | Yes | Yes |
| test-plan.review | Yes | Yes | Yes |
| test-plan.score | Yes | Yes | Yes |
| test-plan.score.test-function | Yes | Yes | Yes |
| test-plan.ui-verify | Yes | Yes | Yes |
| test-plan.update | Yes | Yes | Yes |

`test-plan-common` contains only a symlink (`scripts -> ../../../scripts`) and serves as a shared resource hub. It is not a skill and correctly has no SKILL.md.

Two skills have `README.md` alongside `SKILL.md`: `test-plan.case-implement` and `test-plan.ui-verify`. Acceptable when README.md provides supplementary documentation not duplicated in SKILL.md.

**Verdict:** WARN

---

## Check 2: Naming Conventions

All skill directories use kebab-case with dot separators for hierarchical namespacing:

- `test-plan.create` (root skill)
- `test-plan.analyze.endpoints` (analyzer sub-skill)
- `test-plan.score.test-function` (scorer sub-skill)

The dot convention creates a clear taxonomy:
- `test-plan.analyze.*` — 4 analyzer sub-skills
- `test-plan.create*` — 3 creation skills
- `test-plan.score*` — 2 scoring skills

The `name` fields in frontmatter all match their directory names. No reserved words found.

The one outlier is `test-plan-common` (hyphen not dot), which is appropriate since it's a shared resource directory, not a skill.

**Verdict:** PASS

---

## Check 3: Frontmatter Fields

All 16 skills have `name` and `description` (required). Field type validation:

| Field | Used by | Valid values |
|-------|---------|-------------|
| `name` | All 16 | All match directory names |
| `description` | All 16 | All present and specific |
| `model` | 15 of 16 | `opus` (6), `sonnet` (9) — all valid |
| `user-invocable` | All 16 | `true` (8), `false` (8) |
| `context` | 6 skills | All `fork` — valid |
| `argument-hint` | 7 skills | Present on user-invocable skills that accept args |

**Field name inconsistency:**

| Field variant | Skills using it |
|---------------|-----------------|
| `allowedTools` (camelCase, YAML list) | case-implement, create, merge, publish, resolve-feedback, resolve-gaps, review, score, ui-verify, update (10 skills) |
| `allowed-tools` (hyphenated, comma string) | analyze.endpoints, analyze.infra, analyze.placement, analyze.risks, create-cases, create.test-function, score.test-function (7 skills) |

Both forms are accepted by Claude Code, but the inconsistency within a single repository is notable. The `allowed-tools` form appears predominantly on sub-agent/fork skills, while `allowedTools` appears on orchestrator skills.

`test-plan.ui-verify` is the only user-invocable skill without a `model` field — it will inherit the session's model.

**Verdict:** WARN

---

## Check 4: Description Quality

All descriptions are specific, actionable, and clearly scoped:

- `test-plan.create`: Specifies input types (strategy, RHOAIENG, ADR) and output
- `test-plan.case-implement`: "Generate executable test automation code from test case specifications"
- `test-plan.review`: Explains methodology (5-criteria rubric, score-revise-rescore cycles)
- `test-plan.ui-verify`: Full flow description (loads TCs, Playwright, HTML report, verdicts, screenshots)
- `test-plan.publish`: Concrete actions (branch, commit, PR, reviewer assignment)

Sub-skills clearly state their analytical focus. User-invocable skills describe what they produce.

**Verdict:** PASS

---

## Check 5: Size / Progressive Disclosure

Line counts (sorted descending):

| Skill | Lines | Status |
|-------|-------|--------|
| test-plan.case-implement | **1049** | **Over limit** — 2x the 500-line guideline |
| test-plan.publish | 422 | OK |
| test-plan.update | 375 | OK |
| test-plan.create | 314 | OK |
| test-plan.create-cases | 292 | OK |
| test-plan.resolve-feedback | 272 | OK |
| test-plan.review | 239 | OK |
| test-plan.analyze.placement | 222 | OK |
| test-plan.merge | 209 | OK |
| test-plan.create.test-function | 194 | OK |
| test-plan.resolve-gaps | 175 | OK |
| test-plan.analyze.risks | 126 | OK |
| test-plan.analyze.infra | 106 | OK |
| test-plan.score | 99 | OK |
| test-plan.analyze.endpoints | 91 | OK |
| test-plan.ui-verify | 88 | OK (delegates to `instructions.md`) |
| test-plan.score.test-function | 75 | OK |

`test-plan.case-implement` (1049 lines) covers repo discovery, cloning, convention extraction, repo instruction gathering, test function generation, scoring, syntax validation, container validation, and git push. The convention-extraction and repo-discovery phases (~400 lines) should be extracted to `references/` files.

`test-plan.ui-verify` demonstrates good progressive disclosure at 88 lines, delegating detail to `instructions.md` (11KB).

**Verdict:** WARN

---

## Check 6: Variable Substitution

Variables found across all skills:

| Variable | Occurrences | Valid |
|----------|-------------|-------|
| `${CLAUDE_SKILL_DIR}` | ~40+ across 11 skills | Yes |
| `$ARGUMENTS` | All user-invocable + sub-agent skills | Yes |

No invalid variables found in any SKILL.md. Five skills use no variables at all (the 4 analyzers + resolve-gaps), which is correct — they receive inputs inline from parent skills.

**Verdict:** PASS

---

## Check 7: File References

**References that resolve correctly:**
- `${CLAUDE_SKILL_DIR}/scripts/frontmatter.py` — resolves via symlink chain (11 skills)
- `${CLAUDE_SKILL_DIR}/scripts/repo.py` — resolves via symlink chain (6 skills)
- `${CLAUDE_SKILL_DIR}/test-plan-template.md` — exists in `test-plan.create/`
- `${CLAUDE_SKILL_DIR}/test-case-template.md` — exists in `test-plan.create-cases/`
- `${CLAUDE_SKILL_DIR}/prompts/*.md` — exist in `test-plan.review/` and `test-plan.score.test-function/`
- `${CLAUDE_SKILL_DIR}/calibration/` — exists in both `test-plan.review/` and `test-plan.score.test-function/`

**Cross-skill reference issue:**

`test-plan.score` hardcodes paths to another skill's internal files without using `${CLAUDE_SKILL_DIR}`:
```
.claude/skills/test-plan.review/prompts/score-agent.md
.claude/skills/test-plan.review/calibration/
```

These assume the project directory structure and will break if `test-plan.review` is moved or skills are packaged separately. The prompt and calibration files should be copied into `test-plan.score/` with `${CLAUDE_SKILL_DIR}` references.

**Verdict:** WARN

---

## Check 8: External Script Detection

All runtime scripts live in the repo-root `scripts/` directory, accessed via a 2-hop symlink chain:

```
<skill>/scripts -> ../test-plan-common/scripts -> ../../../scripts
```

11 of 16 skills use this symlink pattern. Scripts shared this way:
- `frontmatter.py` — frontmatter CRUD (used by 10 skills)
- `repo.py` — repository discovery and cloning (used by 6 skills)
- `tc_regeneration.py` — test case regeneration checks
- `filter_for_revision.py` — review revision filtering
- `preserve_review_state.py` — review state persistence
- `validate_gap_counts.py` — gap count validation
- `utils/` — shared utilities (component_map, repo_discovery, repo_utils, test_analyzer, etc.)

**Exception:** `test-plan.ui-verify` has its own real `scripts/` directory (not a symlink) with 15 Python files. This is the correct self-contained approach.

Symlinks work within the repo but are fragile across git clones (especially Windows), tar archives, and marketplace distribution.

**Verdict:** WARN

---

## Check 9: Runtime Dependencies

| Dependency | Skills affected | Type |
|------------|----------------|------|
| `scripts/frontmatter.py` | 10 skills | Shared via symlink |
| `scripts/repo.py` | 6 skills | Shared via symlink |
| `scripts/utils/*.py` | 1 skill (case-implement) | Shared via symlink |
| `uv` | 11 skills | Python runner (requires `pyproject.toml`) |
| `jq` | 4 skills | CLI tool |
| `gh` | 2 skills (publish, resolve-feedback) | GitHub CLI |
| `git` | 3 skills | Direct git operations |
| `podman` | 1 skill (case-implement) | Container validation |
| `mcp__atlassian__getJiraIssue` | 2 skills (create, review) | MCP server |
| Playwright + Chrome | 1 skill (ui-verify) | Browser automation |

The `uv run python` pattern assumes `uv` is installed and the project's `pyproject.toml` is in scope. The `test-plan.update` skill lists `mcp__atlassian__getJiraIssue` usage in its body but does not include it in `allowedTools` — it relies on sub-skills for Jira access, which is fine but worth documenting.

**Verdict:** WARN

---

## Check 10: `context: fork` Impact

6 skills declare `context: fork` in frontmatter:

| Skill | user-invocable | allowed-tools | Called by |
|-------|---------------|---------------|----------|
| test-plan.analyze.endpoints | false | Read | create, update |
| test-plan.analyze.infra | false | Read | create, update |
| test-plan.analyze.placement | false | Read, AskUserQuestion | case-implement |
| test-plan.analyze.risks | false | Read | create, update |
| test-plan.create.test-function | false | Read | case-implement |
| test-plan.score.test-function | false | Read, Write | case-implement |

All 6 are non-user-invocable sub-agents. Streaming suppression is expected and correct for forked sub-agents — no interactive use is affected.

**Verdict:** INFO

---

## Check 11: Script Path Portability

All SKILL.md files correctly use `${CLAUDE_SKILL_DIR}/scripts/...` for script invocations:
```bash
uv run python ${CLAUDE_SKILL_DIR}/scripts/frontmatter.py ...
uv run python ${CLAUDE_SKILL_DIR}/scripts/repo.py ...
```

No bare `python3 scripts/...` or `./scripts/...` patterns found in SKILL.md files.

`test-plan.ui-verify` SKILL.md body (line 33) uses a project-relative path (`.claude/skills/test-plan.ui-verify/scripts/ui_prepare.py`) for its pre-invocation step. This works within the repo but would break if moved. The `allowedTools` correctly use glob patterns (`*scripts/ui_interact.py *`) for tool permissions.

**Verdict:** PASS

---

## Check 12: Shared Artifact Safety

Multiple skills write to the same feature directory artifacts:

| Artifact | Written by | Ordering |
|----------|-----------|----------|
| `TestPlan.md` | create, create-cases (sections), update, resolve-feedback | Pipeline-ordered |
| `TestPlanGaps.md` | create, create-cases, update | Pipeline-ordered |
| `TestPlanReview.md` | review | Single owner |
| `TC-*.md` frontmatter | case-implement, resolve-feedback | Different fields |
| `test_cases/INDEX.md` | create-cases | Single owner |

The skills have a clear pipeline ordering (create -> create-cases -> review -> update -> publish) that prevents concurrent writes to the same artifact. No broad `*.md` globs or shared index file writes detected.

One concern: `test-plan.resolve-feedback` uses `git add <feature_dir>/` which stages everything (including internal files like `.review-state.json`), while `test-plan.publish` carefully stages only public artifacts. This inconsistency could leak internal state into PRs.

**Verdict:** INFO

---

## Check 13: Marketplace Compatibility

**NOT marketplace-compatible** for 11 of 16 skills due to the 2-hop symlink chain:

```
<skill>/scripts -> ../test-plan-common/scripts -> ../../../scripts
```

Installation requirements:
1. Full repository checkout (`git clone`)
2. `uv sync` to install Python dependencies from `pyproject.toml`
3. All skills must remain in `.claude/skills/` alongside `test-plan-common`
4. Repo-root `scripts/` directory must be present

**Near-marketplace-ready:** `test-plan.ui-verify` has its own real `scripts/` directory with 15 bundled Python files and a `requirements.txt`. It would need only the hardcoded path on line 33 changed to `${CLAUDE_SKILL_DIR}` to be fully self-contained.

**Fully self-contained:** The 5 skills with no script dependencies (4 analyzers + `create.test-function`) are structurally marketplace-compatible but are never used independently — they're always invoked by parent skills that depend on the symlink chain.

**Verdict:** WARN

---

## Priority Fixes

### High Priority

1. **Split `test-plan.case-implement`** (1049 lines -> target <500)
   - Extract repo discovery and convention extraction (Steps 2-4, ~400 lines) into `references/repo-setup.md`
   - Extract generation-and-scoring loop (Steps 5-6, ~300 lines) into `references/generate-and-score.md`
   - Keep orchestration flow and pre-flight checks in SKILL.md

2. **Fix `test-plan.score` cross-skill references**
   ```
   # Before (breaks if test-plan.review moves)
   .claude/skills/test-plan.review/prompts/score-agent.md
   .claude/skills/test-plan.review/calibration/

   # After (self-contained)
   ${CLAUDE_SKILL_DIR}/prompts/score-agent.md
   ${CLAUDE_SKILL_DIR}/calibration/
   ```
   Copy `score-agent.md` and the 2 calibration files into `test-plan.score/prompts/` and `test-plan.score/calibration/`.

3. **Fix `resolve-feedback` git staging**
   - Replace `git add <feature_dir>/` with explicit file staging matching `test-plan.publish`'s approach
   - Prevents committing `.review-state.json` and other internal files

### Medium Priority

4. **Standardize frontmatter field names**
   - Pick one convention (`allowed-tools` or `allowedTools`) across all 16 skills
   - `allowed-tools` is the documented spec form; `allowedTools` (YAML list) is more readable for long lists

5. **Add `model` field to `test-plan.ui-verify`**
   - Only user-invocable skill without an explicit model
   - UI verification with Playwright likely benefits from `opus` for complex DOM reasoning

6. **Fix `test-plan.ui-verify` hardcoded path** (line 33 of SKILL.md)
   - `.claude/skills/test-plan.ui-verify/scripts/ui_prepare.py` -> `${CLAUDE_SKILL_DIR}/scripts/ui_prepare.py`

### Low Priority

7. **Add `argument-hint` to sub-agent skills that parse `$ARGUMENTS`**
   - `test-plan.merge`, `test-plan.resolve-gaps`, `test-plan.create.test-function`, `test-plan.score.test-function`
   - Documents expected argument format for parent skills and developers

8. **Document `test-plan-common` purpose**
   - Add a brief README.md explaining it's a shared resource directory for the skill suite
