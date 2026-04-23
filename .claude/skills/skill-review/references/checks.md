# Skill Review — Detailed Check Reference

## Table of Contents

1. [SKILL.md Structure](#1-skillmd-structure)
2. [Naming Conventions](#2-naming-conventions)
3. [Frontmatter Field Validation](#3-frontmatter-field-validation)
4. [Description Quality](#4-description-quality)
5. [SKILL.md Size and Progressive Disclosure](#5-skillmd-size-and-progressive-disclosure)
6. [Variable Substitution Validation](#6-variable-substitution-validation)
7. [File Reference Validation](#7-file-reference-validation)
8. [External Script Detection](#8-external-script-detection)
9. [Runtime Dependency Analysis](#9-runtime-dependency-analysis)
10. [context: fork Impact Assessment](#10-context-fork-impact-assessment)
11. [Script Path Portability](#11-script-path-portability-marketplace-install)
12. [Shared Artifact Directory Safety](#12-shared-artifact-directory-safety)
13. [Marketplace Compatibility](#13-marketplace-compatibility)

---

### 1. SKILL.md Structure
- ✅ File exists (must be exactly `SKILL.md`, case-sensitive — not SKILL.MD, skill.md, etc.)
- ✅ YAML frontmatter present (must start with `---`)
- ✅ Frontmatter is valid YAML
- ✅ Required fields present: `name`, `description`
- ✅ No `README.md` in skill directory (all documentation belongs in SKILL.md or `references/`)

### 2. Naming Conventions
**Skill folder name:**
- ✅ kebab-case only: `notion-project-setup`
- ❌ No spaces: `Notion Project Setup`
- ❌ No underscores: `notion_project_setup`
- ❌ No capitals: `NotionProjectSetup`
- ❌ No dots: `strategy.refine` (use `strategy-refine`)

**`name` field in frontmatter:**
- Maximum 64 characters
- Must contain only lowercase letters, numbers, and hyphens
- Must not contain "claude" or "anthropic" (reserved by Anthropic)
- Must not contain XML tags
- Should match the folder name

### 3. Frontmatter Field Validation
- **name** (string, required): Skill name in kebab-case, must match directory name
- **description** (string, required): Must include BOTH what the skill does AND when to use it (trigger conditions). Under 1024 characters. No XML angle brackets (`<` or `>`). Include specific tasks/phrases users might say. Mention relevant file types if applicable.
- **user-invocable** (boolean, optional): Whether user can invoke with `/skill-name`
- **allowed-tools** (string or array, optional): Tools the skill is allowed to use
- **model** (string, optional): Must be "opus", "sonnet", or "haiku"
- **effort** (string, optional): Must be "low", "medium", or "high"
- **context** (string, optional): Must be "fork" or other valid context type
- **disable-model-invocation** (boolean, optional): For non-AI skills
- **compatibility** (string, optional): 1-500 characters, environment requirements
- **license** (string, optional): e.g., MIT, Apache-2.0
- **metadata** (object, optional): Custom key-value pairs (author, version, mcp-server)

**Security restrictions in frontmatter:**
- ❌ No XML angle brackets (`<` or `>`) — frontmatter appears in system prompt, could inject content
- ❌ No "claude" or "anthropic" in skill name — reserved names

### 4. Description Quality
The description is the most important field — it determines when Claude loads the skill.

**Structure:** `[What it does] + [When to use it] + [Key capabilities]`

**Good descriptions:**
- Include trigger phrases users would actually say
- Mention relevant file types if applicable
- Are specific and actionable

**Bad descriptions:**
- Too vague: "Helps with projects"
- Missing triggers: "Creates sophisticated multi-page documentation systems"
- Too technical: "Implements the Project entity model with hierarchical relationships"

### 5. SKILL.md Size and Progressive Disclosure
- ⚠️ SKILL.md body should be under 500 lines for optimal performance
- If content exceeds 500 lines, split into separate files using progressive disclosure
- Move detailed documentation to `references/` directory and link to it
- Keep references one level deep from SKILL.md (no nested references)
- For reference files over 100 lines, include a table of contents at the top
- Skills use a three-level progressive disclosure system:
  1. **Frontmatter** — always loaded, tells Claude when to use the skill
  2. **SKILL.md body** — loaded when skill is relevant
  3. **Linked files** (references/, scripts/) — loaded on demand

### 6. Variable Substitution Validation
Checks for invalid variable references in SKILL.md content.

**Valid variables:**
- `$ARGUMENTS` - All arguments as a single string
- `$0`, `$1`, `$2`, ..., `$9` - Individual positional arguments
- `${CLAUDE_SKILL_DIR}` - Absolute path to the skill directory
- `${CLAUDE_SESSION_ID}` - Unique session identifier

**Invalid examples:**
- `${N}` - Generic placeholder, not a real variable
- `${SKILL_DIR}` - Missing CLAUDE_ prefix
- `$ARG` - Non-standard variable name

### 7. File Reference Validation
Detects files referenced in SKILL.md and checks if they exist.

**Explicit references:**
- Markdown links: `[text](file.md)`
- Skill directory references: `${CLAUDE_SKILL_DIR}/file.txt`

**Categorizes findings:**
- ✅ **Found in skill directory** - Correctly packaged
- ⚠️ **Found in repo root** - Packaging issue (won't work after marketplace install)
- ❌ **Not found** - Missing file (will fail at runtime)

### 8. External Script Detection
Identifies scripts referenced at repository root that won't be available after marketplace installation.

**Common patterns:**
- `python3 scripts/script.py`
- `bash scripts/script.sh`
- `source scripts/helper.sh`

**Impact:** Skills claiming marketplace install support (`/plugin install`) must be self-contained.

### 9. Runtime Dependency Analysis
Analyzes what files the skill will attempt to access during execution.

**Detection patterns:**
- Shell file operations: `cat file.txt`, `head file.yaml`, `source config.sh`
- Python/bash script execution: `python3 analyze.py`, `bash build.sh`
- Explicit references: `${CLAUDE_SKILL_DIR}/template.md`
- Data files: `.json`, `.yaml`, `.csv`, `.xml` extensions

**Output:** Categorizes dependencies by location (skill dir, repo root, missing).

### 10. `context: fork` Impact Assessment
Checks if the skill uses `context: fork` in frontmatter and warns about its implications.

**What `context: fork` does:**
- Creates an isolated sub-agent that runs the skill in a forked context
- All intermediate messages (thinking, tool use, streaming) are consumed locally
- Only the final result text is returned to the parent agent
- `--output-format stream-json` and SDK `receive_response()` produce zero output until completion

**When to flag:**
- ⚠️ Any skill with `context: fork` — warn that streaming/logging will be suppressed in CI/pipeline contexts
- ❌ Skills that don't orchestrate background agents but use `context: fork` — likely unnecessary and should be removed
- ✅ Skills that orchestrate multiple sub-agents (e.g., strategy-review launching 4 independent reviewers) — `context: fork` may be intentional

**Detection:**
```bash
if grep -q '^context: *fork' /tmp/frontmatter.yaml; then
    echo "⚠️ context:fork detected — streaming output will be suppressed"
    echo "   This means --output-format stream-json and SDK receive_response()"
    echo "   will produce zero events until the skill completes."
    echo "   Remove context:fork unless this skill orchestrates background agents."
fi
```

### 11. Script Path Portability (Marketplace Install)
Validates that script references will resolve correctly after marketplace installation.

**The problem:** When a skill is installed via `claude plugin install`, the entire repo is cloned to:
```
~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/
```
But the agent's `cwd` remains the invoking project (e.g., `/app`), not the plugin directory. Scripts referenced as `python3 scripts/foo.py` assume cwd is the repo root and will fail.

**What to check:**
- Scripts referenced without `${CLAUDE_SKILL_DIR}` prefix — will break after install
- Scripts at repo root (`scripts/`, `./scripts/`) — exist in the plugin clone but cwd won't find them
- Scripts using relative paths (`../../scripts/`) — fragile, depends on install location

**Correct patterns:**
- `python3 ${CLAUDE_SKILL_DIR}/scripts/foo.py` — works regardless of cwd
- `bash ${CLAUDE_SKILL_DIR}/../../scripts/foo.py` — works but fragile; better to vendor scripts into skill dir
- Scripts symlinked into skill directory — works if symlink targets are also in the repo

**Detection:**
```bash
# Find script references NOT using ${CLAUDE_SKILL_DIR}
grep -E '(python3?|bash|sh|node) +[a-zA-Z]' "$skill_dir/SKILL.md" | \
    grep -v 'CLAUDE_SKILL_DIR' | \
    while read line; do
        echo "⚠️ Script reference without \${CLAUDE_SKILL_DIR}: $line"
        echo "   Will fail after marketplace install (cwd is not the plugin dir)"
    done
```

### 12. Shared Artifact Directory Safety
Analyzes whether a skill is safe to run concurrently on a shared filesystem.

**The problem:** Skills that glob an entire directory (e.g., `artifacts/strat-tasks/*.md`) and process all files will:
- Waste tokens reading/processing unrelated artifacts in per-ticket job mode
- Race with concurrent jobs writing to the same files
- Rely on LLM reasoning to filter to the right artifact, which is non-deterministic

**What to check:**

**Glob patterns — does the skill scan everything?**
- ❌ `ls artifacts/strat-tasks/` or `artifacts/strat-tasks/*.md` — processes all files
- ✅ `artifacts/strat-tasks/RHAISTRAT-*.md` — targeted glob, skips stubs and symlinks
- ✅ `artifacts/strat-tasks/$ISSUE_KEY.md` — opens exactly one file

**Index files — are writes atomic?**
- ❌ Skills that rewrite an entire index file (read-then-write pattern) — will clobber under concurrency
- ⚠️ Skills that append to shared files — not atomic on shared PVCs
- ✅ Skills that use per-ticket files or symlinks — inherently safe

**Per-ticket filtering — does the skill respect $ARGUMENTS?**
- ❌ Skill globs all artifacts and relies on LLM to pick the right one
- ⚠️ Skill reads $ARGUMENTS but filtering is done by LLM reasoning, not code
- ✅ Skill uses $ARGUMENTS to construct a specific filename and opens only that file

**Recommended pattern for shared artifact dirs:**
- Use symlinks for cross-referencing (e.g., `RHAIRFE-1981.md → RHAISTRAT-3.md`)
- Use targeted globs with known prefixes (e.g., `RHAISTRAT-*.md` not `*.md`)
- Accept `--issue KEY` in `$ARGUMENTS` and open that file directly
- Write per-ticket output files, not shared index tables

**Detection:**
```bash
# Check for broad glob patterns in code blocks
grep -E '(ls|for.*in|glob) .*\*\.md' "$skill_dir/SKILL.md" | \
    grep -v 'RHAISTRAT-\*\|RHAIRFE-\*' | \
    while read line; do
        echo "⚠️ Broad glob pattern: $line"
        echo "   Will process ALL files in directory — unsafe for concurrent per-ticket jobs"
        echo "   Consider using a targeted prefix (e.g., RHAISTRAT-*.md)"
    done

# Check for shared index file writes
grep -E '(Write|write|>|>>).*\.(md|yaml|json)' "$skill_dir/SKILL.md" | \
    grep -v 'RHAISTRAT-\|RHAIRFE-\|review' | \
    while read line; do
        echo "⚠️ Shared file write: $line"
        echo "   May race with concurrent jobs writing to the same file"
    done
```

### 13. Marketplace Compatibility
Determines if a skill can be installed via `/plugin install` or requires full repository checkout.

**Self-contained skills:**
- All supporting files in skill directory
- No references to `scripts/` at repo root
- No references to `requirements.txt` at repo root
- No references to other skills' directories

**Repository-dependent skills:**
- References `scripts/` directory
- Uses shared utilities
- Requires repo-level `requirements.txt`
- Expected usage: Full repo checkout for CI/CD
