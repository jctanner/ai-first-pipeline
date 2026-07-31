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
    assert steps["strat_create"]["vars"]["skill_fqn"] == "{{ strategy_create_fqn }}"
    assert steps["strat_refine"]["vars"]["skill_fqn"] == "{{ strategy_refine_fqn }}"
    assert steps["strat_review"]["vars"]["skill_fqn"] == "{{ strategy_review_fqn }}"


def test_rfe_subworkflow_accepts_overridable_skill_fqns():
    workflow = load("workflows/run-rfe.yaml")
    steps = {step["name"]: step for step in workflow["steps"]}
    assert steps["rfe_speedrun"]["vars"]["skill_fqn"] == "{{ rfe_speedrun_fqn }}"
    assert steps["rfe_submit"]["vars"]["skill_fqn"] == "{{ rfe_submit_fqn }}"


def test_sme_loop_uses_supplied_branch_and_reuses_existing_strategy():
    initial = load("workflows/main.yaml")
    initial_names = [step["name"] for step in initial["steps"]]
    assert initial_names.index("run_initial_strategy") < initial_names.index("discover_strat_key")
    assert initial_names.index("discover_strat_key") < initial_names.index("assert_initial_refine_count")
    assert initial_names[-1] == "assert_initial_refine_count"
    assert initial["vars"]["strat_skill_owner"] == "jctanner-opendatahub-io"
    assert initial["vars"]["strat_skill_branch"] == (
        "feature/dashboard-sme-and-loop-metrics"
    )
    assert initial["vars"]["strategy_refine_fqn"].endswith(":strategy-refine")

    continuation = load("workflows/continue-sme-loop.yaml")
    continuation_names = [step["name"] for step in continuation["steps"]]
    assert continuation_names.index("populate_sme_input") < continuation_names.index("re_refine_strategy")
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
    assert "refine_count=2" in final
    assert "business_need_sha256" in initial_command
    assert "Business Need section was modified" in final
    assert "entered by sme-reviewer" in populate
    assert "Certificate-expiry" in populate


def test_sme_account_is_created_before_authenticated_sme_action():
    initial = load("workflows/main.yaml")
    continuation = load("workflows/continue-sme-loop.yaml")
    assert "sme_user" in initial["steps"][2]["params"]["body"]["name"]
    populate = next(step for step in continuation["steps"] if step["name"] == "populate_sme_input")
    assert "-u \"{{ sme_user }}:{{ sme_token }}\"" in populate["params"]["command"]
    assert "comment.get(\"author\", {})" in populate["params"]["command"]
    assert "author.get(\"name\") != \"{{ sme_user }}\"" in populate["params"]["command"]
