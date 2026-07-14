import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "validate-verification.py"
spec = importlib.util.spec_from_file_location("validate_verification", SCRIPT)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def valid_payload():
    return {
        "claim_occurrence_id": 42,
        "verifier_revision": "git-tree:verifier",
        "repository_revision": "pipeline-commit",
        "model": "claude-opus-4-6",
        "harness": "claude-code",
        "configuration_digest": "sha256:config",
        "evidence_context_digest": "sha256:evidence",
        "verdict": "supported",
        "severity": "info",
        "confidence": 95,
        "evidence_summary": "The versioned component document explicitly confirms the claim.",
        "evidence": [{
            "evidence_type": "repository_file",
            "uri": "repo://architecture/component.md",
            "repository_revision": "context-commit",
            "source_locator": "component.md:Architecture",
            "relationship": "supports",
            "authority": "architecture-context",
        }],
    }


def test_accepts_versioned_repository_evidence():
    assert validator.validate(valid_payload()) == []


def test_rejects_plausibility_as_supported_verdict():
    payload = valid_payload()
    payload["evidence_summary"] = "The unverified count is plausible."

    assert validator.validate(payload) == [
        "supported verdict relies on plausibility or explicitly unverified evidence"
    ]


def test_requires_immutable_repository_provenance():
    payload = valid_payload()
    del payload["evidence"][0]["repository_revision"]

    assert "evidence[0].repository_revision is required" in validator.validate(payload)


def test_requires_artifact_digest_and_locator():
    payload = valid_payload()
    payload["evidence"] = [{
        "evidence_type": "source_document",
        "uri": "file:///app/artifacts/RFE-1.md",
        "relationship": "supports",
        "authority": "pipeline-artifact",
    }]

    errors = validator.validate(payload)
    assert "evidence[0].artifact_digest must be a sha256 digest" in errors
    assert "evidence[0].source_locator is required" in errors


def test_skill_requires_whole_claim_support_and_validation():
    skill = " ".join((SCRIPT.parents[1] / "SKILL.md").read_text().split())

    assert "Every material, independently checkable element" in skill
    assert "Never promote plausibility to support" in skill
    assert "validate-verification.py" in skill
