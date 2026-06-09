# CLI Runner for Production Pipeline

## Problem

The production pipeline uses the Claude Agent SDK (`lib/agent_runner.py`) with a single `query()` + `receive_response()` cycle. This has two proven problems:

1. **`end_turn` drops background tasks.** When an agent emits text without a tool call, the SDK interprets it as session-over and closes the stream — even if background sub-agents are still running. Tested at N=30 with batch_size=5: SDK achieves 40-60% perfect runs vs CLI's 100% (see `tests/notes.md`, Findings 1-12).

2. **SDK has no skill discovery.** The SDK does not load `.claude/skills/` unless `setting_sources=["project"]` is passed, and even then skill invocation via the `Skill` tool is unreliable. The current workaround (`enable_skills=True` in `agent_runner.py`) sets `setting_sources` but native skill phases still depend on the SDK session staying alive long enough to complete.

The CLI runner (`claude -p` without `--bare`) solves both: persistent session for background tasks, native skill discovery, argument passthrough — all validated in containerized tests (Findings 8-10, 13).

## Goal

Add a CLI runner mode to `lib/agent_runner.py` so phases can choose between SDK and CLI execution. The interface (`run_agent()`) stays the same — callers don't change. The runner mode is configured per-phase in `pipeline-skills.yaml`.

## Design

### `lib/agent_runner.py` Changes

Add a `run_agent_cli()` function alongside the existing SDK-based `run_agent()`. Then modify `run_agent()` to dispatch based on a `runner` parameter.

#### `run_agent()` signature change

```python
async def run_agent(
    name: str,
    cwd: str,
    prompt: str,
    log_dir: Path,
    model: str = "sonnet",
    allowed_tools: list[str] | None = None,
    log_file: Path | None = None,
    enable_skills: bool = False,
    env: dict[str, str] | None = None,
    mcp_servers: dict | None = None,
    runner: str = "sdk",           # NEW: "sdk" or "cli"
) -> dict:
```

When `runner="cli"`, delegate to `run_agent_cli()`. When `runner="sdk"`, use the existing SDK code path. Default remains `"sdk"` so all existing callers are unaffected.

#### `run_agent_cli()` implementation

```python
async def run_agent_cli(
    name: str,
    cwd: str,
    prompt: str,
    log_file: Path,
    model: str = "sonnet",
    allowed_tools: list[str] | None = None,
    enable_skills: bool = False,
    env: dict[str, str] | None = None,
) -> dict:
```

Build and run a `claude -p` subprocess:

```python
cmd = [
    "claude", "-p", prompt,
    "--model", get_model_id(model),
    "--dangerously-skip-permissions",
    "--allowed-tools", ",".join(allowed_tools),
    "--verbose",
]

# Only use --bare when skills are NOT needed
if not enable_skills:
    cmd.append("--bare")
```

Key implementation details:

- **Subprocess via `asyncio.create_subprocess_exec`** — non-blocking, fits the existing asyncio concurrency model in `phases.py`.
- **stdout → log file** — stream stdout line-by-line to the log file and to the console (same as SDK runner does today).
- **stderr → error capture** — read stderr on non-zero exit for error reporting.
- **Environment forwarding** — merge `_FORWARDED_ENV_VARS` + caller `env` into the subprocess environment via the `env` parameter of `create_subprocess_exec`. The SDK does this via `ClaudeAgentOptions(env=...)`.
- **Return format** — same `dict` with `name`, `success`, `log_file`, `duration_seconds`, and optional `error`. Callers see no difference.
- **No `--bare` when `enable_skills=True`** — skills require CLAUDE.md and `.claude/skills/` discovery. When skills are disabled, use `--bare` for isolation and faster startup.

#### MCP servers

The CLI supports MCP config via `--mcp-config <path>` pointing to a JSON file. When `mcp_servers` is provided:

1. Write a temporary `.mcp.json` file in the agent's `cwd` with the server config.
2. Do NOT pass `--bare` (MCP discovery requires non-bare mode, same as skills).
3. Clean up the temp file after the subprocess exits.

Alternatively, if `--bare` is not used, the CLI will auto-discover `.mcp.json` in the working directory — so just ensure the project's `.mcp.json` is in place.

### `pipeline-skills.yaml` Changes

Add a `runner` field to phase config:

```yaml
phases:
  # Bug analysis — simple single-turn, SDK is fine
  completeness:
    skill: bug-completeness
    runner: sdk

  # Native skill phases — need skill discovery
  patch-validation:
    skill: patch-validation
    invoke: native
    runner: cli
    allowed_tools: [Read, Write, Glob, Grep, Bash]

  # RFE phases — native skills + may use sub-agents
  rfe-create:
    skill: rfe.create
    source: rfe-creator
    invoke: native
    runner: cli
    allowed_tools: [Read, Write, Edit, Glob, Grep, Bash]

  rfe-speedrun:
    skill: rfe.speedrun
    source: rfe-creator
    invoke: native
    runner: cli
    allowed_tools: [Read, Write, Edit, Glob, Grep, Bash, Skill]
    mcp_servers: [atlassian]
```

**Rule of thumb:**
- `invoke: templated` → `runner: sdk` (single-turn, prompt injection, no skills needed)
- `invoke: native` → `runner: cli` (needs skill discovery, may use sub-agents)

If `runner` is omitted, default to `sdk` for backward compatibility.

### `lib/skill_config.py` Changes

Update the YAML parser to read the `runner` field from phase config and pass it through to `run_agent()`.

### `lib/phases.py` Changes

All four `run_agent()` call sites pass through the `runner` parameter from the phase config. Since `run_agent()` dispatches internally, the changes are minimal:

1. **`_run_templated_phase()`** (line ~611) — add `runner=runner` kwarg. Will typically be `"sdk"`.
2. **`run_with_semaphore()`** (line ~692) — same pattern, pass `runner` from job config.
3. **`_run_native_skill_single()`** (line ~2554) — add `runner=runner`. Will typically be `"cli"`.
4. **`_run_native_skill_batch()`** (line ~2783) — same pattern.

## Files to Modify

| File | Change |
|------|--------|
| `lib/agent_runner.py` | Add `run_agent_cli()`, add `runner` param to `run_agent()`, dispatch logic |
| `lib/skill_config.py` | Parse `runner` field from phase YAML config |
| `lib/phases.py` | Pass `runner` through to all `run_agent()` call sites |
| `pipeline-skills.yaml` | Add `runner: cli` to native skill phases |

## Files NOT to Modify

| File | Reason |
|------|--------|
| `tests/conftest.py` | Already has a working CLI runner — test infrastructure is separate |
| `lib/cli.py` | No new CLI flags needed; runner is per-phase config, not a user flag |
| `main.py` | No changes — dispatches to phases which handle runner internally |

## Testing

1. **Unit validation:** Run a single native-skill phase (e.g., `strat-security-review`) with `runner: cli` and confirm it completes, produces valid output, and the log captures agent output.

2. **Comparison test:** Run the same phase with `runner: sdk` and `runner: cli` on the same issue. Compare outputs for correctness. CLI should be at least as reliable.

3. **Concurrency:** Run `bug-all` (templated phases, SDK) and a native-skill phase (CLI) concurrently to verify the asyncio semaphore works with mixed runner types.

4. **MCP:** Test a phase that uses MCP servers (e.g., `strat-submit` with Atlassian) via CLI runner. Verify the agent can reach the MCP server.

## Rollout

1. Implement `run_agent_cli()` and the dispatch logic in `agent_runner.py`.
2. Add `runner` field parsing to `skill_config.py`.
3. Update `pipeline-skills.yaml` — start with one phase (e.g., `strat-security-review`) set to `runner: cli`.
4. Validate that phase end-to-end.
5. Switch remaining `invoke: native` phases to `runner: cli`.
6. Leave `invoke: templated` phases on `runner: sdk` — they work fine and SDK is slightly faster for single-turn.

## Evidence

All findings referenced below are documented in `tests/notes.md`:

- **Findings 1, 11:** SDK simple drops 40-60% of batched background tasks
- **Finding 2:** Root cause is SDK `end_turn` closing the session prematurely
- **Finding 4:** SDK nudge loop works but agent ignores batch constraints
- **Finding 12:** SDK nudge achieves 100% but is 2.4x slower than CLI
- **Findings 8-10:** CLI runner is 100% reliable across 5 iterations (150/150 tasks)
- **Finding 13:** CLI runner supports skill invocation and argument passthrough
