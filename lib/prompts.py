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


def load_skill_instructions(skill_name: str) -> str:
    """Read a SKILL.md file and return the content under ``## Instructions``.

    Raises FileNotFoundError if the skill directory or SKILL.md is missing.
    Raises ValueError if the ``## Instructions`` heading is not found.
    """
    skill_path = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(f"Skill file not found: {skill_path}")

    text = skill_path.read_text()

    # Extract everything after the first ``## Instructions`` heading.
    match = re.search(r"^## Instructions\s*\n", text, re.MULTILINE)
    if not match:
        raise ValueError(
            f"Skill {skill_name}: SKILL.md missing '## Instructions' heading"
        )

    return text[match.end():]


def build_phase_prompt(
    skill_name: str,
    issue_key: str,
    issue_text: str,
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
    **extra_context:
        Additional context blocks to inject before the instructions.
        Keys become section headings (underscored names are title-cased),
        values are the section body text.
        Example: ``completeness_text="..."`` becomes
        ``## Completeness Analysis\\n\\n...``.
    """
    instructions = load_skill_instructions(skill_name)

    # Build the issue data header
    sections = [
        f"## Working Directory\n\n{BASE_DIR}\n\nAll relative paths in the instructions below are relative to this directory. "
        f"When writing output files, use this exact absolute prefix — for example, "
        f"`{BASE_DIR}/issues/{issue_key}.context-map.json`.",
        f"## Issue\n\nKey: {issue_key}\n\n{issue_text}",
    ]

    # Inject any extra context blocks (completeness analysis, context map, etc.)
    for name, text in extra_context.items():
        heading = name.replace("_", " ").title()
        sections.append(f"## {heading}\n\n{text}")

    header = "\n\n".join(sections)

    return f"{header}\n\n## Instructions\n\n{instructions}"
