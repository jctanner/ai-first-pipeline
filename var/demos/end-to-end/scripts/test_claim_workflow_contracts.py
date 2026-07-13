import json
import subprocess
from pathlib import Path

import yaml

from claim_receipt_contract import reusable


ROOT = Path(__file__).parents[1]


def load(name: str):
    return yaml.safe_load((ROOT / name).read_text())


def step_command(workflow_name: str, step_name: str) -> str:
    workflow = load(workflow_name)
    step = next(item for item in workflow["steps"] if item["name"] == step_name)
    return step["params"]["command"]


def run_embedded(command: str, artifacts: Path, values: dict) -> dict:
    rendered = command.replace("Path('/app/artifacts')", f"Path({str(artifacts)!r})")
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", str(value))
    assert "{{" not in rendered, rendered
    result = subprocess.run(
        ["bash", "-c", rendered], capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def extraction_values(**overrides):
    values = {
        "claim_issue": "RFE-1",
        "claims_skill_repo": "github.local/example/claims@main",
        "claims_skill_revision": "skill-a",
        "claims_repository_revision": "commit-a",
        "claims_model": "claude-opus-4-6",
        "claims_harness": "claude-code",
        "claims_configuration_digest": "config-a",
        "force_claims": "false",
    }
    values.update(overrides)
    return values


def analysis_values(**overrides):
    values = {
        **extraction_values(),
        "claim_stage": "verify-claims",
        "claims_evidence_revision": "evidence-a",
    }
    values.update(overrides)
    return values


def test_claim_workflow_has_both_assurance_gates_and_regression_replay():
    workflow = load("workflows/run-claims.yaml")
    steps = {step["name"]: step for step in workflow["steps"]}
    assert steps["gate_extraction_quality"]["type"] == "gate"
    assert steps["verify_claims"]["when"] == "claims_ready_for_verification"
    assert steps["gate_verification_quality"]["type"] == "gate"
    assert steps["explain_claims"]["when"] == "claims_ready_for_explanation"
    assert steps["gate_explanation_routes"]["type"] == "gate"
    assert "human_review_explanations" in steps["gate_explanation_routes"]["facts"]
    assert steps["submit_claim_regression"]["when"] == (
        "claim_improvement_loop_ready and run_claim_regression"
    )
    assert steps["wait_for_claim_regression"]["type"] == "agent_job_wait"
    assert steps["record_claim_regression_pass"]["type"] == "shell_exec"
    assert steps["submit_claim_regression"]["params"]["path"] == "/api/evals/submit"

    rules = {rule["name"]: rule for rule in load("rules.yaml")}
    assert rules["extraction_entailment_block"]["action"] == "pause"
    assert rules["explanation_human_review"]["action"] == "pause"


def test_all_claim_stages_have_versioned_receipts():
    extraction = (ROOT / "workflows/run-claim-extraction.yaml").read_text()
    analysis = (ROOT / "workflows/run-claim-analysis-stage.yaml").read_text()
    for contract in (extraction, analysis):
        assert "'schema_version': 2" in contract
        assert "skill_revision" in contract
        assert "configuration_digest" in contract
        assert "evidence_context_digest" in analysis


def test_dataset_fqn_matches_workflow_default():
    dataset = json.loads((ROOT / "eval-datasets/claim-assurance-v1.json").read_text())
    workflow = load("workflows/run-claims.yaml")
    assert workflow["vars"]["claim_regression_dataset_fqn"] == dataset["dataset_fqn"]


def test_reset_imports_the_repository_addressed_by_the_claim_skill_fqn():
    variables = load("vars.yaml")
    claims = load("workflows/run-claims.yaml")
    reset = load("workflows/reset-github.yaml")
    steps = {step["name"]: step for step in reset["steps"]}

    expected_fqn = (
        f"github.local/{variables['claims_skill_owner']}/"
        "ai-first-pipeline@main"
    )
    assert claims["vars"]["claims_skill_repo"] == expected_fqn
    assert steps["ensure_claims_skill_owner"]["params"]["body"]["login"] == (
        "{{ claims_skill_owner }}"
    )
    imported = steps["import_claims_skill_source"]["vars"]
    assert imported == {
        "org": "{{ claims_skill_owner }}",
        "repo_name": "ai-first-pipeline",
        "upstream": "{{ claims_skill_upstream }}",
    }

    seed_command = steps["seed_claim_assurance_dataset"]["params"]["command"]
    assert seed_command.count("git -c http.sslVerify=false") == 2
    assert "git checkout -B main" in seed_command


def test_claim_jobs_use_pinned_execution_fqn_and_stage_specific_revisions():
    workflow = load("workflows/run-claims.yaml")
    steps = {step["name"]: step for step in workflow["steps"]}
    assert workflow["vars"]["claims_model"] == "claude-opus-4-6"
    assert workflow["vars"]["claims_harness"] == "claude-code"
    expected = {
        "extract_claims": "{{ resolved_extract_claims_revision }}",
        "verify_claims": "{{ resolved_verify_claims_revision }}",
        "explain_claims": "{{ resolved_explain_claims_revision }}",
    }
    for name, revision in expected.items():
        assert steps[name]["vars"]["claims_skill_revision"] == revision
        assert steps[name]["vars"]["claims_skill_execution_repo"] == (
            "{{ resolved_claims_execution_repo }}"
        )

    run_skill = load("workflows/run-skill.yaml")
    submit = next(step for step in run_skill["steps"] if step["name"] == "submit")
    args = submit["params"]["body"]["args"]
    assert args["model"] == "{{ skill_model }}"
    assert args["harness"] == "{{ skill_harness }}"


def test_receipt_invalidates_only_when_a_dependency_changes():
    expected = {
        "stage": "verify-claims", "scope": {"issue": "RFE-1"},
        "implementation": {"skill_revision": "abc", "model": "opus"},
        "input_digest": "source-a", "evidence_context_digest": "context-a",
        "outputs_exist": True,
    }
    receipt = {
        "schema_version": 2, "result": "complete", "stage": expected["stage"],
        "scope": expected["scope"], "implementation": expected["implementation"],
        "inputs": {"digest": expected["input_digest"],
                   "evidence_context_digest": expected["evidence_context_digest"]},
    }
    assert reusable(receipt, expected) == (True, "receipt-current")
    for field, value, reason in (
        ("input_digest", "source-b", "inputs-changed"),
        ("evidence_context_digest", "context-b", "evidence-context-changed"),
        ("outputs_exist", False, "outputs-missing"),
    ):
        changed = {**expected, field: value}
        assert reusable(receipt, changed) == (False, reason)
    changed = {**expected, "implementation": {"skill_revision": "def", "model": "opus"}}
    assert reusable(receipt, changed) == (False, "implementation-changed")


def test_embedded_extraction_receipt_hits_then_invalidates_source_and_skill(tmp_path):
    source = tmp_path / "strategies" / "RFE-1.md"
    source.parent.mkdir()
    source.write_text("# Strategy\n\nThe API retains immutable history.\n")
    check = step_command("workflows/run-claim-extraction.yaml", "check_receipt")
    write = step_command("workflows/run-claim-extraction.yaml", "write_receipt")

    first = run_embedded(check, tmp_path, extraction_values())
    assert first["reusable"] is False
    assert first["reason"] == "receipt-missing"

    claims = tmp_path / "claims" / "strategies"
    claims.mkdir(parents=True)
    (claims / "RFE-1.md.claims.json").write_text(json.dumps({
        "source_file": "strategies/RFE-1.md",
        "claims": [{"claim": "The API retains immutable history."}],
    }))
    (claims / "RFE-1.md.extraction.json").write_text(json.dumps({
        "source_file": "strategies/RFE-1.md",
        "observatory_run_id": 7,
        "units": [{
            "source_unit": {"id": "unit-a", "digest": "unit-digest-a"},
            "selection": {
                "classification": "verifiable", "evaluator_revision": "selector-a",
            },
            "ambiguity": {"status": "none", "evaluator_revision": "ambiguity-a"},
            "claims": [{"evaluation": {"evaluator_revision": "evaluation-a"}}],
        }],
    }))
    written = run_embedded(
        write, tmp_path,
        extraction_values(**{"receipt.input_digest": first["input_digest"]}),
    )
    assert written["written"] is True

    hit = run_embedded(check, tmp_path, extraction_values())
    assert hit["reusable"] is True
    assert hit["reason"] == "receipt-current"
    same_tree_new_commit = run_embedded(
        check, tmp_path,
        extraction_values(claims_repository_revision="commit-b"),
    )
    assert same_tree_new_commit["reusable"] is True

    source.write_text(source.read_text() + "The UI exposes the history.\n")
    source_change = run_embedded(check, tmp_path, extraction_values())
    assert source_change["reusable"] is False
    assert source_change["reason"] == "inputs-changed"

    source.write_text("# Strategy\n\nThe API retains immutable history.\n")
    skill_change = run_embedded(
        check, tmp_path, extraction_values(claims_skill_revision="skill-b"),
    )
    assert skill_change["reusable"] is False
    assert skill_change["reason"] == "implementation-changed"


def test_embedded_analysis_receipt_tracks_inputs_evidence_and_outputs(tmp_path):
    claims = tmp_path / "claims" / "RFE-1.extraction.json"
    claims.parent.mkdir()
    claims.write_text(json.dumps({
        "source_file": "strategies/RFE-1.md", "observatory_run_id": 7,
    }))
    verification = tmp_path / "verification" / "7" / "run.verification.json"
    verification.parent.mkdir(parents=True)
    verification.write_text(json.dumps({
        "issue": "RFE-1", "observatory_run_id": 11, "verdict": "supported",
    }))
    check = step_command("workflows/run-claim-analysis-stage.yaml", "check_stage_receipt")
    write = step_command("workflows/run-claim-analysis-stage.yaml", "write_stage_receipt")

    first = run_embedded(check, tmp_path, analysis_values())
    assert first["reusable"] is False
    written = run_embedded(write, tmp_path, analysis_values(**{
        "stage_receipt.evidence_revision": first["evidence_revision"],
        "stage_receipt.input_digest": first["input_digest"],
        "stage_receipt.evidence_context_digest": first["evidence_context_digest"],
    }))
    assert written["outputs"] == 1

    hit = run_embedded(check, tmp_path, analysis_values())
    assert hit["reusable"] is True
    verifier_change = run_embedded(
        check, tmp_path, analysis_values(claims_skill_revision="verify-tree-b"),
    )
    assert verifier_change["reusable"] is False
    claims.write_text(claims.read_text() + "\n")
    assert run_embedded(check, tmp_path, analysis_values())["reusable"] is False
    claims.write_text(json.dumps({
        "source_file": "strategies/RFE-1.md", "observatory_run_id": 7,
    }))
    evidence_change = run_embedded(
        check, tmp_path,
        analysis_values(claims_evidence_revision="evidence-b"),
    )
    assert evidence_change["reusable"] is False

    verification.unlink()
    missing_output = run_embedded(check, tmp_path, analysis_values())
    assert missing_output["reusable"] is False
