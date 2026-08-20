"""M3 source transformation for local emulator runtime endpoints.

This recipe only changes environment wiring. It intentionally leaves the
pipeline stages, rules, scripts, and job definitions unchanged.
"""

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}: {old!r}")
    path.write_text(content.replace(old, new, 1))


def apply(root: Path) -> list[str]:
    ci = root / ".gitlab-ci.yml"
    replace_once(
        ci,
        '    ANTHROPIC_VERTEX_PROJECT_ID: "$GCP_PROJECT_ID"\n'
        '    CLOUD_ML_REGION: "global"\n'
        '    DISABLE_AUTOUPDATER: "1"\n'
        '    CLAUDE_CODE_SUBAGENT_MODEL: "claude-opus-4-6"\n'
        '    JIRA_SERVER: "https://redhat.atlassian.net"\n'
        '    JIRA_TOKEN: "$JIRA_API_TOKEN"\n',
        '    CLOUD_ML_REGION: "global"\n'
        '    DISABLE_AUTOUPDATER: "1"\n'
        '    CLAUDE_CODE_SUBAGENT_MODEL: "claude-opus-4-6"\n',
    )

    clone_script = root / "ci-scripts/clone-data-repo.sh"
    replace_once(
        clone_script,
        'token="${RESULTS_PUSH_TOKEN:-}"\n'
        'if [[ "$repo" != *"://"* ]] && [ -n "$token" ]; then\n'
        '  repo="https://bot:${token}@gitlab.com/${repo}.git"\n'
        'fi\n',
        'token="${RESULTS_PUSH_TOKEN:-}"\n'
        'gitlab_git_url="${GITLAB_GIT_URL:-https://gitlab.com}"\n'
        'gitlab_git_url="${gitlab_git_url%/}"\n'
        'if [[ "$repo" != *"://"* ]]; then\n'
        '  if [ -n "$token" ]; then\n'
        '    repo="${gitlab_git_url%%://*}://bot:${token}@${gitlab_git_url#*://}/${repo}.git"\n'
        '  else\n'
        '    repo="${gitlab_git_url}/${repo}.git"\n'
        '  fi\n'
        'fi\n',
    )

    push_script = root / "ci-scripts/push-results.py"
    replace_once(
        push_script,
        "from pathlib import Path\n",
        "from pathlib import Path\nfrom urllib.parse import quote, urlsplit, urlunsplit\n",
    )
    replace_once(
        push_script,
        "def organize_run(results_dir):\n",
        'def authenticated_git_url(base_url, project_path, token):\n'
        '    """Build a GitLab URL for either the public service or local emulator."""\n'
        '    parsed = urlsplit(base_url.rstrip("/"))\n'
        '    if not parsed.scheme or not parsed.netloc:\n'
        '        raise ValueError(f"GITLAB_GIT_URL must be an absolute URL: {base_url}")\n'
        '    netloc = f"bot:{quote(token, safe=\'\')}@{parsed.netloc}"\n'
        '    path = f"/{project_path.lstrip(\'/\')}"\n'
        '    if not path.endswith(".git"):\n'
        '        path += ".git"\n'
        '    return urlunsplit((parsed.scheme, netloc, path, "", ""))\n\n\n'
        'def organize_run(results_dir):\n',
    )
    replace_once(
        push_script,
        '        repo_url = f"https://bot:{token}@gitlab.com/{args.results_repo}.git"\n',
        '        gitlab_url = os.environ.get("GITLAB_GIT_URL", "https://gitlab.com")\n'
        '        repo_url = authenticated_git_url(gitlab_url, args.results_repo, token)\n',
    )

    return [".gitlab-ci.yml", "ci-scripts/clone-data-repo.sh", "ci-scripts/push-results.py"]
