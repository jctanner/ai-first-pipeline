"""Claude SDK agent launcher and model utilities."""

import os
import time
import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions


# Environment variables forwarded to every agent session so that
# skills and scripts that need Jira access (or other shared config)
# can find them.  Values are read from ``os.environ`` at launch time.
_FORWARDED_ENV_VARS = [
    "JIRA_SERVER",
    "JIRA_USER",
    "JIRA_TOKEN",
]


def get_model_display_name(model_shorthand: str) -> str:
    """Convert model shorthand to human-readable display name."""
    display_names = {
        "sonnet": "Claude Sonnet 4.5",
        "opus": "Claude Opus 4.6",
        "haiku": "Claude Haiku 3.5",
    }
    return display_names.get(model_shorthand, model_shorthand)


def get_model_id(model_shorthand: str) -> str:
    """Convert model shorthand to full model ID."""
    model_mapping = {
        "sonnet": "claude-sonnet-4-5",
        "opus": "claude-opus-4-6",
        "haiku": "claude-haiku-3-5",
    }
    return model_mapping.get(model_shorthand, model_shorthand)


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


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
) -> dict:
    """
    Launch one independent Claude agent session.

    Args:
        name: Job name for identification
        cwd: Working directory for the agent
        prompt: Prompt to send to the agent
        log_dir: Directory to write log files
        model: Claude model to use (sonnet, opus, or haiku)
        allowed_tools: Tools the agent can use (default: Read, Write, Glob, Grep)
        log_file: Explicit log file path. When provided, used instead of
                  ``log_dir / f"{name}.log"``.
        enable_skills: When True, load project skills from ``.claude/skills/``
                       and add the ``Skill`` tool so the agent can invoke them
                       natively.
        env: Extra environment variables to pass to the agent session.
             Variables from ``_FORWARDED_ENV_VARS`` that are present in
             ``os.environ`` are always included automatically.
        mcp_servers: MCP server configurations to connect to the agent
                     session (e.g. ``{"atlassian": {"type": "sse",
                     "url": "http://localhost:8081/sse"}}``).

    Returns:
        dict with 'name', 'success', 'log_file', and optional 'error' keys
    """
    if allowed_tools is None:
        allowed_tools = ["Read", "Write", "Glob", "Grep"]

    if enable_skills and "Skill" not in allowed_tools:
        allowed_tools = [*allowed_tools, "Skill"]

    if log_file is None:
        log_file = log_dir / f"{name.replace('/', '_')}.log"
    model_id = get_model_id(model)

    # Build the environment dict: start with auto-forwarded vars,
    # then layer on any caller-provided overrides.
    agent_env: dict[str, str] = {}
    for var in _FORWARDED_ENV_VARS:
        val = os.environ.get(var)
        if val:
            agent_env[var] = val
    if env:
        agent_env.update(env)

    # NOTE on context isolation: each query() call starts a fresh session
    # with no memory of previous runs.  The SDK does NOT load auto-memory
    # (~/.claude/projects/<project>/memory/) — that is a CLI-only feature.
    # CLAUDE.md / project settings are also NOT loaded unless explicitly
    # enabled via setting_sources=["project"].  We omit that option here
    # so every agent session is fully isolated — unless enable_skills is
    # set, in which case we load project settings so .claude/skills/ are
    # discovered.
    extra_opts: dict = {}
    if enable_skills:
        extra_opts["setting_sources"] = ["project"]
    if mcp_servers:
        extra_opts["mcp_servers"] = mcp_servers

    options = ClaudeAgentOptions(
        cwd=cwd,
        allowed_tools=allowed_tools,
        permission_mode="bypassPermissions",
        model=model_id,
        env=agent_env,
        **extra_opts,
    )

    log_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"Starting agent: {name}")
    print(f"Model: {model}")
    print(f"Working directory: {cwd}")
    print(f"Log file: {log_file}")
    print(f"{'=' * 60}")

    with open(log_file, 'w') as log:
        log.write(f"Agent: {name}\n")
        log.write(f"Model: {model}\n")
        log.write(f"Working directory: {cwd}\n")
        log.write(f"{'=' * 60}\n\n")
        log.write("PROMPT:\n")
        log.write(prompt)
        log.write(f"\n\n{'=' * 60}\n")
        log.write("AGENT OUTPUT:\n\n")

    start_time = time.monotonic()

    try:
        with open(log_file, 'a') as log:
            async with ClaudeSDKClient(options=options) as client:
                await client.query(prompt)

                async for msg in client.receive_response():
                    print(f"[{name}] {msg}")
                    log.write(f"{msg}\n")
                    log.flush()

        elapsed = time.monotonic() - start_time

        print(f"\n{'=' * 60}")
        print(f"Completed: {name} ({format_duration(elapsed)})")
        print(f"{'=' * 60}")

        return {"name": name, "success": True, "log_file": str(log_file), "duration_seconds": elapsed}

    except Exception as e:
        elapsed = time.monotonic() - start_time

        print(f"\n{'=' * 60}")
        print(f"Failed: {name} ({format_duration(elapsed)})")
        print(f"Error: {e}")
        print(f"{'=' * 60}")

        with open(log_file, 'a') as log:
            log.write(f"\n\n{'=' * 60}\n")
            log.write(f"ERROR: {e}\n")

        return {"name": name, "success": False, "error": str(e), "log_file": str(log_file), "duration_seconds": elapsed}
