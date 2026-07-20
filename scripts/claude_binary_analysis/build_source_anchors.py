#!/usr/bin/env python3
"""Build a semantic anchor catalog from the old Claude Code source tree."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


TOPICS = (
    {
        "id": "marketplace-registration",
        "file": "src/utils/plugins/marketplaceManager.ts",
        "function": "addMarketplaceSource",
        "anchors": (
            "known_marketplaces.json",
            "Source already materialized as",
            "exists with different source",
            "Added marketplace source:",
            "Marketplace source '",
        ),
        "calls": ("loadAndCacheMarketplace", "updateKnownMarketplaces", "writeFile"),
    },
    {
        "id": "installed-marketplace-loading",
        "file": "src/utils/plugins/pluginLoader.ts",
        "function": "loadPluginsFromMarketplaces",
        "anchors": (
            "enabledPlugins",
            "marketplace-blocked-by-policy",
            "plugin-not-found",
            "plugin-cache-miss",
            "installed_plugins.json",
        ),
        "calls": ("getSettings_DEPRECATED", "loadInstalledPluginsV2", "Promise.all"),
    },
    {
        "id": "plugin-install-state-mutation",
        "file": "src/utils/plugins/pluginInstallationHelpers.ts",
        "function": "installResolvedPlugin",
        "anchors": (
            "local-source-no-location",
            "settings-write-failed",
            "dependency-blocked-by-policy",
            "blocked-by-policy",
            "enabledPlugins",
        ),
        "calls": ("updateSettingsForSource", "cacheAndRegisterPlugin", "clearAllCaches"),
    },
    {
        "id": "manifest-conflict",
        "file": "src/utils/plugins/pluginLoader.ts",
        "function": "finishLoadingPluginFromPath",
        "anchors": (
            "both plugin.json and marketplace manifest entries",
            "has conflicting manifests",
            "Set strict: true in marketplace entry",
            "generic-error",
            "Processing ${Array.isArray(entry.skills)",
            "Found ${validPaths.length} valid skill paths",
        ),
        "calls": ("createPluginFromPath", "validatePluginPaths", "Promise.all"),
    },
    {
        "id": "session-only-plugin-loading",
        "file": "src/utils/plugins/pluginLoader.ts",
        "function": "loadSessionOnlyPlugins",
        "anchors": (
            "session-only plugins from --plugin-dir",
            "Plugin path does not exist:",
            "Loaded inline plugin from path:",
            "Failed to load session plugin from",
            "Failed to load plugin:",
        ),
        "calls": ("createPluginFromPath", "Promise.all", "flatMap"),
    },
    {
        "id": "skill-enumeration",
        "file": "src/utils/plugins/loadPluginCommands.ts",
        "function": "loadSkillsFromDirectory",
        "anchors": (
            "SKILL.md",
            "Failed to load skill from",
            "Failed to load skills from directory",
            "getPluginSkills: Processing",
            "Attempting to load skills from plugin",
            "Total plugin skills loaded:",
        ),
        "calls": ("readdir", "readFile", "createPluginCommand"),
    },
    {
        "id": "command-list-construction",
        "file": "src/commands.ts",
        "function": "getCommands",
        "anchors": (
            "getSkills returning:",
            "Plugin skills failed to load",
            "Skill directory commands failed to load",
            "Available commands:",
            "pluginSkills",
        ),
        "calls": ("Promise.all", "getPluginCommands", "getPluginSkills"),
    },
    {
        "id": "slash-command-resolution",
        "file": "src/utils/processUserInput/processSlashCommand.tsx",
        "function": "processPromptSlashCommand",
        "anchors": (
            "Unknown command:",
            "processPromptSlashCommand",
            "Expected 'prompt' command",
            "command_permissions",
            "skipSkillDiscovery",
            "Skill \"/${command.name}\" is available for workers",
        ),
        "calls": ("findCommand", "getPromptForCommand", "addInvokedSkill"),
    },
    {
        "id": "installed-snapshot-initialization",
        "file": "src/utils/plugins/installedPluginsManager.ts",
        "function": "initializeVersionedPlugins",
        "anchors": (
            "installed_plugins.json",
            "Syncing installed_plugins.json with enabledPlugins",
            "Creating installed_plugins.json from settings.json files",
            "Sync completed:",
            "enabledPlugins",
        ),
        "calls": ("migrateToSinglePluginFile", "migrateFromEnabledPlugins", "loadInstalledPluginsV2"),
    },
    {
        "id": "plugin-source-merge",
        "file": "src/utils/plugins/pluginLoader.ts",
        "function": "mergePluginSources",
        "anchors": (
            "from --plugin-dir is blocked by managed settings",
            "overrides installed version",
            "generic-error",
            "policySettings.enabledPlugins",
            "Session first, then non-overridden marketplace",
        ),
        "calls": ("Set", "filter", "map"),
    },
    {
        "id": "plugin-skill-construction",
        "file": "src/utils/plugins/loadPluginCommands.ts",
        "function": "getPluginSkills",
        "anchors": (
            "getPluginSkills: Processing",
            "Attempting to load skills from plugin",
            "Loaded ${skills.length} skills from plugin",
            "Failed to load skills from plugin",
            "Total plugin skills loaded:",
        ),
        "calls": ("loadAllPluginsCacheOnly", "loadSkillsFromDirectory", "Promise.all"),
    },
    {
        "id": "command-lookup",
        "file": "src/commands.ts",
        "function": "getCommand",
        "anchors": (
            "not found. Available commands:",
            "aliases: ",
            "Command ",
        ),
        "calls": ("findCommand", "getCommandName", "sort"),
    },
)


def git(source: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source), *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def find_lines(text: str, needle: str) -> list[int]:
    return [number for number, line in enumerate(text.splitlines(), 1) if needle in line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.source_root.resolve()
    output = args.output.resolve()
    if not source.is_dir():
        parser.error(f"source root is not a directory: {source}")

    head = git(source, "rev-parse", "HEAD")
    dirty = git(source, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    topics: list[dict[str, object]] = []
    failures: list[str] = []
    for spec in TOPICS:
        relative = str(spec["file"])
        path = source / relative
        if not path.is_file():
            failures.append(f"missing source file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        function_lines = find_lines(text, f"function {spec['function']}")
        anchor_records = []
        for position, anchor in enumerate(spec["anchors"]):
            lines = find_lines(text, str(anchor))
            anchor_records.append(
                {
                    "order": position,
                    "text": anchor,
                    "source_lines": lines,
                    "distinctive": len(str(anchor)) >= 12,
                }
            )
        topics.append(
            {
                "id": spec["id"],
                "old_source": {
                    "file": relative,
                    "function": spec["function"],
                    "function_lines": function_lines,
                    "commit": head,
                },
                "ordered_anchors": anchor_records,
                "direct_calls": list(spec["calls"]),
            }
        )

    if failures:
        parser.error("; ".join(failures))
    result = {
        "schema_version": 1,
        "source": {"path": str(source), "head": head, "dirty": dirty},
        "topics": topics,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode()
    if output.exists():
        if not output.is_file() or output.is_symlink() or output.read_bytes() != data:
            parser.error(f"refusing to overwrite different catalog: {output}")
    else:
        temporary = output.with_name(f".{output.name}.tmp")
        temporary.write_bytes(data)
        temporary.replace(output)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
