"""Skill-based prompt loader for bug bash analysis phases.

Replaces hardcoded prompt templates with SKILL.md files loaded from
.claude/skills/{skill_name}/SKILL.md.  Each skill file contains YAML
front matter and an ``## Instructions`` section that is injected into
the agent prompt after an issue-data header block.
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / ".claude" / "skills"


def load_skill_instructions(
    skill_name: str,
    skills_dir: "Path | None" = None,
) -> str:
    """Read a SKILL.md file and return the content under ``## Instructions``.

    Parameters
    ----------
    skill_name:
        Directory name under the skills root (e.g. ``"bug-completeness"``).
    skills_dir:
        Override the default ``.claude/skills`` directory.  Use this to
        load skills from an external repository resolved via
        ``skill_config.resolve_skills_dir()``.

    Raises FileNotFoundError if the skill directory or SKILL.md is missing.
    Raises ValueError if the ``## Instructions`` heading is not found.
    """
    base = skills_dir if skills_dir is not None else SKILLS_DIR
    skill_path = base / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")

    text = skill_path.read_text()

    # Prefer content after an explicit ``## Instructions`` heading.
    match = re.search(r"^## Instructions\s*\n", text, re.MULTILINE)
    if match:
        return text[match.end():]

    # Fall back to everything after the YAML front matter (``---``
    # delimited).  External skills (e.g. rfe-creator) use this format.
    fm_match = re.match(r"^---\s*\n.*?\n---\s*\n", text, re.DOTALL)
    if fm_match:
        return text[fm_match.end():]

    # No front matter either — return the entire file.
    return text


def build_phase_prompt(
    skill_name: str,
    issue_key: str,
    issue_text: str,
    output_dir: "Path | None" = None,
    skills_dir: "Path | None" = None,
    **extra_context: str,
) -> str:
    """Build a full agent prompt from a skill file and issue data.

    Parameters
    ----------
    skill_name:
        Name of the skill directory under ``.claude/skills/``.
    issue_key:
        Jira issue key, e.g. ``RHOAIENG-37036``.
    issue_text:
        Pre-formatted plain-text rendering of the issue.
    output_dir:
        When provided, the agent is told to write output files into
        this directory (e.g. ``workspace/KEY/claude-opus-4-6/``).
        Paths in the instructions become relative to *output_dir*.
        When ``None`` (legacy), output paths use the old
        ``issues/{KEY}.phase.json`` convention.
    skills_dir:
        Override the default ``.claude/skills`` directory.  Use this
        to load skills from an external repository.
    **extra_context:
        Additional context blocks to inject before the instructions.
        Keys become section headings (underscored names are title-cased),
        values are the section body text.
        Example: ``completeness_text="..."`` becomes
        ``## Completeness Analysis\\n\\n...``.
    """
    instructions = load_skill_instructions(skill_name, skills_dir=skills_dir)

    # Build the issue data header
    if output_dir is not None:
        working_dir_section = (
            f"## Working Directory\n\n{BASE_DIR}\n\nAll relative paths in the instructions below are relative to this directory.\n\n"
            f"## Output Directory\n\n{output_dir}\n\n"
            f"Write all output files (JSON and markdown) into this directory. "
            f"For example, write `{output_dir}/completeness.json` (not `issues/{issue_key}.completeness.json`)."
        )
    else:
        working_dir_section = (
            f"## Working Directory\n\n{BASE_DIR}\n\nAll relative paths in the instructions below are relative to this directory. "
            f"When writing output files, use this exact absolute prefix — for example, "
            f"`{BASE_DIR}/issues/{issue_key}.context-map.json`."
        )

    sections = [
        working_dir_section,
        f"## Issue\n\nKey: {issue_key}\n\n{issue_text}",
    ]

    # Inject any extra context blocks (completeness analysis, context map, etc.)
    for name, text in extra_context.items():
        heading = name.replace("_", " ").title()
        sections.append(f"## {heading}\n\n{text}")

    header = "\n\n".join(sections)

    return f"{header}\n\n## Instructions\n\n{instructions}"
