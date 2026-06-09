# Pluggable Runner System + MLflow for agentic-ci

## Context

agentic-ci currently only supports invoking Claude via the CLI (`claude -p` subprocess). The pipeline's `lib/agent_runner.py` already has a working dual-runner (CLI + SDK) but it's tightly coupled to the pipeline. We want agentic-ci to be the universal runner layer, supporting both CLI and SDK invocation, with MLflow observability built in.

**Goal**: Add a runner abstraction, an SDK runner, and MLflow integration (metrics by default, tool-level tracing opt-in) to agentic-ci while keeping the package zero-dependency by default via optional extras.

## Files to Create

| File | Purpose |
|------|---------|
| `src/agentic_ci/types.py` | `RunConfig` and `RunResult` dataclasses |
| `src/agentic_ci/base_runner.py` | `Runner` protocol (typing.Protocol) |
| `src/agentic_ci/cli_runner.py` | `CLIRunner` class — extracted from current `runner.py` |
| `src/agentic_ci/sdk_runner.py` | `SDKRunner` class — ports pattern from `lib/agent_runner.py` |
| `src/agentic_ci/mlflow_metrics.py` | Post-run MLflow metrics logging from OTEL/RunResult data |
| `src/agentic_ci/mlflow_tracing.py` | `MLflowRunTracer` with observer interface for tool-level spans |

## Files to Modify

| File | Changes |
|------|---------|
| `src/agentic_ci/runner.py` | Refactor to thin dispatcher — delegates to CLIRunner or SDKRunner, calls MLflow post-hooks |
| `src/agentic_ci/stream.py` | Add optional `observer` callback to StreamProcessor for tracing hooks |
| `src/agentic_ci/cli.py` | Add `--runner` and `--mlflow-tracing` args to `run` subcommand |
| `pyproject.toml` | Add optional dependency extras: `sdk`, `mlflow`, `all` |

## Phase 1: Types and Protocol

### `src/agentic_ci/types.py`
```python
from dataclasses import dataclass, field

@dataclass
class RunConfig:
    prompt: str
    workdir: str = "."
    model: str | None = None
    user: str = "claude-ci"
    extra_args: list[str] = field(default_factory=list)
    allowed_tools: list[str] | None = None
    enable_skills: bool = False
    env: dict[str, str] | None = None
    mcp_servers: dict | None = None
    mlflow_tracing: bool = False

@dataclass
class RunResult:
    exit_code: int
    model: str
    otel_log: str | None = None        # path to OTEL JSONL (CLI runner)
    stream_capture: str | None = None   # path to stream-json capture
    stderr_log: str | None = None       # path to stderr log
    duration_seconds: float = 0.0
    # SDK runner populates these directly (no OTEL):
    total_cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    num_turns: int = 0
```

### `src/agentic_ci/base_runner.py`
```python
from typing import Protocol
from agentic_ci.types import RunConfig, RunResult

class Runner(Protocol):
    def execute(self, config: RunConfig) -> RunResult: ...
```

## Phase 2: Extract CLIRunner

### `src/agentic_ci/cli_runner.py`

Extract the current `run()` logic from `runner.py` into a `CLIRunner` class implementing `Runner.execute()`. The logic stays identical — just restructured:

- `execute(config) -> RunResult` — main entrypoint
- `_start_otel_collector(run_tmp)` — start collector subprocess, return (proc, port)
- `_stop_otel_collector(proc)` — terminate with timeout
- `_run_claude(config, otel_port, stderr_log, stream_capture, observer)` — spawn claude subprocess, stream output
- `_copy_artifacts(otel_log, stderr_log)` — copy to CI workspace

Key: the observer parameter threads through to StreamProcessor for tracing hooks.

### Refactor `src/agentic_ci/runner.py`

Becomes a thin dispatcher:
```python
def run(prompt, workdir=".", model=None, user="claude-ci",
        extra_args=None, runner="cli", mlflow_tracing=False, **kwargs) -> int:
    config = RunConfig(prompt=prompt, workdir=workdir, model=model,
                       user=user, extra_args=extra_args or [],
                       mlflow_tracing=mlflow_tracing, **kwargs)

    # Select runner
    if runner == "sdk":
        from agentic_ci.sdk_runner import SDKRunner
        backend = SDKRunner()
    else:
        from agentic_ci.cli_runner import CLIRunner
        backend = CLIRunner()

    # Optional tracing observer
    observer = None
    if mlflow_tracing:
        from agentic_ci.mlflow_tracing import MLflowRunTracer
        observer = MLflowRunTracer()
        observer.initialize(config)
        backend.observer = observer

    result = backend.execute(config)

    # Post-run MLflow metrics (auto-enabled when MLFLOW_TRACKING_URI is set)
    _log_mlflow(result, config)

    if observer:
        observer.finalize(result)

    return result.exit_code
```

Backward-compatible: existing callers of `run(prompt, workdir, model=..., extra_args=...)` work unchanged.

## Phase 3: SDK Runner

### `src/agentic_ci/sdk_runner.py`

Port from `lib/agent_runner.py` lines 110-204. Key adaptations:

- Import `claude_agent_sdk` lazily — fail with clear message if not installed
- Wrap async in `asyncio.run()` since the protocol is sync
- SDK doesn't emit OTEL, so populate RunResult directly from SDK response:
  - Cost from ResultMessage
  - Token counts from usage
  - Duration from wall clock
- Still start the StreamProcessor for console output (parse SDK messages into the same format)
- Support `observer` for MLflow tracing hooks — call observer.on_tool_start/end from SDK message events

```python
class SDKRunner:
    observer = None

    def execute(self, config: RunConfig) -> RunResult:
        try:
            from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        except ImportError:
            print("SDK runner requires claude-agent-sdk. Install with: pip install agentic-ci[sdk]")
            return RunResult(exit_code=1, model=config.model or "unknown")

        return asyncio.run(self._run_sdk(config))

    async def _run_sdk(self, config):
        # Build options (model, tools, permissions, env, mcp, skills)
        # async with ClaudeSDKClient(...) as client:
        #     await client.query(prompt)
        #     async for msg in client.receive_response():
        #         print, log, and call observer hooks
```

## Phase 4: MLflow Metrics

### `src/agentic_ci/mlflow_metrics.py`

```python
def mlflow_available() -> bool:
    """Check env var first (fast), then try import."""
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        return False
    try:
        import mlflow  # noqa: F401
        return True
    except ImportError:
        return False

def log_run_metrics(result: RunResult, config: RunConfig) -> None:
    """Log metrics from a completed run to MLflow."""
    import mlflow

    tracking_uri = os.environ["MLFLOW_TRACKING_URI"]
    mlflow.set_tracking_uri(tracking_uri)
    experiment = os.environ.get("MLFLOW_EXPERIMENT_NAME", "agentic-ci")
    mlflow.set_experiment(experiment)

    with mlflow.start_run():
        # Params
        mlflow.log_param("model", result.model)
        mlflow.log_param("runner", "cli" or "sdk")
        mlflow.log_param("prompt_length", len(config.prompt))

        # Metrics — from RunResult (SDK) or parsed from OTEL log (CLI)
        mlflow.log_metric("duration_seconds", result.duration_seconds)
        mlflow.log_metric("total_cost_usd", result.total_cost_usd)
        mlflow.log_metric("input_tokens", result.input_tokens)
        mlflow.log_metric("output_tokens", result.output_tokens)
        mlflow.log_metric("cache_read_tokens", result.cache_read_tokens)
        mlflow.log_metric("exit_code", result.exit_code)

        # For CLI runner, also parse OTEL log for richer data
        if result.otel_log:
            _log_otel_metrics(result.otel_log)

        # Artifacts
        if result.otel_log and os.path.exists(result.otel_log):
            mlflow.log_artifact(result.otel_log)
        if result.stream_capture and os.path.exists(result.stream_capture):
            mlflow.log_artifact(result.stream_capture)

def _log_otel_metrics(otel_log: str) -> None:
    """Parse OTEL JSONL and log detailed per-model token breakdowns."""
    from agentic_ci.otel_summary import parse_metrics
    # ... parse and log per-model token totals and cost
```

Called from `runner.py` as a post-run hook. Silently skipped when MLFLOW_TRACKING_URI is unset or mlflow isn't installed.

## Phase 5: MLflow Tracing (opt-in)

### `src/agentic_ci/mlflow_tracing.py`

Adapted from ambient-runner's `MLflowSessionTracer` (`deploy/repos/ambient-code.platform/components/runners/ambient-runner/ambient_runner/mlflow_observability.py`). Observer interface that both runners can call:

```python
class MLflowRunTracer:
    def initialize(self, config: RunConfig) -> None:
        """Set up MLflow experiment and start root span."""

    def on_turn_start(self, model: str, turn_number: int) -> None:
        """Create a CHAIN span for this turn."""

    def on_turn_end(self, output_text: str, usage: dict | None) -> None:
        """Close the turn span with outputs and token usage."""

    def on_tool_start(self, tool_name: str, tool_id: str, tool_input: dict) -> None:
        """Create a nested TOOL span."""

    def on_tool_end(self, tool_id: str, result: str, is_error: bool) -> None:
        """Close the tool span."""

    def finalize(self, result: RunResult) -> None:
        """Emit session summary span and flush."""
```

### StreamProcessor observer integration (`stream.py`)

Add optional `observer` parameter. At key stream-json events, call the observer:
- `message_start` → `observer.on_turn_start(model, turn_num)`
- `content_block_start` type=tool_use → `observer.on_tool_start(name, id, input)`
- `content_block_stop` for tool → `observer.on_tool_end(id, result, is_error)`
- `message_delta` / result → `observer.on_turn_end(text, usage)`

Minimally invasive — just 4-6 callback lines added to existing event handlers.

## Phase 6: CLI and Packaging

### `cli.py` changes

Add to the `run` subparser:
```python
p_run.add_argument("--runner", choices=["cli", "sdk"], default="cli")
p_run.add_argument("--mlflow-tracing", action="store_true")
```

Pass through to `run()`.

### `pyproject.toml` changes

```toml
[project.optional-dependencies]
sdk = ["claude-agent-sdk>=0.1.61"]
mlflow = ["mlflow>=3.4"]
all = ["claude-agent-sdk>=0.1.61", "mlflow>=3.4"]
```

Keep base dependencies at zero — stdlib only.

## Verification

1. **Existing behavior preserved**: `agentic-ci run "prompt" .` works exactly as before (CLI runner, no MLflow)
2. **SDK runner**: `agentic-ci run --runner sdk "prompt" .` uses SDK (requires `pip install agentic-ci[sdk]`)
3. **MLflow metrics**: Set `MLFLOW_TRACKING_URI=http://mlflow:5000` and run — metrics logged automatically
4. **MLflow tracing**: `agentic-ci run --mlflow-tracing "prompt" .` creates turn/tool spans
5. **Graceful degradation**: Running with `--runner sdk` without claude-agent-sdk installed prints clear error and exits 1
6. **Tests**: Run existing tests to verify no regressions. Add tests for RunConfig/RunResult, runner dispatch, and MLflow metric logging (with mocked mlflow).
