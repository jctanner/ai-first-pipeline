# Task: Isolate Normal-Discovery Ordering Source

## Context

Runs 4 and 5 of the skill disambiguation experiment proved that reversing
plugin installation order reverses the normal-discovery collision winner,
ruling out fixed alphabetical ordering. However, `claude plugin install`
writes to two files simultaneously:

- `~/.claude/plugins/installed_plugins.json` — plugin registry records
- `/app/.claude/settings.local.json` → `enabledPlugins` — project-level
  plugin enablement keys

The runner's post-install Python snippet iterates `installed_plugins.json`
and writes matching keys into `enabledPlugins`, so both files always
reflect the same insertion order. The proximate ordering source has not
been isolated.

## Goal

Determine whether Claude Code's normal-discovery iteration order comes
from `installed_plugins.json` record order or `enabledPlugins` key
iteration order.

## Controls

### Control A — Reverse only `enabledPlugins`

1. Install plugins in a fixed order: imperial-first, metric-second.
2. After installation, rewrite `enabledPlugins` in
   `.claude/settings.local.json` so metric's key appears before
   imperial's key. Leave `installed_plugins.json` unchanged.
3. Run with `--no-plugin-dir`.
4. If metric wins → `enabledPlugins` key iteration order is the source.
   If imperial wins → `enabledPlugins` is not the source.

### Control B — Reverse only `installed_plugins.json`

1. Install plugins in a fixed order: imperial-first, metric-second.
2. After installation, rewrite `installed_plugins.json` so metric's
   record appears before imperial's record. Leave `enabledPlugins`
   unchanged.
3. Run with `--no-plugin-dir`.
4. If metric wins → `installed_plugins.json` record order is the source.
   If imperial wins → `installed_plugins.json` is not the source.

## Expected outcomes

| Control A result | Control B result | Conclusion |
|-----------------|-----------------|------------|
| metric wins | imperial wins | `enabledPlugins` key order controls |
| imperial wins | metric wins | `installed_plugins.json` record order controls |
| metric wins | metric wins | Both files independently influence (unlikely) |
| imperial wins | imperial wins | Neither file controls; some third source |

## Implementation

### 1. Add flags to `run_skill.sh`

Add `--swap-enabled-order` and `--swap-installed-order` boolean flags.
After the existing plugin installation and enablement block (around line
264), add:

```bash
if [ -n "$SWAP_ENABLED_ORDER" ]; then
  echo "  Reversing enabledPlugins key order..."
  python3 -c "
import json
f = '/app/.claude/settings.local.json'
with open(f) as fh:
    s = json.load(fh)
ep = s.get('enabledPlugins', {})
s['enabledPlugins'] = dict(reversed(list(ep.items())))
with open(f, 'w') as fh:
    json.dump(s, fh, indent=2)
print('  enabledPlugins order reversed')
"
fi

if [ -n "$SWAP_INSTALLED_ORDER" ]; then
  echo "  Reversing installed_plugins.json record order..."
  python3 -c "
import json
f = os.path.expanduser('~/.claude/plugins/installed_plugins.json')
with open(f) as fh:
    d = json.load(fh)
plugins = d.get('plugins', {})
d['plugins'] = dict(reversed(list(plugins.items())))
with open(f, 'w') as fh:
    json.dump(d, fh, indent=2)
print('  installed_plugins.json order reversed')
"
fi
```

### 2. Add flags to `k8s_orchestrator.py`

Pass `--swap-enabled-order` / `--swap-installed-order` from
`args.get("swap_enabled_order")` / `args.get("swap_installed_order")`.

### 3. Add battery categories to `vars.yaml`

```yaml
  - id: unambiguous-swap-enabled-order
    description: "Control A: install imperial-first, reverse enabledPlugins only"
    plugins:
      - imperial-converter
      - metric-converter
    no_plugin_dir: true
    swap_enabled_order: true
    prompts:
      - "/unit-convert Convert 5 miles to kilometers"
      - "/unit-convert Convert 100 kilograms to pounds"
      - "/unit-convert What is 32 degrees Fahrenheit in Celsius?"
  - id: unambiguous-swap-installed-order
    description: "Control B: install imperial-first, reverse installed_plugins.json only"
    plugins:
      - imperial-converter
      - metric-converter
    no_plugin_dir: true
    swap_installed_order: true
    prompts:
      - "/unit-convert Convert 5 miles to kilometers"
      - "/unit-convert Convert 100 kilograms to pounds"
      - "/unit-convert What is 32 degrees Fahrenheit in Celsius?"
```

### 4. Thread through workflow chain

Same pattern as `category_no_plugin_dir` — add `swap_enabled_order` and
`swap_installed_order` fields to all battery entries (default false),
thread through run-battery → run-category → run-trials →
run-single-trial, include in job submission body.

### 5. Update scraper

Add new category IDs to `CATEGORIES` in `scrape_results.py`.

### 6. Verification

After the run, check pod logs for each control to confirm:
- Control A: `installed_plugins.json` has imperial first,
  `enabledPlugins` has metric first.
- Control B: `installed_plugins.json` has metric first,
  `enabledPlugins` has imperial first.

## Trial count

2 categories x 3 prompts x 10 trials = 60 new trials. Combined with
the existing 10 categories = 360 total per run.
