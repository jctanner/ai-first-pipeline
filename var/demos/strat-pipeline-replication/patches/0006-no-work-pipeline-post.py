#!/usr/bin/env python3
"""Make the shared post step succeed when a batch produced no artifacts."""

from __future__ import annotations

from pathlib import Path


OLD = 'WORKDIR="/tmp/claude-workdir"\n\n'
NEW = '''WORKDIR="/tmp/claude-workdir"

# A valid batch may contain only already-processed RFEs.  The creator skill
# records that outcome without creating strategy files; there is then nothing
# for the report/data exporters to publish.
if ! find "${WORKDIR}/artifacts/strat-tasks" -maxdepth 1 -type f -name 'RHAISTRAT-*.md' -print -quit 2>/dev/null | grep -q .; then
  echo "INFO: No strategy artifacts produced; nothing to publish."
  rm -rf /root/.tokens
  exit 0
fi

'''


def apply(root: Path) -> list[str]:
    path = root / "ci-scripts/pipeline-post.sh"
    content = path.read_text()
    if content.count(OLD) != 1:
        raise RuntimeError(f"expected one insertion point in {path}")
    path.write_text(content.replace(OLD, NEW, 1))
    return [path.relative_to(root).as_posix()]
