"""Post-fix patch validation using odh-tests-context container recipes.

Validates patches produced by the fix-attempt agent by running lint and test
commands inside podman containers, using pre-validated recipes from
odh-tests-context.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from lib.repo_mapping import get_midstream

BASE_DIR = Path(__file__).resolve().parent.parent
TESTS_CONTEXT_DIR = BASE_DIR / "odh-tests-context" / "tests"

# Extension → language key mapping for nested container_recipe resolution
_EXT_TO_LANG = {
    ".go": "go",
    ".py": "python",
    ".ts": "frontend",
    ".tsx": "frontend",
    ".js": "frontend",
    ".jsx": "frontend",
}

# Timeouts (seconds)
SETUP_TIMEOUT = 600
COMMAND_TIMEOUT = 300
FULL_TEST_TIMEOUT = 1200  # 20 min for full test suite
CONTAINER_STOP_TIMEOUT = 30

# Max bytes of stdout/stderr to capture per command
MAX_OUTPUT_BYTES = 4096


@dataclass
class ValidationCommand:
    command: str
    category: str  # "lint" or "test"
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    passed: bool = False


@dataclass
class ValidationResult:
    repo_name: str
    agent_readiness: str = ""
    setup_success: bool = False
    commands: list[ValidationCommand] = field(default_factory=list)
    lint_passed: bool = False
    tests_passed: bool = False
    overall_passed: bool = False
    skipped: bool = False
    skip_reason: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


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

    Flat format: ``container_recipe.base_image`` exists at top level →
    return ``[("default", recipe)]``.

    Nested format: ``container_recipe.go``, ``container_recipe.python``, etc. →
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

    Returns the container name on success, ``None`` on failure.
    """
    ts = int(time.time())
    container_name = f"bugbash-val-{repo_name}-{ts}"
    base_image = recipe.get("base_image", "")
    if not base_image:
        return None

    # Install system deps first if specified
    system_deps = recipe.get("system_deps", [])

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

    # Install system deps if any
    if system_deps:
        dep_cmd = _build_system_deps_command(system_deps)
        if dep_cmd:
            try:
                subprocess.run(
                    ["podman", "exec", container_name, "sh", "-c", dep_cmd],
                    capture_output=True, text=True, timeout=SETUP_TIMEOUT,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass  # Best effort

    return container_name


def _build_system_deps_command(deps: list[str]) -> str:
    """Build an install command for system dependencies."""
    if not deps:
        return ""
    dep_str = " ".join(deps)
    # Try apt-get first, fall back to yum/dnf
    return (
        f"(apt-get update -qq && apt-get install -y -qq {dep_str}) 2>/dev/null || "
        f"(yum install -y -q {dep_str}) 2>/dev/null || "
        f"(dnf install -y -q {dep_str}) 2>/dev/null || true"
    )


def run_setup_commands(container_name: str, recipe: dict) -> bool:
    """Run setup commands inside the container.

    Returns ``True`` if all commands succeeded.
    """
    setup_cmds = recipe.get("setup_commands", [])
    if not setup_cmds:
        return True

    for cmd_str in setup_cmds:
        try:
            result = subprocess.run(
                ["podman", "exec", container_name, "sh", "-c", cmd_str],
                capture_output=True, text=True, timeout=SETUP_TIMEOUT,
            )
            if result.returncode != 0:
                print(f"  VALIDATION: Setup command failed: {cmd_str}")
                print(f"    stderr: {result.stderr.strip()[:200]}")
                return False
        except subprocess.TimeoutExpired:
            print(f"  VALIDATION: Setup command timed out: {cmd_str}")
            return False
        except OSError as exc:
            print(f"  VALIDATION: Setup command error: {exc}")
            return False

    return True


def _build_selective_test_commands(
    recipe: dict, changed_files: list[str],
) -> list[str]:
    """Build per-directory test commands from the ``test_single_file`` template.

    For Go repos, deduplicate to unique package directories (e.g.
    ``./internal/controller/components/workbenches/``).
    For Python, use the file paths directly.

    Returns an empty list if no ``test_single_file`` template exists.
    """
    template = recipe.get("test_single_file", "")
    if not template or not changed_files:
        return []

    # Determine unique directories containing changed files
    dirs: set[str] = set()
    for f in changed_files:
        parent = str(Path(f).parent)
        if parent == ".":
            continue
        # Normalize to ./ prefix for Go-style paths
        if not parent.startswith("./"):
            parent = "./" + parent
        # Trailing slash for directory
        if not parent.endswith("/"):
            parent = parent + "/"
        dirs.add(parent)

    if not dirs:
        return []

    commands = []
    for d in sorted(dirs):
        # Replace {file} placeholder with the directory path
        cmd = template.replace("{file}", d)
        commands.append(cmd)

    return commands


def _run_command_in_container(
    container_name: str,
    cmd_str: str,
    cat_label: str,
    timeout: int,
    changed_files: list[str] | None = None,
) -> ValidationCommand:
    """Execute a single command in a container and return a ValidationCommand."""
    start = time.monotonic()
    try:
        proc = subprocess.run(
            ["podman", "exec", container_name, "sh", "-c", cmd_str],
            capture_output=True, text=True, timeout=timeout,
        )
        elapsed = time.monotonic() - start
        stdout = proc.stdout[:MAX_OUTPUT_BYTES] if proc.stdout else ""
        stderr = proc.stderr[:MAX_OUTPUT_BYTES] if proc.stderr else ""

        # Filter lint output to lines mentioning changed files
        if cat_label == "lint" and proc.returncode != 0 and changed_files:
            stdout = _filter_output_to_changed_files(stdout, changed_files)
            stderr = _filter_output_to_changed_files(stderr, changed_files)

        return ValidationCommand(
            command=cmd_str,
            category=cat_label,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=round(elapsed, 2),
            passed=proc.returncode == 0,
        )
    except subprocess.TimeoutExpired:
        elapsed = time.monotonic() - start
        return ValidationCommand(
            command=cmd_str,
            category=cat_label,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            duration_seconds=round(elapsed, 2),
            passed=False,
        )
    except OSError as exc:
        elapsed = time.monotonic() - start
        return ValidationCommand(
            command=cmd_str,
            category=cat_label,
            exit_code=-1,
            stdout="",
            stderr=str(exc),
            duration_seconds=round(elapsed, 2),
            passed=False,
        )


def run_validation_commands(
    container_name: str,
    recipe: dict,
    changed_files: list[str],
    *,
    selective: bool = True,
) -> list[ValidationCommand]:
    """Run lint and test commands, capturing results.

    When ``selective=True`` (default, used during retry iterations),
    lint commands run normally but test commands are replaced with
    targeted per-directory runs using ``test_single_file`` from the
    recipe.  This provides fast, focused feedback on the changed code.

    When ``selective=False`` (used for the final validation), the full
    ``test_commands`` from the recipe are run with a longer timeout.

    Skips commands where ``validated`` is ``false`` in the recipe (already
    broken on base repo). Filters lint output to lines mentioning files
    in the patch.
    """
    results: list[ValidationCommand] = []

    # --- Lint commands (always run in full) ---
    for cmd_entry in recipe.get("lint_commands", []):
        if isinstance(cmd_entry, str):
            cmd_str = cmd_entry
            validated = True
        elif isinstance(cmd_entry, dict):
            cmd_str = cmd_entry.get("command", "")
            validated = cmd_entry.get("validated", True)
        else:
            continue

        if not cmd_str or not validated:
            continue

        vc = _run_command_in_container(
            container_name, cmd_str, "lint", COMMAND_TIMEOUT, changed_files,
        )
        results.append(vc)

    # --- Test commands ---
    if selective:
        # Build targeted test commands from test_single_file template
        selective_cmds = _build_selective_test_commands(recipe, changed_files)
        if selective_cmds:
            for cmd_str in selective_cmds:
                vc = _run_command_in_container(
                    container_name, cmd_str, "test", COMMAND_TIMEOUT,
                )
                results.append(vc)
        else:
            # No test_single_file template — fall back to full commands
            for cmd_entry in recipe.get("test_commands", []):
                if isinstance(cmd_entry, str):
                    cmd_str = cmd_entry
                    validated = True
                elif isinstance(cmd_entry, dict):
                    cmd_str = cmd_entry.get("command", "")
                    validated = cmd_entry.get("validated", True)
                else:
                    continue
                if not cmd_str or not validated:
                    continue
                vc = _run_command_in_container(
                    container_name, cmd_str, "test", FULL_TEST_TIMEOUT,
                )
                results.append(vc)
    else:
        # Full test suite — longer timeout
        for cmd_entry in recipe.get("test_commands", []):
            if isinstance(cmd_entry, str):
                cmd_str = cmd_entry
                validated = True
            elif isinstance(cmd_entry, dict):
                cmd_str = cmd_entry.get("command", "")
                validated = cmd_entry.get("validated", True)
            else:
                continue
            if not cmd_str or not validated:
                continue
            vc = _run_command_in_container(
                container_name, cmd_str, "test", FULL_TEST_TIMEOUT,
            )
            results.append(vc)

    return results


def _filter_output_to_changed_files(output: str, changed_files: list[str]) -> str:
    """Filter output lines to those mentioning any changed file."""
    if not output or not changed_files:
        return output

    # Build basenames and relative paths for matching
    patterns: set[str] = set()
    for f in changed_files:
        patterns.add(Path(f).name)  # basename
        patterns.add(f)  # full relative path
        # Also add without leading ./ or /
        stripped = f.lstrip("./")
        if stripped:
            patterns.add(stripped)

    filtered_lines = []
    for line in output.splitlines():
        if any(p in line for p in patterns):
            filtered_lines.append(line)

    if not filtered_lines:
        # If filtering removes everything, return original (error might be
        # structural, not file-specific)
        return output

    return "\n".join(filtered_lines)


def stop_validation_container(container_name: str) -> None:
    """Remove a validation container (forced)."""
    try:
        subprocess.run(
            ["podman", "rm", "-f", container_name],
            capture_output=True, text=True, timeout=CONTAINER_STOP_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass  # Best effort


def validate_patch(
    repo_name: str,
    workspace_path: Path,
    changed_files: list[str],
    *,
    selective: bool = True,
) -> ValidationResult:
    """Orchestrate full validation lifecycle for one repo.

    Loads test context, checks eligibility, starts container, runs setup +
    validation commands, and cleans up.

    When ``selective=True`` (the default), tests are scoped to directories
    containing changed files using ``test_single_file`` from the recipe.
    When ``selective=False``, the full ``test_commands`` suite is run.

    Returns a ``ValidationResult`` with all details.
    """
    overall_start = time.monotonic()
    vr = ValidationResult(repo_name=repo_name)

    # Load test context
    test_context = load_test_context(repo_name)
    if test_context is None:
        vr.skipped = True
        vr.skip_reason = "no test context available"
        vr.duration_seconds = round(time.monotonic() - overall_start, 2)
        return vr

    vr.agent_readiness = test_context.get("agent_readiness", "")

    if not is_validation_eligible(test_context):
        vr.skipped = True
        vr.skip_reason = f"agent_readiness is '{vr.agent_readiness}' (need high or medium)"
        vr.duration_seconds = round(time.monotonic() - overall_start, 2)
        return vr

    # Resolve recipes
    recipes = resolve_container_recipes(test_context, changed_files)
    if not recipes:
        vr.skipped = True
        vr.skip_reason = "no matching container recipe"
        vr.duration_seconds = round(time.monotonic() - overall_start, 2)
        return vr

    all_commands: list[ValidationCommand] = []
    setup_ok = True
    containers: list[str] = []

    try:
        for lang_key, recipe in recipes:
            container_name = start_validation_container(
                f"{repo_name}-{lang_key}", recipe, workspace_path,
            )
            if container_name is None:
                setup_ok = False
                break
            containers.append(container_name)

            if not run_setup_commands(container_name, recipe):
                setup_ok = False
                break

            cmds = run_validation_commands(
                container_name, recipe, changed_files, selective=selective,
            )
            all_commands.extend(cmds)
    finally:
        for cn in containers:
            stop_validation_container(cn)

    vr.setup_success = setup_ok
    vr.commands = all_commands
    vr.lint_passed = all(c.passed for c in all_commands if c.category == "lint")
    vr.tests_passed = all(c.passed for c in all_commands if c.category == "test")
    vr.overall_passed = setup_ok and vr.lint_passed and vr.tests_passed
    vr.duration_seconds = round(time.monotonic() - overall_start, 2)

    return vr


def validate_patch_reuse_container(
    repo_name: str,
    workspace_path: Path,
    changed_files: list[str],
    containers: dict[str, list[str]],
    recipes: dict[str, list[tuple[str, dict]]],
    *,
    selective: bool = True,
) -> ValidationResult:
    """Run validation using already-started containers (for retry iterations).

    ``containers`` and ``recipes`` are keyed by repo_name and populated by
    the first iteration's setup.

    When ``selective=True``, tests are scoped to changed directories.
    When ``selective=False``, the full test suite runs.
    """
    overall_start = time.monotonic()
    vr = ValidationResult(repo_name=repo_name)

    repo_containers = containers.get(repo_name, [])
    repo_recipes = recipes.get(repo_name, [])

    if not repo_containers or not repo_recipes:
        vr.skipped = True
        vr.skip_reason = "no container from initial setup"
        vr.duration_seconds = round(time.monotonic() - overall_start, 2)
        return vr

    vr.setup_success = True
    all_commands: list[ValidationCommand] = []

    for (lang_key, recipe), container_name in zip(repo_recipes, repo_containers):
        cmds = run_validation_commands(
            container_name, recipe, changed_files, selective=selective,
        )
        all_commands.extend(cmds)

    vr.commands = all_commands
    vr.lint_passed = all(c.passed for c in all_commands if c.category == "lint")
    vr.tests_passed = all(c.passed for c in all_commands if c.category == "test")
    vr.overall_passed = vr.lint_passed and vr.tests_passed
    vr.duration_seconds = round(time.monotonic() - overall_start, 2)

    return vr


def format_validation_feedback(results: list[ValidationResult]) -> str:
    """Format validation failures into markdown for the retry prompt.

    Returns a markdown string describing which commands failed, with exit
    codes and relevant output lines.
    """
    sections: list[str] = []

    for vr in results:
        if vr.skipped or vr.overall_passed:
            continue

        lines = [f"### {vr.repo_name}"]

        if not vr.setup_success:
            lines.append("")
            lines.append("**Setup failed** — container setup commands did not complete successfully.")
            sections.append("\n".join(lines))
            continue

        failed_cmds = [c for c in vr.commands if not c.passed]
        if not failed_cmds:
            continue

        for cmd in failed_cmds:
            lines.append("")
            lines.append(f"**{cmd.category.upper()} FAILED:** `{cmd.command}`")
            lines.append(f"- Exit code: {cmd.exit_code}")
            if cmd.stdout.strip():
                lines.append(f"- stdout:")
                lines.append(f"```")
                lines.append(cmd.stdout.strip())
                lines.append(f"```")
            if cmd.stderr.strip():
                lines.append(f"- stderr:")
                lines.append(f"```")
                lines.append(cmd.stderr.strip())
                lines.append(f"```")

        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = (
        "## Validation Feedback\n\n"
        "The following lint/test commands failed after applying your patch. "
        "Please fix the errors and re-apply your changes.\n"
    )
    return header + "\n\n".join(sections)


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
