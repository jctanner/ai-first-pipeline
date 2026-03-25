"""Command-line argument parsing for the bug bash analysis tool."""

import argparse


def _add_common_analysis_args(parser: argparse.ArgumentParser) -> None:
    """Add flags shared across analysis phase subcommands."""
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


def parse_args():
    """Parse command line arguments with subcommands for each phase."""
    parser = argparse.ArgumentParser(
        description="AI-driven RHOAIENG bug bash analysis pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py completeness --issue RHOAIENG-37036 --model haiku
  python main.py completeness --max-concurrent 5
  python main.py context-map --max-concurrent 5
  python main.py fix-attempt --limit 10
  python main.py test-plan --max-concurrent 5
  python main.py all --max-concurrent 5
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Phase to run")

    # Phase 1: Fetch issues from Jira
    subparsers.add_parser(
        "fetch",
        help="Phase 1: Fetch issues from Jira into issues/ directory",
    )

    # Phase 2: Completeness scoring
    completeness_parser = subparsers.add_parser(
        "completeness",
        help="Phase 2: Score bug completeness (0-100)",
    )
    _add_common_analysis_args(completeness_parser)
    completeness_parser.add_argument(
        "--component",
        help="Only process issues whose Jira component matches (case-insensitive substring match)",
    )

    # Phase 3: Context mapping
    context_map_parser = subparsers.add_parser(
        "context-map",
        help="Phase 3: Map bugs to architecture context",
    )
    _add_common_analysis_args(context_map_parser)
    context_map_parser.add_argument(
        "--component",
        help="Only process issues whose Jira component matches (case-insensitive substring match)",
    )

    # Phase 4: Fix attempt
    fix_attempt_parser = subparsers.add_parser(
        "fix-attempt",
        help="Phase 4: Attempt fixes for eligible bugs",
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

    # Phase 5: Test plan generation
    test_plan_parser = subparsers.add_parser(
        "test-plan",
        help="Phase 5: Generate test plans",
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

    # Phase 6: Write QE tests
    write_test_parser = subparsers.add_parser(
        "write-test",
        help="Phase 6: Write QE tests for opendatahub-tests",
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

    # Run all analysis phases (2-6)
    all_parser = subparsers.add_parser(
        "all",
        help="Run phases 2-6 in dependency order",
    )
    _add_common_analysis_args(all_parser)
    all_parser.add_argument(
        "--include-fetch",
        action="store_true",
        help="Also run Phase 1 (fetch) before analysis phases",
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

    # Reporting dashboard
    report_parser = subparsers.add_parser(
        "report",
        help="Launch the reporting dashboard web app",
    )
    report_parser.add_argument(
        "--port", type=int, default=5000,
        help="Port to serve on (default: 5000)",
    )
    report_parser.add_argument(
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
