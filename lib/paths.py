"""Single source of truth for all workspace and output paths.

Every module that needs to locate issue data, phase outputs, logs, or
workspace directories imports from here.  The ``model_id`` parameter
is the full model ID string returned by ``get_model_id()`` (e.g.
``claude-opus-4-6``) and is used directly as the directory name.
"""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ISSUES_DIR = BASE_DIR / "issues"
WORKSPACE_DIR = BASE_DIR / "workspace"


def model_workspace(key: str, model_id: str) -> Path:
    """Return ``workspace/{KEY}/{model_id}/``."""
    return WORKSPACE_DIR / key / model_id


def phase_json(key: str, model_id: str, phase: str) -> Path:
    """Return ``workspace/{KEY}/{model_id}/{phase}.json``."""
    return model_workspace(key, model_id) / f"{phase}.json"


def phase_md(key: str, model_id: str, phase: str) -> Path:
    """Return ``workspace/{KEY}/{model_id}/{phase}.md``."""
    return model_workspace(key, model_id) / f"{phase}.md"


def phase_log(key: str, model_id: str, phase: str) -> Path:
    """Return ``workspace/{KEY}/{model_id}/{phase}.log``."""
    return model_workspace(key, model_id) / f"{phase}.log"


def src_dir(key: str, model_id: str) -> Path:
    """Return ``workspace/{KEY}/{model_id}/src/``."""
    return model_workspace(key, model_id) / "src"


def patch_diff(key: str, model_id: str) -> Path:
    """Return ``workspace/{KEY}/{model_id}/patch.diff``."""
    return model_workspace(key, model_id) / "patch.diff"


def memory_md(key: str, model_id: str) -> Path:
    """Return ``workspace/{KEY}/{model_id}/MEMORY.md``."""
    return model_workspace(key, model_id) / "MEMORY.md"


def issue_copy(key: str) -> Path:
    """Return ``workspace/{KEY}/issue.json``."""
    return WORKSPACE_DIR / key / "issue.json"


def discover_models(key: str) -> list[str]:
    """List model_id subdirectories that exist under ``workspace/{KEY}/``.

    Returns an empty list if the issue workspace does not exist.
    """
    issue_ws = WORKSPACE_DIR / key
    if not issue_ws.is_dir():
        return []
    return sorted(
        d.name for d in issue_ws.iterdir()
        if d.is_dir() and d.name != "issue.json"
    )
