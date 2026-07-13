import importlib.util
import json
from pathlib import Path

import yaml


SCRIPT = Path(__file__).with_name("evaluate-claim-extraction.py")
SPEC = importlib.util.spec_from_file_location("claim_eval", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_corpus_has_required_size_and_artifact_classes():
    dataset = json.loads(
        (Path(__file__).parents[1] / "eval-datasets" / "claim-assurance-v1.json").read_text()
    )
    assert len(dataset["units"]) >= 50
    assert {unit["artifact_type"] for unit in dataset["units"]} == {
        "rfe", "strategy", "security_review", "epic", "investigation", "code_generation"
    }
    case_root = Path(__file__).parents[1] / "eval-datasets" / "claim-assurance" / "cases"
    case_ids = {path.name for path in case_root.iterdir() if path.is_dir()}
    assert case_ids == {unit["id"] for unit in dataset["units"]}
    assert all((case_root / case_id / "annotations.yaml").is_file() for case_id in case_ids)
    for unit in dataset["units"]:
        annotation = unit["annotation"]
        if annotation["ambiguity_status"] == "unresolved":
            assert annotation["acceptable_claims"] == []
        rendered_claims = " ".join(annotation["acceptable_claims"]).lower()
        for qualifier in annotation["required_qualifiers"]:
            assert qualifier.lower() in rendered_claims
        case_annotation = yaml.safe_load(
            (case_root / unit["id"] / "annotations.yaml").read_text()
        )
        assert case_annotation["acceptable_claims"] == annotation["acceptable_claims"]


def test_perfect_predictions_score_one():
    dataset = {
        "dataset_fqn": "test:v1",
        "units": [{
            "id": "one",
            "artifact_type": "rfe",
            "annotation": {
                "selection": "verifiable",
                "ambiguity_status": "none",
                "acceptable_claims": ["A claim."],
            },
        }],
    }
    predictions = {"units": [{
        "id": "one", "selection": "verifiable", "ambiguity_status": "none",
        "claims": ["A claim"], "entailed": True,
        "unverifiable_elements": [],
        "decontextualization": "desirable",
    }]}
    result = MODULE.score(dataset, predictions)
    assert result["selection_accuracy"] == 1
    assert result["verifiable_element_f1"] == 1
    assert result["source_entailment_rate"] == 1
