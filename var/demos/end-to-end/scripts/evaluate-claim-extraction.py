#!/usr/bin/env python3
"""Score staged claim extraction predictions against the demo corpus."""

import argparse
import json
from collections import Counter
from pathlib import Path


def normalized(text: str) -> str:
    return " ".join(text.lower().split()).strip(" .")


def safe_div(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def score(dataset: dict, predictions: dict, include_breakdown: bool = True) -> dict:
    predicted = {item["id"]: item for item in predictions.get("units", [])}
    counts = Counter()
    missing = []
    for expected in dataset["units"]:
        unit_id = expected["id"]
        actual = predicted.get(unit_id)
        if actual is None:
            missing.append(unit_id)
            actual = {}
        annotation = expected["annotation"]
        counts["units"] += 1
        counts["selection_correct"] += (
            actual.get("selection") == annotation["selection"]
        )
        counts["ambiguity_correct"] += (
            actual.get("ambiguity_status") == annotation["ambiguity_status"]
        )
        expected_claims = {normalized(value) for value in annotation["acceptable_claims"]}
        actual_claims = {normalized(value) for value in actual.get("claims", [])}
        counts["verifiable_tp"] += len(expected_claims & actual_claims)
        counts["verifiable_fp"] += len(actual_claims - expected_claims)
        counts["verifiable_fn"] += len(expected_claims - actual_claims)
        expected_unverifiable = {
            normalized(value) for value in annotation.get("unverifiable_elements", [])
        }
        classified_unverifiable = {
            normalized(value) for value in actual.get("unverifiable_elements", [])
        }
        counts["unverifiable_tp"] += len(expected_unverifiable & classified_unverifiable)
        counts["unverifiable_fp"] += len(classified_unverifiable - expected_unverifiable)
        counts["unverifiable_fn"] += len(expected_unverifiable - classified_unverifiable)
        counts["unverifiable_included"] += len(expected_unverifiable & actual_claims)
        counts["unverifiable_total"] += len(expected_unverifiable)
        if actual.get("entailed") is True:
            counts["entailed"] += 1
        if actual.get("decontextualization") == "desirable":
            counts["desirable_decontextualization"] += 1
        if actual.get("ambiguity_status") == "unresolved":
            counts["unresolved"] += 1

    precision = safe_div(
        counts["verifiable_tp"], counts["verifiable_tp"] + counts["verifiable_fp"]
    )
    recall = safe_div(
        counts["verifiable_tp"], counts["verifiable_tp"] + counts["verifiable_fn"]
    )
    f1 = safe_div(2 * precision * recall, precision + recall)
    unverifiable_precision = safe_div(
        counts["unverifiable_tp"],
        counts["unverifiable_tp"] + counts["unverifiable_fp"],
    )
    unverifiable_recall = safe_div(
        counts["unverifiable_tp"],
        counts["unverifiable_tp"] + counts["unverifiable_fn"],
    )
    unverifiable_f1 = safe_div(
        2 * unverifiable_precision * unverifiable_recall,
        unverifiable_precision + unverifiable_recall,
    )
    result = {
        "dataset_fqn": dataset["dataset_fqn"],
        "extractor_revision": predictions.get("extractor_revision"),
        "model": predictions.get("model"),
        "configuration_digest": predictions.get("configuration_digest"),
        "unit_count": counts["units"],
        "missing_prediction_ids": missing,
        "selection_accuracy": safe_div(counts["selection_correct"], counts["units"]),
        "ambiguity_accuracy": safe_div(counts["ambiguity_correct"], counts["units"]),
        "source_entailment_rate": safe_div(counts["entailed"], counts["units"]),
        "verifiable_element_precision": precision,
        "verifiable_element_recall": recall,
        "verifiable_element_f1": f1,
        "unverifiable_element_precision": unverifiable_precision,
        "unverifiable_element_recall": unverifiable_recall,
        "unverifiable_element_f1": unverifiable_f1,
        "element_macro_f1": (f1 + unverifiable_f1) / 2,
        "explicit_unverifiable_element_inclusion_rate": safe_div(
            counts["unverifiable_included"], counts["unverifiable_total"]
        ),
        "unresolved_ambiguity_rate": safe_div(counts["unresolved"], counts["units"]),
        "desirable_decontextualization_rate": safe_div(
            counts["desirable_decontextualization"], counts["units"]
        ),
    }
    if include_breakdown:
        result["by_artifact_type"] = {}
        for artifact_type in sorted({unit["artifact_type"] for unit in dataset["units"]}):
            subset = {
                **dataset,
                "units": [
                    unit for unit in dataset["units"]
                    if unit["artifact_type"] == artifact_type
                ],
            }
            result["by_artifact_type"][artifact_type] = score(
                subset, predictions, include_breakdown=False
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = score(
        json.loads(args.dataset.read_text()), json.loads(args.predictions.read_text())
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered)
        temporary.replace(args.output)
    else:
        print(rendered, end="")
    return 1 if result["missing_prediction_ids"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
