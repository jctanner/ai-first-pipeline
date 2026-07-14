import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_script(name, module_name):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCAFFOLD = load_script("create-staged-scaffold.py", "create_staged_scaffold")
PROJECT = load_script("project-legacy-claims.py", "project_legacy_claims")
VALIDATE = ROOT / "scripts" / "validate-stages.py"


def segments():
    return {
        "source_file": "rfe-tasks/RFE-1.md",
        "source_digest": "sha256:source",
        "configuration": {
            "segmenter_version": "markdown-v1",
            "preceding_units": 1,
            "following_units": 1,
            "artifact_type": "rfe",
            "artifact_type_override": {},
        },
        "configuration_digest": "sha256:segments",
        "units": [{
            "id": "unit-1",
            "kind": "sentence",
            "text": "The API retains immutable history.",
            "source_locator": "rfe-tasks/RFE-1.md:L1-L1",
            "line_start": 1,
            "line_end": 1,
            "heading_path": [],
            "preceding_context": [],
            "following_context": [],
            "list_preamble": None,
        }],
    }


def metadata():
    return {
        "pipeline_slug": "rfe-tasks",
        "artifact_type": "rfe",
        "extractor_revision": "git-tree:extract",
        "repository_revision": "commit-1",
        "model": "model-1",
        "harness": "harness-1",
        "configuration_digest": "sha256:config",
        "decontextualization_mode": "basic",
        "segmentation_version": "claim-segmentation-v1",
        "preceding_context_units": 1,
        "following_context_units": 1,
    }


def completed_artifact():
    artifact = SCAFFOLD.create_scaffold(segments(), metadata())
    unit = artifact["units"][0]
    unit["selection"]["classification"] = "verifiable"
    unit["ambiguity"]["status"] = "none"
    unit["claims"] = [{
        "claim_text": "The API retains immutable history.",
        "claim_type": "architectural",
        "original_text": "The API retains immutable history.",
        "accepted": True,
        "evaluation": {
            "evaluator_revision": "git-tree:extract",
            "entailed": True,
            "coverage_result": "complete",
            "coverage_elements": [{
                "element_text": "retains immutable history",
                "element_kind": "verifiable",
                "coverage": "explicit",
            }],
            "decontextualization_result": "self_contained",
            "evidence": [{
                "evidence_type": "source_unit",
                "source_locator": "rfe-tasks/RFE-1.md:L1-L1",
                "excerpt": "The API retains immutable history.",
            }],
        },
    }]
    return artifact


def test_scaffold_is_canonical_and_intentionally_fails_until_judged(tmp_path):
    artifact = SCAFFOLD.create_scaffold(segments(), metadata())
    assert set(artifact["units"][0]) == {
        "source_unit", "selection", "ambiguity", "claims",
    }
    assert "stages" not in artifact
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(artifact))
    result = subprocess.run(
        [sys.executable, str(VALIDATE), str(candidate)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert "__REQUIRED__" in result.stdout


def test_completed_scaffold_validates_and_projects_legacy_claims(tmp_path):
    artifact = completed_artifact()
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(artifact))
    result = subprocess.run(
        [sys.executable, str(VALIDATE), str(candidate)],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout
    assert PROJECT.project(artifact) == {
        "source_file": "rfe-tasks/RFE-1.md",
        "pipeline_slug": "rfe-tasks",
        "claim_count": 1,
        "claims": [{
            "claim": "The API retains immutable history.",
            "type": "architectural",
            "original_text": "The API retains immutable history.",
        }],
    }


def test_legacy_projector_fails_closed_on_invented_assurance(tmp_path):
    artifact = completed_artifact()
    artifact["units"][0]["claims"][0]["evaluation"]["evidence"] = [{
        "source": "bounded_source_context",
        "excerpt": "The API retains immutable history.",
    }]
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "claims.json"
    candidate.write_text(json.dumps(artifact))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "project-legacy-claims.py"),
            str(candidate), "--output", str(output),
        ],
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 1
    assert "evidence_type" in result.stdout
    assert not output.exists()
