"""Kubernetes Job naming helpers."""

import re
import secrets
from datetime import datetime


def build_job_name(
    phase: str,
    issue_key: str,
    model_slug: str,
    unique_suffix: str | None = None,
) -> str:
    """Build a unique DNS-label-safe Kubernetes Job name."""
    scope = issue_key or "all"
    prefix = re.sub(
        r"[^a-z0-9-]+", "-", f"{phase}-{scope}-{model_slug}".lower()
    ).strip("-")
    suffix = unique_suffix or (
        datetime.now().strftime("%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    )
    suffix = re.sub(r"[^a-z0-9-]+", "-", suffix.lower()).strip("-")
    max_prefix = 63 - len(suffix) - 1
    if max_prefix < 1:
        raise ValueError("job-name suffix is too long")
    prefix = prefix[:max_prefix].rstrip("-") or "job"
    return f"{prefix}-{suffix}"
