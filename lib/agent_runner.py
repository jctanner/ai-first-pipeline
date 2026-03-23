"""Claude SDK agent launcher and model utilities."""

import time
import asyncio
from pathlib import Path

from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions


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


async def run_agent(name: str, cwd: str, prompt: str, log_dir: Path, model: str = "sonnet") -> dict:
    """
    Launch one independent Claude agent session.

    Args:
        name: Job name for identification
        cwd: Working directory for the agent
        prompt: Prompt to send to the agent
        log_dir: Directory to write log files
        model: Claude model to use (sonnet, opus, or haiku)

    Returns:
        dict with 'name', 'success', 'log_file', and optional 'error' keys
    """
    log_file = log_dir / f"{name.replace('/', '_')}.log"
    model_id = get_model_id(model)

    options = ClaudeAgentOptions(
        cwd=cwd,
        allowed_tools=["Read", "Write", "Glob", "Grep"],
        permission_mode="bypassPermissions",
        model=model_id,
    )

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
