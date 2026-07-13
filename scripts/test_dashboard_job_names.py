from pathlib import Path

from src.dashboard.job_names import build_job_name


ROOT = Path(__file__).parents[1]


def test_job_names_are_unique_for_concurrent_submissions():
    names = {
        build_job_name("extract-claims", "RHAIRFE-1", "claude-opus-4-6")
        for _ in range(100)
    }

    assert len(names) == 100
    assert all(len(name) <= 63 for name in names)


def test_job_name_preserves_unique_suffix_when_prefix_is_truncated():
    suffix = "0713-210913-abcdef"
    name = build_job_name(
        "phase_with_an_extremely_long_and_invalid_name",
        "RHAIRFE-1234567890",
        "a-model-name-that-is-also-intentionally-long",
        unique_suffix=suffix,
    )

    assert name.endswith("-" + suffix)
    assert len(name) <= 63
    assert name == name.lower()
    assert "_" not in name


def test_skill_runners_preserve_dashboard_supplied_job_identity():
    runners = [
        "run_skill.sh",
        "run_skill_sdk.sh",
        "run_skill_agentic_ci.sh",
        "run_skill_opencode.sh",
        "run_skill_opencode_sdk.sh",
    ]

    for runner in runners:
        text = (ROOT / "scripts" / runner).read_text()
        assert 'PIPELINE_JOB_NAME="${PIPELINE_JOB_NAME:-' in text
