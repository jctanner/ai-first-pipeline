#!/usr/bin/env python3
"""Add the fixture-only RFE batch used by emulator smoke validation."""

from __future__ import annotations

from pathlib import Path


CONTENT = """# Fixture-only batch for the breadboard emulator.
# This file is generated in the adapted mirror; the source checkout is never changed.
test_rfes:
  - id: RHAIRFE-2
    title: "Breadboard emulator strategy smoke test"
    size: S
    comment: "Controlled fixture issue for repeatable batch-config validation."
    cross_component: false
"""


def apply_strat_creator(worktree: Path) -> list[str]:
    target = worktree / "config/emulator-smoke.yaml"
    target.write_text(CONTENT)
    return [target.relative_to(worktree).as_posix()]
