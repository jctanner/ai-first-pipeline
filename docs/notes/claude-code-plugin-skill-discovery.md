# Claude Code Plugin Skill Discovery

Claude Code plugins must place skills in a top-level `skills/` directory at
the plugin root. The `.claude/skills/` layout is for standalone project-level
skills and is not a default plugin component location.

## Correct plugin layout

```text
unit-tools/
├── .claude-plugin/
│   └── plugin.json
└── skills/
    └── unit-convert/
        └── SKILL.md
```

The following layout does not register `unit-convert` as a plugin skill by
default:

```text
unit-tools/
├── .claude-plugin/
│   └── plugin.json
└── .claude/
    └── skills/
        └── unit-convert/
            └── SKILL.md
```

This explains the case where the plugin appears in the `stream-json` init
message but its skill is absent from the `skills` and `slash_commands` lists:
Claude Code discovered the plugin manifest, but it found no skill in a default
plugin component location.

## Minimal example

`.claude-plugin/plugin.json`:

```json
{
  "name": "unit-tools",
  "description": "Unit conversion utilities",
  "version": "1.0.0"
}
```

`skills/unit-convert/SKILL.md`:

```markdown
---
description: Convert values between measurement units
disable-model-invocation: true
---

Convert the following value and units:

$ARGUMENTS
```

Invoke the skill with the plugin namespace and skill directory name:

```text
/unit-tools:unit-convert 10 miles to kilometers
```

## Discovery and invocation rules

- `plugin.json` needs only `name` when a manifest is present. The name supplies
  the plugin namespace, such as `unit-tools`.
- The directory below `skills/` supplies the fallback command name, such as
  `unit-convert`.
- The `name` field in `SKILL.md` is optional. When present in 2.1.214 it
  supplies the namespaced command suffix; otherwise the child-directory name
  is used.
- `description` is recommended for automatic model discovery but is not
  required for manual invocation.
- `user-invocable` defaults to `true`; setting it explicitly is unnecessary.
- `user-invocable: false` hides the skill from user invocation.
- `disable-model-invocation: true` makes the skill manual-only. It does not
  prevent `/unit-tools:unit-convert` from working.
- `--dangerously-skip-permissions` does not affect skill discovery.

No `skills` property is necessary in `plugin.json` when the standard top-level
`skills/` directory is used.

## Custom skill locations

A plugin can declare a nonstandard skill directory explicitly:

```json
{
  "name": "unit-tools",
  "skills": "./.claude/skills/"
}
```

Custom component paths must begin with `./` and are resolved relative to the
plugin root. In Claude Code 2.1.214, a `skills` path in `plugin.json` is
additive: valid skills from both that path and the conventional top-level
`skills/` directory are registered. The conventional layout remains the
preferred simple form. Do not also declare the component in a `strict:false`
marketplace entry; a plugin manifest plus non-strict marketplace component
ownership is rejected as conflicting.

## Reloading and validation

After changing the layout, restart Claude Code or run the reload command
available in the current client (2.1.214 exposes `/reload-skills`):

```text
/reload-skills
```

Useful validation and debugging commands are:

```bash
claude plugin validate /path/to/plugin
claude --debug --plugin-dir /path/to/plugin
```

References:

- [Create plugins](https://code.claude.com/docs/en/plugins)
- [Extend Claude with skills](https://code.claude.com/docs/en/slash-commands)
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference)

The version-specific statements above are backed by the exact 2.1.214 bundle
and the controlled cases in
[`claude-code-2.1.214-plugin-analysis.md`](claude-code-2.1.214-plugin-analysis.md).
