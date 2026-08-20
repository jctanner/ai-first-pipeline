"""Adapt strat-dashboard's Pages job to the local forge emulators.

The upstream job keeps public GitHub/GitLab defaults.  The transformation
only derives equivalent URLs from CI variables when the fixture supplies
emulator endpoints and enables the fixture's opt-in TLS bypass.
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
        "  before_script:\n"
        "    - microdnf install -y --nodocs git-core python3 python3-pip\n"
        "    - pip3 install pyyaml\n"
        "    - git clone --depth 1 \"$CREATOR_REPO\" /tmp/strat-creator\n"
        "    - git clone \"https://bot:${DATA_REPO_TOKEN}@gitlab.com/${DATA_REPO}.git\" /tmp/strat-data\n",
        "  before_script:\n"
        '    - if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then export GIT_SSL_NO_VERIFY=true; fi\n'
        "    - |\n"
        '      github_git_url="${GITHUB_GIT_URL:-https://github.com}"\n'
        '      github_git_url="${github_git_url%/}"\n'
        '      export CREATOR_REPO="${github_git_url}/opendatahub-io/strat-creator.git"\n'
        '      gitlab_git_url="${GITLAB_GIT_URL:-https://gitlab.com}"\n'
        '      gitlab_git_url="${gitlab_git_url%/}"\n'
        '      data_repo="${DATA_REPO}"\n'
        '      if [[ "$data_repo" != *"://"* ]]; then\n'
        '        if [ -n "${DATA_REPO_TOKEN:-}" ]; then\n'
        '          data_repo="${gitlab_git_url%%://*}://bot:${DATA_REPO_TOKEN}@${gitlab_git_url#*://}/${data_repo}.git"\n'
        '        else\n'
        '          data_repo="${gitlab_git_url}/${data_repo}.git"\n'
        "        fi\n"
        "      fi\n"
        '      export DATA_REPO_URL="${data_repo}"\n'
        "    - microdnf install -y --nodocs git-core python3 python3-pip\n"
        "    - pip3 install pyyaml\n"
        "    - git clone --depth 1 \"$CREATOR_REPO\" /tmp/strat-creator\n"
        "    - git clone \"$DATA_REPO_URL\" /tmp/strat-data\n",
    )
    return [".gitlab-ci.yml"]
