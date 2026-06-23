#!/usr/bin/env python3
"""Parse OpenCode --format json (JSONL) output into a human-readable CI log.

OpenCode emits one JSON object per line with event types:
  step_start, step_finish, tool_use, error

Same interface as stream-claude.py: reads stdin, writes to stdout, accepts --pid.
"""

import argparse
import json
import os
import signal
import sys

parser = argparse.ArgumentParser(description="Parse OpenCode JSONL stream output")
parser.add_argument(
    "--no-color", action="store_true",
    help="Disable ANSI color codes in output",
)
parser.add_argument(
    "--pid", type=int, default=0,
    help="PID of OpenCode process to kill on completion",
)
args = parser.parse_args()

if args.no_color:
    THINK_COLOR = TOOL_COLOR = TEXT_COLOR = RED = YELLOW = RESET = ""
else:
    THINK_COLOR = "\033[3;31m"
    TOOL_COLOR = "\033[1;90m"
    TEXT_COLOR = ""
    RED = "\033[31m"
    YELLOW = "\033[33m"
    RESET = "\033[0m"

_total_input_tokens = 0
_total_output_tokens = 0


def _format_tool(name, params):
    """Return a compact one-line summary for known tools."""
    if not params:
        return ""
    if name in ("bash", "Bash"):
        return params.get("command", "")
    if name in ("read", "Read"):
        return params.get("file_path", params.get("path", ""))
    if name in ("write", "Write"):
        return params.get("file_path", params.get("path", ""))
    if name in ("edit", "Edit"):
        path = params.get("file_path", params.get("path", ""))
        return path
    if name in ("grep", "Grep"):
        pattern = params.get("pattern", "")
        path = params.get("path", ".")
        return f"/{pattern}/ in {path}"
    return ", ".join(f"{k}={v}" for k, v in list(params.items())[:3])


for raw_line in sys.stdin:
    raw_line = raw_line.strip()
    if not raw_line:
        continue

    try:
        event = json.loads(raw_line)
    except (json.JSONDecodeError, ValueError):
        continue

    event_type = event.get("type", "")

    if event_type == "step_start":
        snapshot = event.get("part", {}).get("snapshot", "")
        if snapshot:
            print(f"{THINK_COLOR}\U0001f9e0 Thinking {snapshot[:200]}{RESET}", flush=True)
        else:
            print(f"{THINK_COLOR}\U0001f9e0 Step started{RESET}", flush=True)

    elif event_type == "step_finish":
        part = event.get("part", {})
        tokens = part.get("tokens", {})
        cache = tokens.get("cache", {})
        cost = part.get("cost", 0)
        tokens_in = tokens.get("input", 0)
        tokens_out = tokens.get("output", 0)
        reasoning = tokens.get("reasoning", 0)
        cache_read = cache.get("read", 0)
        cache_write = cache.get("write", 0)
        _total_input_tokens += tokens_in
        _total_output_tokens += tokens_out

        total = tokens_in + tokens_out + reasoning + cache_read + cache_write
        cost_str = f" cost=${cost:.4f}" if cost else ""
        print(
            f"{TOOL_COLOR}  \U0001f4ca TOKENS in={tokens_in} out={tokens_out} "
            f"reasoning={reasoning} cache_r={cache_read} cache_w={cache_write} "
            f"total={total}{cost_str}{RESET}",
            flush=True,
        )

    elif event_type == "tool_use":
        part = event.get("part", {})
        tool_name = part.get("tool", part.get("name", event.get("name", "unknown")))
        state = part.get("state", {})
        status = state.get("status", "") if isinstance(state, dict) else state
        params = state.get("input", {}) if isinstance(state, dict) else {}

        summary = _format_tool(tool_name, params) if params else ""

        if status in ("running", "start", ""):
            icon = "\U0001f527"
            line = f"  {TOOL_COLOR}{icon} {tool_name}"
            if summary:
                line += f" {summary}"
            line += RESET
            print(line, flush=True)

        if status == "error":
            err = state.get("error", "") if isinstance(state, dict) else ""
            print(f"  {RED}✗ {tool_name} error: {err}{RESET}", flush=True)

    elif event_type == "error":
        error = event.get("error", {})
        error_name = error.get("name", "unknown") if isinstance(error, dict) else "unknown"
        error_data = error.get("data", {}) if isinstance(error, dict) else {}
        error_msg = error_data.get("message", str(error)) if isinstance(error_data, dict) else str(event)
        print(f"{RED}❌ Error: {error_name}: {error_msg}{RESET}", flush=True)

    elif event_type == "text":
        part = event.get("part", {})
        text = part.get("text", event.get("text", ""))
        time_info = part.get("time", {})
        if text and time_info.get("end"):
            print(f"{TEXT_COLOR}\U0001f4ac {text}{RESET}", flush=True)

print()
print(
    f"{TOOL_COLOR}\U0001f4ca TOTAL in={_total_input_tokens} "
    f"out={_total_output_tokens}{RESET}",
    flush=True,
)
