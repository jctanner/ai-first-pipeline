"""Post-fix patch validation using an agent with Bash access.

The validation agent reads odh-tests-context markdown documentation, runs
commands via ``podman exec`` inside a container, and writes a structured
result JSON.  The orchestrator manages container lifecycle and reads the
result.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from lib.repo_mapping import get_midstream

BASE_DIR = Path(__file__).resolve().parent.parent
TESTS_CONTEXT_DIR = BASE_DIR / "odh-tests-context" / "tests"

# Extension -> language key mapping for nested container_recipe resolution
_EXT_TO_LANG = {
    ".go": "go",
    ".py": "python",
    ".ts": "frontend",
    ".tsx": "frontend",
    ".js": "frontend",
    ".jsx": "frontend",
}

# Timeouts (seconds)
CONTAINER_STOP_TIMEOUT = 30


def _resolve_test_context_name(repo_name: str) -> str:
    """Resolve a downstream/workspace repo name to the test context file name.

    Test context files are named after the midstream repo name (e.g.
    ``opendatahub-operator.json``), but workspace directories use the
    downstream name (e.g. ``rhods-operator``).  Try the downstream name
    first, then fall back to the midstream repo name.
    """
    if (TESTS_CONTEXT_DIR / f"{repo_name}.json").exists():
        return repo_name

    midstream = get_midstream(repo_name)
    if midstream:
        _org, midstream_repo = midstream
        if (TESTS_CONTEXT_DIR / f"{midstream_repo}.json").exists():
            return midstream_repo

    return repo_name


def load_test_context(repo_name: str) -> dict | None:
    """Load ``odh-tests-context/tests/{repo_name}.json``.

    Resolves downstream names to midstream repo names when needed.
    Returns the parsed JSON dict, or ``None`` if the file is missing or
    malformed.
    """
    resolved = _resolve_test_context_name(repo_name)
    json_path = TESTS_CONTEXT_DIR / f"{resolved}.json"
    if not json_path.exists():
        return None
    try:
        with open(json_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_test_context_markdown(repo_name: str) -> str | None:
    """Load ``odh-tests-context/tests/{repo_name}.md``.

    Resolves downstream names to midstream repo names when needed.
    Returns the markdown text, or ``None`` if the file is missing.
    """
    resolved = _resolve_test_context_name(repo_name)
    md_path = TESTS_CONTEXT_DIR / f"{resolved}.md"
    if not md_path.exists():
        return None
    try:
        return md_path.read_text()
    except OSError:
        return None


def is_validation_eligible(test_context: dict) -> bool:
    """Return ``True`` if ``agent_readiness`` is ``"high"`` or ``"medium"``."""
    readiness = test_context.get("agent_readiness", "").lower()
    return readiness in ("high", "medium")


def resolve_container_recipes(
    test_context: dict, changed_files: list[str]
) -> list[tuple[str, dict]]:
    """Resolve container recipes from test context, handling flat and nested formats.

    Returns a list of ``(language_key, recipe_dict)`` tuples.

    Flat format: ``container_recipe.base_image`` exists at top level ->
    return ``[("default", recipe)]``.

    Nested format: ``container_recipe.go``, ``container_recipe.python``, etc. ->
    match changed file extensions and return matching sub-recipes.
    """
    recipe = test_context.get("container_recipe")
    if not recipe or not isinstance(recipe, dict):
        return []

    # Flat format: base_image at top level
    if "base_image" in recipe and recipe["base_image"]:
        return [("default", recipe)]

    # Nested format: check for language sub-keys
    # Determine which languages are touched by the changed files
    touched_langs: set[str] = set()
    for fpath in changed_files:
        ext = Path(fpath).suffix.lower()
        lang = _EXT_TO_LANG.get(ext)
        if lang:
            touched_langs.add(lang)

    # If no changed files match known extensions, try all available languages
    if not touched_langs:
        touched_langs = set(recipe.keys())

    results = []
    for lang in sorted(touched_langs):
        sub_recipe = recipe.get(lang)
        if isinstance(sub_recipe, dict) and sub_recipe.get("base_image"):
            results.append((lang, sub_recipe))

    return results


def start_validation_container(
    repo_name: str, recipe: dict, workspace_path: Path
) -> str | None:
    """Start a podman container for validation.

    Starts a long-running container with the workspace mounted.  The
    validation agent handles all setup and command execution via
    ``podman exec``.

    Returns the container name on success, ``None`` on failure.
    """
    ts = int(time.time())
    container_name = f"bugbash-val-{repo_name}-{ts}"
    base_image = recipe.get("base_image", "")
    if not base_image:
        return None

    cmd = [
        "podman", "run", "-d",
        "--name", container_name,
        "-v", f"{workspace_path}:/app:Z",
        "-w", "/app",
        base_image,
        "sleep", "infinity",
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"  VALIDATION: Failed to start container {container_name}: {result.stderr.strip()[:200]}")
            return None
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"  VALIDATION: Container start error: {exc}")
        return None

    return container_name


def stop_validation_container(container_name: str) -> None:
    """Remove a validation container (forced)."""
    try:
        subprocess.run(
            ["podman", "rm", "-f", container_name],
            capture_output=True, text=True, timeout=CONTAINER_STOP_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass  # Best effort


def remove_validation_image(image: str) -> None:
    """Remove a container image used for validation (best-effort)."""
    try:
        subprocess.run(
            ["podman", "rmi", image],
            capture_output=True, text=True, timeout=CONTAINER_STOP_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass  # Best effort


def get_changed_files_from_workspace(workspace_path: Path) -> dict[str, list[str]]:
    """Get changed files per repo directory from a workspace.

    Returns a dict mapping repo directory names to lists of changed file
    paths (relative to the repo root).
    """
    result: dict[str, list[str]] = {}

    if not workspace_path.exists():
        return result

    for child in sorted(workspace_path.iterdir()):
        if not child.is_dir() or not (child / ".git").exists():
            continue
        try:
            proc = subprocess.run(
                ["git", "-C", str(child), "diff", "--name-only"],
                capture_output=True, text=True, timeout=30,
            )
            if proc.stdout.strip():
                files = [f for f in proc.stdout.strip().splitlines() if f]
                if files:
                    result[child.name] = files
        except (subprocess.TimeoutExpired, OSError):
            pass

    return result


async def run_validation_agent(
    key: str,
    container_name: str,
    test_context_md_path: str | None,
    changed_files: list[str],
    result_output_path: Path,
    log_dir: Path,
    model: str = "sonnet",
) -> dict | None:
    """Launch a validation agent with Bash access.

    Uses the native ``patch-validation`` skill from ``.claude/skills/``
    for the validation methodology.  The prompt provides only the
    runtime context (container name, changed files, output path) and
    directs the agent to invoke the skill.

    Args:
        key: Issue key for identification
        container_name: Name of the running podman container
        test_context_md_path: Path to the test context .md file (or None)
        changed_files: List of changed file paths (relative to repo root)
        result_output_path: Path where the agent should write result JSON
        log_dir: Directory for agent logs
        model: Claude model to use

    Returns:
        The parsed result dict, or None if the agent failed or produced
        no valid output.
    """
    from lib.agent_runner import run_agent

    # Build a short prompt with runtime context only.  The full
    # validation methodology lives in .claude/skills/patch-validation/
    # and is loaded natively by the SDK via enable_skills=True.
    files_list = "\n".join(f"- `{f}`" for f in changed_files)

    if test_context_md_path:
        test_ctx_section = (
            f"Read the test context documentation at: `{test_context_md_path}`\n"
            "This file describes the project's lint/test infrastructure, available "
            "commands, setup requirements, and which commands are validated as working."
        )
    else:
        test_ctx_section = (
            "No test context file is available. Look in the repo itself for "
            "Makefile, go.mod, pytest.ini, tox.ini, or similar to discover how "
            "to run tests."
        )

    prompt = (
        f"Validate the patch for issue **{key}** using the patch-validation skill.\n"
        f"\n"
        f"Container name: `{container_name}`\n"
        f"Workspace is mounted at `/app` inside the container.\n"
        f"Run commands with: `podman exec {container_name} sh -c \"...\"`\n"
        f"\n"
        f"Changed files:\n{files_list}\n"
        f"\n"
        f"Test context:\n{test_ctx_section}\n"
        f"\n"
        f"Write the validation result JSON to: `{result_output_path}`\n"
    )

    agent_result = await run_agent(
        name=f"{key}-validation",
        cwd=str(BASE_DIR),
        prompt=prompt,
        log_dir=log_dir,
        model=model,
        allowed_tools=["Read", "Write", "Glob", "Grep", "Bash"],
        enable_skills=True,
    )

    if not isinstance(agent_result, dict) or not agent_result.get("success"):
        return None

    # Read the result JSON written by the agent
    if not result_output_path.exists():
        print(f"  [{key}] validation agent did not write result JSON")
        return None

    try:
        with open(result_output_path) as f:
            raw = json.load(f)
        return _normalize_validation_result(raw)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  [{key}] failed to read validation result: {exc}")
        return None


def _normalize_validation_result(raw: dict) -> dict:
    """Normalize agent output to the expected schema.

    Agents don't always follow the exact schema.  This handles common
    alternate field names so the orchestrator gets consistent data.
    """
    result = dict(raw)

    # overall_passed: agent may write "overall_result": "pass" instead
    if "overall_passed" not in result or result["overall_passed"] is None:
        alt = result.get("overall_result", "")
        if isinstance(alt, str):
            result["overall_passed"] = alt.lower() in ("pass", "passed", "true")
        elif isinstance(alt, bool):
            result["overall_passed"] = alt

    # lint_passed: may be missing; infer from validation_steps
    if "lint_passed" not in result or result["lint_passed"] is None:
        steps = result.get("validation_steps", result.get("commands_run", []))
        lint_steps = [s for s in steps if s.get("category", s.get("step", "")).lower() in ("lint",)]
        if lint_steps:
            result["lint_passed"] = all(
                s.get("passed", s.get("result", "").lower() in ("pass", "passed"))
                for s in lint_steps
            )

    # commands_run: agent may use "validation_steps" instead
    if "commands_run" not in result and "validation_steps" in result:
        normalized_cmds = []
        for step in result["validation_steps"]:
            normalized_cmds.append({
                "command": step.get("command", ""),
                "category": step.get("step", step.get("category", "unknown")),
                "exit_code": step.get("exit_code"),
                "passed": step.get("passed", step.get("result", "").lower() in ("pass", "passed")),
                "output_summary": step.get("output_summary", step.get("output", "")),
            })
        result["commands_run"] = normalized_cmds

    # test_context_helpfulness: provide default if missing
    if "test_context_helpfulness" not in result:
        result["test_context_helpfulness"] = {
            "rating": "medium",
            "explanation": "Agent did not provide an explicit rating",
        }

    # summary: synthesize from notes if missing
    if "summary" not in result:
        result["summary"] = result.get("notes", "")

    return result
