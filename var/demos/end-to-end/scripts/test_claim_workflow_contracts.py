import json
import hashlib
import subprocess
from pathlib import Path

import pytest
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
    rendered = command.replace("/app/artifacts", str(artifacts))
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
        "claims_decontextualization_mode": "basic",
        "claims_segmentation_version": "claim-segmentation-v1",
        "claims_preceding_context_units": 1,
        "claims_following_context_units": 1,
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
    assert steps["submit_claim_regression"]["params"]["body"]["context_ref"] == (
        "{{ resolved_claims_evidence_revision }}"
    )
    for name in ("record_claim_regression", "record_claim_regression_pass"):
        command = steps[name]["params"]["command"]
        assert "eligible_verification_runs" in command
        assert "data.get('verification_run_id') not in eligible_verification_runs" in command

    rules = {rule["name"]: rule for rule in load("rules.yaml")}
    assert rules["extraction_entailment_block"]["action"] == "pause"
    assert rules["explanation_human_review"]["action"] == "pause"


def test_eval_runner_accepts_immutable_context_commits():
    runner = (ROOT.parents[2] / "scripts" / "run_eval.sh").read_text()
    assert "checkout_context_ref()" in runner
    assert 'checkout --detach "$target"' in runner
    assert 'clone --depth 1 -b "$CONTEXT_REF"' not in runner


def test_claim_discovery_allows_an_rfe_without_descendants():
    workflow = load("workflows/run-claims.yaml")
    steps = {step["name"]: step for step in workflow["steps"]}
    command = step_command("workflows/run-claims.yaml", "discover_issues")
    assert "discovered = {rfe, *strategies}" in command
    assert "processing the RFE only" in command
    assert "ERROR: no RHAISTRAT link found" not in command
    assert steps["set_all_issues"]["vars"]["all_issues"] == (
        "{{ discovered.all_issues | tojson }}"
    )


def test_all_claim_stages_have_versioned_receipts():
    extraction = (ROOT / "workflows/run-claim-extraction.yaml").read_text()
    analysis = (ROOT / "workflows/run-claim-analysis-stage.yaml").read_text()
    for contract in (extraction, analysis):
        assert "'schema_version': 2" in contract
        assert "skill_revision" in contract
        assert "configuration_digest" in contract
        assert "evidence_context_digest" in analysis


def test_analysis_receipt_observability_uses_explicit_hit_and_miss_steps():
    workflow = load("workflows/run-claim-analysis-stage.yaml")
    steps = {step["name"]: step for step in workflow["steps"]}

    hit = steps["record_stage_receipt_hit"]
    assert hit["when"] == "stage_receipt.reusable"
    assert hit["params"]["body"]["status"] == "hit"
    assert hit["params"]["body"]["agent_job_avoided"] is True

    miss = steps["record_stage_receipt_miss"]
    assert miss["when"] == "not stage_receipt.reusable"
    assert miss["params"]["body"]["status"] == "miss"
    assert miss["params"]["body"]["agent_job_avoided"] is False

    rendered = (ROOT / "workflows/run-claim-analysis-stage.yaml").read_text()
    assert " if stage_receipt.reusable else " not in rendered


def test_stage_output_directories_remain_writable_across_receipt_runs():
    extraction = load("workflows/run-claim-extraction.yaml")
    extraction_steps = {step["name"]: step for step in extraction["steps"]}
    prepare_claims = extraction_steps["prepare_claim_output"]
    assert prepare_claims["when"] == "not receipt.reusable"
    assert "chmod 0777 /app/artifacts/claims" in prepare_claims["params"]["command"]
    extraction_receipt = step_command(
        "workflows/run-claim-extraction.yaml", "write_receipt"
    )
    assert "os.chmod(receipt_path, 0o666)" in extraction_receipt
    assert "os.chmod(claims_root, 0o777)" in extraction_receipt

    analysis = load("workflows/run-claim-analysis-stage.yaml")
    analysis_steps = {step["name"]: step for step in analysis["steps"]}
    prepare_stage = analysis_steps["prepare_stage_output"]
    assert prepare_stage["when"] == "not stage_receipt.reusable"
    assert "chmod 0777 \"$OUTPUT_DIR\"" in prepare_stage["params"]["command"]
    analysis_receipt = step_command(
        "workflows/run-claim-analysis-stage.yaml", "write_stage_receipt"
    )
    assert "os.chmod(path, 0o666)" in analysis_receipt
    assert "os.chmod(base, 0o777)" in analysis_receipt

    analysis_check = step_command(
        "workflows/run-claim-analysis-stage.yaml", "check_stage_receipt"
    )
    assert "f'safe.directory={context_repo}'" in analysis_check


def test_receipt_misses_force_each_agent_skill_to_rebuild_outputs():
    extraction = load("workflows/run-claim-extraction.yaml")
    extract = next(step for step in extraction["steps"] if step["name"] == "extract")
    assert "force=true" in extract["vars"]["skill_extra_kwargs"]
    assert extract["for_each"] == "receipt.input_artifacts"
    assert extract["as"] == "artifact"
    assert "artifact_filter={{ artifact }}" in extract["vars"]["skill_extra_kwargs"]
    assert "decontextualization_mode={{ claims_decontextualization_mode }}" in (
        extract["vars"]["skill_extra_kwargs"]
    )

    analysis = load("workflows/run-claim-analysis-stage.yaml")
    run_stage = next(step for step in analysis["steps"] if step["name"] == "run_stage")
    assert "force=true" in run_stage["vars"]["skill_extra_kwargs"]


def test_stage_receipts_exclude_human_original_claim_outputs():
    check = step_command(
        "workflows/run-claim-analysis-stage.yaml", "check_stage_receipt"
    )
    assert "excluded_dirs = {'rfe-originals', 'strat-originals', 'ci-jobs'}" in check
    assert "set(path.relative_to(root).parts)" in check
    assert "set(Path(source_file).parts)" in check


def test_extraction_excludes_human_owned_original_inputs():
    check = step_command("workflows/run-claim-extraction.yaml", "check_receipt")
    write = step_command("workflows/run-claim-extraction.yaml", "write_receipt")
    for command in (check, write):
        assert "'rfe-originals'" in command
        assert "'strat-originals'" in command
        assert "'ci-jobs'" in command


def test_extraction_quality_accepts_null_ambiguity_for_unselected_units(tmp_path):
    staged = tmp_path / "claims" / "rfe-tasks" / "RFE-1.extraction.json"
    staged.parent.mkdir(parents=True)
    staged.write_text(json.dumps({
        "source_file": "rfe-tasks/RFE-1.md",
        "units": [{"ambiguity": None, "claims": []}],
    }))
    stale = tmp_path / "claims" / "rfe-originals" / "RFE-1.extraction.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(json.dumps({
        "source_file": "rfe-originals/RFE-1.md",
        "units": [{
            "ambiguity": {"status": "unresolved"},
            "claims": [{"accepted": True, "evaluation": {"entailed": False}}],
        }],
    }))
    assess = step_command("workflows/run-claims.yaml", "assess_extraction_quality")
    metrics = run_embedded(
        assess,
        tmp_path,
        {"all_issues | tojson": '[{"key":"RFE-1"}]'},
    )
    assert metrics == {
        "entailment_failures": 0,
        "unresolved_units": 0,
        "low_coverage_units": 0,
        "accepted_claims": 0,
    }


def test_extraction_quality_uses_element_outcomes_not_model_summary_label(tmp_path):
    staged = tmp_path / "claims" / "rfe-tasks" / "RFE-1.extraction.json"
    staged.parent.mkdir(parents=True)
    staged.write_text(json.dumps({
        "source_file": "rfe-tasks/RFE-1.md",
        "units": [{
            "ambiguity": {"status": "none"},
            "claims": [{
                "accepted": True,
                "evaluation": {
                    "entailed": True,
                    "coverage_result": "complete",
                    "coverage_elements": [{
                        "element_kind": "unverifiable", "coverage": "included",
                    }],
                },
            }],
        }, {
            "ambiguity": {"status": "none"},
            "claims": [{
                "accepted": True,
                "evaluation": {
                    "entailed": True,
                    "coverage_result": "partial",
                    "coverage_elements": [{
                        "element_kind": "unverifiable", "coverage": "omitted",
                    }],
                },
            }],
        }],
    }))
    assess = step_command("workflows/run-claims.yaml", "assess_extraction_quality")
    metrics = run_embedded(
        assess,
        tmp_path,
        {"all_issues | tojson": '[{"key":"RFE-1"}]'},
    )
    assert metrics["low_coverage_units"] == 1


def test_explanation_quality_is_scoped_by_immutable_verification_run(tmp_path):
    verification = tmp_path / "verification" / "17" / "run.verification.json"
    verification.parent.mkdir(parents=True)
    verification.write_text(json.dumps({
        "source_file": "rfe-tasks/RFE-1.md",
        "verdict": "contradicted",
        "observatory_run_id": 71,
    }))
    legacy = tmp_path / "explanations" / "17.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# RFE-1 explanation\n")
    structured = tmp_path / "explanations" / "71" / "run.explanation.json"
    structured.parent.mkdir(parents=True)
    # The structured artifact deliberately contains no Jira key. Its immutable
    # verification-run binding is the authoritative scope relationship.
    structured.write_text(json.dumps({
        "verification_run_id": 71,
        "category": "retrieval_failure",
        "improvement_target": "architecture alias index",
        "remediation": "add the missing alias",
        "regression_test": "resolve the alias before verification",
    }))

    assess = step_command("workflows/run-claims.yaml", "assess_explanation_routes")
    metrics = run_embedded(
        assess,
        tmp_path,
        {"all_issues | tojson": '[{"key":"RFE-1"}]'},
    )
    assert metrics == {
        "invalid_explanation_routes": 0,
        "human_review_explanations": 0,
        "unstructured_explanations": 0,
    }

    structured.unlink()
    missing = run_embedded(
        assess,
        tmp_path,
        {"all_issues | tojson": '[{"key":"RFE-1"}]'},
    )
    assert missing["unstructured_explanations"] == 1


def test_verification_quality_is_scoped_by_claim_occurrence_identity(tmp_path):
    extraction = tmp_path / "claims" / "rfe-tasks" / "RFE-1.extraction.json"
    extraction.parent.mkdir(parents=True)
    extraction.write_text(json.dumps({
        "source_file": "rfe-tasks/RFE-1.md",
        "observatory_occurrence_ids": [11, 12],
    }))
    first = tmp_path / "verification" / "11" / "run.verification.json"
    first.parent.mkdir(parents=True)
    # Verification artifacts deliberately need not duplicate a Jira key.
    first.write_text(json.dumps({
        "claim_occurrence_id": 11,
        "observatory_run_id": 101,
        "verdict": "contradicted",
        "severity": "high",
    }))
    second = tmp_path / "verification" / "12" / "run.verification.json"
    second.parent.mkdir(parents=True)
    second.write_text(json.dumps({
        "claim_occurrence_id": 12,
        "observatory_run_id": 102,
        "verdict": "supported",
        "severity": "info",
    }))
    unrelated = tmp_path / "verification" / "999" / "run.verification.json"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text(json.dumps({
        "claim_occurrence_id": 999,
        "verdict": "contradicted",
        "severity": "critical",
    }))

    assess = step_command("workflows/run-claims.yaml", "assess_verification_quality")
    metrics = run_embedded(
        assess,
        tmp_path,
        {"all_issues | tojson": '[{"key":"RFE-1"}]'},
    )
    assert metrics == {
        "high_severity_contradictions": 1,
        "verifier_disagreements": 0,
        "unstructured_verifications": 0,
        "blocking_occurrences": [11],
        "review_occurrences": [11],
        "review_targets": [{
            "claim_occurrence_id": 11,
            "verification_run_id": 101,
        }],
    }

    second.unlink()
    missing = run_embedded(
        assess,
        tmp_path,
        {"all_issues | tojson": '[{"key":"RFE-1"}]'},
    )
    assert missing["unstructured_verifications"] == 1


def test_dataset_fqn_matches_workflow_default():
    dataset = json.loads((ROOT / "eval-datasets/claim-assurance-v1.json").read_text())
    workflow = load("workflows/run-claims.yaml")
    assert workflow["vars"]["claim_regression_dataset_fqn"] == dataset["dataset_fqn"]


def test_reset_imports_the_repository_addressed_by_the_claim_skill_fqn():
    variables = load("vars.yaml")
    claims = load("workflows/run-claims.yaml")
    reset = load("workflows/reset-github.yaml")
    steps = {step["name"]: step for step in reset["steps"]}
    step_names = [step["name"] for step in reset["steps"]]

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
    assert step_names.index("import_claims_skill_source") < step_names.index(
        "seed_claim_assurance_dataset"
    )
    assert step_names.index("settle_after_dataset_seed") < step_names.index(
        "process_repos"
    )
    assert steps["process_repos"]["concurrency"] == 1

    import_repo = load("workflows/import-repo.yaml")
    import_steps = {step["name"]: step for step in import_repo["steps"]}
    delete_command = import_steps["delete_repo"]["params"]["command"]
    start_command = import_steps["start_import"]["params"]["command"]
    assert "for attempt in $(seq 1 10)" in delete_command
    assert "500|503" in delete_command
    assert "for attempt in $(seq 1 10)" in start_command
    assert "500|503" in start_command
    assert import_steps["settle_import_writes"]["params"]["command"] == "sleep 2"


def test_claim_jobs_use_flexible_execution_fqn_and_resolved_receipt_revisions():
    workflow = load("workflows/run-claims.yaml")
    steps = {step["name"]: step for step in workflow["steps"]}
    assert workflow["vars"]["claims_model"] == "claude-opus-4-6"
    assert workflow["vars"]["claims_harness"] == "claude-code"
    assert workflow["vars"]["claims_decontextualization_mode"] == "basic"
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

    resolution = step_command(
        "workflows/run-claims.yaml", "resolve_claim_skill_revision"
    )
    assert "execution_ref = configured if configured != 'unresolved' else ref" in resolution
    assert "'execution_repo': repository + '@' + execution_ref" in resolution
    assert "'repository_revision': commit" in resolution
    assert "'stage_revisions': revisions" in resolution

    configuration = step_command(
        "workflows/run-claims.yaml", "resolve_claim_configuration"
    )
    assert "'decontextualization_mode': os.environ['DECONTEXTUALIZATION_MODE']" in (
        configuration
    )

    evaluation = load("eval-datasets/claim-assurance/eval.yaml")
    assert "decontextualization_mode=full" in evaluation["execution"]["arguments"]

    run_skill = load("workflows/run-skill.yaml")
    submit = next(step for step in run_skill["steps"] if step["name"] == "submit")
    args = submit["params"]["body"]["args"]
    assert args["model"] == "{{ skill_model }}"
    assert args["harness"] == "{{ skill_harness }}"


def test_extraction_gate_aggregates_coverage_across_atomic_sibling_claims():
    command = step_command("workflows/run-claims.yaml", "assess_extraction_quality")
    assert "element_coverage.setdefault(key, set()).add" in command
    assert "not outcomes.intersection({'explicit', 'implicit'})" in command
    assert "if accepted and evaluation.get('entailed') is not True" in command
    skill = (ROOT.parents[2] / ".claude/skills/extract-claims/SKILL.md").read_text()
    assert "competitive-positioning phrases" in skill
    assert "combined coverage" in skill


def test_extraction_gate_runtime_ignores_sibling_omissions_but_keeps_real_gaps(
    tmp_path,
):
    command = step_command("workflows/run-claims.yaml", "assess_extraction_quality")
    output = tmp_path / "claims" / "RFE-1.extraction.json"
    output.parent.mkdir()
    sibling_elements = [
        {"element_text": "element A", "element_kind": "verifiable",
         "coverage": "explicit"},
        {"element_text": "element B", "element_kind": "verifiable",
         "coverage": "omitted"},
    ]
    output.write_text(json.dumps({
        "source_file": "strategies/RFE-1.md",
        "units": [
            {"ambiguity": {"status": "none"}, "claims": [
                {"accepted": True, "evaluation": {
                    "entailed": True, "coverage_elements": sibling_elements,
                }},
                {"accepted": True, "evaluation": {
                    "entailed": True, "coverage_elements": [
                        {**sibling_elements[0], "coverage": "omitted"},
                        {**sibling_elements[1], "coverage": "explicit"},
                    ],
                }},
            ]},
            {"ambiguity": {"status": "none"}, "claims": [
                {"accepted": True, "evaluation": {
                    "entailed": True, "coverage_elements": [{
                        "element_text": "genuinely dropped",
                        "element_kind": "verifiable", "coverage": "omitted",
                    }],
                }},
            ]},
        ],
    }))
    metrics = run_embedded(command, tmp_path, {
        "all_issues | tojson": '[{"key":"RFE-1"}]',
    })
    assert metrics == {
        "entailment_failures": 0,
        "unresolved_units": 0,
        "low_coverage_units": 1,
        "accepted_claims": 3,
    }


def test_verifier_does_not_silently_truncate_pending_occurrences():
    skill = (ROOT.parents[2] / ".claude/skills/verify-claims/SKILL.md").read_text()
    assert "pending_only=true&limit=1000" in skill
    assert "exactly 1000 occurrences" in skill
    assert "report any missing IDs" in skill


def test_human_override_binds_exact_immutable_verification_run(tmp_path):
    claims = tmp_path / "claims" / "RFE-1.extraction.json"
    claims.parent.mkdir()
    claims.write_text(json.dumps({
        "source_file": "strategies/RFE-1.md",
        "observatory_occurrence_ids": [42],
    }))
    verification = tmp_path / "verification" / "42" / "current.verification.json"
    verification.parent.mkdir(parents=True)
    verification.write_text(json.dumps({
        "claim_occurrence_id": 42,
        "observatory_run_id": "314",
        "verdict": "contradicted",
        "severity": "high",
    }))

    assess = step_command("workflows/run-claims.yaml", "assess_verification_quality")
    metrics = run_embedded(assess, tmp_path, {
        "all_issues | tojson": '[{"key":"RFE-1"}]',
    })
    assert metrics["review_occurrences"] == [42]
    assert metrics["review_targets"] == [{
        "claim_occurrence_id": 42,
        "verification_run_id": 314,
    }]

    audit = step_command("workflows/run-claims.yaml", "audit_human_override")
    assert "'verification_run_id': verification_run" in audit
    assert "lacks immutable verification run ID" in audit


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


def test_extraction_receipt_refuses_unvalidated_or_stale_agent_output(tmp_path):
    source = tmp_path / "strategies" / "RFE-1.md"
    source.parent.mkdir()
    source_text = (
        "# Strategy\n\nThe API retains immutable history for every submitted "
        "job, including its resolved skill identity and execution result.\n"
    )
    source.write_text(source_text)
    check = step_command("workflows/run-claim-extraction.yaml", "check_receipt")
    write = step_command("workflows/run-claim-extraction.yaml", "write_receipt")
    first = run_embedded(check, tmp_path, extraction_values())
    values = extraction_values(**{"receipt.input_digest": first["input_digest"]})

    with pytest.raises(subprocess.CalledProcessError):
        run_embedded(write, tmp_path, values)

    outputs = tmp_path / "claims" / "strategies"
    outputs.mkdir(parents=True)
    staged_path = outputs / "RFE-1.md.extraction.json"
    legacy_path = outputs / "RFE-1.md.claims.json"
    staged = {
        "run_key": "run-a",
        "source_file": "strategies/RFE-1.md",
        "pipeline_slug": "strategies",
        "artifact_type": "strategy",
        "artifact_digest": "sha256:" + hashlib.sha256(
            source.read_bytes()).hexdigest(),
        "extractor_revision": "skill-a",
        "repository_revision": "commit-a",
        "model": "claude-opus-4-6",
        "harness": "claude-code",
        "configuration_digest": "config-a",
        "decontextualization_mode": "basic",
        "configuration": {
            "segmenter_version": "markdown-v1",
            "preceding_units": 1,
            "following_units": 1,
            "artifact_type": "strategy",
            "artifact_type_override": {},
        },
        "segmentation_version": "claim-segmentation-v1",
        "segmentation_configuration_digest": "sha256:segments-a",
        "preceding_context_units": 1,
        "following_context_units": 1,
        "units": [{
            "source_unit": {"id": "unit-a"},
            "selection": {
                "classification": "__REQUIRED__",
                "evaluator_revision": "skill-a",
            },
            "ambiguity": None,
            "claims": [],
        }],
    }
    staged_path.write_text(json.dumps(staged))
    legacy_path.write_text(json.dumps({
        "source_file": "strategies/RFE-1.md",
        "pipeline_slug": "strategies",
        "claim_count": 0,
        "claims": [],
    }))
    with pytest.raises(subprocess.CalledProcessError):
        run_embedded(write, tmp_path, values)

    staged["units"][0]["selection"]["classification"] = "unverifiable"
    staged_path.write_text(json.dumps(staged))
    result = run_embedded(write, tmp_path, values)
    assert result["written"] is True
    receipt = json.loads(
        (tmp_path / "claims" / ".receipts" / "RFE-1.json").read_text())
    assert receipt["outputs"]["artifacts"] == [
        "claims/strategies/RFE-1.md.claims.json",
        "claims/strategies/RFE-1.md.extraction.json",
    ]


def test_embedded_analysis_receipt_tracks_inputs_evidence_and_outputs(tmp_path):
    claims = tmp_path / "claims" / "RFE-1.extraction.json"
    claims.parent.mkdir()
    claims.write_text(json.dumps({
        "source_file": "strategies/RFE-1.md", "observatory_run_id": 7,
    }))
    original = tmp_path / "claims" / "rfe-originals" / "RFE-1.extraction.json"
    original.parent.mkdir()
    original.write_text(json.dumps({
        "source_file": "rfe-originals/RFE-1.md", "observatory_run_id": 99,
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
    assert first["inputs"] == ["claims/RFE-1.extraction.json"]
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
