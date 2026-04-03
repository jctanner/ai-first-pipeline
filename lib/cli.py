"""Command-line argument parsing for the analysis pipeline."""

import argparse


def _add_common_analysis_args(parser: argparse.ArgumentParser) -> None:
    """Add flags shared across bug analysis phase subcommands."""
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum number of agents to run concurrently (default: 5)",
    )
    parser.add_argument(
        "--model",
        action="append",
        choices=["sonnet", "opus", "haiku"],
        default=None,
        dest="model",
        help="Claude model to use (can be specified multiple times, default: opus)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Process only the first N issues (for testing)",
    )
    parser.add_argument(
        "--issue",
        help="Process a single issue by key (e.g., RHOAIENG-37036)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate output even if it already exists",
    )


def _add_native_skill_args(parser: argparse.ArgumentParser) -> None:
    """Add flags for native-skill phases (rfe-creator, etc.)."""
    parser.add_argument(
        "--model",
        choices=["sonnet", "opus", "haiku"],
        default="opus",
        help="Claude model to use (default: opus)",
    )
    parser.add_argument(
        "--issue",
        help="Jira issue key to process (e.g., RHAIRFE-1234)",
    )


def parse_args():
    """Parse command line arguments with subcommands for each phase."""
    parser = argparse.ArgumentParser(
        description="AI-driven analysis pipeline for RHOAIENG bugs, RFEs, and strategies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py bug-completeness --issue RHOAIENG-37036 --model haiku
  python main.py bug-completeness --max-concurrent 5
  python main.py bug-context-map --max-concurrent 5
  python main.py bug-fix-attempt --limit 10
  python main.py bug-test-plan --max-concurrent 5
  python main.py bug-all --max-concurrent 5
  python main.py rfe-review --issue RHAIRFE-1234
  python main.py strat-review --issue RHAISTRAT-400
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Phase to run")

    # === Bug analysis phases ===

    # Bug Phase 1: Fetch issues from Jira
    subparsers.add_parser(
        "bug-fetch",
        help="Fetch RHOAIENG bug issues from Jira into issues/ directory",
    )

    # Bug Phase 2: Completeness scoring
    completeness_parser = subparsers.add_parser(
        "bug-completeness",
        help="Score bug completeness (0-100)",
    )
    _add_common_analysis_args(completeness_parser)
    completeness_parser.add_argument(
        "--component",
        help="Only process issues whose Jira component matches (case-insensitive substring match)",
    )

    # Bug Phase 3: Context mapping
    context_map_parser = subparsers.add_parser(
        "bug-context-map",
        help="Map bugs to architecture context",
    )
    _add_common_analysis_args(context_map_parser)
    context_map_parser.add_argument(
        "--component",
        help="Only process issues whose Jira component matches (case-insensitive substring match)",
    )

    # Bug Phase 4: Fix attempt
    fix_attempt_parser = subparsers.add_parser(
        "bug-fix-attempt",
        help="Attempt fixes for eligible bugs",
    )
    _add_common_analysis_args(fix_attempt_parser)
    fix_attempt_parser.add_argument(
        "--triage",
        choices=["ai-fixable", "needs-enrichment", "needs-info"],
        help="Only process issues with this triage recommendation",
    )
    fix_attempt_parser.add_argument(
        "--component",
        help="Only process issues whose context-map includes this component (case-insensitive substring match)",
    )
    fix_attempt_parser.add_argument(
        "--recommendation",
        choices=[
            "ai-fixable", "already-fixed", "not-a-bug", "docs-only",
            "upstream-required", "insufficient-info", "ai-could-not-fix",
        ],
        help="Only re-run issues whose existing fix-attempt has this recommendation (implies --force)",
    )
    fix_attempt_parser.add_argument(
        "--validation-retries",
        type=int,
        default=2,
        help="Max validation-retry iterations after fix attempt (0 disables validation, default: 2)",
    )
    fix_attempt_parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip post-fix validation entirely",
    )

    # Bug Phase 5: Test plan generation
    test_plan_parser = subparsers.add_parser(
        "bug-test-plan",
        help="Generate test plans",
    )
    _add_common_analysis_args(test_plan_parser)
    test_plan_parser.add_argument(
        "--triage",
        choices=["ai-fixable", "needs-enrichment", "needs-info"],
        help="Only process issues with this triage recommendation",
    )
    test_plan_parser.add_argument(
        "--component",
        help="Only process issues whose context-map includes this component (case-insensitive substring match)",
    )
    test_plan_parser.add_argument(
        "--recommendation",
        choices=[
            "ai-fixable", "already-fixed", "not-a-bug", "docs-only",
            "upstream-required", "insufficient-info", "ai-could-not-fix",
        ],
        help="Only re-run issues whose existing fix-attempt has this recommendation",
    )

    # Bug Phase 6: Write QE tests
    write_test_parser = subparsers.add_parser(
        "bug-write-test",
        help="Write QE tests for opendatahub-tests",
    )
    _add_common_analysis_args(write_test_parser)
    write_test_parser.add_argument(
        "--recommendation",
        choices=[
            "ai-fixable", "already-fixed", "not-a-bug", "docs-only",
            "upstream-required", "insufficient-info", "ai-could-not-fix",
        ],
        help="Only process issues with this fix-attempt recommendation",
    )
    write_test_parser.add_argument(
        "--component",
        help="Filter by component",
    )

    # Run all bug analysis phases (2-6)
    all_parser = subparsers.add_parser(
        "bug-all",
        help="Run bug analysis phases 2-6 in dependency order",
    )
    _add_common_analysis_args(all_parser)
    all_parser.add_argument(
        "--include-fetch",
        action="store_true",
        help="Also run fetch before analysis phases",
    )
    all_parser.add_argument(
        "--triage",
        choices=["ai-fixable", "needs-enrichment", "needs-info"],
        help="Only process issues with this triage recommendation (applies to phases 4 and 5)",
    )
    all_parser.add_argument(
        "--component",
        help="Only process issues whose context-map includes this component (applies to phases 4 and 5)",
    )
    all_parser.add_argument(
        "--recommendation",
        choices=[
            "ai-fixable", "already-fixed", "not-a-bug", "docs-only",
            "upstream-required", "insufficient-info", "ai-could-not-fix",
        ],
        help="Only re-run issues whose existing fix-attempt has this recommendation (applies to phases 4 and 5, implies --force)",
    )
    all_parser.add_argument(
        "--validation-retries",
        type=int,
        default=2,
        help="Max validation-retry iterations after fix attempt (0 disables validation, default: 2)",
    )
    all_parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip post-fix validation entirely",
    )
    all_parser.add_argument(
        "--dashboard-url",
        default="http://127.0.0.1:5000",
        help="URL of the reporting dashboard for live event push (default: http://127.0.0.1:5000)",
    )

    # === RFE phases (rfe-creator skills, native invocation) ===
    rfe_create_parser = subparsers.add_parser(
        "rfe-create",
        help="Write a new RFE from a problem statement or idea",
    )
    _add_native_skill_args(rfe_create_parser)

    rfe_review_parser = subparsers.add_parser(
        "rfe-review",
        help="Review and improve an RFE (rubric scoring, feasibility, auto-revision)",
    )
    _add_native_skill_args(rfe_review_parser)

    rfe_split_parser = subparsers.add_parser(
        "rfe-split",
        help="Split an oversized RFE into smaller, right-sized RFEs",
    )
    _add_native_skill_args(rfe_split_parser)

    rfe_submit_parser = subparsers.add_parser(
        "rfe-submit",
        help="Submit or update RFEs in Jira",
    )
    _add_native_skill_args(rfe_submit_parser)

    rfe_speedrun_parser = subparsers.add_parser(
        "rfe-speedrun",
        help="End-to-end RFE pipeline: create/fetch, review, auto-fix, and submit (alias: rfe-all)",
    )
    _add_native_skill_args(rfe_speedrun_parser)
    rfe_speedrun_parser.add_argument(
        "--limit", type=int,
        help="Process only the first N RFEs (for testing)",
    )
    rfe_speedrun_parser.add_argument(
        "--max-concurrent", type=int, default=5,
        help="Maximum number of agents to run concurrently (default: 5)",
    )

    # === Strategy phases (rfe-creator skills, native invocation) ===
    strat_create_parser = subparsers.add_parser(
        "strat-create",
        help="Create strategies from approved RFEs",
    )
    _add_native_skill_args(strat_create_parser)

    strat_refine_parser = subparsers.add_parser(
        "strat-refine",
        help="Refine strategies with HOW, dependencies, and NFRs",
    )
    _add_native_skill_args(strat_refine_parser)

    strat_review_parser = subparsers.add_parser(
        "strat-review",
        help="Adversarial review of refined strategies",
    )
    _add_native_skill_args(strat_review_parser)

    strat_submit_parser = subparsers.add_parser(
        "strat-submit",
        help="Push refined strategy content to RHAISTRAT Jira tickets",
    )
    _add_native_skill_args(strat_submit_parser)

    strat_security_review_parser = subparsers.add_parser(
        "strat-security-review",
        help="Security review of refined strategies",
    )
    _add_native_skill_args(strat_security_review_parser)

    # === Batch pipelines ===
    rfe_all_parser = subparsers.add_parser(
        "rfe-all",
        help="Alias for rfe-speedrun: end-to-end RFE pipeline",
    )
    _add_native_skill_args(rfe_all_parser)
    rfe_all_parser.add_argument(
        "--limit", type=int,
        help="Process only the first N RFEs (for testing)",
    )
    rfe_all_parser.add_argument(
        "--max-concurrent", type=int, default=5,
        help="Maximum number of agents to run concurrently (default: 5)",
    )

    strat_all_parser = subparsers.add_parser(
        "strat-all",
        help="Run strategy pipeline: refine, review, submit, and security-review for all strategies",
    )
    _add_common_analysis_args(strat_all_parser)
    strat_all_parser.add_argument(
        "--dashboard-url", default="http://127.0.0.1:5000",
        help="URL of the reporting dashboard for live event push",
    )

    # === Dashboard ===
    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Launch the reporting dashboard web app",
    )
    dashboard_parser.add_argument(
        "--port", type=int, default=5000,
        help="Port to serve on (default: 5000)",
    )
    dashboard_parser.add_argument(
        "--host", default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)",
    )

    args = parser.parse_args()

    # Default --model to ["opus"] when not specified.
    # ``action="append"`` with ``default=None`` leaves the attribute as
    # None when never used, so we replace it with the default list here.
    if getattr(args, "model", None) is None:
        args.model = ["opus"]

    return args
