#!/usr/bin/env python3
"""Bound MLflow's Claude Stop hook so tracing cannot hang agent shutdown."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


TARGET_COMMAND = "mlflow autolog claude stop-hook"


def bound_stop_hooks(settings_path: Path, timeout_seconds: int) -> int:
    settings = json.loads(settings_path.read_text())
    changed = 0
    for matcher in settings.get("hooks", {}).get("Stop", []):
        for hook in matcher.get("hooks", []):
            if hook.get("type") != "command":
                continue
            if hook.get("command", "").strip() != TARGET_COMMAND:
                continue
            hook["command"] = (
                "timeout --signal=TERM --kill-after=5s "
                f"{timeout_seconds}s {TARGET_COMMAND} || true"
            )
            changed += 1
    if changed:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return changed


def main() -> int:
    settings_path = Path(
        sys.argv[1] if len(sys.argv) > 1 else "~/.claude/settings.json"
    ).expanduser()
    timeout_seconds = int(os.environ.get("MLFLOW_CLAUDE_HOOK_TIMEOUT_SECONDS", "30"))
    if timeout_seconds <= 0:
        raise ValueError("MLFLOW_CLAUDE_HOOK_TIMEOUT_SECONDS must be positive")
    if not settings_path.is_file():
        raise FileNotFoundError(settings_path)
    changed = bound_stop_hooks(settings_path, timeout_seconds)
    print(f"Bound {changed} MLflow Claude Stop hook(s) to {timeout_seconds}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
