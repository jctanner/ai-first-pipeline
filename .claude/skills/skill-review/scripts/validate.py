#!/usr/bin/env python3
"""
Skill validation script for Claude Code skills.
Validates SKILL.md structure, frontmatter, file references, and packaging.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml")
    sys.exit(1)


def parse_frontmatter(skill_md_path: Path) -> Tuple[Dict[str, Any], str, List[str]]:
    """Parse YAML frontmatter from SKILL.md file.

    Returns:
        (frontmatter_dict, markdown_content, errors)
    """
    errors = []

    if not skill_md_path.exists():
        return {}, "", [f"SKILL.md not found: {skill_md_path}"]

    with open(skill_md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Check for frontmatter
    if not content.startswith('---'):
        return {}, content, ["No frontmatter found (must start with ---)"]

    # Split by frontmatter delimiters
    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content, ["Invalid frontmatter structure (need two --- delimiters)"]

    frontmatter_text = parts[1].strip()
    markdown_content = parts[2].strip()

    # Parse YAML
    try:
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            return {}, markdown_content, ["Frontmatter is not a valid YAML dictionary"]
    except yaml.YAMLError as e:
        return {}, markdown_content, [f"YAML parse error: {e}"]

    return frontmatter, markdown_content, errors


KEBAB_CASE_RE = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
RESERVED_WORDS = {'claude', 'anthropic'}


def validate_naming(folder_name: str, frontmatter: Dict[str, Any]) -> List[str]:
    """Validate folder name and name field against naming conventions."""
    errors = []

    if not KEBAB_CASE_RE.match(folder_name):
        suggestions = []
        if '.' in folder_name:
            suggestions.append("dots are not allowed")
        if '_' in folder_name:
            suggestions.append("underscores are not allowed")
        if folder_name != folder_name.lower():
            suggestions.append("must be lowercase")
        if ' ' in folder_name:
            suggestions.append("spaces are not allowed")
        kebab = re.sub(r'[._\s]+', '-', folder_name).lower()
        kebab = re.sub(r'[^a-z0-9-]', '', kebab)
        kebab = re.sub(r'-+', '-', kebab).strip('-')
        detail = f" ({', '.join(suggestions)})" if suggestions else ""
        errors.append(
            f"Folder name '{folder_name}' is not kebab-case{detail}; "
            f"suggested: '{kebab}'"
        )

    name_field = frontmatter.get('name', '')
    if isinstance(name_field, str) and name_field:
        if len(name_field) > 64:
            errors.append(f"Name field is {len(name_field)} chars (max 64)")
        if any(w in name_field.lower() for w in RESERVED_WORDS):
            errors.append(f"Name field contains reserved word (claude/anthropic)")
        if '<' in name_field or '>' in name_field:
            errors.append("Name field contains XML angle brackets")
        if name_field != folder_name:
            errors.append(
                f"Name field '{name_field}' does not match folder name '{folder_name}'"
            )

    return errors


def validate_frontmatter_fields(frontmatter: Dict[str, Any], skill_name: str) -> List[str]:
    """Validate frontmatter field types and values.

    Returns:
        List of validation errors
    """
    errors = []

    # Required fields
    if 'name' not in frontmatter:
        errors.append("Missing required field: name")
    elif not isinstance(frontmatter['name'], str):
        errors.append("Field 'name' must be a string")

    if 'description' not in frontmatter:
        errors.append("Missing required field: description")
    elif not isinstance(frontmatter['description'], str):
        errors.append("Field 'description' must be a string")

    # Optional fields with type validation
    if 'user-invocable' in frontmatter:
        if not isinstance(frontmatter['user-invocable'], bool):
            errors.append("Field 'user-invocable' must be a boolean")

    if 'model' in frontmatter:
        valid_models = ['opus', 'sonnet', 'haiku']
        if frontmatter['model'] not in valid_models:
            errors.append(f"Invalid model: {frontmatter['model']} (must be opus, sonnet, or haiku)")

    if 'effort' in frontmatter:
        valid_efforts = ['low', 'medium', 'high']
        if frontmatter['effort'] not in valid_efforts:
            errors.append(f"Invalid effort: {frontmatter['effort']} (must be low, medium, or high)")

    if 'context' in frontmatter:
        # Common valid values
        valid_contexts = ['fork', 'inline', 'main']
        if frontmatter['context'] not in valid_contexts:
            # Warn but don't error - may be other valid values
            errors.append(f"Uncommon context value: {frontmatter['context']} (common: fork, inline, main)")

    if 'disable-model-invocation' in frontmatter:
        if not isinstance(frontmatter['disable-model-invocation'], bool):
            errors.append("Field 'disable-model-invocation' must be a boolean")

    return errors


def validate_variables(markdown_content: str) -> List[str]:
    """Check for invalid variable substitution patterns.

    Returns:
        List of invalid variable references
    """
    errors = []

    # Valid variables
    valid_vars = {
        '${CLAUDE_SKILL_DIR}',
        '${CLAUDE_SESSION_ID}',
        '$ARGUMENTS'
    }

    # Find ${...} patterns
    var_pattern = r'\$\{([A-Z_]+)\}'
    for match in re.finditer(var_pattern, markdown_content):
        var = match.group(0)
        if var not in valid_vars:
            errors.append(f"Invalid variable substitution: {var} (valid: $ARGUMENTS, $0-$N, ${{CLAUDE_SKILL_DIR}}, ${{CLAUDE_SESSION_ID}})")

    return errors


def find_file_references(markdown_content: str, skill_dir: Path, repo_root: Path = None) -> Dict[str, List[str]]:
    """Find all file references in SKILL.md and categorize by location.

    Returns:
        Dict with 'found_in_skill', 'found_in_repo', 'not_found' lists
    """
    found_in_skill = []
    found_in_repo = []
    not_found = []

    # Pattern 1: Markdown links [text](file)
    md_link_pattern = r'\[([^\]]+)\]\(([^)]+)\)'
    for match in re.finditer(md_link_pattern, markdown_content):
        file_ref = match.group(2)

        # Skip URLs
        if file_ref.startswith(('http://', 'https://', '#')):
            continue

        # Check existence
        skill_file = skill_dir / file_ref
        if skill_file.exists():
            found_in_skill.append(file_ref)
        elif repo_root and (repo_root / file_ref).exists():
            found_in_repo.append(file_ref)
        else:
            not_found.append(file_ref)

    # Pattern 2: ${CLAUDE_SKILL_DIR}/file references
    skill_dir_pattern = r'\$\{CLAUDE_SKILL_DIR\}/([a-zA-Z0-9_\-/\.]+?)(?:`|\.\s|,\s|;\s|:\s|$)'
    for match in re.finditer(skill_dir_pattern, markdown_content):
        file_ref = match.group(1)

        skill_file = skill_dir / file_ref
        if skill_file.exists():
            found_in_skill.append(file_ref)
        elif repo_root and (repo_root / file_ref).exists():
            found_in_repo.append(file_ref)
        else:
            not_found.append(file_ref)

    return {
        'found_in_skill': sorted(set(found_in_skill)),
        'found_in_repo': sorted(set(found_in_repo)),
        'not_found': sorted(set(not_found))
    }


def find_external_scripts(markdown_content: str, repo_root: Path = None) -> List[Dict[str, str]]:
    """Find references to scripts at repo root that won't be available after marketplace install.

    Returns:
        List of dicts with 'script', 'status', 'location'
    """
    external_scripts = []

    # Pattern: python3/bash/sh/source followed by scripts/ or ../
    script_pattern = r'(?:python3?|bash|sh|source|\.) +([^\s`]+)'

    for match in re.finditer(script_pattern, markdown_content):
        script_path = match.group(1)

        # Only flag if it looks like a repo root reference
        if script_path.startswith(('scripts/', '../', './', '../../')):
            status = 'packaging_issue'
            location = 'repo_root'

            # Check if file exists
            if repo_root and (repo_root / script_path).exists():
                external_scripts.append({
                    'script': script_path,
                    'status': status,
                    'location': location,
                    'message': 'Script exists in repo root but will not be copied during skill installation'
                })
            elif not script_path.startswith('../'):
                # Don't report ../ references if we don't have repo_root to check
                external_scripts.append({
                    'script': script_path,
                    'status': 'unknown',
                    'location': 'unknown',
                    'message': 'Script reference may not be available after marketplace installation'
                })

    return external_scripts


def assess_marketplace_compatibility(skill_dir: Path, frontmatter: Dict[str, Any],
                                     file_refs: Dict[str, List[str]],
                                     external_scripts: List[Dict[str, str]]) -> Dict[str, Any]:
    """Assess whether skill is marketplace-compatible.

    Returns:
        Dict with 'compatible', 'reason', 'recommendations'
    """
    issues = []

    # Check for external scripts
    if external_scripts:
        issues.append(f"{len(external_scripts)} external script(s) at repo root")

    # Check for files at repo root
    if file_refs['found_in_repo']:
        issues.append(f"{len(file_refs['found_in_repo'])} file(s) at repo root")

    # Check for missing files (may be runtime-generated, but flag for review)
    if file_refs['not_found']:
        # Filter out likely runtime files
        runtime_patterns = ['.yaml', '.json', 'tmp/', 'artifacts/']
        non_runtime_missing = [
            f for f in file_refs['not_found']
            if not any(pattern in f for pattern in runtime_patterns)
        ]
        if non_runtime_missing:
            issues.append(f"{len(non_runtime_missing)} referenced file(s) missing")

    compatible = len(issues) == 0

    result = {
        'compatible': compatible,
        'issues': issues,
        'recommendations': []
    }

    if not compatible:
        result['recommendations'] = [
            "To make marketplace-compatible:",
            "1. Copy all referenced scripts into the skill directory",
            "2. Update references to use ${CLAUDE_SKILL_DIR}/script-name",
            "3. Ensure all supporting files are in skill directory",
            "4. Test with: /plugin install from a registry"
        ]

    return result


CHECK_MANIFEST = {
    1: "SKILL.md Structure",
    2: "Naming Conventions",
    3: "Frontmatter Field Validation",
    4: "Description Quality",
    5: "Size / Progressive Disclosure",
    6: "Variable Substitution",
    7: "File Reference Validation",
    8: "External Script Detection",
    9: "Runtime Dependencies",
    10: "context: fork Impact",
    11: "Script Path Portability",
    12: "Shared Artifact Safety",
    13: "Marketplace Compatibility",
}

VALID_VERDICTS = {"PASS", "WARN", "FAIL", "INFO"}


def audit_report(report_path: Path) -> Dict[str, Any]:
    """Audit a skill review report for completeness.

    Checks that every canonical check (1-13) appears as a
    '## Check N: <Name>' heading with a '**Verdict:** <V>' line.
    """
    if not report_path.exists():
        return {"error": f"Report not found: {report_path}", "valid": False}

    content = report_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    found_checks: Dict[int, str] = {}
    checks_without_verdict: List[int] = []

    heading_re = re.compile(r"^## Check (\d+):")
    verdict_re = re.compile(r"\*\*(?:Verdict|Severity):\*\*\s*(PASS|WARN|FAIL|INFO|WARNING)")

    current_check = None
    current_has_verdict = False

    for line in lines:
        hm = heading_re.match(line)
        if hm:
            if current_check is not None and not current_has_verdict:
                checks_without_verdict.append(current_check)
            current_check = int(hm.group(1))
            current_has_verdict = False
            found_checks[current_check] = line
        elif current_check is not None:
            vm = verdict_re.search(line)
            if vm:
                current_has_verdict = True

    if current_check is not None and not current_has_verdict:
        checks_without_verdict.append(current_check)

    found_ids = sorted(found_checks.keys())
    missing_ids = sorted(set(CHECK_MANIFEST.keys()) - set(found_ids))

    result = {
        "total_checks": len(CHECK_MANIFEST),
        "found_checks": found_ids,
        "missing_checks": missing_ids,
        "checks_without_verdict": checks_without_verdict,
        "valid": len(missing_ids) == 0 and len(checks_without_verdict) == 0,
    }

    if missing_ids:
        result["missing_details"] = {
            n: CHECK_MANIFEST[n] for n in missing_ids
        }

    return result


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: validate.py <skill-directory>")
        print("       validate.py --audit-report <report.md>")
        sys.exit(1)

    if sys.argv[1] == "--audit-report":
        if len(sys.argv) < 3:
            print("Usage: validate.py --audit-report <report.md>")
            sys.exit(1)
        report_path = Path(sys.argv[2]).resolve()
        result = audit_report(report_path)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["valid"] else 1)

    skill_dir = Path(sys.argv[1]).resolve()
    skill_md = skill_dir / "SKILL.md"

    # Attempt to find repo root (go up until we find .git or hit /)
    repo_root = skill_dir
    while repo_root.parent != repo_root:
        if (repo_root / '.git').exists():
            break
        repo_root = repo_root.parent
    if not (repo_root / '.git').exists():
        repo_root = None

    # Parse frontmatter
    frontmatter, markdown_content, parse_errors = parse_frontmatter(skill_md)

    # Run validations
    results = {
        'skill_dir': str(skill_dir),
        'skill_name': skill_dir.name,
        'parse_errors': parse_errors,
        'frontmatter_valid': len(parse_errors) == 0,
        'frontmatter': frontmatter,
        'naming_errors': [],
        'field_errors': [],
        'variable_errors': [],
        'file_references': {},
        'external_scripts': [],
        'marketplace_compatibility': {}
    }

    results['naming_errors'] = validate_naming(skill_dir.name, frontmatter or {})

    if frontmatter:
        results['field_errors'] = validate_frontmatter_fields(frontmatter, skill_dir.name)

    if markdown_content:
        results['variable_errors'] = validate_variables(markdown_content)
        results['file_references'] = find_file_references(markdown_content, skill_dir, repo_root)
        results['external_scripts'] = find_external_scripts(markdown_content, repo_root)
    else:
        # Provide empty structure if no content
        results['file_references'] = {'found_in_skill': [], 'found_in_repo': [], 'not_found': []}

    # Assess marketplace compatibility
    results['marketplace_compatibility'] = assess_marketplace_compatibility(
        skill_dir, frontmatter, results['file_references'], results['external_scripts']
    )

    # Categorize by severity
    critical_errors = []
    warnings = []

    # CRITICAL: Missing frontmatter or required fields
    if not results['frontmatter_valid']:
        critical_errors.extend(results['parse_errors'])

    if results['frontmatter_valid']:
        # Check for missing required fields
        if 'name' not in frontmatter:
            critical_errors.append("Missing required field: name")
        if 'description' not in frontmatter:
            critical_errors.append("Missing required field: description")

        # Other field errors are warnings
        warnings.extend(results['field_errors'])

    # Naming errors are warnings
    warnings.extend(results['naming_errors'])

    # Variable errors are warnings
    warnings.extend(results['variable_errors'])

    # External scripts are warnings
    warnings.extend([s['message'] for s in results['external_scripts']])

    # Add severity summary to results
    results['severity'] = {
        'critical': len(critical_errors),
        'warnings': len(warnings),
        'critical_issues': critical_errors,
        'warning_issues': warnings,
        'status': 'FAILED' if critical_errors else ('WARNED' if warnings else 'PASSED')
    }

    # Print JSON result
    print(json.dumps(results, indent=2))

    # Exit with error code based on severity
    # Exit 2 for critical errors, 1 for warnings, 0 for pass
    if critical_errors:
        sys.exit(2)
    elif warnings:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
