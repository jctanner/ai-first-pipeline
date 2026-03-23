# Plan: Post-Fix Validation Loop with odh-tests-context

## Context

The bug-bash pipeline's fix-attempt phase spawns Claude agents that edit code in cloned midstream repos, but never validates the patches. The agent only has Read/Write/Glob/Grep tools -- no Bash -- so it can't run linters or tests. The orchestrator (`lib/phases.py`) captures `git diff` after the agent finishes but does nothing else. Patches are suggestions, not validated changes.

The `odh-tests-context` project (symlinked at `./odh-tests-context/`) already solved the discovery problem: it has pre-validated container recipes with lint/test commands for 162 opendatahub-io repos (31% high readiness, 38% medium). The data is sitting there unused.

This plan connects the two: after the fix agent produces a patch, the orchestrator runs lint/tests in a container using the odh-tests-context recipes, and if validation fails, launches a new agent session with the error output so it can fix its work.

## Architecture Decision

**Orchestrator-driven validation (not agent Bash access).**

The fix agent keeps its restricted tool set. The orchestrator (Python code in `phases.py`) handles container lifecycle, command execution, and result capture -- it already does analogous work with `subprocess` for `git diff` and workspace cleanup. The agent's job is understanding code and producing fixes; validation feedback is just structured text that gets injected into a retry prompt.

This avoids escalating the agent's permissions (these run with `bypassPermissions` across hundreds of repos) and keeps container orchestration deterministic rather than LLM-driven.

## Implementation

### Step 1: Create `lib/validation.py`

New module with these functions:

- **`load_test_context(repo_name)`** -- Loads `odh-tests-context/tests/{repo_name}.json`. Returns `None` if missing/malformed.
- **`is_validation_eligible(test_context)`** -- Returns `True` if `agent_readiness` is `"high"` or `"medium"`.
- **`resolve_container_recipes(test_context, changed_files)`** -- Handles two JSON formats:
  - Flat: `container_recipe.base_image` exists at top level (odh-dashboard style) → return `[recipe]`
  - Nested by language: `container_recipe.go`, `container_recipe.python` (kserve style) → match changed file extensions (`.go`→go, `.py`→python, `.ts/.tsx/.js`→frontend) and return matching sub-recipes
- **`start_validation_container(repo_name, recipe, workspace_path)`** -- `podman run -d --name bugbash-val-{repo}-{ts} -v {path}:/app:Z -w /app {base_image} sleep infinity`
- **`run_setup_commands(container_name, recipe)`** -- Install system deps + run setup commands. Returns success bool.
- **`run_validation_commands(container_name, recipe, changed_files)`** -- Run `lint_commands` then `test_commands`. For each: capture exit code, stdout (truncated to 4KB), stderr. Skip commands where the test context says `validated: false` (already broken on base repo). Filter lint output to lines mentioning files in the patch for cleaner signal.
- **`stop_validation_container(container_name)`** -- `podman rm -f {name}`
- **`validate_patch(repo_name, workspace_path, changed_files)`** -- Orchestrates full lifecycle. Returns a `ValidationResult` dataclass.
- **`format_validation_feedback(results)`** -- Formats failures into markdown for the retry prompt: command, exit code, relevant stdout/stderr lines. This is what the agent reads to understand what to fix.

Key data structures:
```python
@dataclass
class ValidationCommand:
    command: str
    category: str  # "lint" or "test"
    exit_code: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    passed: bool

@dataclass
class ValidationResult:
    repo_name: str
    agent_readiness: str
    setup_success: bool
    commands: list[ValidationCommand]
    lint_passed: bool
    tests_passed: bool
    overall_passed: bool
    skipped: bool
    skip_reason: str
    duration_seconds: float
```

### Step 2: Update `lib/schemas.py`

Add optional `validation` property to `FIX_ATTEMPT_SCHEMA`. The agent doesn't produce this -- the orchestrator injects it post-hoc. Structure:

```python
"validation": {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["iteration", "results", "all_passed"],
        "properties": {
            "iteration": {"type": "integer"},
            "all_passed": {"type": "boolean"},
            "results": { ... per-repo validation results ... }
        }
    }
}
```

Not added to `required` array -- existing fix-attempt outputs without it remain valid.

### Step 3: Update `lib/cli.py`

Add to `fix-attempt` and `all` subcommands:
- `--validation-retries N` (default: 2, 0 disables validation)
- `--skip-validation` (flag to skip entirely)

### Step 4: Update `lib/phases.py`

**4a. Add helper functions:**
- `_run_validation_loop()` -- async function that validates the patch, and on failure launches a new agent session with the original prompt plus a `## Validation Feedback` section containing the error output. Repeats up to `max_iterations` times.
- `_update_fix_json_validation()` -- Injects the validation results array into the fix-attempt JSON.

**4b. Inject test context into the fix agent's prompt:**

Before building the fix prompt, look up `odh-tests-context/tests/{comp_name}.md` for each cloned repo and pass it as `test_context=...` to `build_phase_prompt()`. This way the agent knows upfront which lint/test commands will run post-fix and can proactively write cleaner code.

**4c. Insert validation loop into `_maybe_run_fix_attempt()`:**

After the existing git diff capture (around line 1312), add:

```
if not skip_validation and validation_retries > 0:
    validation_results = await _run_validation_loop(...)
    _update_fix_json_validation(json_path, validation_results)
```

Same change in `run_fix_attempt_phase()` for batch mode.

**4d. Validation loop flow:**

```
for iteration in 1..max_iterations:
    run validation in container for each eligible repo
    if all passed: break
    if last iteration: record failure and break
    build retry prompt = original prompt + "## Validation Feedback\n\n{errors}"
    reset workspace (git checkout . && git clean -fd)
    launch new agent session with retry prompt
    capture new git diff
```

Container lifecycle: start once per repo, reuse across iterations (only `git checkout/clean` between iterations, not re-install deps). Cleanup in `finally` block.

### Step 5: Update `.claude/skills/bug-fix-attempt/SKILL.md`

Add after the "Self-review" step:

```markdown
5. **Anticipate validation:**
   - If a Test Context section is provided, review the lint and test commands
   - Ensure changes pass the linting rules described
   - If validation feedback is provided (retry), fix the specific errors reported
```

## Key Design Decisions

**Only validate commands marked `validated: true` in the test context.** Commands with `validated: false` already fail on the base repo and provide no signal about whether the patch broke something.

**Filter lint output to changed files.** Pre-existing lint violations in untouched files shouldn't block the patch. Parse `git diff --name-only` and grep lint output for those filenames.

**Container per-issue, not per-pipeline.** Containers hold state (installed deps). Reuse across retry iterations of the same issue (saves setup time). Don't reuse across different issues (dirty state risk). Concurrency is bounded by the existing `--max-concurrent` semaphore.

**2 retry iterations default.** Most lint failures are trivial (unused import, formatting). 2 retries gives the agent a chance to fix. Configurable via `--validation-retries`.

**Timeouts:** 600s for setup commands (go mod download / npm install are slow), 300s per validation command, container cleanup always runs in `finally`.

## Files to Modify

| File | Change |
|------|--------|
| `lib/validation.py` | **New file** -- container validation logic |
| `lib/schemas.py` | Add optional `validation` property to `FIX_ATTEMPT_SCHEMA` |
| `lib/cli.py` | Add `--validation-retries` and `--skip-validation` flags |
| `lib/phases.py` | Add `_run_validation_loop()`, inject test context into prompt, insert validation after git diff capture in both `_maybe_run_fix_attempt()` and `run_fix_attempt_phase()` |
| `.claude/skills/bug-fix-attempt/SKILL.md` | Add "Anticipate validation" step |

## Verification

1. Run against a single issue with a known-fixable bug in a "high" readiness repo:
   ```
   python main.py fix-attempt --issue RHOAIENG-XXXXX --force --validation-retries 2
   ```
2. Check the resulting `.fix-attempt.json` for the `validation` array
3. Verify container starts, runs lint/test, captures output, cleans up
4. If the first iteration fails, verify the retry prompt includes the error output and the agent produces a corrected fix
5. Verify `--skip-validation` bypasses the loop entirely
6. Verify repos with `agent_readiness: "low"` or `"none"` are skipped gracefully
