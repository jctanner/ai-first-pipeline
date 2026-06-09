"""Resolve pipeline skills to their sources and invocation settings.

Reads ``pipeline-skills.yaml`` from the project root and provides
helper functions that return the skill directory, working directory,
and invocation method for any registered skill.
"""

from __future__ import annotations

import os
import re
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


def _get_skills_block() -> dict:
    """Return the skills block, supporting both 'skills' and legacy 'phases' key."""
    cfg = _load()
    return cfg.get("skills") or cfg.get("phases") or {}


def get_phase_config(phase: str) -> dict:
    """Return the full config dict for *phase*.

    Raises ``KeyError`` if the phase is not registered.
    """
    skills = _get_skills_block()
    if phase not in skills:
        raise KeyError(
            f"Skill {phase!r} is not registered in {_CONFIG_PATH.name}. "
            f"Known skills: {', '.join(sorted(skills))}"
        )
    return dict(skills[phase])


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


def get_repo_github(source: str) -> str | None:
    """Return the ``github`` owner/repo string for a skill repo, or None."""
    cfg = _load()
    repos = cfg.get("skill_repos", {})
    repo = repos.get(source, {})
    return repo.get("github")


def get_repo_registry(source: str) -> str | None:
    """Return the marketplace registry identifier for a skill repo, or None."""
    cfg = _load()
    repos = cfg.get("skill_repos", {})
    repo = repos.get(source, {})
    return repo.get("registry")


def get_repo_ref(source: str) -> str:
    """Return the git ref (branch/tag) for a skill repo, defaulting to 'main'."""
    cfg = _load()
    repos = cfg.get("skill_repos", {})
    repo = repos.get(source, {})
    return repo.get("ref", "main")


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


def get_runner(phase: str) -> str:
    """Return ``"sdk"`` or ``"cli"`` for *phase*.

    Defaults to ``"sdk"`` when not specified in the config.
    """
    return get_phase_config(phase).get("runner", "sdk")


def _expand_env(value: str) -> str:
    """Expand ``${VAR:-default}`` and ``${VAR}`` patterns in a string."""
    def _replace(m: re.Match) -> str:
        var = m.group("var")
        default = m.group("default")
        return os.environ.get(var, default if default is not None else "")
    return re.sub(r"\$\{(?P<var>[^}:]+)(?::-(?P<default>[^}]*))?\}", _replace, value)


def get_mcp_servers(phase: str) -> dict:
    """Return MCP server configs for *phase* as a dict suitable for
    ``ClaudeAgentOptions.mcp_servers``.

    Each phase may list MCP server names in its ``mcp_servers`` field.
    Those names are resolved against the top-level ``mcp_servers`` config
    block.  Returns an empty dict if the phase needs no MCP servers.
    """
    pc = get_phase_config(phase)
    server_names = pc.get("mcp_servers", [])
    if not server_names:
        return {}

    cfg = _load()
    all_servers = cfg.get("mcp_servers", {})
    result = {}
    for name in server_names:
        if name not in all_servers:
            raise KeyError(
                f"MCP server {name!r} referenced by skill {phase!r} "
                f"is not defined in {_CONFIG_PATH.name}"
            )
        server_cfg = dict(all_servers[name])
        # Expand env var references in string values (e.g. URLs).
        for k, v in server_cfg.items():
            if isinstance(v, str):
                server_cfg[k] = _expand_env(v)
        result[name] = server_cfg
    return result


def list_skills() -> list[dict]:
    """Return all registered skills with display metadata.

    Each entry contains:
      - key: the internal skill key (e.g. "rfe-create")
      - skill: the skill name (e.g. "rfe.create")
      - source: the repo key or None for local
      - display: fully-qualified display name (e.g. "jwforres/rfe-creator:rfe.create")
    """
    skills_block = _get_skills_block()
    result = []
    for key, conf in skills_block.items():
        skill_name = conf.get("skill", key)
        source = conf.get("source")
        if source:
            github = get_repo_github(source)
            ref = get_repo_ref(source)
            repo_part = github if github else source
            display = f"{repo_part}@{ref}:{skill_name}"
        else:
            display = f"local:{skill_name}"
        result.append({
            "key": key,
            "skill": skill_name,
            "source": source,
            "display": display,
        })
    result.sort(key=lambda s: s["display"])
    return result
