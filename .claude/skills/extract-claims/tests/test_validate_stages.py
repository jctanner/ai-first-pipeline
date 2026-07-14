import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-stages.py"
SPEC = importlib.util.spec_from_file_location("validate_stages", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def document(units):
    return {
        "run_key": "run:test", "source_file": "test.md",
        "pipeline_slug": "test", "artifact_type": "rfe",
        "artifact_digest": "sha256:artifact",
        "extractor_revision": "extract@test",
        "repository_revision": "commit:test", "model": "model:test",
        "harness": "harness:test", "configuration_digest": "sha256:config",
        "decontextualization_mode": "basic",
        "configuration": {
            "segmenter_version": "markdown-v1", "preceding_units": 1,
            "following_units": 1, "artifact_type": "rfe",
            "artifact_type_override": {},
        },
        "segmentation_version": "claim-segmentation-v1",
        "segmentation_configuration_digest": "sha256:segments",
        "preceding_context_units": 1, "following_context_units": 1,
        "units": units,
    }


def valid_unit():
    return {
        "source_unit": {
            "unit_key": "u1", "unit_kind": "sentence",
            "source_locator": "test.md:L1-L1",
            "original_text": "The API retains immutable verification history.",
        },
        "selection": {
            "classification": "verifiable", "evaluator_revision": "selection@test"
        },
        "ambiguity": {"status": "none", "evaluator_revision": "ambiguity@test"},
        "claims": [{
            "claim_text": "The API retains immutable verification history.",
            "claim_type": "architectural",
            "original_text": "The API retains immutable verification history.",
            "accepted": True,
            "evaluation": {
                "entailed": True,
                "evaluator_revision": "evaluation@test",
                "coverage_result": "complete",
                "decontextualization_result": "self_contained",
                "evidence": [{
                    "evidence_type": "source_unit",
                    "source_locator": "test.md:L1-L1",
                }],
                "coverage_elements": [{
                    "element_text": "retains immutable verification history",
                    "element_kind": "verifiable",
                    "coverage": "explicit",
                }],
            },
        }],
    }


def test_accepts_fully_evaluated_stages():
    assert MODULE.validate(document([valid_unit()])) == []


def test_full_mode_requires_and_accepts_independent_comparison_evidence():
    data = document([valid_unit()])
    data["decontextualization_mode"] = "full"
    evaluation = data["units"][0]["claims"][0]["evaluation"]
    evaluation.update({
        "decontextualization_result": "desirable",
        "maximally_contextualized_claim": (
            "In the documented API, verification history is immutable."
        ),
        "extracted_retrieval_digest": "sha256:extracted",
        "comparison_retrieval_digest": "sha256:comparison",
        "evidence_context_digest": "sha256:evidence-context",
    })
    assert MODULE.validate(data) == []


def test_full_mode_rejects_basic_judgment_and_missing_comparison_digests():
    data = document([valid_unit()])
    data["decontextualization_mode"] = "full"
    errors = " ".join(MODULE.validate(data))
    assert "must be desirable or undesirable in full mode" in errors

    evaluation = data["units"][0]["claims"][0]["evaluation"]
    evaluation["decontextualization_result"] = "undesirable"
    errors = " ".join(MODULE.validate(data))
    for field in MODULE.FULL_DECONTEXTUALIZATION_FIELDS:
        assert f"{field} is required" in errors


def test_accepts_observatory_identity_added_after_ingestion():
    data = document([valid_unit()])
    data["observatory_run_id"] = 7
    data["observatory_occurrence_ids"] = [41]
    assert MODULE.validate(data) == []


def test_rejects_incomplete_or_synthesized_observatory_identity():
    data = document([valid_unit()])
    data["observatory_run_id"] = 7
    errors = " ".join(MODULE.validate(data))
    assert "observatory_occurrence_ids" in errors

    data["observatory_occurrence_ids"] = [41, 42]
    errors = " ".join(MODULE.validate(data))
    assert "exactly one ID per claim" in errors


def test_rejects_claims_from_unresolved_unit():
    unit = valid_unit()
    unit["ambiguity"]["status"] = "unresolved"
    assert "unresolved units cannot emit claims" in " ".join(
        MODULE.validate(document([unit]))
    )


def test_rejects_non_entailed_claim():
    unit = valid_unit()
    unit["claims"][0]["evaluation"]["entailed"] = False
    assert "cannot accept a non-entailed claim" in " ".join(
        MODULE.validate(document([unit]))
    )


def test_preserves_rejected_non_entailed_candidate_for_audit():
    unit = valid_unit()
    unit["claims"][0]["evaluation"]["entailed"] = False
    unit["claims"][0]["accepted"] = False
    assert MODULE.validate(document([unit])) == []


def test_accepts_empty_and_abstained_outputs():
    assert MODULE.validate(document([])) == []
    unit = valid_unit()
    unit["selection"]["classification"] = "unverifiable"
    unit["ambiguity"] = None
    unit["claims"] = []
    assert MODULE.validate(document([unit])) == []


def test_selected_unit_requires_ambiguity_result():
    unit = valid_unit()
    unit["ambiguity"] = None
    assert "ambiguity is required" in " ".join(MODULE.validate(document([unit])))


def test_rejects_unmeasurable_coverage_and_context_results():
    unit = valid_unit()
    unit["claims"][0]["evaluation"]["coverage_elements"] = []
    unit["claims"][0]["evaluation"]["decontextualization_result"] = None
    errors = " ".join(MODULE.validate(document([unit])))
    assert "coverage_elements is required" in errors
    assert "decontextualization_result is invalid" in errors


def test_rejects_non_exact_source_excerpt():
    unit = valid_unit()
    unit["claims"][0]["original_text"] = "The API maybe retains history."
    assert "not an exact bounded-source excerpt" in " ".join(
        MODULE.validate(document([unit]))
    )


def test_mixed_and_resolved_stages_require_durable_resolution_text():
    unit = valid_unit()
    unit["selection"]["classification"] = "mixed"
    unit["ambiguity"]["status"] = "resolved"
    errors = " ".join(MODULE.validate(document([unit])))
    assert "selected_text is required" in errors
    assert "clarified_text is required" in errors


def test_rejects_worker_specific_separate_stage_arrays():
    malformed = document([])
    malformed.pop("units")
    malformed["source_units"] = [valid_unit()["source_unit"]]
    malformed["stages"] = {
        "selection": [], "ambiguity": [], "decomposition": [],
    }
    errors = " ".join(MODULE.validate(malformed))
    assert "'units' is a required property" in errors
    assert "Additional properties are not allowed" in errors


def test_rejects_evidence_without_a_declared_type():
    unit = valid_unit()
    unit["claims"][0]["evaluation"]["evidence"] = [{
        "source": "bounded_source_context",
        "excerpt": unit["claims"][0]["original_text"],
    }]
    errors = " ".join(MODULE.validate(document([unit])))
    assert "evidence_type" in errors
    assert "Additional properties are not allowed" in errors


def test_rejects_post_hoc_assurance_fields_outside_the_contract():
    unit = valid_unit()
    unit["claims"][0]["evaluation"]["invented_default"] = True
    assert "Additional properties are not allowed" in " ".join(
        MODULE.validate(document([unit]))
    )


def test_rejects_dropped_scaffold_provenance():
    data = document([valid_unit()])
    data["artifact_digest"] = None
    data["configuration"] = {}
    errors = " ".join(MODULE.validate(data))
    assert "artifact_digest" in errors
    assert "segmenter_version" in errors


def test_coverage_result_must_match_element_level_outcomes():
    unit = valid_unit()
    element = unit["claims"][0]["evaluation"]["coverage_elements"][0]
    element["element_kind"] = "unverifiable"
    element["coverage"] = "included"
    errors = " ".join(MODULE.validate(document([unit])))
    assert "cannot be complete" in errors

    element["coverage"] = "omitted"
    unit["claims"][0]["evaluation"]["coverage_result"] = "partial"
    errors = " ".join(MODULE.validate(document([unit])))
    assert "must be complete" in errors
