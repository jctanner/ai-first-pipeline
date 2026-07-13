from src.dashboard.job_names import build_job_name


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
