#!/usr/bin/env python3
"""Validate claim-ledger evidence levels and referenced local artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


VERDICTS = {"runtime-confirmed", "bundle-confirmed", "source-correlated", "hypothesis", "incomplete"}


def load_ledger(path: Path) -> object:
    if path.suffix == ".json":
        return json.loads(path.read_text())
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError as error:
        raise ValueError("YAML ledger requires PyYAML; use JSON or install project dependencies") from error
    return yaml.safe_load(path.read_text())


def nonempty_list(claim: dict[str, object], *path: str) -> bool:
    value: object = claim
    for key in path:
        if not isinstance(value, dict):
            return False
        value = value.get(key)
    return isinstance(value, list) and bool(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--check-paths", action="store_true")
    args = parser.parse_args()
    value = load_ledger(args.ledger)
    claims = value.get("claims") if isinstance(value, dict) else value
    if not isinstance(claims, list):
        parser.error("ledger must be a list or an object with a claims list")

    errors: list[str] = []
    seen: set[str] = set()
    for index, claim in enumerate(claims):
        label = f"claim[{index}]"
        if not isinstance(claim, dict):
            errors.append(f"{label}: must be an object")
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id:
            errors.append(f"{label}: missing id")
        elif claim_id in seen:
            errors.append(f"{label}: duplicate id {claim_id}")
        else:
            seen.add(claim_id)
            label = claim_id
        if not isinstance(claim.get("claim"), str) or not claim["claim"]:
            errors.append(f"{label}: missing claim text")
        verdict = claim.get("verdict")
        if verdict not in VERDICTS:
            errors.append(f"{label}: invalid verdict {verdict!r}")
            continue
        binary = claim.get("binary")
        if not isinstance(binary, dict) or not binary.get("version") or not binary.get("sha256"):
            errors.append(f"{label}: binary version and sha256 are required")
        if verdict in {"bundle-confirmed", "runtime-confirmed"} and not (
            nonempty_list(claim, "bundle", "offsets") and nonempty_list(claim, "bundle", "anchors")
        ):
            errors.append(f"{label}: {verdict} requires bundle offsets and anchors")
        if verdict == "runtime-confirmed" and not nonempty_list(claim, "runtime", "runs"):
            errors.append(f"{label}: runtime-confirmed requires runtime runs")
        if verdict == "source-correlated" and not nonempty_list(claim, "old_source", "files"):
            errors.append(f"{label}: source-correlated requires old-source files")
        if args.check_paths:
            runtime = claim.get("runtime")
            if isinstance(runtime, dict):
                for key in ("runs", "strace_artifacts"):
                    paths = runtime.get(key, [])
                    if isinstance(paths, list):
                        for path in paths:
                            if isinstance(path, str) and not Path(path).exists():
                                errors.append(f"{label}: missing referenced path {path}")

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"validated {len(claims)} claims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
