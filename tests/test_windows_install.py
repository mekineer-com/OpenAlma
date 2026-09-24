import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import settings  # noqa: E402
import windows_install  # noqa: E402


def test_windows_installer_uses_openalma_icon_everywhere():
    script = (
        Path(__file__).resolve().parents[1] / "installer/windows/OpenAlma.iss"
    ).read_text(encoding="utf-8")

    assert "SetupIconFile=OpenAlma.ico" in script
    assert "UninstallDisplayIcon={app}\\OpenAlma.ico" in script
    assert script.count('IconFilename: "{app}\\OpenAlma.ico"') == 2
    assert 'Type: filesandordirs; Name: "{app}\\launcher\\.venv"' in script
    assert 'Type: files; Name: "{app}\\.openalma-version"' in script
    assert "{pf64}\\Git\\cmd\\git.exe" in script


def test_windows_configuration_preserves_release_and_other_settings(tmp_path, monkeypatch):
    apps_root = tmp_path / "OpenAlma"
    settings_path = tmp_path / "paths.json"
    settings_path.write_text('{"other": true}\n', encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / ".openalma-version")

    windows_install.configure(apps_root, "v0.0.14-buildfix")
    (apps_root / "mcp-memu-server").mkdir()
    (apps_root / "mcp-memu-server/run.py").touch()
    (apps_root / "memu").mkdir()
    (apps_root / "memu/pyproject.toml").touch()
    windows_install.configure(apps_root, "v0.0.15-buildfix")

    assert (apps_root / windows_install.RELEASE_FILE).read_text(encoding="utf-8") == "v0.0.14-buildfix\n"
    assert (apps_root / windows_install.PENDING_RELEASE_FILE).read_text(encoding="utf-8") == "v0.0.15-buildfix\n"
    assert settings.PACKAGED_VERSION_PATH.read_text(encoding="utf-8") == "v0.0.15-buildfix\n"
    assert (apps_root / windows_install.OWNER_FILE).read_text(encoding="utf-8").strip() == str(apps_root)
    assert settings.read_paths() == {"other": True, "apps_root": str(apps_root)}


def test_windows_configuration_refuses_unowned_nonempty_root(tmp_path, monkeypatch):
    apps_root = tmp_path / "OpenAlma"
    apps_root.mkdir()
    (apps_root / "unrelated.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")

    with pytest.raises(ValueError, match="Refusing to claim"):
        windows_install.configure(apps_root, "v0.0.14-buildfix")

    assert (apps_root / "unrelated.txt").read_text(encoding="utf-8") == "keep"


def test_windows_release_comparison_rejects_downgrade(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / "missing-version")
    (tmp_path / windows_install.RELEASE_FILE).write_text("v2.1.0-buildfix\n", encoding="utf-8")

    assert windows_install.compare_release(tmp_path, "v2.1.1-buildfix") == 1
    assert windows_install.compare_release(tmp_path, "v2.1.0-buildfix") == 0
    assert windows_install.compare_release(tmp_path, "v2.0.9-buildfix") == -1


def test_windows_release_comparison_orders_prereleases(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / "missing-version")
    (tmp_path / windows_install.RELEASE_FILE).write_text("v0.3.0-rc.1\n", encoding="utf-8")

    assert windows_install.compare_release(tmp_path, "v0.3.0-rc.2") == 1
    assert windows_install.compare_release(tmp_path, "v0.3.0") == 1
    assert windows_install.compare_release(tmp_path, "v0.3.0-beta.9") == -1


def test_windows_configuration_rejects_older_installer_while_update_pending(tmp_path, monkeypatch):
    apps_root = tmp_path / "OpenAlma"
    apps_root.mkdir()
    (apps_root / windows_install.OWNER_FILE).write_text(str(apps_root) + "\n", encoding="utf-8")
    (apps_root / windows_install.RELEASE_FILE).write_text("v1.0.0\n", encoding="utf-8")
    (apps_root / windows_install.PENDING_RELEASE_FILE).write_text("v1.1.0\n", encoding="utf-8")
    packaged = tmp_path / ".openalma-version"
    packaged.write_text("v1.1.0\n", encoding="utf-8")
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", packaged)

    with pytest.raises(ValueError, match="cannot downgrade"):
        windows_install.configure(apps_root, "v1.0.0")

    assert (apps_root / windows_install.PENDING_RELEASE_FILE).read_text(encoding="utf-8") == "v1.1.0\n"


def test_windows_upgrade_before_core_updates_future_install_selection(tmp_path, monkeypatch):
    apps_root = tmp_path / "OpenAlma"
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / ".openalma-version")

    windows_install.configure(apps_root, "v1.0.0")
    windows_install.configure(apps_root, "v1.1.0")

    assert (apps_root / windows_install.RELEASE_FILE).read_text(encoding="utf-8") == "v1.1.0\n"
    assert not (apps_root / windows_install.PENDING_RELEASE_FILE).exists()


def test_windows_upgrade_uses_saved_apps_root(tmp_path, monkeypatch):
    saved = tmp_path / "saved-root"
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")
    settings.write_paths({"apps_root": str(saved)})

    assert windows_install.selected_apps_root(tmp_path / "fallback") == saved.resolve()
