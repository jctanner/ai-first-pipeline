#!/usr/bin/env python3
"""One-time migration: move existing phase outputs from issues/ to workspace/.

For each ``issues/RHOAIENG-*.{phase}.json`` (and ``.md``):
  - Creates ``workspace/{KEY}/claude-opus-4-6/``
  - Moves phase files into it (all existing runs used opus as the default)
  - Copies raw ``{KEY}.json`` to ``workspace/{KEY}/issue.json``

Raw issue JSONs in ``issues/`` are left in place (they're still needed).

Usage:
    python scripts/migrate_to_workspace.py          # dry-run (default)
    python scripts/migrate_to_workspace.py --apply  # actually move files
"""

import argparse
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ISSUES_DIR = BASE_DIR / "issues"
WORKSPACE_DIR = BASE_DIR / "workspace"

PHASE_SUFFIXES = ["completeness", "context-map", "fix-attempt", "test-plan"]
DEFAULT_MODEL = "claude-opus-4-6"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true",
        help="Actually move files (default is dry-run)",
    )
    args = parser.parse_args()

    if not ISSUES_DIR.exists():
        print(f"issues/ directory not found at {ISSUES_DIR}", file=sys.stderr)
        sys.exit(1)

    # Discover issue keys
    raw_files = sorted(
        p for p in ISSUES_DIR.glob("RHOAIENG-*.json")
        if "." not in p.stem  # raw issue files only
    )
    keys = [p.stem for p in raw_files]

    moved = 0
    copied = 0
    skipped = 0

    for key in keys:
        model_dir = WORKSPACE_DIR / key / DEFAULT_MODEL
        issue_copy_dst = WORKSPACE_DIR / key / "issue.json"

        # Copy raw issue JSON → workspace/{KEY}/issue.json
        raw_src = ISSUES_DIR / f"{key}.json"
        if raw_src.exists() and not issue_copy_dst.exists():
            if args.apply:
                issue_copy_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(raw_src, issue_copy_dst)
            print(f"  COPY {raw_src.name} → {issue_copy_dst.relative_to(BASE_DIR)}")
            copied += 1

        # Move phase output files
        for suffix in PHASE_SUFFIXES:
            for ext in (".json", ".md"):
                src = ISSUES_DIR / f"{key}.{suffix}{ext}"
                if not src.exists():
                    continue
                dst = model_dir / f"{suffix}{ext}"
                if dst.exists():
                    print(f"  SKIP {src.name} (destination exists: {dst.relative_to(BASE_DIR)})")
                    skipped += 1
                    continue
                if args.apply:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                print(f"  MOVE {src.name} → {dst.relative_to(BASE_DIR)}")
                moved += 1

    action = "Moved" if args.apply else "Would move"
    copy_action = "Copied" if args.apply else "Would copy"
    print(f"\n{action} {moved} phase files, {copy_action} {copied} issue files, skipped {skipped}")
    if not args.apply and (moved or copied):
        print("Run with --apply to execute the migration.")


if __name__ == "__main__":
    main()
