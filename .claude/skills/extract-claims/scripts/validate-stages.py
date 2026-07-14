#!/usr/bin/env python3
"""Validate staged claim-extraction output and cross-stage invariants."""

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator

SELECTIONS = {"verifiable", "mixed", "unverifiable"}
AMBIGUITIES = {"none", "resolved", "unresolved"}
CLAIM_TYPES = {"factual", "architectural", "security", "scope", "attribution"}
DECONTEXTUALIZATION_MODES = {"basic", "full"}
FULL_DECONTEXTUALIZATION_FIELDS = (
    "maximally_contextualized_claim",
    "extracted_retrieval_digest",
    "comparison_retrieval_digest",
    "evidence_context_digest",
)
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "staged-extraction.schema.json"


def _format_path(parts) -> str:
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += ("." if path else "") + str(part)
    return path or "$"


def validate_schema(data: dict) -> list[str]:
    """Validate the complete canonical artifact before cross-stage checks."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [
        f"schema {_format_path(error.absolute_path)}: {error.message}"
        for error in sorted(
            validator.iter_errors(data),
            key=lambda item: (_format_path(item.absolute_path), item.message),
        )
    ]


def validate(data: dict) -> list[str]:
    errors: list[str] = validate_schema(data)
    for field in ("run_key", "source_file", "pipeline_slug", "extractor_revision"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            errors.append(f"{field} is required")
    decontextualization_mode = data.get("decontextualization_mode")
    if decontextualization_mode not in DECONTEXTUALIZATION_MODES:
        errors.append("decontextualization_mode is invalid")
    units = data.get("units")
    if not isinstance(units, list):
        return [*errors, "units must be a list"]
    occurrence_ids = data.get("observatory_occurrence_ids")
    if isinstance(occurrence_ids, list):
        claim_count = sum(
            len(unit.get("claims", [])) for unit in units
            if isinstance(unit, dict)
        )
        if len(occurrence_ids) != claim_count:
            errors.append(
                "observatory_occurrence_ids must contain exactly one ID per claim"
            )
    seen: set[str] = set()
    for index, unit in enumerate(units):
        prefix = f"units[{index}]"
        source_unit = unit.get("source_unit", {})
        key = source_unit.get("unit_key", source_unit.get("id"))
        if not key:
            errors.append(f"{prefix}.source_unit.unit_key is required")
        elif key in seen:
            errors.append(f"{prefix}.source_unit.unit_key is duplicated")
        seen.add(key)
        if not source_unit.get("source_locator"):
            errors.append(f"{prefix}.source_unit.source_locator is required")
        source_text = source_unit.get("original_text", source_unit.get("text"))
        if not isinstance(source_text, str) or not source_text.strip():
            errors.append(f"{prefix}.source_unit.original_text is required")
        selection = unit.get("selection", {}).get("classification")
        if selection not in SELECTIONS:
            errors.append(f"{prefix}.selection.classification is invalid")
        if not unit.get("selection", {}).get("evaluator_revision"):
            errors.append(f"{prefix}.selection.evaluator_revision is required")
        if selection == "mixed" and not unit.get("selection", {}).get("selected_text"):
            errors.append(f"{prefix}.selection.selected_text is required for mixed units")
        ambiguity = unit.get("ambiguity")
        claims = unit.get("claims", [])
        if selection == "unverifiable" and claims:
            errors.append(f"{prefix} unverifiable units cannot emit claims")
        if selection != "unverifiable" and not isinstance(ambiguity, dict):
            errors.append(f"{prefix}.ambiguity is required for selected units")
            continue
        status = ambiguity.get("status") if ambiguity else None
        if ambiguity and status not in AMBIGUITIES:
            errors.append(f"{prefix}.ambiguity.status is invalid")
        if ambiguity and not ambiguity.get("evaluator_revision"):
            errors.append(f"{prefix}.ambiguity.evaluator_revision is required")
        if status == "resolved" and not ambiguity.get("clarified_text"):
            errors.append(f"{prefix}.ambiguity.clarified_text is required when resolved")
        if status == "unresolved" and claims:
            errors.append(f"{prefix} unresolved units cannot emit claims")
        for claim_index, claim in enumerate(claims):
            claim_prefix = f"{prefix}.claims[{claim_index}]"
            claim_text = claim.get("claim_text", claim.get("claim"))
            if not isinstance(claim_text, str) or not claim_text.strip():
                errors.append(f"{claim_prefix}.claim_text is required")
            if not isinstance(claim.get("original_text"), str) or not claim["original_text"].strip():
                errors.append(f"{claim_prefix}.original_text is required")
            else:
                context = "\n".join([
                    *source_unit.get("preceding_context", []),
                    source_text or "",
                    *source_unit.get("following_context", []),
                ])
                if claim["original_text"] not in context:
                    errors.append(
                        f"{claim_prefix}.original_text is not an exact bounded-source excerpt"
                    )
            claim_type = claim.get("claim_type", claim.get("type"))
            if claim_type not in CLAIM_TYPES:
                errors.append(f"{claim_prefix}.claim_type is invalid")
            evaluation = claim.get("evaluation")
            if not isinstance(evaluation, dict) or not isinstance(
                evaluation.get("entailed"), bool
            ):
                errors.append(f"{claim_prefix} requires an entailment decision")
            elif evaluation["entailed"] is False and claim.get("accepted", True):
                errors.append(f"{claim_prefix} cannot accept a non-entailed claim")
            if isinstance(evaluation, dict):
                if not evaluation.get("evaluator_revision"):
                    errors.append(f"{claim_prefix}.evaluation.evaluator_revision is required")
                if not isinstance(evaluation.get("evidence"), list) or not evaluation["evidence"]:
                    errors.append(f"{claim_prefix}.evaluation.evidence is required")
                else:
                    for evidence_index, evidence in enumerate(evaluation["evidence"]):
                        if not isinstance(evidence, dict) or not isinstance(
                            evidence.get("evidence_type"), str
                        ) or not evidence["evidence_type"].strip():
                            errors.append(
                                f"{claim_prefix}.evaluation.evidence[{evidence_index}]"
                                ".evidence_type is required"
                            )
                coverage_elements = evaluation.get("coverage_elements")
                if not isinstance(coverage_elements, list) or not coverage_elements:
                    errors.append(f"{claim_prefix}.evaluation.coverage_elements is required")
                else:
                    coverage_problem = False
                    for element_index, element in enumerate(coverage_elements):
                        element_prefix = (
                            f"{claim_prefix}.evaluation.coverage_elements[{element_index}]"
                        )
                        kind = element.get("element_kind")
                        coverage = element.get("coverage")
                        allowed = (
                            {"explicit", "implicit", "omitted"}
                            if kind == "verifiable" else {"omitted", "included"}
                            if kind == "unverifiable" else set()
                        )
                        if coverage not in allowed:
                            errors.append(
                                f"{element_prefix} has invalid kind/coverage combination"
                            )
                        if (
                            kind == "verifiable" and coverage == "omitted"
                        ) or (
                            kind == "unverifiable" and coverage == "included"
                        ):
                            coverage_problem = True
                    coverage_result = evaluation.get("coverage_result")
                    if coverage_problem and coverage_result == "complete":
                        errors.append(
                            f"{claim_prefix}.evaluation.coverage_result cannot be "
                            "complete when a verifiable element is omitted or an "
                            "unverifiable element is included"
                        )
                    if not coverage_problem and coverage_result in {"partial", "failed"}:
                        errors.append(
                            f"{claim_prefix}.evaluation.coverage_result must be complete "
                            "when all verifiable elements are covered and all unverifiable "
                            "elements are omitted"
                        )
                if evaluation.get("coverage_result") not in {
                    "complete", "partial", "failed",
                }:
                    errors.append(f"{claim_prefix}.evaluation.coverage_result is invalid")
                if evaluation.get("decontextualization_result") not in {
                    "desirable", "undesirable", "self_contained", "needs_review",
                    "not_sampled",
                }:
                    errors.append(
                        f"{claim_prefix}.evaluation.decontextualization_result is invalid"
                    )
                decontextualization_result = evaluation.get(
                    "decontextualization_result"
                )
                if (
                    decontextualization_mode == "full"
                    and claim.get("accepted", True)
                    and decontextualization_result not in {"desirable", "undesirable"}
                ):
                    errors.append(
                        f"{claim_prefix}.evaluation.decontextualization_result must be "
                        "desirable or undesirable in full mode"
                    )
                if decontextualization_result in {"desirable", "undesirable"}:
                    for field in FULL_DECONTEXTUALIZATION_FIELDS:
                        value = evaluation.get(field)
                        if not isinstance(value, str) or not value.strip():
                            errors.append(
                                f"{claim_prefix}.evaluation.{field} is required for "
                                f"{decontextualization_result} decontextualization"
                            )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    errors = validate(data)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"valid: {len(data['units'])} source units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
