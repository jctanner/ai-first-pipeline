import json
from pathlib import Path


SCHEMA_PATH = (
    Path(__file__).parents[1] / "schemas" / "staged-extraction.schema.json"
)


def reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate schema key: {key}")
        value[key] = item
    return value


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(), object_pairs_hook=reject_duplicate_keys)


def test_schema_has_no_duplicate_object_keys():
    load_schema()


def test_schema_requires_every_durable_stage_discriminator():
    schema = load_schema()
    definitions = schema["$defs"]
    assert set(definitions["selection"]["required"]) == {
        "classification", "evaluator_revision",
    }
    assert set(definitions["ambiguity"]["required"]) == {
        "status", "evaluator_revision",
    }
    assert set(definitions["evaluation"]["required"]) == {
        "evaluator_revision", "entailed", "coverage_result", "coverage_elements",
        "decontextualization_result", "evidence",
    }


def test_schema_exposes_artifact_type_and_structured_evidence():
    schema = load_schema()
    assert "artifact_type" in schema["properties"]
    assert "repository_revision" in schema["properties"]
    evidence = schema["$defs"]["evidenceRecord"]
    assert evidence["required"] == ["evidence_type"]
    assert schema["$defs"]["evaluation"]["properties"]["evidence"] == {
        "type": "array",
        "minItems": 1,
        "items": {"$ref": "#/$defs/evidenceRecord"},
    }
    assert schema["$defs"]["evaluation"]["properties"]["coverage_elements"][
        "minItems"
    ] == 1


def test_schema_rejects_worker_specific_and_unknown_shapes():
    schema = load_schema()
    assert schema["additionalProperties"] is False
    for definition in (
        "segmentationConfiguration", "sourceUnit", "selection", "ambiguity",
        "coverageElement",
        "evaluation", "evidenceRecord", "claim", "unit",
    ):
        assert schema["$defs"][definition]["additionalProperties"] is False
    assert "stages" not in schema["properties"]
    assert "source_units" not in schema["properties"]


def test_schema_requires_complete_scaffold_provenance():
    schema = load_schema()
    required = set(schema["required"])
    assert {
        "artifact_type", "artifact_digest", "repository_revision", "model",
        "harness", "configuration_digest", "configuration",
        "decontextualization_mode",
        "segmentation_version", "segmentation_configuration_digest",
        "preceding_context_units", "following_context_units",
    } <= required
