---
name: skill-review
description: >-
  Review and validate Claude Code skills for completeness, packaging correctness,
  and marketplace compatibility. Use when reviewing a skill, checking skill packaging,
  validating SKILL.md before publishing, or running /skill-review. Checks frontmatter,
  file references, variable substitution, and external dependencies.
user-invocable: true
allowed-tools: Read, Glob, Grep, Bash
---

# Skill Review

Comprehensive validation of Claude Code skills to ensure they are well-formed, self-contained, and marketplace-compatible.

## Usage

```
/skill-review [skill-directory]
```

If no directory specified, reviews the current working directory as a skill.

## What This Skill Checks

This skill performs 13 validation checks. See [references/checks.md](references/checks.md) for detailed descriptions of each check.

1. **SKILL.md Structure** — file exists, frontmatter present, valid YAML, required fields, no README.md
2. **Naming Conventions** — kebab-case folder name, name field rules, no reserved words
3. **Frontmatter Fields** — type validation for all standard fields (name, description, model, effort, context, etc.)
4. **Description Quality** — trigger phrases, specificity, actionability
5. **Size / Progressive Disclosure** — body under 500 lines, split to `references/` if needed
6. **Variable Substitution** — only `$ARGUMENTS`, `$0`-`$9`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_SESSION_ID}`
7. **File References** — markdown links and `${CLAUDE_SKILL_DIR}/` refs resolve to real files
8. **External Script Detection** — repo-root scripts that break marketplace install
9. **Runtime Dependencies** — files the skill reads/executes at runtime
10. **`context: fork` Impact** — streaming suppression in CI/pipeline contexts
11. **Script Path Portability** — refs without `${CLAUDE_SKILL_DIR}` fail after marketplace install
12. **Shared Artifact Safety** — broad globs and shared index writes unsafe under concurrency
13. **Marketplace Compatibility** — self-contained vs. requires full repo checkout

## Python Validation Script

This skill includes a Python script for automated validation:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/validate.py <skill-directory>
```

The script returns JSON output with validation results and exits with:
- `0` if no errors found
- `1` if validation errors detected

You can use this script directly for quick validation, or follow the step-by-step bash instructions below for detailed interactive feedback.

## Instructions

When the user invokes this skill:

1. **Determine skill directory**
   - If user provided path: `skill_dir = $ARGUMENTS`
   - If no arguments: `skill_dir = $(pwd)`
   - Expand to absolute path: `skill_dir=$(cd "$skill_dir" && pwd)`

2. **Check SKILL.md exists**
   ```bash
   if [ ! -f "$skill_dir/SKILL.md" ]; then
       echo "❌ ERROR: SKILL.md not found in $skill_dir"
       exit 1
   fi
   ```

3. **Parse and validate frontmatter**
   
   Use Read tool to read `$skill_dir/SKILL.md`.
   
   Check for frontmatter:
   ```python
   content = # content from Read
   if not content.startswith('---'):
       print("❌ ERROR: No frontmatter found (must start with ---)")
       issues.append("missing_frontmatter")
   ```
   
   Extract frontmatter (lines between first `---` and second `---`):
   ```python
   lines = content.split('\n')
   if lines[0] == '---':
       fm_end = lines[1:].index('---') + 1
       fm_text = '\n'.join(lines[1:fm_end])
       markdown_content = '\n'.join(lines[fm_end+1:])
   ```
   
   Parse YAML (in bash):
   ```bash
   # Extract frontmatter
   awk '/^---$/{f=!f;next}f' "$skill_dir/SKILL.md" > /tmp/frontmatter.yaml
   
   # Validate required fields
   if ! grep -q '^name:' /tmp/frontmatter.yaml; then
       echo "❌ Missing required field: name"
   fi
   if ! grep -q '^description:' /tmp/frontmatter.yaml; then
       echo "❌ Missing required field: description"
   fi
   ```

4. **Validate frontmatter field types**
   
   Extract and check each field:
   ```bash
   # Check model field if present
   model=$(grep '^model:' /tmp/frontmatter.yaml | awk '{print $2}' | tr -d '"' | tr -d "'")
   if [ -n "$model" ] && [[ ! "$model" =~ ^(opus|sonnet|haiku)$ ]]; then
       echo "⚠️ Invalid model: $model (must be opus, sonnet, or haiku)"
   fi
   
   # Check effort field if present
   effort=$(grep '^effort:' /tmp/frontmatter.yaml | awk '{print $2}' | tr -d '"' | tr -d "'")
   if [ -n "$effort" ] && [[ ! "$effort" =~ ^(low|medium|high)$ ]]; then
       echo "⚠️ Invalid effort: $effort (must be low, medium, or high)"
   fi
   ```

5. **Validate variable substitution**
   
   Use Grep to find variable references:
   ```bash
   # Find all ${...} patterns
   grep -oE '\$\{[A-Z_]+\}' "$skill_dir/SKILL.md" | sort -u > /tmp/variables.txt
   
   # Check each variable
   while read var; do
       case "$var" in
           '${CLAUDE_SKILL_DIR}'|'${CLAUDE_SESSION_ID}')
               # Valid
               ;;
           *)
               echo "⚠️ Invalid variable: $var"
               echo "   Valid: \$ARGUMENTS, \$0-\$9, \${CLAUDE_SKILL_DIR}, \${CLAUDE_SESSION_ID}"
               ;;
       esac
   done < /tmp/variables.txt
   ```

6. **Find file references**
   
   Detect markdown links and ${CLAUDE_SKILL_DIR} references:
   ```bash
   # Markdown links: [text](file)
   grep -oE '\[([^\]]+)\]\(([^)]+)\)' "$skill_dir/SKILL.md" | \
       grep -oE '\(([^)]+)\)' | tr -d '()' > /tmp/md_refs.txt
   
   # ${CLAUDE_SKILL_DIR}/file references
   grep -oE '\$\{CLAUDE_SKILL_DIR\}/[a-zA-Z0-9_\-/\.]+' "$skill_dir/SKILL.md" | \
       sed 's/\${CLAUDE_SKILL_DIR}\///' > /tmp/skill_refs.txt
   
   # Combine and check existence
   cat /tmp/md_refs.txt /tmp/skill_refs.txt | sort -u | while read file; do
       # Skip URLs
       if [[ "$file" =~ ^https?:// ]]; then
           continue
       fi
       
       # Check in skill directory
       if [ -f "$skill_dir/$file" ]; then
           echo "✅ Found in skill dir: $file"
       # Check in repo root (packaging issue)
       elif [ -f "$file" ]; then
           echo "⚠️ Found in repo root: $file (packaging issue)"
       else
           echo "❌ Not found: $file"
       fi
   done
   ```

7. **Check `context: fork` usage**

   ```bash
   if grep -q '^context: *fork' /tmp/frontmatter.yaml; then
       echo "⚠️ context:fork detected — streaming output will be suppressed"
       echo "   --output-format stream-json and SDK receive_response() will"
       echo "   produce zero events until the skill completes."
       echo "   Remove context:fork unless this skill orchestrates background agents."
   fi
   ```

8. **Check script path portability**

   Find script references that won't resolve after marketplace install
   (where cwd is the invoking project, not the plugin directory):
   ```bash
   # Scripts WITHOUT ${CLAUDE_SKILL_DIR} — will break after install
   grep -E '(python3?|bash|sh|node) +[a-zA-Z]' "$skill_dir/SKILL.md" | \
       grep -v 'CLAUDE_SKILL_DIR' | \
       while read line; do
           echo "⚠️ Script reference without \${CLAUDE_SKILL_DIR}: $line"
           echo "   Will fail after marketplace install (cwd is not the plugin dir)"
       done

   # External script dependencies at repo root
   grep -E '(python3?|bash|sh|source|\.) (scripts?|\.\.)/[a-zA-Z0-9_\-/\.]+' "$skill_dir/SKILL.md" | \
       while read line; do
           script=$(echo "$line" | grep -oE '(scripts?|\.\.)/[a-zA-Z0-9_\-/\.]+')
           if [ -f "$script" ]; then
               echo "⚠️ External script dependency: $script"
               echo "   This will NOT be available after marketplace installation"
           fi
       done
   ```

9. **Check shared artifact directory safety**

   Detect patterns that are unsafe for concurrent per-ticket jobs on a
   shared filesystem:
   ```bash
   # Broad glob patterns that process all files
   grep -E '(ls|for.*in|glob) .*\*\.md' "$skill_dir/SKILL.md" | \
       grep -v 'RHAISTRAT-\*\|RHAIRFE-\*' | \
       while read line; do
           echo "⚠️ Broad glob pattern: $line"
           echo "   Will process ALL files in directory — unsafe for concurrent per-ticket jobs"
           echo "   Consider using a targeted prefix (e.g., RHAISTRAT-*.md)"
       done

   # Shared index file writes (read-then-rewrite pattern)
   grep -E '(Write|write|>).*tickets\.(md|yaml|json)' "$skill_dir/SKILL.md" | \
       while read line; do
           echo "⚠️ Shared index file write: $line"
           echo "   Read-then-rewrite will clobber under concurrent jobs"
           echo "   Consider per-ticket files or symlinks instead"
       done
   ```

10. **Analyze runtime dependencies**
   
   Detect file operations and script executions:
   ```bash
   # Shell file operations in code blocks
   awk '/```(bash|sh|!)/,/```/' "$skill_dir/SKILL.md" | \
       grep -E '(cat|head|tail|source|\.|>|>>).*[a-zA-Z0-9_\-]+\.(md|yaml|json|txt|sh|py)' | \
       grep -oE '[a-zA-Z0-9_\-/\.]+\.(md|yaml|json|txt|sh|py|csv|xml)' | \
       sort -u > /tmp/runtime_files.txt
   
   # Categorize each file
   echo ""
   echo "## Runtime Dependencies"
   cat /tmp/runtime_files.txt | while read file; do
       if [ -f "$skill_dir/$file" ]; then
           echo "✅ Available: $file (in skill dir)"
       elif [ -f "$file" ]; then
           echo "⚠️ Packaging issue: $file (at repo root)"
       else
           # May be created at runtime
           echo "ℹ️ Not packaged: $file (may be created at runtime)"
       fi
   done
   ```

11. **Determine marketplace compatibility**
   
   Synthesize all findings:
   ```bash
   echo ""
   echo "## Marketplace Compatibility Assessment"
   echo ""
   
   external_scripts=$(grep -c "External script dependency" /tmp/report.txt || echo 0)
   packaging_issues=$(grep -c "packaging issue" /tmp/report.txt || echo 0)
   
   if [ $external_scripts -eq 0 ] && [ $packaging_issues -eq 0 ]; then
       echo "✅ **MARKETPLACE COMPATIBLE**"
       echo ""
       echo "This skill is self-contained and can be installed via:"
       echo "  /plugin install plugin-name@registry-name"
       echo ""
       echo "All dependencies are bundled in the skill directory."
   else
       echo "⚠️ **REQUIRES FULL REPOSITORY CHECKOUT**"
       echo ""
       echo "This skill has external dependencies and cannot be installed via marketplace."
       echo ""
       echo "Issues found:"
       echo "  - External script dependencies: $external_scripts"
       echo "  - Files at repo root: $packaging_issues"
       echo ""
       echo "Expected usage pattern:"
       echo "  1. Clone full repository"
       echo "  2. Skills discovered from .claude/skills/ directory"
       echo "  3. All repo scripts available during execution"
       echo ""
       echo "To make marketplace-compatible:"
       echo "  1. Copy all scripts from scripts/ into skill directory"
       echo "  2. Update references to use \${CLAUDE_SKILL_DIR}/script-name"
       echo "  3. Bundle requirements.txt if needed"
   fi
   ```

12. **Generate summary report**
    
    Create a comprehensive summary with proper severity assessment:
    ```bash
    echo ""
    echo "============================================================"
    echo "SKILL REVIEW SUMMARY"
    echo "============================================================"
    echo ""
    
    skill_name=$(grep '^name:' /tmp/frontmatter.yaml 2>/dev/null | awk '{print $2}' | tr -d '"' | tr -d "'")
    if [ -z "$skill_name" ]; then
        skill_name="$(basename "$skill_dir")"
    fi
    echo "Skill: $skill_name"
    echo "Location: $skill_dir"
    echo ""
    
    # Categorize issues by severity
    critical=0
    warnings=0
    
    # CRITICAL: Missing frontmatter or required fields
    if ! grep -q '^name:' /tmp/frontmatter.yaml 2>/dev/null; then
        critical=$((critical + 1))
    fi
    if ! grep -q '^description:' /tmp/frontmatter.yaml 2>/dev/null; then
        critical=$((critical + 1))
    fi
    if [ ! -s /tmp/frontmatter.yaml ]; then
        critical=$((critical + 1))
    fi
    
    # Count other issues
    warnings=$(grep -c "^⚠️" /tmp/report.txt 2>/dev/null || echo 0)
    
    # Overall status
    echo "## Validation Status"
    echo ""
    if [ $critical -gt 0 ]; then
        echo "❌ FAILED - Critical issues found"
        echo ""
        echo "This skill is BROKEN and will not function properly."
        echo "Critical issues MUST be fixed before the skill can be used."
    elif [ $warnings -gt 0 ]; then
        echo "⚠️ PASSED WITH WARNINGS"
        echo ""
        echo "Skill is functional but has issues that should be addressed."
    else
        echo "✅ PASSED - No issues found"
        echo ""
        echo "This skill passes all validation checks."
    fi
    
    echo ""
    echo "## Issue Summary"
    echo ""
    echo "Critical (blocking): $critical"
    echo "Warnings (non-blocking): $warnings"
    
    if [ $critical -gt 0 ] || [ $warnings -gt 0 ]; then
        echo ""
        echo "Review the detailed output above for specifics."
    fi
    
    echo ""
    echo "============================================================"
    ```

13. **Categorize issues by severity**
    
    **CRITICAL (skill is BROKEN and will not work):**
    - Missing frontmatter entirely
    - Missing required field: `name`
    - Missing required field: `description`
    - Invalid YAML syntax in frontmatter
    
    **WARNING (skill works but has issues):**
    - External script dependencies (packaging issue)
    - Files at repo root instead of skill directory
    - Invalid variable substitution patterns
    - Missing optional fields
    - Invalid field values (model, effort, context)
    - `context: fork` suppresses streaming output in CI/pipeline contexts
    - Script references without `${CLAUDE_SKILL_DIR}` will break after marketplace install
    - Broad glob patterns process all files in shared artifact directories
    - Shared index file writes race under concurrent jobs
    
    **INFO (recommendations):**
    - Marketplace compatibility suggestions
    - Best practices for file organization
    - Optional field suggestions
    - Use symlinks + targeted globs for shared artifact directories
    - Use `${CLAUDE_SKILL_DIR}` for all script references

14. **Provide actionable recommendations**
    
    Based on findings, suggest next steps with priority:
    
    **If CRITICAL issues found:**
    ```
    ❌ CRITICAL: This skill is BROKEN
    
    Required fixes (skill will not work until these are resolved):
    1. Add YAML frontmatter to SKILL.md:
       ---
       name: skill-name
       description: What this skill does
       user-invocable: true
       allowed-tools: "Read, Write, Bash"
       ---
    
    2. Ensure frontmatter starts at line 1 with ---
    3. Ensure second --- delimiter is present
    4. Verify YAML syntax is valid
    ```
    
    **If WARNING issues found:**
    - If external scripts → Show how to vendor into skill directory
    - If invalid variables → List valid variable names
    - If missing files → Identify which files to create or move
    - If marketplace incompatible but claimed → Recommend removing marketplace claim or fixing packaging
    
    **Important:** Do NOT say "good news: marketplace compatible" if there are critical frontmatter issues. Missing frontmatter means the skill is completely non-functional, regardless of file packaging.

## Examples

### Example 1: Valid, Self-Contained Skill
```
/skill-review .claude/skills/assess-rfe

✅ Frontmatter valid
✅ All required fields present
✅ No invalid variables
✅ All file references found in skill directory
✅ No external script dependencies
✅ MARKETPLACE COMPATIBLE
```

### Example 2: Skill with Packaging Issues
```
/skill-review .claude/skills/rfe.create

✅ Frontmatter valid
❌ Invalid variable: ${N}
⚠️ External script dependency: scripts/frontmatter.py
⚠️ External script dependency: scripts/next_rfe_id.py
⚠️ REQUIRES FULL REPOSITORY CHECKOUT

Recommendations:
1. Replace ${N} with $1, $2, etc. for positional args
2. Copy scripts/frontmatter.py to .claude/skills/rfe.create/
3. Update references to use ${CLAUDE_SKILL_DIR}/frontmatter.py
```

### Example 3: Missing Frontmatter
```
/skill-review .claude/skills/quality-repo-analysis

❌ No frontmatter found (must start with ---)

Add frontmatter to SKILL.md:
---
name: quality-repo-analysis
description: Analyze repository quality metrics
user-invocable: true
allowed-tools: "Read, Grep, Bash"
---
```

### Example 4: CI/Pipeline Safety Issues
```
/skill-review .claude/skills/strategy-refine

✅ Frontmatter valid
⚠️ context:fork detected — streaming output will be suppressed
⚠️ Script reference without ${CLAUDE_SKILL_DIR}: python3 scripts/frontmatter.py
⚠️ Script reference without ${CLAUDE_SKILL_DIR}: python3 scripts/fetch_issue.py
⚠️ Broad glob pattern: for f in artifacts/strat-tasks/*.md
⚠️ REQUIRES FULL REPOSITORY CHECKOUT

Recommendations:
1. Remove context:fork — this skill does not orchestrate background agents
2. Use ${CLAUDE_SKILL_DIR}/scripts/frontmatter.py for marketplace portability
3. Change glob from *.md to RHAISTRAT-*.md for per-ticket safety
4. Add symlink-based RFE→STRAT lookup in strategy-create for O(1) resolution
```

## Notes

- This skill encodes best practices from testing 38 skills across 5 plugins in the opendatahub-io/skills-registry
- Validation rules based on Claude Code 2.1.109 behavior and Agent Skills specification
- Runtime dependency detection may have false positives for generic words (filtered in analysis)
- Marketplace compatibility is the key differentiator for skill distribution strategies
- `context: fork`, script path portability, and shared artifact safety checks are based on real issues found running ederign/strat-creator skills as K8s pipeline jobs (see `bugs/eder-strat-skills-script.txt` and `bugs/eder-strat-skills-tracing.md`)

## See Also

- Agent Skills Specification: https://agentskills.io
- Claude Code Documentation
- Skills Registry: https://github.com/opendatahub-io/skills-registry
