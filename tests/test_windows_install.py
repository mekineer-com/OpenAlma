import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import settings  # noqa: E402
import setup_install  # noqa: E402
import windows_install  # noqa: E402
import windows_remove  # noqa: E402


@pytest.mark.parametrize("platform,version", [("win32", "1.3.14"), ("win32", None), ("linux", "1.3.14")])
def test_bundled_bun_selection_preserves_source_fallbacks(tmp_path, monkeypatch, platform, version):
    monkeypatch.setattr(settings.sys, "platform", platform)
    monkeypatch.setattr(settings, "LAUNCHER_DIR", tmp_path / "launcher")
    monkeypatch.setattr(settings, "bun_version", lambda _path: version)
    monkeypatch.setattr(settings.shutil, "which", lambda _name: str(tmp_path / "system-bun"))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    root = tmp_path / "apps"
    private = root / ".tools" / ("bun.exe" if platform == "win32" else "bun")
    private.parent.mkdir(parents=True)
    private.touch()
    bundled = tmp_path / "launcher/runtime/bun/bun.exe"
    expected = bundled if platform == "win32" and version else private
    assert settings.bun_binary(root) == expected
    private.unlink()
    expected = bundled if platform == "win32" and version else tmp_path / "system-bun"
    assert settings.bun_binary(root) == expected
    monkeypatch.setattr(settings.shutil, "which", lambda _name: None)
    home = tmp_path / "home/.bun/bin" / private.name
    home.parent.mkdir(parents=True)
    home.touch()
    expected = bundled if platform == "win32" and version else home
    assert settings.bun_binary(root) == expected


@pytest.fixture(autouse=True)
def _packaged_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "release-components.json"
    manifest.write_bytes((Path(__file__).resolve().parents[1] / "release-components.json").read_bytes())
    monkeypatch.setattr(settings, "PACKAGED_MANIFEST_PATH", manifest)


@pytest.mark.parametrize("argument", ["", "--prepare-update"])
def test_windows_entry_point_preserves_import_failure(tmp_path, argument):
    script = '''
import ctypes, os, runpy, sys, types
from pathlib import Path
root = Path(sys.argv[1])
argument = sys.argv[2]
Path.home = classmethod(lambda cls: root)
os.environ["LOCALAPPDATA"] = str(root)
(root / "run.py").write_text("raise ValueError('fictional startup failure')")
sys.path.insert(0, str(root))
def unavailable(*args):
    raise OSError("no registry in this test")
sys.modules["winreg"] = types.SimpleNamespace(HKEY_LOCAL_MACHINE=0, HKEY_CURRENT_USER=1, OpenKey=unavailable)
messages = []
ctypes.windll = types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=lambda *args: messages.append(args)))
import settings
sys.argv = [str(settings.LAUNCHER_DIR / "windows_start.pyw"), *([argument] if argument else [])]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except ValueError as exc:
    assert str(exc) == "fictional startup failure"
else:
    raise AssertionError("startup failure was swallowed")
assert len(messages) == (0 if argument else 1)
if not argument:
    assert messages[0][1] == "fictional startup failure"
assert "ValueError: fictional startup failure" in settings.LAUNCHER_LOG_PATH.read_text(encoding="utf-8")
'''
    subprocess.run([sys.executable, "-c", script, str(tmp_path), argument],
                   cwd=Path(settings.__file__).parent, check=True, timeout=10)


def test_windows_installer_uses_openalma_icon_everywhere():
    script = (
        Path(__file__).resolve().parents[1] / "installer/windows/OpenAlma.iss"
    ).read_text(encoding="utf-8")

    assert "SetupIconFile=OpenAlma.ico" in script
    assert "UninstallDisplayIcon={app}\\OpenAlma.ico" in script
    assert script.count('IconFilename: "{app}\\OpenAlma.ico"') == 2
    assert 'Type: filesandordirs; Name: "{app}\\launcher\\.venv"' in script
    assert 'Type: filesandordirs; Name: "{app}\\launcher\\__pycache__"' in script
    assert 'Type: files; Name: "{app}\\.openalma-version"' in script
    assert "{pf64}\\Git\\cmd\\git.exe" in script
    assert "Result := StopInstalledLauncher(True)" in script
    assert "Python := PythonLauncher" in script
    assert "windows_remove.py" in script
    assert "ServicesVerified := FileExists(Python) and FileExists(Script)" in script
    assert "Remove Everything will be unavailable" in script
    assert "LastLauncherCheckCode = 11" in script
    assert "--install-dir" in script and "--registered-install" in script
    assert "else if ResultCode = 14 then" in script
    assert "and DirExists(ExpandConstant('{app}')) and not FileExists(Script)" not in script
    assert 'Source: "..\\..\\release-components.json"; DestDir: "{app}"; Flags: ignoreversion; AfterInstall: PrepareLauncher' in script


def test_windows_configuration_preserves_release_and_other_settings(tmp_path, monkeypatch):
    apps_root = tmp_path / "OpenAlma"
    settings_path = tmp_path / "paths.json"
    settings_path.write_text('{"other": true}\n', encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / ".openalma-version")

    windows_install.configure(apps_root, "v0.0.14-buildfix")
    (apps_root / "mcp-memu-server").mkdir()
    (apps_root / "mcp-memu-server/run.py").touch()
    (apps_root / "mcp-memu-server/config.json").touch()
    (apps_root / "memu").mkdir()
    (apps_root / "memu/pyproject.toml").touch()
    windows_install.configure(apps_root, "v0.0.15-buildfix")

    assert (apps_root / windows_install.RELEASE_FILE).read_text(encoding="utf-8") == "v0.0.14-buildfix\n"
    assert (apps_root / windows_install.PENDING_RELEASE_FILE).read_text(encoding="utf-8") == "v0.0.15-buildfix\n"
    assert settings.PACKAGED_VERSION_PATH.read_text(encoding="utf-8") == "v0.0.15-buildfix\n"
    assert (apps_root / windows_install.OWNER_FILE).read_text(encoding="utf-8").strip() == str(apps_root)
    assert settings.read_paths() == {"other": True, "apps_root": str(apps_root)}


@pytest.mark.parametrize("core_ref", ["v0.1.12", "v0.1.14"])
def test_launcher_patch_only_queues_changed_core(tmp_path, monkeypatch, core_ref):
    root = tmp_path / "OpenAlma"
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / ".openalma-version")
    windows_install.configure(root, "v0.1.12")
    manifest = json.loads(settings.PACKAGED_MANIFEST_PATH.read_text(encoding="utf-8"))
    heads = {}
    for entry in manifest["services"]["memu-server"]["repositories"]:
        destination = root / entry["destination"]
        destination.mkdir()
        marker = "run.py" if entry["destination"] == "mcp-memu-server" else "pyproject.toml"
        (destination / marker).touch()
        for command in (
            ["git", "init", "-q"], ["git", "add", marker],
            ["git", "-c", "user.name=Fictional Tester", "-c", "user.email=tester@example.invalid", "commit", "-qm", "fixture"],
            ["git", "remote", "add", "origin", entry["repository"]], ["git", "tag", "v0.1.12"],
        ):
            subprocess.run(command, cwd=destination, check=True, capture_output=True)
        heads[destination] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=destination)
        entry["ref"] = core_ref
    (root / "mcp-memu-server/config.json").write_text("{}", encoding="utf-8")
    settings.PACKAGED_MANIFEST_PATH.write_text(json.dumps(manifest), encoding="utf-8")
    paths = settings.read_paths()
    paths["echo_enabled"] = True
    settings.write_paths(paths)

    windows_install.configure(root, "v0.1.13")

    changed = core_ref != "v0.1.12"
    assert (root / windows_install.PENDING_RELEASE_FILE).exists() == changed
    assert (root / windows_install.RELEASE_FILE).read_text(encoding="utf-8").strip() == ("v0.1.12" if changed else "v0.1.13")
    assert settings.read_paths()["echo_enabled"] is True
    assert settings.PACKAGED_VERSION_PATH.read_text(encoding="utf-8").strip() == "v0.1.13"
    for destination, head in heads.items():
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=destination) == head
    with pytest.raises(ValueError, match="cannot downgrade"):
        windows_install.configure(root, "v0.1.12")


def test_windows_configuration_refuses_unowned_nonempty_root(tmp_path, monkeypatch):
    apps_root = tmp_path / "OpenAlma"
    apps_root.mkdir()
    (apps_root / "unrelated.txt").write_text("keep", encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")

    with pytest.raises(ValueError, match="Refusing to claim"):
        windows_install.configure(apps_root, "v0.0.14-buildfix")

    assert (apps_root / "unrelated.txt").read_text(encoding="utf-8") == "keep"


def test_windows_release_comparison_uses_monotonic_numeric_version(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / "missing-version")
    (tmp_path / windows_install.RELEASE_FILE).write_text("v0.3.0-buildfix\n", encoding="utf-8")

    assert windows_install.compare_release(tmp_path, "v0.3.1-buildfix") == 1
    assert windows_install.compare_release(tmp_path, "v0.3.0-buildfix") == 0
    assert windows_install.compare_release(tmp_path, "v0.2.9-buildfix") == -1
    with pytest.raises(ValueError, match="same version"):
        windows_install.compare_release(tmp_path, "v0.3.0")


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


def test_windows_upgrade_resumes_partial_core_as_first_install(tmp_path, monkeypatch):
    apps_root = tmp_path / "OpenAlma"
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / ".openalma-version")
    windows_install.configure(apps_root, "v1.0.0")
    (apps_root / "mcp-memu-server").mkdir()
    (apps_root / "mcp-memu-server/run.py").touch()

    windows_install.configure(apps_root, "v1.1.0")

    assert (apps_root / windows_install.RELEASE_FILE).read_text(encoding="utf-8") == "v1.1.0\n"
    assert not (apps_root / windows_install.PENDING_RELEASE_FILE).exists()
    monkeypatch.setattr(setup_install, "_OPERATION", None)
    monkeypatch.setattr(setup_install, "release_issue", lambda *_args, **_kwargs: "Update required: memu")
    monkeypatch.setattr(setup_install, "_prerequisite_issue", lambda _root: "")
    status = setup_install.setup_status(apps_root, verify_runtime=False)
    assert status["action_kind"] == "install"
    assert status["action_label"] == "Continue Install"


def test_windows_upgrade_uses_saved_apps_root(tmp_path, monkeypatch):
    saved = tmp_path / "saved-root"
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "paths.json")
    settings.write_paths({"apps_root": str(saved)})

    assert windows_install.selected_apps_root(tmp_path / "fallback") == saved.resolve()


def test_remove_everything_accepts_utf8_recorded_root(tmp_path, monkeypatch):
    root = tmp_path / "José" / "OpenAlma"
    root.mkdir(parents=True)
    (root / windows_install.OWNER_FILE).write_text(str(root) + "\n", encoding="utf-8")
    settings_path = tmp_path / "config" / "paths.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({"apps_root": str(root)}) + "\n", encoding="utf-8")
    state_dir = tmp_path / "state" / "logs"
    state_dir.mkdir(parents=True)
    unrelated = state_dir.parent / "old-default-data.db"
    unrelated.touch()
    calls = []
    real_rmtree = windows_remove.shutil.rmtree
    monkeypatch.setattr(
        windows_remove.shutil, "rmtree",
        lambda path, *args, **kwargs: calls.append((Path(path), kwargs)) or real_rmtree(path, *args, **kwargs),
    )
    monkeypatch.setattr(settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(settings, "LAUNCHER_LOG_PATH", state_dir / "launcher.log")

    windows_remove.remove_everything()

    assert not root.exists()
    assert not settings_path.parent.exists()
    assert calls[0][1]["onexc"] is not None
    assert unrelated.exists()


def test_remove_everything_rejects_changed_owner_without_deleting(tmp_path, monkeypatch):
    root = tmp_path / "OpenAlma"
    root.mkdir()
    (root / windows_install.OWNER_FILE).write_text(str(tmp_path / "Other") + "\n", encoding="utf-8")
    settings_path = tmp_path / "config" / "paths.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({"apps_root": str(root)}) + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_PATH", settings_path)

    with pytest.raises(RuntimeError, match="does not match"):
        windows_remove.remove_everything()

    assert root.exists()


def test_remove_everything_rejects_unowned_source_root(tmp_path, monkeypatch):
    unrelated = tmp_path / "fictional-notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(settings, "read_paths", lambda: {"apps_root": str(tmp_path)})
    with pytest.raises(RuntimeError, match="ownership marker is unavailable"):
        windows_remove.remove_everything()
    assert unrelated.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("answer", [6, 7])
def test_remove_everything_confirms_exact_root_with_no_as_default(tmp_path, monkeypatch, answer):
    root = tmp_path / "FictionalSharedFolder"
    assert setup_install._write_root_marker(root)
    unrelated = root / "fictional-notes.txt"
    unrelated.write_text("explicit consent required", encoding="utf-8")
    monkeypatch.setattr(settings, "read_paths", lambda: {"apps_root": str(root)})
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "config/paths.json")
    monkeypatch.setattr(settings, "LAUNCHER_LOG_PATH", tmp_path / "state/launcher.log")
    prompts = []

    def confirm(*args):
        prompts.append(args)
        assert unrelated.exists()
        return answer

    monkeypatch.setattr(windows_remove.ctypes, "windll", SimpleNamespace(
        user32=SimpleNamespace(MessageBoxW=confirm),
    ), raising=False)
    windows_remove.remove_everything(confirm=True)
    assert len(prompts) == 1 and str(root.resolve()) in prompts[0][1]
    assert prompts[0][3] & 0x00000100  # MB_DEFBUTTON2 makes No the default.
    assert root.exists() is (answer != 6)
