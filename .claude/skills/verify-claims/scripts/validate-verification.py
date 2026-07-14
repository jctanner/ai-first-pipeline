#!/usr/bin/env python3
"""Validate immutable claim-verification artifacts before Observatory ingest."""

import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS = {
    "claim_occurrence_id",
    "verifier_revision",
    "repository_revision",
    "model",
    "harness",
    "configuration_digest",
    "evidence_context_digest",
    "verdict",
    "severity",
    "confidence",
    "evidence_summary",
    "evidence",
}
VERDICTS = {
    "supported",
    "contradicted",
    "insufficient_evidence",
    "not_applicable",
}
RELATIONSHIPS = {"supports", "contradicts"}
REPOSITORY_EVIDENCE = {"repository_file", "architecture_doc", "arch_query"}
ARTIFACT_EVIDENCE = {"source_document", "source_artifact", "artifact_file", "artifact"}
WEAK_SUPPORT = re.compile(
    r"\b(plausible|well-known|general knowledge|close to|"
    r"could not be independently verified)\b",
    re.IGNORECASE,
)


def validate(payload):
    errors = []
    missing = sorted(REQUIRED_FIELDS - payload.keys())
    if missing:
        errors.append(f"missing required fields: {', '.join(missing)}")

    verdict = payload.get("verdict")
    if verdict not in VERDICTS:
        errors.append(f"invalid verdict: {verdict!r}")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 100:
        errors.append("confidence must be a number from 0 through 100")

    summary = payload.get("evidence_summary", "")
    if verdict == "supported" and WEAK_SUPPORT.search(summary):
        errors.append(
            "supported verdict relies on plausibility or explicitly unverified evidence"
        )

    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence must be a non-empty list")
        return errors

    for index, record in enumerate(evidence):
        prefix = f"evidence[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} must be an object")
            continue
        for field in ("evidence_type", "uri", "relationship", "authority"):
            if not record.get(field):
                errors.append(f"{prefix}.{field} is required")
        if record.get("relationship") not in RELATIONSHIPS:
            errors.append(f"{prefix}.relationship is invalid")

        evidence_type = record.get("evidence_type")
        if evidence_type in REPOSITORY_EVIDENCE:
            if not record.get("repository_revision"):
                errors.append(f"{prefix}.repository_revision is required")
            if not (record.get("source_locator") or record.get("query")):
                errors.append(f"{prefix} needs a source_locator or exact query")
        if evidence_type in ARTIFACT_EVIDENCE:
            digest = record.get("artifact_digest", "")
            if not digest.startswith("sha256:"):
                errors.append(f"{prefix}.artifact_digest must be a sha256 digest")
            if not record.get("source_locator"):
                errors.append(f"{prefix}.source_locator is required")

    return errors


def main(paths):
    if not paths:
        print("usage: validate-verification.py FILE [...]", file=sys.stderr)
        return 2

    failed = False
    for value in paths:
        path = Path(value)
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print(f"{path}: cannot read verification JSON: {exc}", file=sys.stderr)
            failed = True
            continue
        for error in validate(payload):
            print(f"{path}: {error}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
