# Skill Review

Comprehensive validation tool for Claude Code skills. Ensures skills are well-formed, self-contained, and marketplace-compatible.

## What It Does

Validates Claude Code skills against best practices and packaging requirements:

- ✅ **Frontmatter validation** - Checks YAML structure, required fields, field types
- ✅ **Variable validation** - Detects invalid variable substitution patterns
- ✅ **File reference checking** - Finds referenced files and categorizes by location
- ✅ **External dependency detection** - Identifies repo root scripts that break marketplace install
- ✅ **Marketplace compatibility assessment** - Determines if skill can be distributed via `/plugin install`

## Usage

```bash
/skill-review [skill-directory]
```

**Examples:**

```bash
# Review current directory
/skill-review

# Review specific skill
/skill-review .claude/skills/assess-rfe

# Review skill in another repo
/skill-review ../rfe-creator/.claude/skills/rfe.create
```

## What Gets Validated

### 1. SKILL.md Structure
- File exists
- YAML frontmatter present (starts with `---`)
- Valid YAML syntax
- No duplicate frontmatter delimiters

### 2. Frontmatter Fields

**Required:**
- `name` (string) - Skill identifier
- `description` (string) - What the skill does

**Optional (with validation):**
- `user-invocable` (boolean) - Can user invoke with `/skill-name`
- `allowed-tools` (string or array) - Permitted Claude tools
- `model` (string) - Must be `opus`, `sonnet`, or `haiku`
- `effort` (string) - Must be `low`, `medium`, or `high`
- `context` (string) - Execution context (e.g., `fork`)
- `disable-model-invocation` (boolean) - For non-AI skills

### 3. Variable Substitution

**Valid variables:**
- `$ARGUMENTS` - All arguments as single string
- `$0`, `$1`, ..., `$9` - Positional arguments
- `${CLAUDE_SKILL_DIR}` - Absolute path to skill directory
- `${CLAUDE_SESSION_ID}` - Unique session ID

**Common mistakes:**
- ❌ `${N}` - Generic placeholder (not a real variable)
- ❌ `${SKILL_DIR}` - Missing `CLAUDE_` prefix
- ❌ `$ARG` - Non-standard name

### 4. File References

Detects:
- Markdown links: `[text](file.md)`
- Skill directory refs: `${CLAUDE_SKILL_DIR}/template.md`

Categorizes:
- ✅ **Found in skill directory** - Good
- ⚠️ **Found in repo root** - Packaging issue
- ❌ **Not found** - Missing file

### 5. External Scripts

Identifies scripts that won't be available after marketplace install:
- `python3 scripts/analyze.py`
- `bash scripts/build.sh`
- `source scripts/helpers.sh`

**Impact:** Breaks `/plugin install` usage pattern.

### 6. Marketplace Compatibility

Determines if skill can be distributed standalone:

**Self-contained (✅ compatible):**
- All files in skill directory
- No `scripts/` references
- No repo root dependencies

**Repository-dependent (⚠️ incompatible):**
- References `scripts/` directory
- Shared utilities at repo root
- Requires full repo checkout

## Output Format

```
============================================================
SKILL REVIEW: skill-name
============================================================

## Validation Status

❌ FAILED - Critical issues found

This skill is BROKEN and will not function properly.
Critical issues MUST be fixed before the skill can be used.

## Issue Summary

Critical (blocking): 1
Warnings (non-blocking): 2

## Details

❌ CRITICAL: No frontmatter found (must start with ---)
⚠️ External script dependency: scripts/helper.py
⚠️ File reference at repo root: templates/config.yaml

File References:
  ✅ template.md (in skill dir)
  ⚠️ scripts/helper.py (repo root - packaging issue)
  ❌ missing.yaml (not found)

Marketplace Compatibility: ⚠️ INCOMPATIBLE
  - 1 external script(s) at repo root
  - 1 file(s) at repo root

Recommendations:
  CRITICAL FIXES REQUIRED:
  1. Add YAML frontmatter to SKILL.md:
     ---
     name: skill-name
     description: What this skill does
     user-invocable: true
     allowed-tools: "Read, Write, Bash"
     ---
  
  Additional improvements:
  2. Copy scripts/helper.py to skill directory
  3. Update references to use ${CLAUDE_SKILL_DIR}/helper.py
  4. Move templates/config.yaml into skill directory

============================================================
```

### Severity Levels

**CRITICAL (❌ FAILED)** - Skill is completely broken:
- Missing frontmatter
- Missing required field: `name`
- Missing required field: `description`
- Invalid YAML syntax

**WARNING (⚠️ PASSED WITH WARNINGS)** - Skill works but has issues:
- External script dependencies
- Files at repo root (packaging issues)
- Invalid variable references
- Missing optional fields

**PASSED (✅)** - No issues found

## Files

- **SKILL.md** - Skill definition and instructions
- **scripts/validate.py** - Python validation script (requires PyYAML)
- **README.md** - This file

## Dependencies

- Python 3.x
- PyYAML (`pip install pyyaml`)

The skill will check for PyYAML and provide install instructions if missing.

## Testing

Tested against 38 skills from 5 plugins in opendatahub-io/skills-registry:
- assess-rfe (2 skills) - ✅ All marketplace-compatible
- rfe-creator (16 skills) - ⚠️ 35 packaging issues found
- test-plan (6 skills) - ⚠️ 10 packaging issues found
- rhoai-security-reviewer (2 skills) - ⚠️ 1 packaging issue found
- quality-tooling (3 skills) - ❌ Missing frontmatter

See: `SKILL-BUGS-2026-04-15.md` for full test report.

## Known Limitations

1. **Runtime file detection** may flag expected runtime files (e.g., `tmp/*.yaml`, `artifacts/*.md`) as missing
2. **Implicit references** in prose ("Read the config file...") not detected
3. **Dynamic file paths** constructed at runtime not validated
4. **Repo root detection** requires `.git` directory

## See Also

- [Agent Skills Specification](https://agentskills.io)
- [Claude Code Documentation](https://claude.ai/code)
- [Skills Registry](https://github.com/opendatahub-io/skills-registry)
- Test harness: `2026_04_15_claude_skill_install_test/`
