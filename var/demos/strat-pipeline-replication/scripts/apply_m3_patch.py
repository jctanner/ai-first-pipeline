#!/usr/bin/env python3
"""Publish reproducibly adapted strat-creator, strat-pipeline, and dashboard mirrors.

The private/source checkouts are never modified. Temporary clones receive the
tracked transformations, are committed, and are pushed to the local GitHub or
GitLab emulator. Credentials are read from the environment and are not written
to manifests.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[4]
FIXTURE = Path(__file__).resolve().parents[1]
SOURCES = {
    "strat-creator": ROOT / "deploy/repos.third-party/strat-creator",
    "strat-pipeline": (FIXTURE / "strat-pipeline").resolve(),
    "strat-dashboard": ROOT / "deploy/repos.third-party/strat-dashboard",
}
PROJECTS = {
    "strat-creator": "opendatahub-io/strat-creator",
    "strat-pipeline": "redhat/rhel-ai/agentic-ci/strat-pipeline",
    "strat-dashboard": "redhat/rhel-ai/agentic-ci/strat-dashboard",
}
ENDPOINT_TRANSFORM = FIXTURE / "patches/0001-local-emulator-runtime-endpoints.py"
SSL_TRANSFORM = FIXTURE / "patches/0002-no-ssl-verify.py"
DASHBOARD_TRANSFORM = FIXTURE / "patches/0003-dashboard-emulator-runtime.py"
ATTACHMENT_TRANSFORM = FIXTURE / "patches/0004-jira-attachment-runtime-url.py"
SMOKE_CONFIG_TRANSFORM = FIXTURE / "patches/0005-emulator-smoke-config.py"
NO_WORK_TRANSFORM = FIXTURE / "patches/0006-no-work-pipeline-post.py"
API_BODIES_TRANSFORM = FIXTURE / "patches/0007-otel-api-bodies.py"


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"command failed ({' '.join(command[:4])}...): {detail}")
    return result


def git_value(repo: Path, *args: str) -> str:
    return run(["git", "-C", str(repo), *args]).stdout.strip()


def git_url(base: str, user: str, password: str, path: str) -> str:
    parsed = urlsplit(base.rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Git base URL must include scheme and host: {base}")
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{parsed.netloc}"
    return urlunsplit((parsed.scheme, netloc, "/" + path.lstrip("/"), "", ""))


def load_transform(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load transformation: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def publish(
    name: str,
    remote: str,
    transforms: list[tuple[Path, str]],
) -> dict:
    source = SOURCES[name]
    if not source.is_dir() or not (source / ".git").exists():
        raise SystemExit(f"source checkout is missing or not Git: {source}")
    if git_value(source, "status", "--porcelain"):
        raise SystemExit(f"source checkout is dirty; review or restore it: {source}")

    source_commit = git_value(source, "rev-parse", "refs/heads/main")
    with tempfile.TemporaryDirectory(prefix=f"{name}-m3-") as temp_dir:
        worktree = Path(temp_dir) / name
        run(["git", "clone", "--no-hardlinks", str(source), str(worktree)])
        changed_files: list[str] = []
        for transform_path, function_name in transforms:
            module = load_transform(transform_path)
            changed_files.extend(getattr(module, function_name)(worktree))

        run(["git", "config", "user.name", "breadboard mirror bootstrap"], cwd=worktree)
        run(["git", "config", "user.email", "breadboard-mirror@localhost"], cwd=worktree)
        run(["git", "add", *dict.fromkeys(changed_files)], cwd=worktree)
        run(["git", "commit", "-m", "Add emulator-compatible runtime switches"], cwd=worktree)
        adapted_commit = git_value(worktree, "rev-parse", "HEAD")
        run(["git", "-c", "http.sslVerify=false", "push", "--force", remote, "HEAD:refs/heads/main"], cwd=worktree)
        advertised = run(["git", "-c", "http.sslVerify=false", "ls-remote", remote, "refs/heads/main"]).stdout.split("\t", 1)[0]
        if advertised != adapted_commit:
            raise RuntimeError(f"{name} mirror verification failed: expected {adapted_commit}, got {advertised or '<missing>'}")

    return {
        "source_commit": source_commit,
        "adapted_commit": adapted_commit,
        "project": PROJECTS[name],
        "transformations": [path.relative_to(ROOT).as_posix() for path, _ in transforms],
        "files_changed": list(dict.fromkeys(changed_files)),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--github-git", default=os.getenv("GITHUB_GIT_URL", "https://github.local"))
    result.add_argument("--github-token", default=os.getenv("GITHUB_API_TOKEN"))
    result.add_argument("--gitlab-git", default=os.getenv("GITLAB_GIT_URL", "https://gitlab.local"))
    result.add_argument("--gitlab-user", default=os.getenv("GITLAB_USER", "admin"))
    result.add_argument("--gitlab-password", default=os.getenv("GITLAB_ADMIN_PASSWORD", "admin"))
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.github_token:
        raise SystemExit("GITHUB_API_TOKEN is required to publish the GitHub mirror")

    github_remote = git_url(
        args.github_git,
        "admin",
        args.github_token,
        f"{PROJECTS['strat-creator']}.git",
    )
    gitlab_remote = git_url(
        args.gitlab_git,
        args.gitlab_user,
        args.gitlab_password,
        f"{PROJECTS['strat-pipeline']}.git",
    )
    dashboard_remote = git_url(
        args.gitlab_git,
        args.gitlab_user,
        args.gitlab_password,
        f"{PROJECTS['strat-dashboard']}.git",
    )
    creator = publish(
        "strat-creator",
        github_remote,
        [
            (SSL_TRANSFORM, "apply_strat_creator"),
            (ATTACHMENT_TRANSFORM, "apply_strat_creator"),
            (SMOKE_CONFIG_TRANSFORM, "apply_strat_creator"),
        ],
    )
    pipeline = publish(
        "strat-pipeline",
        gitlab_remote,
        [
            (ENDPOINT_TRANSFORM, "apply"),
            (SSL_TRANSFORM, "apply_strat_pipeline"),
            (NO_WORK_TRANSFORM, "apply"),
            (API_BODIES_TRANSFORM, "apply"),
        ],
    )
    dashboard = publish(
        "strat-dashboard",
        dashboard_remote,
        [(DASHBOARD_TRANSFORM, "apply")],
    )
    manifest = {
        "version": 2,
        "sources": {
            "strat-creator": creator,
            "strat-pipeline": pipeline,
            "strat-dashboard": dashboard,
        },
        # Keep this compatibility field for validators and downstream readers.
        "source_commit": pipeline["source_commit"],
        "adapted_commit": pipeline["adapted_commit"],
        "project": pipeline["project"],
    }
    (FIXTURE / "pipeline-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    print("M3 mirror adaptation passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"M3 mirror adaptation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
