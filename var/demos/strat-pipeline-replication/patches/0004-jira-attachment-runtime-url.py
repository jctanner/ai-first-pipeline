"""Make Jira attachment URLs returned by the emulator reachable from jobs.

The emulator currently serializes attachment URLs with its internal loopback
origin (``http://localhost:8080``). Jobs must use their configured
``JIRA_SERVER`` origin instead. Public or non-loopback attachment URLs are
left unchanged.
"""

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}: {old!r}")
    path.write_text(content.replace(old, new, 1))


def apply_strat_creator(root: Path) -> list[str]:
    jira_utils = root / "scripts/jira_utils.py"
    replace_once(
        jira_utils,
        "import urllib.error\n"
        "import urllib.request\n",
        "import urllib.error\n"
        "import urllib.request\n"
        "from urllib.parse import urlsplit, urlunsplit\n",
    )
    replace_once(
        jira_utils,
        "def download_attachment(server, user, token, content_url, dest_path):\n"
        "    \"\"\"Download a Jira attachment by its content URL.\"\"\"\n"
        "    credentials = base64.b64encode(f\"{user}:{token}\".encode()).decode()\n"
        "    headers = {\n"
        "        \"Authorization\": f\"Basic {credentials}\",\n"
        "        \"Accept\": \"*/*\",\n"
        "    }\n"
        "    req = urllib.request.Request(content_url, headers=headers)\n"
        "    with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:\n",
        "def _reachable_attachment_url(server, content_url):\n"
        "    \"\"\"Replace emulator loopback origins with the configured Jira server.\"\"\"\n"
        "    attachment = urlsplit(content_url)\n"
        "    configured = urlsplit(server.rstrip(\"/\"))\n"
        "    if attachment.hostname in {\"localhost\", \"127.0.0.1\", \"::1\"}:\n"
        "        return urlunsplit((configured.scheme, configured.netloc, attachment.path, attachment.query, attachment.fragment))\n"
        "    return content_url\n\n\n"
        "def download_attachment(server, user, token, content_url, dest_path):\n"
        "    \"\"\"Download a Jira attachment by its content URL.\"\"\"\n"
        "    credentials = base64.b64encode(f\"{user}:{token}\".encode()).decode()\n"
        "    headers = {\n"
        "        \"Authorization\": f\"Basic {credentials}\",\n"
        "        \"Accept\": \"*/*\",\n"
        "    }\n"
        "    req = urllib.request.Request(_reachable_attachment_url(server, content_url), headers=headers)\n"
        "    with urllib.request.urlopen(req, timeout=120, context=ssl_ctx) as resp:\n",
    )
    return ["scripts/jira_utils.py"]
