#!/usr/bin/env python3
"""Validate the M0 Fullsend development-stack contract."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
DEMO = ROOT / "var" / "demos" / "fullsend-dev-stack"
CONTRACT_PATH = DEMO / "m0-contract.json"


class ContractError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def load_contract() -> dict:
    try:
        return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot load {CONTRACT_PATH}: {exc}") from exc


def check_git_checkout(path: Path) -> str:
    require(path.is_dir(), f"Fullsend checkout is missing: {path}")
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ContractError(f"Fullsend checkout is not a Git checkout: {path}") from exc
    commit = result.stdout.strip()
    require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "invalid Fullsend HEAD")
    return commit


def check_no_embedded_secret(value: object, path: str = "contract") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            require(
                not any(word in lowered for word in ("password", "private_key", "secret_value")),
                f"credential-bearing field is not allowed: {path}.{key}",
            )
            check_no_embedded_secret(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            check_no_embedded_secret(child, f"{path}[{index}]")
    elif isinstance(value, str):
        require(not re.search(r"(?:ghp|github_pat|sk|ya29)_[A-Za-z0-9_-]{12,}", value), f"possible token in {path}")


def main() -> int:
    contract = load_contract()
    scenario = contract["scenario"]
    trigger = scenario["trigger"]
    target = scenario["target"]
    result = scenario["result"]
    credential = contract["credential_boundary"]
    source = contract["source"]

    require(contract["schema_version"] == 1, "unsupported contract schema")
    require(scenario["role"] == "triage", "M0 role must be triage")
    require(trigger["kind"] == "workflow_dispatch", "M0 trigger must be workflow_dispatch")
    require(target["owner"] and target["repository"], "target repository is incomplete")
    require("/" not in target["owner"], "target owner must be a single GitHub owner")
    require(result["kind"] == "issue_comment", "M0 result must be an issue comment")
    require(result["marker"].startswith("<!-- fullsend-dev-stack:"), "invalid result marker")
    require(credential["token_endpoint"] == "/v1/token", "unexpected mint endpoint")
    require(credential["oidc_mode"].startswith("development-only"), "M0 mint must be development-only")
    require(credential["returned_token_prefix"] == "ghp_", "M0 must return emulator PATs")

    checkout = ROOT / source["fullsend_checkout"]
    commit = check_git_checkout(checkout)
    for relative in source["required_files"]:
        require((checkout / relative).is_file(), f"required Fullsend file is missing: {relative}")

    check_no_embedded_secret(contract)
    print(json.dumps({"status": "passed", "contract": str(CONTRACT_PATH.relative_to(ROOT)), "fullsend_commit": commit}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ContractError, KeyError) as exc:
        print(f"M0 contract failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
