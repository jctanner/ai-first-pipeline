"""Data loaders for RFE and Strategy artifacts.

Scans YAML-frontmatter markdown files produced by the rfe-creator
pipeline and returns structured dicts suitable for the dashboard.
"""

from pathlib import Path

import yaml

from lib.paths import BASE_DIR

# Default artifact directories
_ARTIFACTS_DIR = BASE_DIR / "references" / "rfe-creator" / "artifacts"
_SECURITY_REVIEWS_DIR = BASE_DIR / "security-reviews"


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a ``---``-delimited YAML frontmatter block from markdown body.

    Returns ``(metadata_dict, body_string)``.  If no frontmatter is
    found the metadata dict is empty and the full text is the body.
    """
    text = text.lstrip()
    if not text.startswith("---"):
        return {}, text
    # Find the closing delimiter
    end = text.find("---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[3:end]
    body = text[end + 3:].lstrip("\n")
    meta = yaml.safe_load(yaml_block)
    if not isinstance(meta, dict):
        meta = {}
    return meta, body


def load_security_reviews(security_dir: Path | None = None) -> dict[str, dict]:
    """Scan ``security-reviews/`` for ``*-security-review.md`` files.

    Returns a dict keyed by ``strat_key`` (e.g. ``"RHAISTRAT-1"``) with
    the parsed frontmatter fields.
    """
    d = security_dir or _SECURITY_REVIEWS_DIR
    result: dict[str, dict] = {}
    if not d.is_dir():
        return result
    for f in sorted(d.glob("*-security-review.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        key = meta.get("strat_key", "")
        if not key:
            # Try to derive from filename: RHAISTRAT-1-security-review.md
            stem = f.stem  # e.g. "RHAISTRAT-1-security-review"
            if stem.endswith("-security-review"):
                key = stem[: -len("-security-review")]
        if key:
            meta["_body"] = body
            result[key] = meta
    return result


def load_rfe_issues(artifacts_dir: Path | None = None) -> list[dict]:
    """Scan ``rfe-tasks/`` and ``rfe-reviews/`` under *artifacts_dir*.

    Returns a list of dicts, each with:
    - ``type="rfe"``
    - ``key`` = rfe_id
    - all rfe-task frontmatter fields
    - ``review`` sub-dict with rfe-review frontmatter (or ``None``)
    """
    base = artifacts_dir or _ARTIFACTS_DIR
    tasks_dir = base / "rfe-tasks"
    reviews_dir = base / "rfe-reviews"

    # Load reviews indexed by rfe_id
    reviews: dict[str, dict] = {}
    if reviews_dir.is_dir():
        for f in sorted(reviews_dir.glob("*-review.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(text)
            rid = meta.get("rfe_id", "")
            if rid:
                meta["_body"] = body
                reviews[rid] = meta

    # Load tasks and join reviews
    result: list[dict] = []
    if not tasks_dir.is_dir():
        return result
    for f in sorted(tasks_dir.glob("*.md")):
        # Skip companion files like *-comments.md
        if "-comments" in f.stem or "-removed-context" in f.stem:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        rid = meta.get("rfe_id", "")
        if not rid:
            continue
        entry = {
            "type": "rfe",
            "key": rid,
            **meta,
            "_body": body,
            "review": reviews.get(rid),
        }
        result.append(entry)
    return result


def load_strat_issues(
    artifacts_dir: Path | None = None,
    security_dir: Path | None = None,
) -> list[dict]:
    """Scan ``strat-tasks/`` and ``strat-reviews/`` under *artifacts_dir*.

    Also joins security review data from *security_dir*.

    Returns a list of dicts, each with:
    - ``type="strategy"``
    - ``key`` = strat_id
    - all strat-task frontmatter fields
    - ``review`` sub-dict with strat-review frontmatter (or ``None``)
    - ``security`` sub-dict with security review frontmatter (or ``None``)
    """
    base = artifacts_dir or _ARTIFACTS_DIR
    tasks_dir = base / "strat-tasks"
    reviews_dir = base / "strat-reviews"

    # Load strat reviews indexed by strat_id
    reviews: dict[str, dict] = {}
    if reviews_dir.is_dir():
        for f in sorted(reviews_dir.glob("*-review.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            meta, body = parse_frontmatter(text)
            sid = meta.get("strat_id", "")
            if sid:
                meta["_body"] = body
                reviews[sid] = meta

    # Load security reviews
    sec_reviews = load_security_reviews(security_dir)

    # Load tasks and join reviews + security
    result: list[dict] = []
    if not tasks_dir.is_dir():
        return result
    for f in sorted(tasks_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        meta, body = parse_frontmatter(text)
        sid = meta.get("strat_id", "")
        if not sid:
            continue
        entry = {
            "type": "strategy",
            "key": sid,
            **meta,
            "_body": body,
            "review": reviews.get(sid),
            "security": sec_reviews.get(sid),
        }
        result.append(entry)
    return result
