import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import setup_install


@pytest.fixture(autouse=True)
def isolated_install_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_install, "INSTALL_LOCK", tmp_path / "install.lock")
    monkeypatch.setattr(setup_install, "_OPERATION", None)
    monkeypatch.setattr(setup_install, "_OPERATIONS", {})
