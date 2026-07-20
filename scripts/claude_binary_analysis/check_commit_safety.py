#!/usr/bin/env python3
"""Reject staged binary-analysis payloads, large files, and obvious secrets."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys


MAX_COMMITTED_BYTES = 1024 * 1024
RAW_PREFIX = "tmp/claude-code-binary-analysis/"
SENSITIVE = re.compile(
    rb"(?:sk-ant-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|Bearer\s+[A-Za-z0-9._-]{20,})"
)


def staged_paths(root: Path) -> list[str]:
    output = subprocess.check_output(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"]
    )
    return [item.decode("utf-8") for item in output.split(b"\0") if item]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    root = args.root.resolve()
    paths = args.paths or staged_paths(root)
    errors: list[str] = []
    for relative in paths:
        if relative.startswith(RAW_PREFIX):
            errors.append(f"raw analysis workspace must not be committed: {relative}")
            continue
        if not relative.startswith(("scripts/claude_binary_analysis/", "docs/notes/", "var/demos/skill-disambiguation/results/")):
            continue
        path = root / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > MAX_COMMITTED_BYTES:
            errors.append(f"analysis deliverable exceeds 1 MiB: {relative}")
        if b"\0" in data:
            errors.append(f"analysis deliverable contains NUL/binary data: {relative}")
        if SENSITIVE.search(data):
            errors.append(f"analysis deliverable contains a credential-like value: {relative}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"checked {len(paths)} paths")
    return 0


if __name__ == "__main__":
    sys.exit(main())
