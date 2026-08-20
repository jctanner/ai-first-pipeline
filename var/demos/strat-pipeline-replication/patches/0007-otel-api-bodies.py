#!/usr/bin/env python3
"""Capture Claude API bodies as opt-in GitLab job artifacts.

The pipeline launcher remains safe by default. The emulator bootstrap enables
CAPTURE_API_BODIES=1 on the fixture project so the full Anthropic Messages API
request/response bodies can be inspected without putting them in stdout or the
shared results repository.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}: {old!r}")
    path.write_text(content.replace(old, new, 1))


def apply(root: Path) -> list[str]:
    changed: list[str] = []

    ci = root / ".gitlab-ci.yml"
    replace_once(
        ci,
        "      - claude-stderr.log\n",
        "      - claude-stderr.log\n"
        "      - claude-api-bodies/\n",
    )
    changed.append(".gitlab-ci.yml")

    launcher = root / "ci-scripts/run-claude.sh"
    replace_once(
        launcher,
        "export OTEL_METRIC_EXPORT_INTERVAL=10000\n",
        "export OTEL_METRIC_EXPORT_INTERVAL=10000\n\n"
        "# Raw API bodies are opt-in because they contain the complete\n"
        "# conversation, prompts, tool content, and system instructions.\n"
        'if [ "${CAPTURE_API_BODIES:-0}" = "1" ]; then\n'
        '  APIBODIES_DIR="/tmp/claude-api-bodies"\n'
        '  mkdir -p "$APIBODIES_DIR"\n'
        '  export OTEL_LOG_RAW_API_BODIES="file:${APIBODIES_DIR}"\n'
        '  echo "Claude API body capture enabled: ${APIBODIES_DIR}"\n'
        "fi\n",
    )
    replace_once(
        launcher,
        '  cp -f /tmp/claude-stderr.log "$CI_PROJECT_DIR/claude-stderr.log" 2>/dev/null || true\n',
        '  cp -f /tmp/claude-stderr.log "$CI_PROJECT_DIR/claude-stderr.log" 2>/dev/null || true\n'
        '  if [ -n "${APIBODIES_DIR:-}" ] && [ -d "$APIBODIES_DIR" ]; then\n'
        '    mkdir -p "$CI_PROJECT_DIR/claude-api-bodies"\n'
        '    cp -a "$APIBODIES_DIR/." "$CI_PROJECT_DIR/claude-api-bodies/"\n'
        '  fi\n',
    )
    changed.append("ci-scripts/run-claude.sh")

    return changed
