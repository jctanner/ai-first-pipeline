# epic-codegen SKILL.md references missing "superpowers" plugin

## Status: Open

## Symptom

The epic-codegen skill's SKILL.md (Steps 11-12) instructs the agent to initialize an SDD workspace and invoke `Skill("superpowers:subagent-driven-development")`. This plugin does not exist in the `opendatahub-io/skills-registry` marketplace and is not bundled with the epic-code-gen repo.

The agent's thinking shows it recognizing the gap:

> "Since I can't use SDD (Superpowers) in a headless environment, and the `go` toolchain isn't available in this environment, I'll implement the code directly."

## Impact

Medium. The agent falls back to direct implementation and still produces passing code (8.6-8.8 review scores), but:

- Burns thinking tokens working around the missing plugin each run
- Skips the intended sub-agent fan-out architecture (per-task implementer → task review → fix loop → final branch review)
- The SDD progress ledger at `.superpowers/sdd/progress.md` is never created

## References in SKILL.md

```
Step 11: Initialize SDD Workspace
  cd .target-repo && bash ../superpowers/scripts/sdd-workspace

Step 12: Invoke SDD
  Skill("superpowers:subagent-driven-development")
```

Additional references throughout the file:
- "invokes Superpowers SDD for implementation" (line 11)
- "Every human step in the Superpowers methodology is replaced by autonomous judgment" (line 16)
- SDD checkpoint override tables (lines 38-57)
- Progress ledger path `.superpowers/sdd/progress.md` (line 57)

## Where the plugin should be

Not in `opendatahub-io/skills-registry` — checked all 15 registered plugins, none is "superpowers". Likely a private/internal plugin the epic-code-gen author (`ederign`) had available in their environment but never published to the registry.

## Options

1. **Find and publish the plugin** — locate the superpowers repo and add it to the skills-registry
2. **Remove SDD references from SKILL.md** — simplify the skill to use direct implementation, matching what the agent actually does today
3. **Leave as-is** — the fallback works, but wastes tokens on every run
