"""Contract tests for the strat-creator SME/refine-loop integration workflow."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def load(name: str):
    return yaml.safe_load((ROOT / name).read_text())


def test_strategy_subworkflow_accepts_overridable_skill_fqns():
    workflow = load("workflows/run-strat.yaml")
    assert workflow["vars"]["strategy_refine_fqn"].endswith(":strategy-refine")
    steps = {step["name"]: step for step in workflow["steps"]}
    names = [step["name"] for step in workflow["steps"]]
    assert names.index("strat_create") < names.index("strat_refine") < names.index("strat_review")
    assert steps["strat_create"]["vars"]["skill_fqn"] == "{{ strategy_create_fqn }}"
    assert steps["strat_refine"]["vars"]["skill_fqn"] == "{{ strategy_refine_fqn }}"
    assert steps["strat_review"]["vars"]["skill_fqn"] == "{{ strategy_review_fqn }}"


def test_seed_matches_refined_rfe_state():
    workflow = load("workflows/seed-rfe.yaml")
    fields = workflow["steps"][0]["params"]["body"]["fields"]
    assert fields["summary"] == "Add rhai-cli diagnose subcommand for RHOAI deployment health checks"
    assert fields["priority"] == {"name": "Major"}
    assert fields["components"] == [{"name": "CLI"}]
    assert fields["labels"] == [
        "rfe-creator-autofix-rubric-pass",
        "rfe-creator-feasibility-pass",
        "rfe-creator-needs-attention",
        "strat-creator-3.6",
    ]
    comment = workflow["steps"][1]["params"]["body"]["body"]
    assert "flagged for human review" in comment
    assert "rhai-cli is not in the RHOAI 3.5-ea.2 platform architecture inventory" in comment


def test_sme_loop_uses_supplied_branch_and_reuses_existing_strategy():
    initial = load("workflows/main.yaml")
    initial_names = [step["name"] for step in initial["steps"]]
    assert initial_names.index("run_initial_strategy") < initial_names.index("discover_strat_key")
    assert initial_names.index("discover_strat_key") < initial_names.index("assert_initial_refine_count")
    assert initial_names.index("assert_initial_refine_count") < initial_names.index("continue_sme_loop")
    assert initial_names.index("continue_sme_loop") < initial_names.index("continue_sme_loop_again")
    assert "run_rfe" not in initial_names
    initial_strategy = next(step for step in initial["steps"] if step["name"] == "run_initial_strategy")
    assert initial_strategy["workflow"] == "run-strat"
    assert initial_strategy["vars"]["strategy_review_fqn"] == "{{ strategy_review_fqn }}"
    assert initial["vars"]["strategy_create_fqn"].startswith(
        "github.com/jctanner-opendatahub-io/strat-creator@feature/dashboard-sme-and-loop-metrics:"
    )
    assert initial["vars"]["strategy_refine_fqn"].endswith(":strategy-refine")
    continuation_step = next(step for step in initial["steps"] if step["name"] == "continue_sme_loop")
    assert continuation_step["workflow"] == "continue-sme-loop"
    assert continuation_step["vars"]["strat_issue"] == "{{ strat_issue }}"
    second_continuation = next(step for step in initial["steps"] if step["name"] == "continue_sme_loop_again")
    assert second_continuation["vars"]["expected_refine_count"] == "3"
    assert "stable machine-readable check_id" in second_continuation["vars"]["sme_feedback"]
    assert "schema_version: 1" in second_continuation["vars"]["sme_feedback"]

    continuation = load("workflows/continue-sme-loop.yaml")
    continuation_names = [step["name"] for step in continuation["steps"]]
    assert continuation_names.index("populate_sme_input") < continuation_names.index("re_refine_strategy")
    assert continuation_names.index("clear_review_gate_labels") < continuation_names.index("re_refine_strategy")
    assert continuation_names.index("re_refine_strategy") < continuation_names.index("review_refined_strategy")
    re_refine = next(step for step in continuation["steps"] if step["name"] == "re_refine_strategy")
    assert re_refine["vars"]["skill_fqn"] == "{{ strategy_refine_fqn }}"


def test_sme_loop_assertions_cover_counter_and_protected_sections():
    initial = load("workflows/main.yaml")
    initial_command = next(step for step in initial["steps"] if step["name"] == "assert_initial_refine_count")["params"]["command"]
    continuation = load("workflows/continue-sme-loop.yaml")
    continuation_steps = {step["name"]: step for step in continuation["steps"]}
    final = continuation_steps["assert_sme_refine_count"]["params"]["command"]
    populate = continuation_steps["populate_sme_input"]["params"]["command"]
    assert "refine_count=1" in initial_command
    assert "expected_refine_count" in final
    assert "business_need_sha256" in initial_command
    assert "Business Need section was modified" in final
    assert "strat-reviews" in initial_command
    assert "Entered by sme-reviewer" in populate
    continuation_vars = continuation["vars"]
    assert continuation_vars["expected_refine_count"] == "2"
    assert "certificates produce actionable warnings" in continuation_vars["sme_feedback"]
    assert "opendatahub-io/odh-cli" in continuation_vars["sme_feedback"]
    assert "current Kubernetes context" in continuation_vars["sme_feedback"]
    assert "aggregated report" in continuation_vars["sme_feedback"]


def test_sme_account_is_created_before_authenticated_sme_action():
    initial = load("workflows/main.yaml")
    continuation = load("workflows/continue-sme-loop.yaml")
    assert "sme_user" in initial["steps"][2]["params"]["body"]["name"]
    populate = next(step for step in continuation["steps"] if step["name"] == "populate_sme_input")
    assert "-u \"{{ sme_user }}:{{ sme_token }}\"" in populate["params"]["command"]
    assert "comment.get(\"author\", {})" in populate["params"]["command"]
    assert "author.get(\"name\") != \"{{ sme_user }}\"" in populate["params"]["command"]
    assert "-X PUT" in populate["params"]["command"]
    assert "$jira/rest/api/3/issue/$issue" in populate["params"]["command"]
    assert "strat-sme-description-update.json" in populate["params"]["command"]
    assert "strategy-refine agent must import it" in populate["params"]["command"]
    assert '"type": "heading"' in populate["params"]["command"]
    assert "Jira REST v3 did not return an ADF description" in populate["params"]["command"]
    assert "Jira description lost the formatted SME heading" in populate["params"]["command"]
    assert 'description["content"] = content[:section_index]' in populate["params"]["command"]
    assert "Jira description formatting changed outside the SME section" in populate["params"]["command"]
    assert 'Path("/tmp/strat-sme-input.txt").read_text()' in populate["params"]["command"]
    assert "path.write_text" not in populate["params"]["command"]
    re_refine = next(step for step in continuation["steps"] if step["name"] == "re_refine_strategy")
    assert "sme_input_sync=" in re_refine["vars"]["skill_extra_kwargs"]
    clear_labels = next(step for step in continuation["steps"] if step["name"] == "clear_review_gate_labels")
    assert clear_labels["params"]["body"]["update"]["labels"] == [
        {"remove": "strat-creator-rubric-pass"},
        {"remove": "strat-creator-needs-attention"},
    ]
