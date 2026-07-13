import json
from pathlib import Path

from bound_mlflow_claude_hooks import TARGET_COMMAND, bound_stop_hooks


def test_bounds_only_the_mlflow_claude_stop_hook(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({
        "hooks": {
            "Stop": [{"hooks": [
                {"type": "command", "command": TARGET_COMMAND},
                {"type": "command", "command": "preserve-me"},
            ]}],
            "PreToolUse": [{"hooks": [
                {"type": "command", "command": TARGET_COMMAND},
            ]}],
        },
    }))

    assert bound_stop_hooks(settings_path, 17) == 1
    settings = json.loads(settings_path.read_text())
    stop_hooks = settings["hooks"]["Stop"][0]["hooks"]
    assert stop_hooks[0]["command"] == (
        "timeout --signal=TERM --kill-after=5s 17s "
        "mlflow autolog claude stop-hook || true"
    )
    assert stop_hooks[1]["command"] == "preserve-me"
    assert settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == TARGET_COMMAND
    assert bound_stop_hooks(settings_path, 17) == 0
