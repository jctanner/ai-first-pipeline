"""Opt-in self-signed-certificate support for the local emulator.

The switch is deliberately disabled by default. Upstream CI keeps normal
certificate verification; the emulator bootstrap sets ``NO_SSL_VERIFY=1`` as a
project override because its internal CA is not in the UBI job image trust
store.
"""

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}: {old!r}")
    path.write_text(content.replace(old, new, 1))


def apply_strat_creator(root: Path) -> list[str]:
    changed: list[str] = []

    jira_utils = root / "scripts/jira_utils.py"
    replace_once(
        jira_utils,
        "ssl_ctx = ssl.create_default_context()\n"
        "try:\n"
        "    import certifi\n"
        "    ssl_ctx.load_verify_locations(certifi.where())\n"
        "except (ImportError, OSError):\n"
        "    pass\n",
        "def _no_ssl_verify_enabled():\n"
        "    return os.environ.get(\"NO_SSL_VERIFY\", \"0\").lower() in {\n"
        "        \"1\", \"true\", \"yes\", \"on\"\n"
        "    }\n\n\n"
        "if _no_ssl_verify_enabled():\n"
        "    ssl_ctx = ssl._create_unverified_context()\n"
        "else:\n"
        "    ssl_ctx = ssl.create_default_context()\n"
        "    try:\n"
        "        import certifi\n"
        "        ssl_ctx.load_verify_locations(certifi.where())\n"
        "    except (ImportError, OSError):\n"
        "        pass\n",
    )
    changed.append("scripts/jira_utils.py")

    batches = root / "config/engineering35-batches/generate_batches.py"
    replace_once(
        batches,
        "ssl_ctx = ssl.create_default_context()\n"
        "try:\n"
        "    import certifi\n"
        "    ssl_ctx.load_verify_locations(certifi.where())\n"
        "except (ImportError, OSError):\n"
        "    pass\n",
        "if os.environ.get(\"NO_SSL_VERIFY\", \"0\").lower() in {\"1\", \"true\", \"yes\", \"on\"}:\n"
        "    ssl_ctx = ssl._create_unverified_context()\n"
        "else:\n"
        "    ssl_ctx = ssl.create_default_context()\n"
        "    try:\n"
        "        import certifi\n"
        "        ssl_ctx.load_verify_locations(certifi.where())\n"
        "    except (ImportError, OSError):\n"
        "        pass\n",
    )
    changed.append("config/engineering35-batches/generate_batches.py")

    architecture = root / "scripts/fetch-architecture-context.sh"
    replace_once(
        architecture,
        'CONTEXT_DIR=".context/architecture-context"\n',
        'CONTEXT_DIR=".context/architecture-context"\n\n'
        'if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then\n'
        '  export GIT_SSL_NO_VERIFY=true\n'
        '  CURL_SSL_ARGS=(-k)\n'
        'else\n'
        '  CURL_SSL_ARGS=()\n'
        'fi\n',
    )
    replace_once(
        architecture,
        'LATEST=$(curl -sL https://api.github.com/repos/opendatahub-io/architecture-context/contents/architecture | python3 -c',
        'LATEST=$(curl "${CURL_SSL_ARGS[@]}" -sL https://api.github.com/repos/opendatahub-io/architecture-context/contents/architecture | python3 -c',
    )
    changed.append("scripts/fetch-architecture-context.sh")

    assess_bootstrap = root / "scripts/bootstrap-assess-strat.sh"
    replace_once(
        assess_bootstrap,
        "#!/bin/bash\n",
        "#!/bin/bash\n\n"
        'if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then\n'
        "  export GIT_SSL_NO_VERIFY=true\n"
        "fi\n",
    )
    changed.append("scripts/bootstrap-assess-strat.sh")

    eval_assets = root / "eval/scripts/stage-assets.sh"
    replace_once(
        eval_assets,
        "set -euo pipefail\n",
        "set -euo pipefail\n\n"
        'if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then\n'
        "  export GIT_SSL_NO_VERIFY=true\n"
        "fi\n",
    )
    changed.append("eval/scripts/stage-assets.sh")

    return changed


def apply_strat_pipeline(root: Path) -> list[str]:
    changed: list[str] = []

    ci = root / ".gitlab-ci.yml"
    replace_once(
        ci,
        '    DISABLE_AUTOUPDATER: "1"\n',
        '    DISABLE_AUTOUPDATER: "1"\n',
    )
    replace_once(
        ci,
        "  before_script:\n    - bash ci-scripts/setup-claude-ci.sh\n",
        "  before_script:\n"
        '    - if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then export GIT_SSL_NO_VERIFY=true; fi\n'
        "    - |\n"
        '      github_git_url="${GITHUB_GIT_URL:-https://github.com}"\n'
        '      github_git_url="${github_git_url%/}"\n'
        '      export CLAUDE_REPO="${github_git_url}/opendatahub-io/strat-creator.git"\n'
        '      export CLAUDE_PLUGINS="${github_git_url}/opendatahub-io/assess-strat.git"\n'
        '      export JIRA_SERVER="${JIRA_SERVER:-https://redhat.atlassian.net}"\n'
        '      export JIRA_TOKEN="${JIRA_API_TOKEN:-${JIRA_TOKEN:-}}"\n'
        '      export ANTHROPIC_VERTEX_PROJECT_ID="${GCP_PROJECT_ID:-${ANTHROPIC_VERTEX_PROJECT_ID:-}}"\n'
        "    - bash ci-scripts/setup-claude-ci.sh\n",
    )
    changed.append(".gitlab-ci.yml")

    for relative in (
        "ci-scripts/run-claude.sh",
        "ci-scripts/clone-data-repo.sh",
        "ci-scripts/pipeline-post.sh",
    ):
        path = root / relative
        replace_once(
            path,
            "set -euo pipefail\n",
            "set -euo pipefail\n\n"
            'if [ "${NO_SSL_VERIFY:-0}" = "1" ]; then\n'
            "  export GIT_SSL_NO_VERIFY=true\n"
            "fi\n",
        )
        changed.append(relative)

    push_results = root / "ci-scripts/push-results.py"
    replace_once(
        push_results,
        "from pathlib import Path\n",
        "from pathlib import Path\n"
        "\n"
        "if os.environ.get(\"NO_SSL_VERIFY\", \"0\") == \"1\":\n"
        "    os.environ[\"GIT_SSL_NO_VERIFY\"] = \"true\"\n",
    )
    changed.append("ci-scripts/push-results.py")

    return changed
