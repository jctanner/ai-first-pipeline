# Claude Code 2.1.214 plugin-path pseudocode

This pseudocode is reconstructed from the exact target ranges recorded in
`claude-code-2.1.214-plugin-correspondences.json`. Names describe supported
roles; they are not claimed to be original source identifiers.

## Settings and installed plugin order

```text
enabledSourceOrder = [user, project, local, flag, policy]
merged = pluginBaseSettings

for source in enabledSourceOrder:
    merged = deepMerge(merged, source.settings)
    # later scalar/object values win
    # arrays union/deduplicate, except fallbackModel is replaced
    # replacing an existing object property does not move its insertion slot

enabledIds = Object.entries(merged.enabledPlugins) in insertion order
catalogs = await Promise.all(load marketplace catalog for each enabledId)
settled = await Promise.allSettled(load each enabledId using its matching catalog)

for result in settled in input index order:
    append successful plugin or accumulate its non-fatal error
return plugins and errors in enabledIds order
```

Consequently, the order of `enabledPlugins` keys after the settings cascade is
the installed-plugin discovery order. `installed_plugins.json` supplies cache
metadata and paths; its record order does not reorder this list.

## Marketplace registration and installation state

```text
registerMarketplace(source):
    normalize a local source to an absolute path
    reject source if enterprise marketplace policy blocks it
    if exact source is already materialized: return existing record
    catalog = await loadAndCacheMarketplace(source)
    validate reserved marketplace names

    if same marketplace name already exists with a different source:
        overwrite the record
        remove the old materialization only when it is inside the cache root
        otherwise log and leave the suspicious path untouched

    known_marketplaces[catalog.name] = {
        source, installLocation, lastUpdated
    }
    write known_marketplaces.json
    clear marketplace caches

installPlugin(pluginId, scope):
    resolve policy and the version-aware transitive dependency closure
    compute the closure's initial enabled/default-disabled values
    write the entire closure to settings[scope].enabledPlugins in one action
    try:
        materialize/cache-register closure members in dependency-safe order
        # cache registration updates versioned installed_plugins.json records
        resolve any dependencies learned from materialized plugin manifests
    catch or non-recoverable materialization failure:
        roll back the proposed enabledPlugins values
        return or rethrow the original failure
    apply defaultEnabled corrections discovered from materialized manifests
    clear plugin caches
    return closure, dependency note, and installed-disabled members
```

The CLI wrapper maps structured policy, dependency, version-range, settings,
and materialization failures to user-facing results. A later load failure—such
as conflicting manifests—does not undo an already successful install;
`plugin list` reports that discovery failure separately.

## Plugin manifest/component resolution

```text
finishPlugin(path, marketplaceEntry, strict):
    plugin = createPluginFromPath(path)
    preserve plugin.errors, plugin.warnings, and hasManifest

    if no plugin manifest:
        canonicalize marketplace entry
        use marketplace commands/agents/skills/hooks/mcp/lsp/themes paths
        validate every declared path and accumulate errors
        return plugin or null on fatal validation

    if manifest exists and strict == false and marketplace declares components:
        append generic-error("has conflicting manifests ...")
        return null

    # manifest owns declarations, but conventional defaults still exist
    keep conventional root component directories discovered by createPluginFromPath
    append valid custom component paths declared by the plugin manifest
    merge non-conflicting marketplace metadata
    return plugin with accumulated warnings/errors
```

Thus a plugin manifest's custom `skills` path is additive in 2.1.214; it does
not suppress a valid conventional root `skills/` directory. A non-strict
marketplace component declaration plus a plugin manifest is rejected instead.

## Source loading and precedence

```text
loadAllPluginSources():
    [marketplaceResult, sessionResult, skillFolderResult] = await Promise.all([
        load installed marketplace plugins,
        load every --plugin-dir specification,
        load skill-folder pseudo-plugins
    ])
    builtinResult = getBuiltinPlugins()

    session = drop session plugins whose names are policy-managed; add errors
    marketplace = drop installed plugins overridden by an enabled session copy
    merged = [session..., marketplace..., skillFolder..., builtin...]
    verify dependencies; demote failures and accumulate errors
    return enabled, disabled, errors

loadSessionOnly(specs):
    results = await Promise.all(specs.map(load path, URL, or ZIP))
    # work overlaps; Promise.all returns in CLI argument order
    for result in results in input order:
        flatMap loaded plugin(s), skip failures, accumulate errors
```

A disabled session copy does not replace the installed copy. A managed
installed name cannot be bypassed by `--plugin-dir`.

## Skill enumeration and command list construction

```text
loadSkillsFromDirectory(directory, pluginName):
    if directory/SKILL.md is a valid regular file <= 1 MiB:
        load one skill named frontmatter.name or basename(directory)
    else:
        entries = readdir(directory)
        candidates = await Promise.all(entries.map(load child/SKILL.md if valid))
        for valid child:
            qualifiedName = pluginName + ":" + (frontmatter.name or child basename)
        sort candidates by qualified skill.name using localeCompare
    log and skip invalid/unreadable files; return valid skills

getPluginSkills():
    plugins = enabled plugins in merged plugin order
    perPlugin = await Promise.all(plugins.map(load default and custom paths))
    # plugin results retain input order; custom path results retain path order
    flatten perPlugin
    canonical-realpath deduplicate; first preserved path wins
    return skills

getAllCommands():
    concurrently obtain skill-dir, workflow, plugin-command, and plugin-skill sources
    base = [
        skillDirCommands..., workflowCommands..., pluginCommands...,
        pluginSkills..., bundledSkills..., builtinPluginSkills..., builtinCommands...
    ]
    drop only fallback skills whose unqualified suffix collides with a
        qualified plugin/MCP suffix
    accumulate source-load errors and continue with remaining sources
```

## Lookup, slash expansion, and API input

```text
findCommand(input, commands):
    return commands.find(command =>
        command.name == input OR
        command.userFacingName() == input OR
        command.aliases includes input
    )

processSlash(input, args):
    command = findCommand(input, commands)
    if absent: return "Unknown command"
    if command.type != prompt: return type error
    expansion = await getPromptForCommand(command, args)
    register command hooks and invoked-skill metadata
    enqueue metadata user message containing qualified command name and args
    enqueue meta user message containing exactly the selected skill content,
        base-directory prefix, substitutions, attachments, and permissions
    send the already-resolved messages to the model API
```

`Array.find` makes the first command whose qualified name, display name, or
alias matches authoritative. Exact qualified input is unambiguous. Bare input
is resolved by command-array order before the API request; the model receives
one selected skill, not a choice among collisions.

## Startup timing

```text
commands = await discoverInitialCommands()
record commands-loaded checkpoint
start initializeVersionedPlugins()

if interactive:
    do not await initialization before UI startup
if print/headless:
    register cleanup that awaits initialization before process exit
```

Initial command discovery therefore reads the pre-existing installed snapshot
in both modes. Snapshot migration/synchronization begins afterward and affects
subsequent refreshes or sessions, not the already-built initial command array.
