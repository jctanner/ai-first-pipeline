import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "segment-artifact.py"
SPEC = importlib.util.spec_from_file_location("segment_artifact", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_segments_markdown_with_stable_context_and_locators():
    content = """# Strategy

The dashboard uses React. It uses PatternFly, e.g. for navigation.

Required checks:

- Verify the route certificate.
- Report its expiration date.

| Component | Port |
|---|---|
| Dashboard | 8443 |

```python
print("not prose")
```
"""
    first = MODULE.segment_artifact("strat/RHAISTRAT-1.md", content, 1, 1)
    second = MODULE.segment_artifact("strat/RHAISTRAT-1.md", content, 1, 1)

    assert first == second
    assert first["unit_count"] == 7
    assert [unit["kind"] for unit in first["units"]] == [
        "sentence",
        "sentence",
        "sentence",
        "list_item",
        "list_item",
        "table_row",
        "table_row",
    ]
    assert first["units"][0]["heading_path"] == ["Strategy"]
    assert first["units"][3]["list_preamble"] == "Required checks:"
    assert first["units"][1]["preceding_context"] == ["The dashboard uses React."]
    assert first["units"][0]["source_locator"].startswith("strat/RHAISTRAT-1.md:L")
    assert all("not prose" not in unit["text"] for unit in first["units"])


def test_config_and_content_changes_invalidate_identifiers():
    base = MODULE.segment_artifact("a.md", "One fact. Another fact.", 1, 1)
    changed_content = MODULE.segment_artifact("a.md", "One fact. Changed fact.", 1, 1)
    changed_config = MODULE.segment_artifact("a.md", "One fact. Another fact.", 0, 1)

    assert base["source_digest"] != changed_content["source_digest"]
    assert base["configuration_digest"] != changed_config["configuration_digest"]
    assert base["units"][0]["id"] != changed_content["units"][0]["id"]
    assert base["units"][0]["id"] != changed_config["units"][0]["id"]


def test_nested_headings_lists_and_artifact_override():
    content = """# Epic
## Acceptance

The API behavior is documented:

- The parent item applies.
  - The nested item is retained.

Dr. Smith approved the API. It ships now.
"""
    result = MODULE.segment_artifact(
        "epics/ONE.md", content, artifact_type="security_review"
    )
    assert result["configuration"]["preceding_units"] == 2
    assert result["units"][0]["heading_path"] == ["Epic", "Acceptance"]
    assert [unit["kind"] for unit in result["units"][:2]] == ["sentence", "list_item"]
    assert any(unit["text"] == "Dr. Smith approved the API." for unit in result["units"])
