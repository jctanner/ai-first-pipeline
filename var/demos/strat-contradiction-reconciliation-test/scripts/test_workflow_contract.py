"""Contract tests for the upstream-main contradiction reproduction demo."""

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def load(name: str):
    return yaml.safe_load((ROOT / name).read_text())


def test_all_skill_fqns_use_upstream_main():
    workflow = load("workflows/main.yaml")
    for name in ("strategy_create_fqn", "strategy_refine_fqn", "strategy_review_fqn"):
        assert workflow["vars"][name].startswith(
            "github.com/opendatahub-io/strat-creator@main:"
        )


def test_workflow_runs_and_asserts_baseline():
    workflow = load("workflows/main.yaml")
    names = [step["name"] for step in workflow["steps"]]
    assert names.index("seed_rfe") < names.index("run_strategy")
    assert names.index("run_strategy") < names.index("discover_strat_key")
    assert names.index("discover_strat_key") < names.index("assert_baseline_reproduction")
    assertion = next(
        step for step in workflow["steps"]
        if step["name"] == "assert_baseline_reproduction"
    )["params"]["command"]
    assert "DataRegistry CR" in assertion
    assert "FeatureStore CR" in assertion
    assert "Consistency Review" in assertion
    assert "contradictions-found" in assertion
    assert "Required resolution" in assertion
    assert "Open question for strategy refinement" in assertion
    assert "strat-creator-consistency-needs-attention" in assertion
    assert "strat-creator-rubric-pass" in assertion


def test_fixed_workflow_uses_pushed_consistency_branch():
    workflow = load("workflows/fixed.yaml")
    assert workflow["vars"]["strategy_create_fqn"].startswith(
        "github.com/jctanner-opendatahub-io/strat-creator@bugfix-review-consistency:"
    )
    assert workflow["vars"]["strategy_refine_fqn"].startswith(
        "github.com/jctanner-opendatahub-io/strat-creator@bugfix-review-consistency:"
    )
    assert workflow["vars"]["strategy_review_fqn"].startswith(
        "github.com/jctanner-opendatahub-io/strat-creator@bugfix-review-consistency:"
    )
    assert workflow["vars"]["expected_consistency"] == "contradictions-found"
    assert workflow["steps"][0]["workflow"] == "main"


def test_resolved_workflow_records_sme_decision_and_expects_resolved_signoff():
    workflow = load("workflows/resolved.yaml")
    for name in ("strategy_create_fqn", "strategy_refine_fqn", "strategy_review_fqn"):
        assert workflow["vars"][name].startswith(
            "github.com/jctanner-opendatahub-io/strat-creator@bugfix-review-consistency:"
        )
    assert workflow["vars"]["expected_consistency"] == "resolved"
    assert workflow["vars"]["sme_decision"]
    assert workflow["steps"][0]["workflow"] == "main"


def test_seed_contains_the_two_conflicting_sources():
    workflow = load("workflows/seed-rfe.yaml")
    description = workflow["steps"][0]["params"]["body"]["fields"]["description"]
    comment = workflow["steps"][1]["params"]["body"]["body"]
    assert "DataRegistry CR" in description
    assert "FeatureStore CR" in comment
    assert "Do not" in comment and "DataRegistry CRD" in comment
    assert "[RFE Creator] The following technical implementation details were removed" in comment


def test_run_strat_preserves_create_refine_review_order():
    workflow = load("workflows/run-strat.yaml")
    names = [step["name"] for step in workflow["steps"]]
    assert names.index("strat_create") < names.index("discover_strat_key")
    assert names.index("discover_strat_key") < names.index("set_strat_issue")
    assert names.index("set_strat_issue") < names.index("strat_refine")
    assert names.index("strat_refine") < names.index("strat_review")
    assert workflow["steps"][0]["vars"]["skill_fqn"] == "{{ strategy_create_fqn }}"
    review_step = next(step for step in workflow["steps"] if step["name"] == "strat_review")
    assert review_step["vars"]["skill_fqn"] == "{{ strategy_review_fqn }}"
    assert workflow["steps"][3]["name"] == "seed_sme_input"
    assert workflow["steps"][3]["when"] == "sme_decision != ''"
    quality_step = next(step for step in workflow["steps"] if step["name"] == "apply_sme_quality_constraints")
    assert quality_step["when"] == "sme_decision != ''"
    assert "p95 latency of 5 seconds" in quality_step["params"]["command"]
