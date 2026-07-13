#!/usr/bin/env python3
"""Project a validated canonical extraction artifact to the legacy claim shape."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


VALIDATOR_PATH = Path(__file__).with_name("validate-stages.py")


def _load_validator():
    spec = importlib.util.spec_from_file_location("validate_stages", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def project(data: dict) -> dict:
    claims = []
    for unit in data["units"]:
        for claim in unit.get("claims", []):
            if not claim.get("accepted", True):
                continue
            claims.append({
                "claim": claim["claim_text"],
                "type": claim["claim_type"],
                "original_text": claim["original_text"],
            })
    return {
        "source_file": data["source_file"],
        "pipeline_slug": data["pipeline_slug"],
        "claim_count": len(claims),
        "claims": claims,
    }


def _write_atomic(path: Path, data: dict) -> None:
    payload = json.dumps(data, indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("staged", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    data = json.loads(args.staged.read_text(encoding="utf-8"))
    errors = _load_validator().validate(data)
    if errors:
        for error in errors:
            print(error)
        return 1
    result = project(data)
    _write_atomic(args.output, result)
    print(f"projected legacy claims: {result['claim_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
