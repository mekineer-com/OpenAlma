import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "launcher"))

import settings

# Run before either tests/ or launcher/ imports services and captures its paths.
_paths = TemporaryDirectory(prefix="openalma-tests-")
_root = Path(_paths.name)
(_root / "mcp-memu-server").mkdir()
(_root / "mcp-memu-server" / "run.py").touch()
settings.SETTINGS_PATH = _root / "paths.json"
settings.write_paths({"apps_root": str(_root)})
settings._ACTIVE_APPS_ROOT = _root
settings._ACTIVE_CHANNELS_HOME = _root / "hermes-channels" / "data"

import setup_install


@pytest.fixture(autouse=True)
def isolated_install_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_install, "INSTALL_LOCK", tmp_path / "install.lock")
    monkeypatch.setattr(setup_install, "_OPERATION", None)
    monkeypatch.setattr(setup_install, "_OPERATIONS", {})
