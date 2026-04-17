# Claude SDK + MLflow Integration Options

## Summary

**The claude-agent-sdk does NOT have built-in MLflow support**, but it provides comprehensive hooks and metrics that make manual integration straightforward.

## Evidence

Searched the claude-agent-sdk repository (v0.1.48):
- ❌ No MLflow imports or references
- ❌ No LangChain integration (MLflow's langchain.autolog won't work)
- ✅ Has comprehensive hook system (`PreToolUse`, `PostToolUse`, etc.)
- ✅ Returns detailed metrics in `ResultMessage`

## Available Metrics in SDK

From `src/claude_agent_sdk/types.py`:

```python
class ResultMessage:
    duration_ms: int              # Total execution time
    duration_api_ms: int          # API call time
    is_error: bool               # Success/failure
    num_turns: int               # Number of conversation turns
    stop_reason: str | None      # Why execution stopped
    total_cost_usd: float | None # Cost in USD
    usage: dict[str, Any]        # Token usage details
    model_usage: dict[str, Any]  # Per-model usage
    permission_denials: list     # Blocked operations
    errors: list[str]            # Error messages
```

## Hook System

The SDK provides hooks at these events:

```python
HookEvent = (
    "PreToolUse"            # Before each tool call
    | "PostToolUse"         # After successful tool use
    | "PostToolUseFailure"  # After failed tool use
    | "UserPromptSubmit"    # When user submits prompt
    | "Stop"                # When execution stops
    | "SubagentStop"        # When sub-agent completes
    | "PreCompact"          # Before context compression
    | "Notification"        # System notifications
    | "SubagentStart"       # When sub-agent starts
    | "PermissionRequest"   # When permission is needed
)
```

Example hook usage:

```python
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import HookMatcher, HookInput, HookContext

async def log_tool_use(input_data: HookInput, tool_use_id: str | None, 
                       context: HookContext) -> dict:
    """Log each tool use to MLflow."""
    tool_name = input_data["tool_name"]
    tool_input = input_data["tool_input"]
    
    mlflow.log_metric(f"tool_use_{tool_name}", 1, step=context.turn_number)
    mlflow.log_params({"last_tool": tool_name})
    
    return {}

options = ClaudeAgentOptions(
    hooks={
        "PostToolUse": [
            HookMatcher(matcher=None, hooks=[log_tool_use])
        ]
    }
)

async with ClaudeSDKClient(options=options) as client:
    await client.query("Your prompt here")
    async for msg in client.receive_response():
        if isinstance(msg, ResultMessage):
            # Log final metrics
            mlflow.log_metrics({
                "duration_ms": msg.duration_ms,
                "num_turns": msg.num_turns,
                "total_cost_usd": msg.total_cost_usd or 0.0
            })
```

## Integration Approaches

### Option 1: Wrapper Function (Recommended)

Create `lib/agent_runner_mlflow.py`:

```python
import mlflow
from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
from claude_agent_sdk.types import HookMatcher, ResultMessage

async def run_skill_with_mlflow(skill_name: str, issue_key: str, 
                                  model: str, **kwargs) -> ResultMessage:
    """Run skill with MLflow tracing."""
    
    # Set up MLflow
    mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI"))
    
    with mlflow.start_run(run_name=f"{skill_name}-{issue_key}"):
        # Log input parameters
        mlflow.log_params({
            "skill": skill_name,
            "issue": issue_key,
            "model": model,
            "runner": "sdk"
        })
        
        # Set up hooks for tool-level tracking
        async def log_tool(input_data, tool_use_id, context):
            tool_name = input_data.get("tool_name", "unknown")
            mlflow.log_metric(f"tool_{tool_name}", 1)
            return {}
        
        options = ClaudeAgentOptions(
            model=get_model_id(model),
            hooks={
                "PostToolUse": [HookMatcher(matcher=None, hooks=[log_tool])]
            },
            **kwargs
        )
        
        # Run agent
        async with ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            
            result = None
            async for msg in client.receive_response():
                if isinstance(msg, ResultMessage):
                    result = msg
            
            # Log final metrics
            if result:
                mlflow.log_metrics({
                    "duration_ms": result.duration_ms,
                    "duration_api_ms": result.duration_api_ms,
                    "num_turns": result.num_turns,
                    "cost_usd": result.total_cost_usd or 0.0,
                    "is_error": 1 if result.is_error else 0
                })
                
                if result.usage:
                    for key, value in result.usage.items():
                        mlflow.log_metric(f"usage_{key}", value)
            
            return result
```

**Pros:**
- ✅ Full control over what gets logged
- ✅ Can log per-tool metrics via hooks
- ✅ Access to all SDK metrics
- ✅ ~50 lines of code

**Cons:**
- ❌ Manual implementation (not automatic)
- ❌ Need to maintain logging code

### Option 2: Context Manager

```python
class MLflowTracedAgent:
    """Context manager for SDK execution with MLflow tracing."""
    
    def __init__(self, run_name: str, tracking_uri: str = None):
        self.run_name = run_name
        self.tracking_uri = tracking_uri or os.getenv("MLFLOW_TRACKING_URI")
        self.run = None
    
    def __enter__(self):
        mlflow.set_tracking_uri(self.tracking_uri)
        self.run = mlflow.start_run(run_name=self.run_name)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.run:
            mlflow.end_run()
    
    async def run_agent(self, client: ClaudeSDKClient, prompt: str):
        """Run agent and log to MLflow."""
        await client.query(prompt)
        
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                mlflow.log_metrics({
                    "duration_ms": msg.duration_ms,
                    "num_turns": msg.num_turns,
                    "cost_usd": msg.total_cost_usd or 0.0
                })
                return msg

# Usage:
with MLflowTracedAgent(run_name=f"{skill}-{issue}") as tracer:
    async with ClaudeSDKClient() as client:
        result = await tracer.run_agent(client, prompt)
```

**Pros:**
- ✅ Clean API
- ✅ Reusable pattern
- ✅ Automatic cleanup

**Cons:**
- ❌ Less flexible than Option 1
- ❌ Still manual implementation

### Option 3: Decorator Pattern

```python
def with_mlflow_tracing(run_name_template: str):
    """Decorator to add MLflow tracing to async functions."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            run_name = run_name_template.format(**kwargs)
            
            mlflow.set_tracking_uri(os.getenv("MLFLOW_TRACKING_URI"))
            with mlflow.start_run(run_name=run_name):
                result = await func(*args, **kwargs)
                
                # Log metrics if result is ResultMessage
                if isinstance(result, ResultMessage):
                    mlflow.log_metrics({
                        "duration_ms": result.duration_ms,
                        "num_turns": result.num_turns
                    })
                
                return result
        return wrapper
    return decorator

# Usage:
@with_mlflow_tracing(run_name_template="{skill_name}-{issue_key}")
async def run_skill_agent(skill_name, issue_key, model, **kwargs):
    # ... existing implementation
    pass
```

**Pros:**
- ✅ Minimal code changes to existing functions
- ✅ Clean separation of concerns

**Cons:**
- ❌ Less control over what gets logged
- ❌ Template-based naming can be limiting

## Comparison: CLI vs SDK MLflow Support

| Feature | CLI Runner | SDK Runner |
|---------|-----------|------------|
| MLflow Support | ✅ Built-in (`mlflow autolog claude`) | ❌ Manual implementation needed |
| MCP Support | ❌ Lazy-loading race condition | ✅ Proper initialization |
| Effort to Add | None (already works) | ~50-100 lines of code |
| Control Over Logging | Limited (hook-based) | Full control |
| Tool-level Metrics | Via hooks | Via hooks (same mechanism) |
| Cost Tracking | ✅ Automatic | ✅ Available in ResultMessage |
| Token Usage | ✅ Automatic | ✅ Available in ResultMessage |

## Recommendation

**Use Option 1 (Wrapper Function)** for SDK runner:

1. Create `lib/agent_runner_mlflow.py` with wrapper function
2. Update `scripts/run_skill_sdk.sh` to use the wrapper
3. Test that metrics appear in MLflow UI

**Estimated effort:** 2-3 hours

**Benefits over CLI:**
- ✅ MCP works properly (primary goal)
- ✅ Full control over MLflow logging
- ✅ Can add custom metrics easily
- ✅ Per-tool logging via hooks

**Trade-off:**
- Need to maintain ~100 lines of MLflow integration code
- Not "automatic" like CLI's autolog

## Implementation Priority

Given the MCP issue is blocking strat.create:

1. **Phase 1:** Implement SDK runner WITHOUT MLflow (prove MCP works)
2. **Phase 2:** Add MLflow wrapper (restore observability)
3. **Phase 3:** Add per-tool metrics via hooks (enhancement)

This allows us to fix the immediate MCP problem while deferring the MLflow work.

## References

- SDK Hooks Example: `deploy/repos/claude-agent-sdk/examples/hooks.py`
- SDK Types: `deploy/repos/claude-agent-sdk/src/claude_agent_sdk/types.py`
- Current agent_runner: `lib/agent_runner.py`
- CLI MLflow Setup: `scripts/run_skill.sh` line 94-102
