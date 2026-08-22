from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src/fullsend-dashboard/app.py"
SPEC = importlib.util.spec_from_file_location("fullsend_dashboard_app", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class FakeCollector:
    def state(self):
        return {
            "collected_at": "2026-08-21T00:00:00+00:00",
            "sources": {"github": {"errors": []}, "kubernetes": {"errors": []}},
            "github": {"repos": []},
            "agents": [],
            "jobs": [],
            "events": [],
        }


def test_health_and_state_endpoints():
    client = MODULE.create_app(FakeCollector()).test_client()
    assert client.get("/healthz").get_json() == {"status": "ok"}
    assert client.get("/api/state").get_json()["events"] == []
    assert client.get("/").status_code == 200
