#!/usr/bin/env python3
"""Mirror the small Fullsend action/workflow fixture used by M8.

This deliberately mirrors only files needed by emulator tests.  It does not
pretend to mirror the whole upstream repository or fetch from the network.
"""

from __future__ import annotations

from pathlib import Path
import time

from m1_seed import ORG, REPO, TOKEN, run_git


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "checkouts.tmp" / "fullsend"
FILES = (
    ".github/actions/mint-token/action.yml",
    ".github/actions/prepare-workspace/action.yml",
    ".github/actions/install-fullsend-cli/action.yml",
)
WORKFLOW = ".github/workflows/m8-role-events.yml"
WORKFLOW_CONTENT = """name: M8 Fullsend role and event fixture

on:
  workflow_dispatch:
    inputs:
      role:
        required: true
        default: triage
        type: string
  issues: [opened, labeled]
  issue_comment: [created]

concurrency:
  group: fullsend-m8-${{ github.ref }}
  cancel-in-progress: true

jobs:
  role:
    name: Fullsend ${{ matrix.role }} fixture
    runs-on: [self-hosted, linux, fullsend]
    strategy:
      matrix:
        role: [triage, review, coder]
    permissions:
      contents: read
      issues: write
    steps:
      - name: Record role and event
        run: |
          set -eu
          printf 'm8-role=%s event=%s\\n' '${{ matrix.role }}' '${{ github.event_name }}'
"""


def main() -> None:
    remote = f"https://x-access-token:{TOKEN}@github.local/{ORG}/{REPO}.git"
    with __import__("tempfile").TemporaryDirectory(prefix="fullsend-m8-mirror-") as temp:
        directory = Path(temp)
        run_git(directory, "init", "--initial-branch=main")
        run_git(directory, "config", "user.name", "Breadboard M8 Mirror")
        run_git(directory, "config", "user.email", "breadboard-m8@localhost")
        run_git(directory, "remote", "add", "origin", remote)
        fetched = None
        for _ in range(10):
            fetched = run_git(directory, "fetch", "origin", "main", check=False)
            if fetched.returncode == 0:
                run_git(directory, "reset", "--hard", "FETCH_HEAD")
                break
            time.sleep(2)
        if fetched is None or fetched.returncode != 0:
            raise RuntimeError(fetched.stderr if fetched else "fetch did not run")
        mirrored = []
        for relative in FILES:
            source = SOURCE / relative
            if not source.is_file():
                raise RuntimeError(f"required local Fullsend fixture is missing: {source}")
            destination = directory / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read_bytes())
            mirrored.append(relative)
        destination = directory / WORKFLOW
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(WORKFLOW_CONTENT, encoding="utf-8")
        mirrored.append(WORKFLOW)
        run_git(directory, "add", *mirrored)
        if run_git(directory, "diff", "--cached", "--quiet", check=False).returncode != 0:
            run_git(directory, "commit", "-m", "Mirror M8 Fullsend action and event fixtures")
            pushed = None
            for _ in range(10):
                pushed = run_git(directory, "push", "-u", "origin", "main", check=False)
                if pushed.returncode == 0:
                    break
                time.sleep(2)
            if pushed is None or pushed.returncode != 0:
                raise RuntimeError(pushed.stderr if pushed else "push did not run")
        print({"status": "mirrored", "commit": run_git(directory, "rev-parse", "HEAD").stdout.strip(), "files": mirrored})


if __name__ == "__main__":
    main()
