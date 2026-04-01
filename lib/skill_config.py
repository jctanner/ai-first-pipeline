"""Resolve pipeline phases to skill sources and invocation settings.

Reads ``pipeline-skills.yaml`` from the project root and provides
helper functions that return the skill directory, working directory,
and invocation method for any registered phase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = BASE_DIR / "pipeline-skills.yaml"

# Module-level cache so the YAML is parsed at most once per process.
_config: dict | None = None


def _load() -> dict:
    global _config
    if _config is None:
        with open(_CONFIG_PATH) as f:
            _config = yaml.safe_load(f)
    return _config


def get_phase_config(phase: str) -> dict:
    """Return the full config dict for *phase*.

    Raises ``KeyError`` if the phase is not registered.
    """
    cfg = _load()
    phases = cfg.get("phases", {})
    if phase not in phases:
        raise KeyError(
            f"Phase {phase!r} is not registered in {_CONFIG_PATH.name}. "
            f"Known phases: {', '.join(sorted(phases))}"
        )
    return dict(phases[phase])


def get_skill_name(phase: str) -> str:
    """Return the skill name for *phase* (the ``skill`` field)."""
    return get_phase_config(phase)["skill"]


def get_invoke_method(phase: str) -> Literal["templated", "native"]:
    """Return ``"templated"`` or ``"native"`` for *phase*."""
    return get_phase_config(phase).get("invoke", "templated")


def _resolve_repo_path(source: str) -> Path:
    """Resolve a ``skill_repos`` entry name to an absolute directory path."""
    cfg = _load()
    repos = cfg.get("skill_repos", {})
    if source not in repos:
        raise KeyError(
            f"Skill repo {source!r} is not registered in {_CONFIG_PATH.name}. "
            f"Known repos: {', '.join(sorted(repos))}"
        )
    rel = repos[source].get("path", "")
    if not rel:
        raise ValueError(f"Skill repo {source!r} has no 'path' configured")
    resolved = (BASE_DIR / rel).resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(
            f"Skill repo {source!r} path does not exist: {resolved}"
        )
    return resolved


def resolve_skills_dir(phase: str) -> Path:
    """Return the ``.claude/skills`` directory that contains the skill for *phase*.

    For local skills this is ``<project>/.claude/skills``.
    For external skills this is ``<repo_path>/.claude/skills``.
    """
    pc = get_phase_config(phase)
    source = pc.get("source")
    if source:
        return _resolve_repo_path(source) / ".claude" / "skills"
    return BASE_DIR / ".claude" / "skills"


def resolve_skill_path(phase: str) -> Path:
    """Return the absolute path to the ``SKILL.md`` for *phase*."""
    return resolve_skills_dir(phase) / get_skill_name(phase) / "SKILL.md"


def resolve_cwd(phase: str) -> Path:
    """Return the working directory the agent should use for *phase*.

    For native invocation with an external source, ``cwd`` must point at
    the external repo so the SDK discovers its ``.claude/skills/``,
    ``CLAUDE.md``, scripts, and companion files.

    For everything else, ``cwd`` is the pipeline project root.
    """
    pc = get_phase_config(phase)
    source = pc.get("source")
    if source and pc.get("invoke") == "native":
        return _resolve_repo_path(source)
    return BASE_DIR


def get_allowed_tools(phase: str) -> list[str]:
    """Return the ``allowed_tools`` list for *phase*.

    Falls back to ``["Read", "Write", "Glob", "Grep"]`` when not
    specified in the config.
    """
    pc = get_phase_config(phase)
    return list(pc.get("allowed_tools", ["Read", "Write", "Glob", "Grep"]))


def should_enable_skills(phase: str) -> bool:
    """Return ``True`` if the agent for *phase* needs SDK skill discovery."""
    return get_invoke_method(phase) == "native"
