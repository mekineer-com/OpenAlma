import sys
from pathlib import Path
from fastapi.testclient import TestClient

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

    monkeypatch.setattr(services, "host_prerequisites", lambda _root: {"rows": []})
    client = TestClient(app.app, base_url="http://127.0.0.1")
    page = client.get("/settings").text
    assert 'value="stable" selected' in page
    assert page.index('title="Back to Services"') < page.index('title="Refresh (F5)"')
    assert client.post("/settings", data={"apps_root": str(alias), "release_channel": "prerelease"},
                       follow_redirects=False).status_code == 303
    assert settings.read_paths()["release_channel"] == "prerelease"
    assert settings.apps_root() == active
    assert 'value="prerelease" selected' in client.get("/settings").text
    assert client.post("/settings", data={"release_channel": "invalid"}).status_code == 422
    assert settings.read_paths()["release_channel"] == "prerelease"


def test_channels_editor_uses_active_channels_home(tmp_path, monkeypatch):
    channels_home = tmp_path / "custom-channels"
    monkeypatch.setattr(settings, "channels_home", lambda: channels_home)

    assert app._editable_configs(tmp_path)["channels-config"] == channels_home / "config.json"


def test_setup_apps_root_accepts_existing_directory_before_core(tmp_path, monkeypatch):
    target = tmp_path / "fresh apps"
    target.mkdir()
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")
    settings.write_paths({"apps_root": str(target)})

    assert settings.setup_apps_root() == target.resolve()
    assert settings.resolve_apps_root(str(target)) is None


def test_atomic_binary_prefers_production_then_debug(tmp_path):
    suffix = ".exe" if settings.os.name == "nt" else ""
    debug = tmp_path / "atomic/target/debug" / f"atomic-server{suffix}"
    production = tmp_path / "atomic/target/server" / f"atomic-server{suffix}"
    debug.parent.mkdir(parents=True)
    debug.touch()

    assert settings.atomic_server_binary(tmp_path) == debug

    production.parent.mkdir(parents=True)
    production.touch()
    assert settings.atomic_server_binary(tmp_path) == production


def test_bad_settings_import_is_safe_but_first_path_read_refuses(tmp_path):
    import subprocess
    config = tmp_path / ".config/openalma-launcher/paths.json"
    config.parent.mkdir(parents=True)
    config.write_text('{broken')
    script = '''
import sys
from pathlib import Path
Path.home = classmethod(lambda cls: Path(sys.argv[1]))
import settings
try:
    settings.apps_root()
except ValueError:
    pass
else:
    raise AssertionError("bad settings accepted")
assert settings.SETTINGS_PATH.read_text() == "{broken"
'''
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=Path(settings.__file__).parent, check=True)


def test_linux_startup_opens_error_page_without_replacing_bad_settings(tmp_path):
    import subprocess
    config = tmp_path / ".config/openalma-launcher/paths.json"
    config.parent.mkdir(parents=True)
    config.write_text('{broken')
    script = '''
import sys, tempfile, types
from pathlib import Path
Path.home = classmethod(lambda cls: Path(sys.argv[1]))
tempfile.gettempdir = lambda: sys.argv[1]
opened = []
sys.modules["browser"] = types.SimpleNamespace(open_app=lambda url: opened.append(url))
try:
    import run
except ValueError:
    pass
else:
    raise AssertionError("bad settings accepted")
page, = Path(sys.argv[1]).glob("openalma-startup-*.html")
assert opened == [page.as_uri()]
assert "OpenAlma could not start" in page.read_text()
assert (Path(sys.argv[1]) / ".config/openalma-launcher/paths.json").read_text() == "{broken"
'''
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], cwd=Path(settings.__file__).parent, check=True)
