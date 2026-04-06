"""Claude SDK agent launcher and model utilities."""

import json
import os
import tempfile
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
    runner: str = "sdk",
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
    if runner == "cli":
        if log_file is None:
            log_file = log_dir / f"{name.replace('/', '_')}.log"
        return await run_agent_cli(
            name=name,
            cwd=cwd,
            prompt=prompt,
            log_file=log_file,
            model=model,
            allowed_tools=allowed_tools,
            enable_skills=enable_skills,
            env=env,
            mcp_servers=mcp_servers,
        )

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


async def run_agent_cli(
    name: str,
    cwd: str,
    prompt: str,
    log_file: Path,
    model: str = "sonnet",
    allowed_tools: list[str] | None = None,
    enable_skills: bool = False,
    env: dict[str, str] | None = None,
    mcp_servers: dict | None = None,
) -> dict:
    """Launch a Claude agent session via the ``claude -p`` CLI.

    This runner provides persistent sessions (no premature ``end_turn``
    termination) and native skill discovery — both unavailable in the
    SDK runner for multi-turn / background-task workloads.

    Returns the same dict shape as :func:`run_agent` so callers see no
    difference.
    """
    if allowed_tools is None:
        allowed_tools = ["Read", "Write", "Glob", "Grep"]

    if enable_skills and "Skill" not in allowed_tools:
        allowed_tools = [*allowed_tools, "Skill"]

    model_id = get_model_id(model)

    # Build subprocess environment
    proc_env = dict(os.environ)
    for var in _FORWARDED_ENV_VARS:
        val = os.environ.get(var)
        if val:
            proc_env[var] = val
    if env:
        proc_env.update(env)

    # Build the CLI command
    cmd = [
        "claude", "-p", prompt,
        "--model", model_id,
        "--dangerously-skip-permissions",
        "--verbose",
        "--output-format", "stream-json",
    ]

    if allowed_tools:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])

    # MCP server config: write a temporary .mcp.json in the cwd
    mcp_tmp_path = None
    use_bare = not enable_skills

    if mcp_servers:
        use_bare = False
        mcp_config = {"mcpServers": {}}
        for srv_name, srv_cfg in mcp_servers.items():
            mcp_config["mcpServers"][srv_name] = srv_cfg
        mcp_tmp_path = Path(cwd) / ".mcp.json"
        with open(mcp_tmp_path, "w") as f:
            json.dump(mcp_config, f, indent=2)

    if use_bare:
        cmd.append("--bare")

    log_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 60}")
    print(f"Starting agent (CLI): {name}")
    print(f"Model: {model}")
    print(f"Working directory: {cwd}")
    print(f"Log file: {log_file}")
    print(f"{'=' * 60}")

    with open(log_file, "w") as log:
        log.write(f"Agent: {name}\n")
        log.write(f"Runner: cli\n")
        log.write(f"Model: {model}\n")
        log.write(f"Working directory: {cwd}\n")
        log.write(f"{'=' * 60}\n\n")
        log.write("PROMPT:\n")
        log.write(prompt)
        log.write(f"\n\n{'=' * 60}\n")
        log.write("AGENT OUTPUT:\n\n")

    start_time = time.monotonic()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=proc_env,
        )

        async def _stream_stdout(log_fh):
            async for line in proc.stdout:
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                if not decoded:
                    continue

                # Always write the raw JSON line to the log for full fidelity
                log_fh.write(f"{decoded}\n")
                log_fh.flush()

                # Parse for console summary only
                try:
                    event = json.loads(decoded)
                except json.JSONDecodeError:
                    print(f"[{name}] {decoded}")
                    continue

                etype = event.get("type", "")

                if etype == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "text":
                            print(f"[{name}] {block['text']}")
                        elif block.get("type") == "tool_use":
                            print(f"[{name}] [tool_use] {block.get('name', '?')}")
                        elif block.get("type") == "tool_result":
                            print(f"[{name}] [tool_result]")

                elif etype == "result":
                    cost = event.get("total_cost_usd", 0)
                    duration_ms = event.get("duration_ms", 0)
                    print(f"[{name}] [result] cost=${cost:.4f} duration={duration_ms}ms")

                elif etype == "system":
                    print(f"[{name}] [system:{event.get('subtype', '')}]")

        async def _stream_stderr(log_fh):
            async for line in proc.stderr:
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                if decoded:
                    log_fh.write(f"[stderr] {decoded}\n")
                    log_fh.flush()

        with open(log_file, "a") as log:
            await asyncio.gather(
                _stream_stdout(log),
                _stream_stderr(log),
            )

        await proc.wait()

        elapsed = time.monotonic() - start_time

        if proc.returncode != 0:
            error_msg = f"CLI exited with code {proc.returncode}"

            print(f"\n{'=' * 60}")
            print(f"Failed: {name} ({format_duration(elapsed)})")
            print(f"Error: {error_msg}")
            print(f"{'=' * 60}")

            with open(log_file, "a") as log:
                log.write(f"\n\n{'=' * 60}\n")
                log.write(f"ERROR: {error_msg}\n")

            return {"name": name, "success": False, "error": error_msg, "log_file": str(log_file), "duration_seconds": elapsed}

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

        with open(log_file, "a") as log:
            log.write(f"\n\n{'=' * 60}\n")
            log.write(f"ERROR: {e}\n")

        return {"name": name, "success": False, "error": str(e), "log_file": str(log_file), "duration_seconds": elapsed}

    finally:
        if mcp_tmp_path and mcp_tmp_path.exists():
            mcp_tmp_path.unlink()
