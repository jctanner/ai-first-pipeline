#!/usr/bin/env python3
"""Run credential-free local plugin state and discovery experiments.

The runner uses a fresh CLAUDE_CONFIG_DIR, records every argv, and never copies
the caller's environment or reads existing Claude credential files.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Iterator


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict[str, object]:
    files = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    ]
    records = [
        {"path": str(path.relative_to(root)), "size": path.stat().st_size, "sha256": sha256(path)}
        for path in files
    ]
    digest = hashlib.sha256()
    for record in records:
        digest.update(str(record["path"]).encode())
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode())
        digest.update(b"\n")
    return {"root": str(root), "tree_sha256": digest.hexdigest(), "files": records}


def write_json(path: Path, value: object, *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=sort_keys) + "\n")


def commit_fixture_repository(root: Path) -> dict[str, object]:
    """Create a deterministic local Git commit covering every fixture file."""
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git is required to record fixture provenance")
    fixed_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_AUTHOR_NAME": "Claude binary analysis fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Claude binary analysis fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    }

    def run(*git_args: str) -> str:
        return subprocess.check_output(
            [git, "-C", str(root), *git_args],
            env=fixed_env,
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()

    run("init", "--quiet", "--initial-branch=main")
    run("add", "--all")
    run("commit", "--quiet", "--message", "Create deterministic plugin fixtures")
    head = run("rev-parse", "HEAD")
    tree = run("rev-parse", "HEAD^{tree}")
    status = run("status", "--porcelain=v1")
    return {
        "repository": str(root),
        "head": head,
        "tree": tree,
        "status_porcelain": status,
        "commit_metadata_policy": "Fixed author, committer, timestamp, message, and generated contents",
        "roles": ["marketplace repository", "plugin source repository"],
    }


def plugin_manifest(name: str, *, skills: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "name": name,
        "version": "1.0.0",
        "description": f"Local binary-analysis fixture {name}",
    }
    if skills is not None:
        value["skills"] = skills
    return value


def write_skill(path: Path, name: str, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: Local fixture {marker}\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        f"Return only this JSON: {{\"fixture\": \"{marker}\"}}\n\n"
        "ARGUMENTS: $ARGUMENTS\n"
    )


def create_fixtures(root: Path) -> dict[str, Path]:
    registry = root / "registry"
    entries: list[dict[str, object]] = []

    cases = {
        "case-a-conventional": {"manifest": True, "root_skill": True},
        "case-b-conflict": {
            "manifest": True,
            "root_skill": True,
            "entry_skills": "./skills",
            "strict": False,
        },
        "case-c-marketplace-manifest": {
            "manifest": False,
            "root_skill": True,
            "entry_skills": "./skills",
            "strict": False,
        },
        "case-d-custom-authoritative": {
            "manifest": True,
            "manifest_skills": "./custom-skills",
            "root_skill": True,
            "custom_skill": True,
        },
        "case-e-dot-claude-only": {"manifest": True, "dot_skill": True},
    }
    paths: dict[str, Path] = {}
    for name, case in cases.items():
        plugin = registry / "plugins" / name
        paths[name] = plugin
        if case.get("manifest"):
            write_json(
                plugin / ".claude-plugin" / "plugin.json",
                plugin_manifest(name, skills=case.get("manifest_skills")),  # type: ignore[arg-type]
            )
        if case.get("root_skill"):
            write_skill(plugin / "skills" / "probe" / "SKILL.md", "probe", f"{name}-root")
        if case.get("custom_skill"):
            write_skill(
                plugin / "custom-skills" / "custom-probe" / "SKILL.md",
                "custom-probe",
                f"{name}-custom",
            )
        if case.get("dot_skill"):
            write_skill(
                plugin / ".claude" / "skills" / "probe" / "SKILL.md",
                "probe",
                f"{name}-dot-claude",
            )
        entry: dict[str, object] = {
            "name": name,
            "description": f"Manifest matrix fixture {name}",
            "version": "1.0.0",
            "source": f"./plugins/{name}",
        }
        if "entry_skills" in case:
            entry["skills"] = case["entry_skills"]
        if "strict" in case:
            entry["strict"] = case["strict"]
        entries.append(entry)

    write_json(
        registry / ".claude-plugin" / "marketplace.json",
        {
            "name": "binary-analysis-fixtures",
            "owner": {"name": "local-analysis"},
            "metadata": {"description": "Credential-free local fixture marketplace"},
            "plugins": entries,
        },
    )

    collision_root = root / "plugin-dir"
    for name, marker in (("zulu-first", "zulu"), ("alpha-second", "alpha")):
        plugin = collision_root / name
        paths[name] = plugin
        write_json(plugin / ".claude-plugin" / "plugin.json", plugin_manifest(name))
        write_skill(plugin / "skills" / "collision" / "SKILL.md", "collision", marker)
    return paths


def create_collision_registry(root: Path, marketplace_order: list[str]) -> dict[str, Path]:
    """Create installed-plugin fixtures whose lexical order is alpha, zulu."""
    registry = root / "registry"
    paths: dict[str, Path] = {}
    entries: dict[str, dict[str, object]] = {}
    for name, marker in (("zulu-plugin", "zulu-installed"), ("alpha-plugin", "alpha-installed")):
        plugin = registry / "plugins" / name
        paths[name] = plugin
        write_json(plugin / ".claude-plugin" / "plugin.json", plugin_manifest(name))
        write_skill(plugin / "skills" / "collision" / "SKILL.md", "collision", marker)
        entries[name] = {
            "name": name,
            "description": f"Installed collision fixture {name}",
            "version": "1.0.0",
            "source": f"./plugins/{name}",
        }
    write_json(
        registry / ".claude-plugin" / "marketplace.json",
        {
            "name": "collision-fixtures",
            "owner": {"name": "local-analysis"},
            "plugins": [entries[name] for name in marketplace_order],
        },
    )
    return paths


class CaptureServer(ThreadingHTTPServer):
    output: Path
    label: str
    captures: int


class CaptureHandler(BaseHTTPRequestHandler):
    server: CaptureServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        length = min(int(self.headers.get("Content-Length", "0")), 16 * 1024 * 1024)
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            body = {}
        strings: list[str] = []

        def collect(value: object) -> None:
            if isinstance(value, str):
                if any(token in value for token in ('"fixture"', "<command-message>", "collision")):
                    strings.append(value[:4000])
            elif isinstance(value, list):
                for item in value:
                    collect(item)
            elif isinstance(value, dict):
                for item in value.values():
                    collect(item)

        collect(body.get("messages", []) if isinstance(body, dict) else [])
        markers = sorted(set(re.findall(r'\\?"fixture\\?"\s*:\s*\\?"([^"\\]+)', "\n".join(strings))))
        self.server.captures += 1
        selected_fixture = markers[0] if markers else "none"
        response_text = json.dumps({"selected_fixture": selected_fixture}, sort_keys=True)
        streaming = bool(body.get("stream")) if isinstance(body, dict) else False
        write_json(
            self.server.output / f"{self.server.captures:03d}-{self.server.label}.json",
            {
                "label": self.server.label,
                "method": "POST",
                "path": self.path,
                "request": {
                    "body_keys": sorted(body) if isinstance(body, dict) else [],
                    "model": body.get("model") if isinstance(body, dict) else None,
                    "message_count": len(body.get("messages", [])) if isinstance(body, dict) else 0,
                    "scoped_message_excerpts": strings,
                    "fixture_markers": markers,
                },
                "response": {
                    "mode": "anthropic-sse" if streaming else "anthropic-json",
                    "selected_fixture": selected_fixture,
                    "text": response_text,
                },
                "retention_policy": "Only command/fixture-bearing message strings are retained; headers, system prompts, tools, and unrelated messages are omitted.",
            },
        )
        message = {
            "id": f"msg_fixture_{self.server.captures}",
            "type": "message",
            "role": "assistant",
            "model": body.get("model", "fixture-model") if isinstance(body, dict) else "fixture-model",
            "content": [{"type": "text", "text": response_text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
        if streaming:
            events = [
                ("message_start", {"type": "message_start", "message": {**message, "content": [], "stop_reason": None, "usage": {"input_tokens": 1, "output_tokens": 0}}}),
                ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": response_text}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            response = "".join(
                f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"
                for event, data in events
            ).encode()
            content_type = "text/event-stream"
        else:
            response = json.dumps(message, separators=(",", ":")).encode()
            content_type = "application/json"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


@contextmanager
def capture_server(output: Path) -> Iterator[CaptureServer]:
    output.mkdir(parents=True, exist_ok=False)
    server = CaptureServer(("127.0.0.1", 0), CaptureHandler)
    server.output = output
    server.label = "unassigned"
    server.captures = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class Runner:
    def __init__(self, binary: Path, output: Path, trace: bool, api_server: CaptureServer) -> None:
        self.binary = binary
        self.output = output
        self.trace = trace
        self.config = output / "config"
        self.command_index = 0
        self.api_server = api_server
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "CLAUDE_CONFIG_DIR": str(self.config),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "NO_COLOR": "1",
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{api_server.server_port}",
            "ANTHROPIC_API_KEY": "local-analysis-placeholder-not-a-credential",
        }

    def command(self, label: str, args: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
        self.command_index += 1
        self.api_server.label = label
        command_dir = self.output / "commands" / f"{self.command_index:02d}-{label}"
        command_dir.mkdir(parents=True, exist_ok=False)
        argv = [str(self.binary), *args]
        executed = argv
        if self.trace:
            trace_prefix = command_dir / "strace"
            executed = [
                shutil.which("strace") or "strace",
                "-ff",
                "-ttt",
                "-s",
                "512",
                "-e",
                "trace=process,file,read,write",
                "-o",
                str(trace_prefix),
                *argv,
            ]
        started = datetime.now(timezone.utc)
        before = time.monotonic()
        try:
            result = subprocess.run(
                executed,
                env=self.env,
                cwd=self.output / "fixtures",
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            timed_out = False
        except subprocess.TimeoutExpired as error:
            result = subprocess.CompletedProcess(
                executed,
                124,
                error.stdout or "",
                error.stderr or "",
            )
            timed_out = True
        elapsed = time.monotonic() - before
        (command_dir / "stdout.txt").write_text(result.stdout)
        (command_dir / "stderr.txt").write_text(result.stderr)
        strace_files = sorted(command_dir.glob("strace.*")) if self.trace else []
        execve_records: list[str] = []
        for trace_file in strace_files:
            for line in trace_file.read_text(errors="replace").splitlines():
                if "execve(" in line:
                    execve_records.append(f"{trace_file.name}: {line}")
        if self.trace:
            (command_dir / "execve.txt").write_text("\n".join(execve_records) + ("\n" if execve_records else ""))
        write_json(
            command_dir / "command.json",
            {
                "label": label,
                "argv": argv,
                "executed_argv": executed,
                "started_at": started.isoformat(),
                "duration_seconds": elapsed,
                "returncode": result.returncode,
                "timed_out": timed_out,
                "strace_files": [path.name for path in strace_files],
                "execve_records": execve_records,
                "environment_policy": {
                    "inherited_values": ["PATH"],
                    "fixed_keys": sorted(key for key in self.env if key != "PATH"),
                    "credentials_inherited": False,
                    "credential_values_retained": False,
                },
            },
        )
        return result

    def snapshot_state(self, label: str) -> None:
        state_dir = self.output / "state" / label
        state_dir.mkdir(parents=True, exist_ok=False)
        for name in ("settings.json", "plugins/known_marketplaces.json", "plugins/installed_plugins.json"):
            source = self.config / name
            if source.is_file():
                target = state_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--strace", action="store_true")
    args = parser.parse_args()
    binary = args.binary.resolve()
    output = args.output.resolve()
    if not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
        parser.error("binary must be a regular, non-symlink executable")
    if output.exists():
        parser.error(f"output already exists; experiments are immutable: {output}")
    output.mkdir(parents=True)
    fixtures = create_fixtures(output / "fixtures")
    fixture_repository = commit_fixture_repository(output / "fixtures")
    write_json(
        output / "experiment.json",
        {
            "schema_version": 1,
            "binary": {
                "path": str(binary),
                "sha256": sha256(binary),
                "version": subprocess.check_output([str(binary), "--version"], text=True).strip(),
            },
            "network_policy": "No credentials inherited. API traffic is redirected to a loopback Anthropic response server that retains only fixture-bearing message excerpts.",
            "host": {
                "platform": platform.platform(),
                "python": platform.python_version(),
                "uname": list(os.uname()),
                "cwd": str(Path.cwd()),
            },
            "fixtures": {
                "provenance_type": "generated-git-repository",
                "repository": fixture_repository,
                "generator": {
                    "path": str(Path(__file__).resolve()),
                    "sha256": sha256(Path(__file__).resolve()),
                },
                "initial_tree": tree_manifest(output / "fixtures"),
            },
            "strace": args.strace,
        },
    )
    with capture_server(output / "api-captures") as api:
        runner = Runner(binary, output, args.strace, api)
        debug = output / "commands" / "marketplace-debug.log"
        add = runner.command(
            "marketplace-add",
            ["--debug-file", str(debug), "plugin", "marketplace", "add", str(output / "fixtures" / "registry")],
        )
        runner.snapshot_state("after-marketplace-add")
        if add.returncode != 0:
            print("marketplace registration failed; see retained command output", file=sys.stderr)
            return 1

        for name in (
            "case-a-conventional",
            "case-b-conflict",
            "case-c-marketplace-manifest",
            "case-d-custom-authoritative",
            "case-e-dot-claude-only",
        ):
            runner.command("install-" + name, ["plugin", "install", f"{name}@binary-analysis-fixtures"])
            runner.snapshot_state("after-install-" + name)

        runner.command("plugin-list", ["--debug-file", str(output / "commands" / "list-debug.log"), "plugin", "list"])
        for name, skill in (
            ("case-a-conventional", "probe"),
            ("case-b-conflict", "probe"),
            ("case-c-marketplace-manifest", "probe"),
            ("case-d-custom-authoritative", "custom-probe"),
            ("case-d-custom-authoritative", "probe"),
            ("case-e-dot-claude-only", "probe"),
        ):
            runner.command(
                "probe-" + name + "-" + skill,
                [
                    "--debug-file",
                    str(output / "commands" / f"probe-{name}-{skill}.debug.log"),
                    "--print",
                    "--verbose",
                    "--output-format",
                    "stream-json",
                    f"/{name}:{skill} test",
                ],
                timeout=45,
            )

        first = fixtures["zulu-first"]
        second = fixtures["alpha-second"]
        for label, order in (("zulu-first", [first, second]), ("alpha-first", [second, first])):
            plugin_args: list[str] = []
            for plugin in order:
                plugin_args.extend(["--plugin-dir", str(plugin)])
            runner.command(
                "plugin-dir-" + label,
                [
                    "--debug-file",
                    str(output / "commands" / f"plugin-dir-{label}.debug.log"),
                    *plugin_args,
                    "--print",
                    "--verbose",
                    "--output-format",
                    "stream-json",
                    "/collision test",
                ],
                timeout=45,
            )

        matrix = {
            "case-a": {
                "install": ["alpha-plugin", "zulu-plugin"],
                "marketplace": ["alpha-plugin", "zulu-plugin"],
                "settings": ["alpha-plugin", "zulu-plugin"],
            },
            "case-b": {
                "install": ["zulu-plugin", "alpha-plugin"],
                "marketplace": ["alpha-plugin", "zulu-plugin"],
                "settings": ["alpha-plugin", "zulu-plugin"],
            },
            "case-c": {
                "install": ["zulu-plugin", "alpha-plugin"],
                "marketplace": ["alpha-plugin", "zulu-plugin"],
                "settings": ["zulu-plugin", "alpha-plugin"],
            },
            "case-d": {
                "install": ["alpha-plugin", "zulu-plugin"],
                "marketplace": ["zulu-plugin", "alpha-plugin"],
                "settings": ["alpha-plugin", "zulu-plugin"],
            },
            "case-e": {
                "install": ["alpha-plugin", "zulu-plugin"],
                "marketplace": ["alpha-plugin", "zulu-plugin"],
                "settings": ["zulu-plugin", "alpha-plugin"],
            },
        }
        for case_name, controls in matrix.items():
            case_root = output / "installed-collision" / case_name
            create_collision_registry(case_root / "fixtures", controls["marketplace"])
            controls["fixture_repository"] = commit_fixture_repository(case_root / "fixtures")  # type: ignore[assignment]
            controls["fixture_tree"] = tree_manifest(case_root / "fixtures")  # type: ignore[assignment]
            case_runner = Runner(binary, case_root, args.strace, api)
            case_runner.command(
                case_name + "-marketplace-add",
                ["plugin", "marketplace", "add", str(case_root / "fixtures" / "registry")],
            )
            for plugin in controls["install"]:
                case_runner.command(case_name + "-install-" + plugin, ["plugin", "install", f"{plugin}@collision-fixtures"])
            settings = case_runner.config / "settings.json"
            settings_value = json.loads(settings.read_text())
            settings_value["enabledPlugins"] = {
                f"{plugin}@collision-fixtures": True for plugin in controls["settings"]
            }
            # Object insertion order is the independent variable in this trial.
            write_json(settings, settings_value, sort_keys=False)
            case_runner.snapshot_state("controlled-final-state")
            case_runner.command(
                case_name + "-ambiguous",
                [
                    "--debug-file",
                    str(case_root / "commands" / f"{case_name}-ambiguous.debug.log"),
                    "--print",
                    "--verbose",
                    "--output-format",
                    "stream-json",
                    "/collision test",
                ],
                timeout=45,
            )
            for plugin in ("alpha-plugin", "zulu-plugin"):
                case_runner.command(
                    case_name + "-qualified-" + plugin,
                    [
                        "--debug-file",
                        str(case_root / "commands" / f"{case_name}-qualified-{plugin}.debug.log"),
                        "--print",
                        "--verbose",
                        "--output-format",
                        "stream-json",
                        f"/{plugin}:collision test",
                    ],
                    timeout=45,
                )
        write_json(output / "collision-matrix.json", matrix)
        captures = [json.loads(path.read_text()) for path in sorted((output / "api-captures").glob("*.json"))]
        command_results = []
        for command_path in sorted(output.glob("**/commands/*/command.json")):
            command = json.loads(command_path.read_text())
            command_results.append(
                {
                    "label": command["label"],
                    "returncode": command["returncode"],
                    "timed_out": command["timed_out"],
                    "command_record": str(command_path.relative_to(output)),
                    "stdout": str((command_path.parent / "stdout.txt").relative_to(output)),
                }
            )
        write_json(
            output / "results.json",
            {
                "commands": command_results,
                "api_responses": [
                    {
                        "label": capture["label"],
                        "selected_fixture": capture["response"]["selected_fixture"],
                        "response_mode": capture["response"]["mode"],
                    }
                    for capture in captures
                ],
            },
        )
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
