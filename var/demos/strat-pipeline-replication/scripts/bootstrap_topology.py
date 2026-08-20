#!/usr/bin/env python3
"""Create the local forge topology and mirror the source repositories.

The script is deliberately stdlib-only and safe to re-run.  Credentials are
read from the environment and are never written to the generated topology
manifest.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[4]
FIXTURE = Path(__file__).resolve().parents[1]


class ApiError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: str):
        super().__init__(f"{method} {url} returned HTTP {status}: {body[:500]}")
        self.status = status


class Api:
    def __init__(self, base: str, headers: dict[str, str]):
        self.base = base.rstrip("/")
        self.headers = headers
        self.context = ssl._create_unverified_context()

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base}/{path.lstrip('/')}"
        headers = {"Accept": "application/json", **self.headers}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, context=self.context) as response:
                raw = response.read().decode()
                return json.loads(raw) if raw else None
        except HTTPError as exc:
            raw = exc.read().decode(errors="replace")
            raise ApiError(method, url, exc.code, raw) from exc
        except URLError as exc:
            raise RuntimeError(f"cannot reach {url}: {exc.reason}") from exc

    def get_or_none(self, path: str) -> Any | None:
        try:
            return self.request("GET", path)
        except ApiError as exc:
            if exc.status == 404:
                return None
            raise


def git_value(source: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_url(base: str, user: str, password: str, path: str) -> str:
    parsed = urlsplit(base)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Git base URL must include scheme and host: {base}")
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{parsed.netloc}"
    return urlunsplit((parsed.scheme, netloc, "/" + path.lstrip("/"), "", ""))


def push_main(source: Path, remote: str) -> str:
    commit = git_value(source, "rev-parse", "refs/heads/main")
    command = [
        "git",
        "-C",
        str(source),
        "-c",
        "http.sslVerify=false",
        "push",
        "--force",
        remote,
        "refs/heads/main:refs/heads/main",
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        safe_remote = remote.split("@", 1)[-1]
        detail = (result.stderr or result.stdout).replace(remote, safe_remote)
        raise RuntimeError(f"could not mirror {source}: {detail.strip()}")

    tags = git_value(source, "tag", "--list")
    if tags:
        tag_result = subprocess.run(
            [
                "git",
                "-C",
                str(source),
                "-c",
                "http.sslVerify=false",
                "push",
                "--force",
                remote,
                "--tags",
            ],
            capture_output=True,
            text=True,
        )
        if tag_result.returncode:
            safe_remote = remote.split("@", 1)[-1]
            detail = (tag_result.stderr or tag_result.stdout).replace(remote, safe_remote)
            raise RuntimeError(f"could not mirror tags from {source}: {detail.strip()}")
    advertised = subprocess.run(
        ["git", "-c", "http.sslVerify=false", "ls-remote", remote, "refs/heads/main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\t", 1)[0]
    if advertised != commit:
        raise RuntimeError(
            f"mirror verification failed for {source}: expected {commit}, got {advertised or '<missing>'}"
        )
    return commit


def ensure_github_repo(api: Api, org: str, name: str) -> dict[str, Any]:
    existing = api.get_or_none(f"repos/{quote(org)}/{quote(name)}")
    if existing is not None:
        return existing
    return api.request(
        "POST",
        f"orgs/{quote(org)}/repos",
        {"name": name, "private": False, "default_branch": "main"},
    )


def ensure_gitlab_group(api: Api, full_path: str, parent_id: int | None) -> dict[str, Any]:
    existing = api.get_or_none(f"groups/{quote(full_path, safe='')}")
    if existing is not None:
        return existing
    body: dict[str, Any] = {"name": full_path.rsplit("/", 1)[-1], "path": full_path.rsplit("/", 1)[-1]}
    if parent_id is not None:
        body["parent_id"] = parent_id
    return api.request("POST", "groups", body)


def ensure_gitlab_project(
    api: Api,
    full_path: str,
    namespace_id: int,
    initialize_with_readme: bool,
) -> dict[str, Any]:
    existing = api.get_or_none(f"projects/{quote(full_path, safe='')}")
    if existing is not None:
        return existing
    name = full_path.rsplit("/", 1)[-1]
    return api.request(
        "POST",
        "projects",
        {
            "name": name,
            "path": name,
            "namespace_id": namespace_id,
            "visibility": "private",
            "default_branch": "main",
            "initialize_with_readme": initialize_with_readme,
        },
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--github-api", default=os.getenv("GITHUB_API_URL", "https://github.local/api/v3"))
    result.add_argument("--github-git", default=os.getenv("GITHUB_GIT_URL", "https://github.local"))
    result.add_argument("--github-token", default=os.getenv("GITHUB_API_TOKEN"))
    result.add_argument("--gitlab-api", default=os.getenv("GITLAB_API_URL", "https://gitlab.local/api/v4"))
    result.add_argument("--gitlab-git", default=os.getenv("GITLAB_GIT_URL", "https://gitlab.local"))
    result.add_argument("--gitlab-user", default=os.getenv("GITLAB_USER", "admin"))
    result.add_argument("--gitlab-password", default=os.getenv("GITLAB_ADMIN_PASSWORD", "admin"))
    return result


def main() -> int:
    args = parser().parse_args()
    if not args.github_token:
        raise SystemExit("GITHUB_API_TOKEN is required (the GitHub emulator admin token)")

    github = Api(
        args.github_api,
        {"Authorization": f"token {args.github_token}"},
    )
    gitlab_auth = base64.b64encode(f"{args.gitlab_user}:{args.gitlab_password}".encode()).decode()
    gitlab = Api(args.gitlab_api, {"Authorization": f"Basic {gitlab_auth}"})

    github_org = github.get_or_none("orgs/opendatahub-io")
    if github_org is None:
        github_org = github.request("POST", "orgs", {"login": "opendatahub-io"})

    sources = {
        "strat-creator": ROOT / "deploy/repos.third-party/strat-creator",
        "assess-strat": ROOT / "deploy/repos.third-party/assess-strat",
        "strat-pipeline": (FIXTURE / "strat-pipeline").resolve(),
        "strat-dashboard": ROOT / "deploy/repos.third-party/strat-dashboard",
    }
    for source in sources.values():
        if not source.is_dir() or not (source / ".git").exists():
            raise SystemExit(f"source checkout is missing or not Git: {source}")

    github_results = []
    for name in ("strat-creator", "assess-strat"):
        repo = ensure_github_repo(github, "opendatahub-io", name)
        remote = git_url(args.github_git, "admin", args.github_token, f"opendatahub-io/{name}.git")
        commit = push_main(sources[name], remote)
        github_results.append({"path": f"opendatahub-io/{name}", "commit": commit, "private": repo.get("private", False)})

    groups: dict[str, dict[str, Any]] = {}
    parent_id = None
    for path in ("redhat", "redhat/rhel-ai", "redhat/rhel-ai/agentic-ci"):
        group = ensure_gitlab_group(gitlab, path, parent_id)
        groups[path] = group
        parent_id = int(group["id"])

    project_results = []
    for name, readme in (("strat-pipeline", False), ("strat-pipeline-data", True), ("strat-dashboard", True)):
        full_path = f"redhat/rhel-ai/agentic-ci/{name}"
        project = ensure_gitlab_project(gitlab, full_path, parent_id, readme)
        result: dict[str, Any] = {
            "path": full_path,
            "id": project["id"],
            "default_branch": project.get("default_branch", "main"),
            "visibility": project.get("visibility", "private"),
        }
        if name in {"strat-pipeline", "strat-dashboard"}:
            remote = git_url(args.gitlab_git, args.gitlab_user, args.gitlab_password, f"{full_path}.git")
            result["commit"] = push_main(sources[name], remote)
        project_results.append(result)

    manifest = {
        "version": 1,
        "github": {"base_url": args.github_git, "organization": "opendatahub-io", "repositories": github_results},
        "gitlab": {
            "base_url": args.gitlab_git,
            "groups": list(groups),
            "projects": project_results,
        },
        "notes": [
            "GitHub mirrors preserve the local main branch and tags.",
            "GitLab data is initialized as an empty project; the dashboard is mirrored from the local source checkout.",
            "No credentials are stored in this manifest.",
        ],
    }
    (FIXTURE / "topology-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))
    print("M1 topology bootstrap passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, RuntimeError) as exc:
        print(f"M1 topology bootstrap failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
