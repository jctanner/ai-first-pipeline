"""JSON schemas for bug bash analysis phase outputs.

Each schema is a Python dict conforming to the jsonschema specification.
Used for post-run validation of agent-produced JSON files.
"""

COMPLETENESS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "issue_key",
        "overall_score",
        "dimensions",
        "missing_information",
        "triage_recommendation",
        "issue_type_assessment",
    ],
    "properties": {
        "issue_key": {"type": "string"},
        "overall_score": {"type": "number", "minimum": 0, "maximum": 100},
        "dimensions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "name",
                    "weight",
                    "score",
                    "weighted_score",
                    "justification",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "weight": {"type": "integer"},
                    "score": {"type": "integer", "enum": [0, 50, 100]},
                    "weighted_score": {"type": "number"},
                    "justification": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "missing_information": {
            "type": "array",
            "items": {"type": "string"},
        },
        "triage_recommendation": {
            "type": "string",
            "enum": ["ai-fixable", "needs-enrichment", "needs-info"],
        },
        "issue_type_assessment": {
            "type": "object",
            "required": ["classified_type", "confidence", "justification"],
            "properties": {
                "classified_type": {
                    "type": "string",
                    "enum": [
                        "bug",
                        "feature-request",
                        "enhancement",
                        "task",
                        "epic",
                        "docs-update",
                        "support-request",
                        "configuration",
                        "test-gap",
                    ],
                },
                "confidence": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                },
                "justification": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}

CONTEXT_MAP_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "issue_key",
        "identified_components",
        "context_entries",
        "overall_rating",
        "relevant_files",
        "missing_context",
        "affected_versions",
        "context_helpfulness",
        "repos_and_files_used",
        "repos_and_files_needed",
    ],
    "properties": {
        "issue_key": {"type": "string"},
        "identified_components": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "source"],
                "properties": {
                    "name": {"type": "string"},
                    "source": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "context_entries": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "component",
                    "architecture_doc",
                    "source_checkout",
                    "rating",
                ],
                "properties": {
                    "component": {"type": "string"},
                    "architecture_doc": {"type": "string"},
                    "source_checkout": {"type": "string"},
                    "rating": {
                        "type": "string",
                        "enum": [
                            "full-context",
                            "partial-context",
                            "no-context",
                            "cross-component",
                        ],
                    },
                },
                "additionalProperties": False,
            },
        },
        "overall_rating": {
            "type": "string",
            "enum": [
                "full-context",
                "partial-context",
                "no-context",
                "cross-component",
            ],
        },
        "relevant_files": {
            "type": "array",
            "items": {"type": "string"},
        },
        "missing_context": {
            "type": "array",
            "items": {"type": "string"},
        },
        "affected_versions": {
            "type": "array",
            "items": {"type": "string"},
        },
        "context_helpfulness": {
            "type": "object",
            "required": ["overall_score", "coverage", "depth", "freshness"],
            "properties": {
                "overall_score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                },
                "coverage": {
                    "type": "object",
                    "required": ["score", "justification"],
                    "properties": {
                        "score": {
                            "type": "integer",
                            "enum": [0, 50, 100],
                        },
                        "justification": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "depth": {
                    "type": "object",
                    "required": ["score", "justification"],
                    "properties": {
                        "score": {
                            "type": "integer",
                            "enum": [0, 50, 100],
                        },
                        "justification": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "freshness": {
                    "type": "object",
                    "required": ["score", "justification"],
                    "properties": {
                        "score": {
                            "type": "integer",
                            "enum": [0, 50, 100],
                        },
                        "justification": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },
        "repos_and_files_used": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["repository", "files"],
                "properties": {
                    "repository": {"type": "string"},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
        "repos_and_files_needed": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["repository", "files", "reason"],
                "properties": {
                    "repository": {"type": "string"},
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}

FIX_ATTEMPT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "issue_key",
        "root_cause_hypothesis",
        "affected_files",
        "fix_description",
        "patch",
        "confidence",
        "risks",
        "blockers",
        "recommendation",
        "target_repo",
    ],
    "properties": {
        "issue_key": {"type": "string"},
        "root_cause_hypothesis": {"type": "string"},
        "affected_files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "repository", "change_description"],
                "properties": {
                    "path": {"type": "string"},
                    "repository": {"type": "string"},
                    "change_description": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "fix_description": {"type": "string"},
        "patch": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["low", "medium", "high"],
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "blockers": {
            "type": "array",
            "items": {"type": "string"},
        },
        "recommendation": {
            "type": "string",
            "enum": [
                "ai-fixable",
                "already-fixed",
                "not-a-bug",
                "docs-only",
                "upstream-required",
                "insufficient-info",
                "ai-could-not-fix",
            ],
        },
        "target_repo": {"type": "string"},
        "upstream_consideration": {"type": ["string", "null"]},
        "validation": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["iteration", "results", "all_passed"],
                "properties": {
                    "iteration": {"type": "integer"},
                    "all_passed": {"type": "boolean"},
                    "full_suite": {"type": "boolean"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["repo_name"],
                            "properties": {
                                "repo_name": {"type": "string"},
                                "overall_passed": {"type": "boolean"},
                                "lint_passed": {"type": "boolean"},
                                "selective_tests_passed": {
                                    "type": ["boolean", "null"],
                                },
                                "full_tests_passed": {
                                    "type": ["boolean", "null"],
                                },
                                "setup_success": {"type": "boolean"},
                                "skipped": {"type": "boolean"},
                                "skip_reason": {"type": "string"},
                                "summary": {"type": "string"},
                                "test_context_helpfulness": {
                                    "type": "object",
                                    "properties": {
                                        "rating": {
                                            "type": "string",
                                            "enum": [
                                                "high",
                                                "medium",
                                                "low",
                                                "none",
                                            ],
                                        },
                                        "explanation": {
                                            "type": "string",
                                        },
                                    },
                                },
                                "commands_run": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "command": {
                                                "type": "string",
                                            },
                                            "category": {
                                                "type": "string",
                                            },
                                            "exit_code": {
                                                "type": ["integer", "null"],
                                            },
                                            "passed": {
                                                "type": "boolean",
                                            },
                                            "output_summary": {
                                                "type": "string",
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
    "additionalProperties": False,
}

TEST_PLAN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "issue_key",
        "decision_rationale",
        "target_test_repos",
        "unit_tests",
        "integration_tests",
        "regression_tests",
        "manual_verification_steps",
        "environment_requirements",
        "effort_estimate",
    ],
    "properties": {
        "issue_key": {"type": "string"},
        "decision_rationale": {"type": "string"},
        "target_test_repos": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["repo", "test_directory", "framework", "run_command"],
                "properties": {
                    "repo": {"type": "string"},
                    "test_directory": {"type": "string"},
                    "framework": {"type": "string"},
                    "run_command": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "unit_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "description",
                    "file",
                    "setup",
                    "input",
                    "expected",
                    "edge_cases",
                ],
                "properties": {
                    "description": {"type": "string"},
                    "file": {"type": "string"},
                    "setup": {"type": "string"},
                    "input": {"type": "string"},
                    "expected": {"type": "string"},
                    "edge_cases": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "additionalProperties": False,
            },
        },
        "integration_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "description",
                    "components",
                    "setup",
                    "steps",
                    "expected",
                ],
                "properties": {
                    "description": {"type": "string"},
                    "components": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "setup": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "expected": {"type": "string"},
                    "api_verification": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
        },
        "regression_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "description",
                    "steps",
                    "before_fix",
                    "after_fix",
                ],
                "properties": {
                    "description": {"type": "string"},
                    "steps": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "before_fix": {"type": "string"},
                    "after_fix": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "manual_verification_steps": {
            "type": "array",
            "items": {"type": "string"},
        },
        "environment_requirements": {
            "type": "object",
            "properties": {
                "ocp_version": {"type": "string"},
                "rhoai_version": {"type": "string"},
                "platform": {"type": "string"},
                "special_config": {"type": "string"},
            },
        },
        "effort_estimate": {
            "type": "string",
            "enum": ["lightweight", "moderate", "heavy"],
        },
        "qe_coverage_note": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

# Map phase names to their schemas for easy lookup
PHASE_SCHEMAS = {
    "completeness": COMPLETENESS_SCHEMA,
    "context-map": CONTEXT_MAP_SCHEMA,
    "fix-attempt": FIX_ATTEMPT_SCHEMA,
    "test-plan": TEST_PLAN_SCHEMA,
}
