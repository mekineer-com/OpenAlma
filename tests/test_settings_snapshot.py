import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import services  # noqa: E402
import settings  # noqa: E402
import app  # noqa: E402


def _apps_root(path: Path) -> Path:
    (path / "mcp-memu-server").mkdir(parents=True)
    (path / "mcp-memu-server" / "run.py").touch()
    return path


def test_saved_apps_root_waits_for_restart(tmp_path, monkeypatch):
    active = _apps_root(tmp_path / "active").resolve()
    pending = _apps_root(tmp_path / "pending").resolve()
    alias = tmp_path / "pending-alias"
    alias.symlink_to(pending, target_is_directory=True)
    monkeypatch.setattr(settings, "_ACTIVE_APPS_ROOT", active)
    monkeypatch.setattr(settings, "_ACTIVE_CHANNELS_HOME", active / "hermes-channels" / "data")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")

    settings.write_paths({"apps_root": str(alias)})

    assert settings.apps_root() == active
    assert settings.channels_home() == active / "hermes-channels" / "data"
    assert settings.resolve_apps_root(settings.read_paths()["apps_root"]) == pending
    assert services.all_services()[0].cwd == active / "mcp-memu-server"
    assert settings.read_paths()["apps_root"] == str(alias)


def test_channels_editor_uses_active_channels_home(tmp_path, monkeypatch):
    channels_home = tmp_path / "custom-channels"
    monkeypatch.setattr(settings, "channels_home", lambda: channels_home)

    assert app._editable_configs(tmp_path)["channels-config"] == channels_home / "config.json"
