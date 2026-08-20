#!/usr/bin/env python3
"""Validate the private strat-pipeline checkout used by the local fixture."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parents[1]
MANIFEST_PATH = FIXTURE_DIR / "source-manifest.json"
SOURCE_LINK = FIXTURE_DIR / "strat-pipeline"


def run_git(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="return success when the source checkout has local changes",
    )
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    source_info = manifest["sources"]["strat-pipeline"]

    if not SOURCE_LINK.is_symlink():
        print(f"ERROR: expected symlink is missing: {SOURCE_LINK}", file=sys.stderr)
        return 2

    try:
        source = SOURCE_LINK.resolve(strict=True)
    except FileNotFoundError:
        print(f"ERROR: source symlink is dangling: {SOURCE_LINK}", file=sys.stderr)
        return 2

    if not (source / ".git").exists():
        print(f"ERROR: source is not a Git checkout: {source}", file=sys.stderr)
        return 2

    try:
        top_level = Path(run_git(source, "rev-parse", "--show-toplevel")).resolve()
        remote = run_git(source, "remote", "get-url", "origin")
        branch = run_git(source, "branch", "--show-current") or "(detached HEAD)"
        commit = run_git(source, "rev-parse", "HEAD")
        status = run_git(source, "status", "--short", "--untracked-files=all")
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: Git inspection failed for {source}: {exc}", file=sys.stderr)
        return 2

    expected_remote = source_info["expected_remote"].removesuffix(".git")
    actual_remote = remote.removesuffix(".git")
    errors: list[str] = []
    warnings: list[str] = []

    if top_level != source:
        errors.append(f"Git top-level is {top_level}, expected {source}")
    if actual_remote != expected_remote:
        errors.append(f"origin is {remote!r}, expected {source_info['expected_remote']!r}")
    if branch != source_info["expected_branch"]:
        errors.append(f"branch is {branch!r}, expected {source_info['expected_branch']!r}")
    if commit != source_info["baseline_commit"]:
        warnings.append(
            f"HEAD {commit} differs from recorded baseline {source_info['baseline_commit']}"
        )
    if status:
        warnings.append("source checkout has local changes")
        if not args.allow_dirty:
            errors.append("rerun with --allow-dirty after reviewing local changes")

    report = {
        "source": str(source),
        "remote": remote,
        "branch": branch,
        "commit": commit,
        "baseline_commit": source_info["baseline_commit"],
        "dirty": bool(status),
        "status": status.splitlines(),
        "warnings": warnings,
        "errors": errors,
    }
    print(json.dumps(report, indent=2))

    if errors:
        return 1
    print("M0 preflight passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
