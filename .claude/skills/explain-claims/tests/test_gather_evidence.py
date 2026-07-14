import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "gather-evidence.py"


def load_module(monkeypatch):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "RHAIRFE-1"])
    spec = importlib.util.spec_from_file_location("gather_evidence", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()


def test_artifact_index_includes_nested_immutable_runs(tmp_path, monkeypatch):
    module = load_module(monkeypatch)
    module.ARTIFACTS_DIR = str(tmp_path)

    verification = tmp_path / "verification" / "94" / "run.verification.json"
    verification.parent.mkdir(parents=True)
    verification.write_text(json.dumps({"claim_occurrence_id": 94}))
    explanation = tmp_path / "explanations" / "650" / "run.explanation.json"
    explanation.parent.mkdir(parents=True)
    explanation.write_text(json.dumps({"claim_occurrence_id": 94}))

    indexed = module.find_artifacts([94])

    assert {item["type"] for item in indexed} == {
        "verification_run",
        "existing_explanation",
    }
    assert {item["path"] for item in indexed} == {
        str(verification),
        str(explanation),
    }


def test_observatory_index_fetches_full_page_and_selects_latest_run(monkeypatch):
    module = load_module(monkeypatch)
    requested = []

    def urlopen(request, timeout=10):
        url = request.full_url if hasattr(request, "full_url") else request
        requested.append(url)
        if "/history" in url:
            occurrence_id = int(url.split("/")[-2])
            return Response({
                "verification_runs": [
                    {"id": occurrence_id + 1000, "verdict": "supported"},
                    {"id": occurrence_id + 2000, "verdict": "contradicted"},
                ]
            })
        return Response({
            "total": 245,
            "occurrences": [
                {"id": occurrence_id, "claim_text": f"claim {occurrence_id}"}
                for occurrence_id in range(1, 246)
            ],
        })

    monkeypatch.setattr(module.urllib.request, "urlopen", urlopen)
    result = module.find_observatory_claims()

    assert "limit=1000" in requested[0]
    assert result["overflow"] is False
    assert len(result["claims"]) == 245
    assert result["claims"][0]["verification_run_id"] == 2001
    assert result["claims"][0]["verdict"] == "contradicted"


def test_observatory_index_stops_on_possible_truncation(monkeypatch):
    module = load_module(monkeypatch)

    monkeypatch.setattr(
        module.urllib.request,
        "urlopen",
        lambda request, timeout=10: Response({
            "total": 1200,
            "occurrences": [{"id": value} for value in range(1000)],
        }),
    )

    result = module.find_observatory_claims()

    assert result["overflow"] is True
    assert result["claims"] == []
    assert "may be truncated" in result["error"]


def test_skill_requires_self_contained_causal_outputs():
    skill = " ".join((SCRIPT.parents[1] / "SKILL.md").read_text().split())

    assert "cannot be the only evidence" in skill
    assert "A context-setup write or clone does not prove" in skill
    assert "Every JSON file must be independently understandable" in skill
    assert "Never glob all `*.explanation.json` files" in skill
