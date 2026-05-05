# Dashboard Redesign: Multi-Type Issue Support

## Context

The dashboard (`lib/webapp.py`) currently displays only bug issues (RHOAIENG) with 20 bug-specific columns. The pipeline now handles three issue types — Bugs, RFEs (RHAIRFE), and Strategies (RHAISTRAT) — each with distinct metadata schemas. The dashboard needs a tabbed interface with type-specific views plus a unified summary tab.

## Architecture

### Current State
- **webapp.py** (3,232 lines): All templates are inline Jinja2 strings loaded via `DictLoader`
- **report_data.py**: Loads bug data from `issues/*.json` + `workspace/{key}/{model}/{phase}.json`
- **RFE/Strategy data**: YAML frontmatter in `references/rfe-creator/artifacts/` — read via `scripts/frontmatter.py` CLI or `artifact_utils.py` Python module
- **Security review data**: YAML frontmatter in `security-reviews/*.md` — produced by the `strat-security-review` skill, keyed by RHAISTRAT ID
- **Frontend**: PicoCSS + vanilla JS, client-side filtering, no JS frameworks

### Target State
4 tabs: **All Issues** (default) | **Bugs** | **RFEs** | **Strategies**

## Tab Designs

### Tab 1: All Issues (Summary)
Unified view across all types. Common columns plus a compact quality indicator per type.

| Column | Source | Notes |
|--------|--------|-------|
| Type | computed | Badge: Bug / RFE / Strategy |
| Key | all types | RHOAIENG-*, RHAIRFE-*, RHAISTRAT-* |
| Summary | all types | Truncated title |
| Status | all types | Bug: Jira status; RFE: Draft/Ready/Submitted/Archived; Strat: Draft/Ready/Refined/Reviewed |
| Priority | all types | Blocker/Critical/Major/Normal/Minor |
| Quality | per-type | Bug: completeness score (0-100); RFE: review score (0-10); Strat: recommendation |
| Recommendation | per-type | Bug: fix recommendation; RFE: submit/revise/split/reject; Strat: approve/revise/split/reject |
| Security | strat only | Security review verdict badge: PASS/CONCERNS/FAIL (blank for non-strat types) |
| Attention | per-type | Bug: triage; RFE: needs_attention flag; Strat: any reviewer "reject" or security verdict CONCERNS/FAIL |

Filters: Type, Status, Priority, text search.

### Tab 2: Bugs (existing, mostly unchanged)
Keep the current 20-column bug table. Just move it into a tab context.

| Column | Source |
|--------|--------|
| Key | issue.key |
| Model | row.model |
| Summary | issue.summary |
| Status | issue.status |
| Priority | issue.priority |
| Components | issue.components |
| Issue Type | completeness.issue_type_assessment.classified_type |
| Bug Quality | completeness.overall_score (0-100) |
| AI Type | completeness classified_type badge |
| Triage | completeness.triage_recommendation |
| Arch Context | context_map.overall_rating |
| Arch Quality | context_map.context_helpfulness.overall_score |
| Arch Docs | all/partial/none |
| Src Code | all/partial/none |
| Test Context | high/medium/low |
| Fix | fix_attempt.recommendation |
| Confidence | fix_attempt.confidence |
| Test Effort | test_plan.effort_estimate |
| Write Test | write_test.decision |
| Processed | last_processed timestamp |

### Tab 3: RFEs

| Column | Source | Notes |
|--------|--------|-------|
| Key | rfe-task.rfe_id | RHAIRFE-* or RFE-* |
| Title | rfe-task.title | |
| Priority | rfe-task.priority | |
| Size | rfe-task.size | S/M/L/XL badge |
| Status | rfe-task.status | Draft/Ready/Submitted/Archived |
| Score | rfe-review.score | x/10, color-coded (red <5, yellow 5-7, green 8+) |
| Pass | rfe-review.pass | checkmark or X |
| Recommendation | rfe-review.recommendation | submit/revise/split/reject badge |
| Feasibility | rfe-review.feasibility | feasible/infeasible/indeterminate badge |
| WHAT | rfe-review.scores.what | 0-2, color dot |
| WHY | rfe-review.scores.why | 0-2, color dot |
| HOW | rfe-review.scores.open_to_how | 0-2, color dot |
| Not Task | rfe-review.scores.not_a_task | 0-2, color dot |
| Right-Sized | rfe-review.scores.right_sized | 0-2, color dot |
| Auto-Revised | rfe-review.auto_revised | bool badge |
| Attention | rfe-review.needs_attention | flag |
| Delta | score - before_score | +N or 0, shows revision improvement |

Filters: Status, Priority, Size, Recommendation, Feasibility, Pass/Fail, Needs Attention, text search.

### Tab 4: Strategies

| Column | Source | Notes |
|--------|--------|-------|
| Key | strat-task.strat_id | RHAISTRAT-* or STRAT-* |
| Title | strat-task.title | |
| Source RFE | strat-task.source_rfe | Link to RFE tab/detail |
| Priority | strat-task.priority | |
| Status | strat-task.status | Draft/Ready/Refined/Reviewed |
| Jira Key | strat-task.jira_key | RHAISTRAT-* (if submitted) |
| Recommendation | strat-review.recommendation | approve/revise/split/reject badge |
| Feasibility | strat-review.reviewers.feasibility | approve/revise/reject badge |
| Testability | strat-review.reviewers.testability | approve/revise/reject badge |
| Scope | strat-review.reviewers.scope | approve/revise/reject badge |
| Architecture | strat-review.reviewers.architecture | approve/revise/reject badge |
| Sec Verdict | security-review.verdict | PASS (green) / CONCERNS (yellow) / FAIL (red) badge; blank if no review |
| Sec Tier | security-review.review_tier | light/standard/deep badge |
| Sec Risks | security-review.risk_count | Total risk count (sum of critical+high+medium); color-coded: 0=green, 1-2=yellow, 3+=red |
| Critical | security-review.risk_count.critical | Count, red if >0 |
| High | security-review.risk_count.high | Count, orange if >0 |
| Medium | security-review.risk_count.medium | Count, yellow if >0 |

Filters: Status, Priority, Recommendation, any reviewer verdict, Security Verdict, text search.

## Data Loading

### New: `load_rfe_issues()` and `load_strat_issues()`

Add to `lib/report_data.py` (or a new `lib/rfe_data.py`):

```python
def load_rfe_issues(artifacts_dir: Path) -> list[dict]:
    """Scan rfe-tasks/ and rfe-reviews/ under artifacts_dir.

    Returns list of dicts with merged task + review frontmatter.
    Each dict has: type="rfe", all rfe-task fields, all rfe-review
    fields (prefixed or nested under 'review'), and the review
    markdown body.
    """

def load_strat_issues(artifacts_dir: Path) -> list[dict]:
    """Scan strat-tasks/ and strat-reviews/ under artifacts_dir.

    Returns list of dicts with merged task + review frontmatter.
    """

def load_security_reviews(security_reviews_dir: Path) -> dict[str, dict]:
    """Scan security-reviews/ for *-security-review.md files.

    Returns dict keyed by strat_key (e.g. "RHAISTRAT-1") with
    frontmatter fields: verdict, review_tier, review_date,
    risk_count (critical, high, medium, low), and
    architecture_context_consulted.
    """
```

Reading frontmatter: use `yaml.safe_load()` on the YAML between `---` delimiters (same approach as `scripts/frontmatter.py`). Do NOT import from the rfe-creator repo — keep the pipeline self-contained with a simple frontmatter parser.

### Artifacts Directories

- **RFE/Strategy artifacts**: `references/rfe-creator/artifacts/`. Path determined by `pipeline-skills.yaml` → `skill_repos.rfe-creator.path`. The dashboard should resolve this from config or accept it as a parameter.
- **Security reviews**: `security-reviews/` in the pipeline project root. Files named `<STRAT-KEY>-security-review.md` with YAML frontmatter. Joined to strategy data by `strat_key`.

## Implementation Steps

### Step 1: Data loaders
- Add `load_rfe_issues()` and `load_strat_issues()` functions
- Add `load_security_reviews()` function for `security-reviews/` directory
- Simple YAML frontmatter parser (don't depend on rfe-creator scripts)
- Join task + review data by ID; join security reviews to strategies by `strat_key`

### Step 2: API endpoints
- Add `/api/rfes` and `/api/strategies` JSON endpoints (strategies include merged security review data)
- Modify `/api/issues` to optionally include all types

### Step 3: Dashboard template — tabs
- Add tab navigation bar to `DASHBOARD` template
- Wrap existing bug table in a tab panel
- Add RFE and Strategy tab panels with their column layouts
- Add "All Issues" summary tab as the default

### Step 4: Client-side filtering per tab
- Each tab has its own filter bar with type-appropriate dropdowns
- Reuse the existing `applyFilters()` pattern — one filter function per tab
- Tab switching shows/hides the appropriate filter bar + table

### Step 5: Styling
- Tab styling consistent with PicoCSS
- Color-coded badges for new fields (feasibility, recommendation, rubric scores)
- Rubric scores (0-2) as colored dots: red=0, yellow=1, green=2
- Security verdict badges: PASS=green, CONCERNS=yellow, FAIL=red
- Security risk counts: 0=green, >0=red/orange/yellow per severity

### Step 6: Detail views (optional, later)
- RFE detail page showing full review markdown, feasibility notes, revision history
- Strategy detail page showing all reviewer assessments and security review body (threat surface analysis, risks, NFR gaps, amendments)

## Files to Modify

| File | Change |
|------|--------|
| `lib/report_data.py` (or new `lib/rfe_data.py`) | Add frontmatter parser, `load_rfe_issues()`, `load_strat_issues()`, `load_security_reviews()` |
| `lib/webapp.py` | Add tabs to DASHBOARD template, new tab templates, new API routes, badge CSS |
| `pipeline-skills.yaml` | No changes needed (artifacts path already configured) |

## Verification

1. Run `uv run main.py dashboard` and verify 4 tabs render
2. Bug tab should look identical to the current dashboard
3. RFE tab should show RHAIRFE-953 with all review data
4. Strategy tab should show any RHAISTRAT entries (if strat-create has run)
5. Strategy tab should show security review columns for RHAISTRAT-1 (verdict=CONCERNS, tier=standard, 1 medium risk)
6. All Issues tab should show all three types with summary columns, including security verdict for strategies
7. Filtering should work independently per tab (including Security Verdict filter on Strategies tab)
8. Sorting should work on all columns
