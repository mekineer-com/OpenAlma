import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import settings  # noqa: E402
import setup_install  # noqa: E402
import windows_install  # noqa: E402
import windows_remove  # noqa: E402


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_bun_selection_prefers_private_then_system_then_home(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(settings.sys, "platform", platform)
    monkeypatch.setattr(settings.shutil, "which", lambda _name: str(tmp_path / "system-bun"))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path / "home"))
    root = tmp_path / "apps"
    private = root / ".tools" / ("bun.exe" if platform == "win32" else "bun")
    private.parent.mkdir(parents=True)
    private.touch()
    assert settings.bun_binary(root) == private
    private.unlink()
    assert settings.bun_binary(root) == tmp_path / "system-bun"
    monkeypatch.setattr(settings.shutil, "which", lambda _name: None)
    home = tmp_path / "home/.bun/bin" / private.name
    home.parent.mkdir(parents=True)
    home.touch()
    assert settings.bun_binary(root) == home
    home.unlink()
    assert settings.bun_binary(root) == private


@pytest.mark.parametrize("failure", ["timeout", "nonzero", "empty"])
def test_transient_bun_probe_failure_is_retried_then_success_cached(tmp_path, monkeypatch, failure):
    binary = tmp_path / "fictional-bun"
    binary.touch()
    calls = []
    def probe(command, **kwargs):
        calls.append(command)
        assert kwargs["check"] is True
        if len(calls) == 1:
            if failure == "timeout":
                raise subprocess.TimeoutExpired(command, 10)
            if failure == "nonzero":
                raise subprocess.CalledProcessError(1, command)
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="1.3.14\n")
    monkeypatch.setattr(settings.subprocess, "run", probe)
    assert settings.bun_version(binary) is None
    assert settings.bun_version(binary) == "1.3.14"
    assert settings.bun_version(binary) == "1.3.14"
    assert len(calls) == 2


@pytest.fixture(autouse=True)
def _packaged_manifest(tmp_path, monkeypatch):
    manifest = tmp_path / "release-components.json"
    manifest.write_bytes((Path(__file__).resolve().parents[1] / "release-components.json").read_bytes())
    monkeypatch.setattr(settings, "PACKAGED_MANIFEST_PATH", manifest)
    monkeypatch.setattr(settings, "SETTINGS_ROOT", tmp_path / "storage")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "storage/paths.json")
    monkeypatch.setattr(settings, "LAUNCHER_LOG_PATH", tmp_path / "storage/launcher.log")
    monkeypatch.setattr(settings, "LEGACY_SETTINGS_PATH", tmp_path / "legacy/paths.json")
    monkeypatch.setattr(settings, "BROWSER_PROFILE_PATH", tmp_path / "profile")
    monkeypatch.setattr(windows_remove, "LAUNCHER_UPDATE_DIR", tmp_path / "updates")


@pytest.mark.parametrize("argument", ["", "--prepare-update", "--stop-existing"])
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
settings.SETTINGS_ROOT = root / "storage"
settings.SETTINGS_PATH = settings.SETTINGS_ROOT / "paths.json"
settings.LAUNCHER_LOG_PATH = settings.SETTINGS_ROOT / "launcher.log"
settings.LEGACY_SETTINGS_PATH = root / "legacy/paths.json"
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
if argument:
    assert not settings.SETTINGS_ROOT.exists()
else:
    assert "ValueError: fictional startup failure" in settings.LAUNCHER_LOG_PATH.read_text(encoding="utf-8")
'''
    subprocess.run([sys.executable, "-c", script, str(tmp_path), argument],
                   cwd=Path(settings.__file__).parent, check=True, timeout=10)


@pytest.mark.parametrize("existing_log", [False, True])
def test_maintenance_preserves_readiness_code_without_creating_log(tmp_path, existing_log):
    script = '''
import os, runpy, sys, types
from pathlib import Path
import settings
root = Path(sys.argv[1])
settings.SETTINGS_ROOT = root / "storage"
settings.SETTINGS_PATH = settings.SETTINGS_ROOT / "paths.json"
settings.LAUNCHER_LOG_PATH = settings.SETTINGS_ROOT / "launcher.log"
settings.LEGACY_SETTINGS_PATH = root / "old/paths.json"
if sys.argv[2] == "True":
    settings.SETTINGS_ROOT.mkdir()
    settings.LAUNCHER_LOG_PATH.write_text("existing log\\n")
def unavailable(*args):
    raise OSError("no registry")
sys.modules["winreg"] = types.SimpleNamespace(HKEY_LOCAL_MACHINE=0, HKEY_CURRENT_USER=1, OpenKey=unavailable)
class ActiveServicesError(RuntimeError):
    pass
def prepare_update():
    raise ActiveServicesError("fictional service is active")
sys.modules["run"] = types.SimpleNamespace(ActiveServicesError=ActiveServicesError, prepare_update=prepare_update)
sys.argv = [str(settings.LAUNCHER_DIR / "windows_start.pyw"), "--prepare-update"]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as exc:
    assert exc.code == 11
else:
    raise AssertionError("readiness code lost")
if settings.LAUNCHER_LOG_PATH.exists():
    assert "fictional service is active" in settings.LAUNCHER_LOG_PATH.read_text()
else:
    assert not settings.SETTINGS_ROOT.exists()
'''
    subprocess.run([sys.executable, "-c", script, str(tmp_path), str(existing_log)],
                   cwd=Path(settings.__file__).parent, check=True, timeout=10)


@pytest.mark.parametrize("failure", ["corrupt_legacy", "log_open"])
def test_windows_storage_startup_errors_are_visible(tmp_path, failure):
    script = '''
import ctypes, runpy, sys, types
from pathlib import Path
import settings
root = Path(sys.argv[1])
failure = sys.argv[2]
settings.SETTINGS_ROOT = root / "storage"
settings.SETTINGS_PATH = settings.SETTINGS_ROOT / "paths.json"
settings.LAUNCHER_LOG_PATH = settings.SETTINGS_ROOT / "launcher.log"
settings.LEGACY_SETTINGS_PATH = root / "legacy.json"
if failure == "corrupt_legacy":
    settings.LEGACY_SETTINGS_PATH.write_text("{broken")
else:
    settings.SETTINGS_ROOT.mkdir()
    settings.LAUNCHER_LOG_PATH.mkdir()
messages = []
ctypes.windll = types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=lambda *args: messages.append(args)))
sys.modules["winreg"] = types.SimpleNamespace()
sys.argv = [str(settings.LAUNCHER_DIR / "windows_start.pyw")]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except (ValueError, OSError) as exc:
    assert len(messages) == 1
    assert messages[0][1] == str(exc)
else:
    raise AssertionError("startup error was swallowed")
assert not settings.SETTINGS_PATH.exists()
if failure == "corrupt_legacy":
    assert settings.LEGACY_SETTINGS_PATH.read_text() == "{broken"
    assert not settings.LEGACY_SETTINGS_PATH.with_suffix(".json.orig").exists()
'''
    subprocess.run([sys.executable, "-c", script, str(tmp_path), failure],
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
    install_delete = script.split('[InstallDelete]', 1)[1].split('[Files]', 1)[0]
    assert install_delete.strip() == 'Type: filesandordirs; Name: "{app}\\launcher\\runtime\\bun"'
    assert 'runtime\\bun\\*' in script.split('Excludes:', 1)[1].split(';', 1)[0]
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


def test_windows_installer_reuses_environment_and_prepares_pip():
    script = (Path(__file__).resolve().parents[1] / "installer/windows/OpenAlma.iss").read_text(encoding="utf-8")
    preparation = script.split('procedure PrepareLauncher();', 1)[1].split('function InitializeUninstall', 1)[0]
    creation = preparation.split('if not FileExists(VenvPython) then', 1)[1].split('end;', 1)[0]
    assert '-3.12 -m venv' in creation
    assert preparation.count('-3.12 -m venv') == 1
    assert preparation.index('end;') < preparation.index('-m pip install')
    assert preparation.index('end;') < preparation.index('-m ensurepip --upgrade') < preparation.index('-m pip install')


def test_windows_installer_bootstraps_pinned_python_without_winget():
    script = (Path(__file__).resolve().parents[1] / "installer/windows/OpenAlma.iss").read_text(encoding="utf-8")
    prerequisites = script.split("function EnsurePrerequisites(): String;", 1)[1].split("function StopInstalledLauncher", 1)[0]
    assert "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" in script
    assert "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb" in script
    assert "DownloadTemporaryFile(PythonInstallerUrl, PythonInstallerName, PythonInstallerSHA256, nil)" in prerequisites
    assert "/quiet /norestart InstallAllUsers=0 PrependPath=1 Include_launcher=1 InstallLauncherAllUsers=0" in prerequisites
    assert "InstallWithWinget('Python.Python.3.12'" not in script
    assert "if ResultCode = 3010 then" in prerequisites
    assert "Restart Windows, then run OpenAlma Setup again." in prerequisites
    verification = prerequisites.rsplit("PythonLauncher := FindPythonLauncher();", 1)[1]
    assert "RunHidden(PythonLauncher, '-3.12 --version', ResultCode)" in verification
    assert "ResultCode <> 0" in verification
    assert "InstallWithWinget('Git.Git', 'user') and not InstallWithWinget('Git.Git', '')" in script
    assert 'https://git-scm.com/download/win' in prerequisites
    assert 'then run OpenAlma Setup again.' in prerequisites
    winget = script.split('function InstallWithWinget(', 1)[1].split('function EnsurePrerequisites', 1)[0]
    assert 'MsgBox' not in winget


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


def test_installer_prepares_storage_before_selecting_saved_root(tmp_path, monkeypatch):
    root = tmp_path / "private"
    legacy = tmp_path / "old.json"
    saved = tmp_path / "selected"
    legacy.write_text(json.dumps({"apps_root": str(saved), "unknown": 7}))
    monkeypatch.setattr(settings.sys, "platform", "win32")
    monkeypatch.setattr(settings, "SETTINGS_ROOT", root)
    monkeypatch.setattr(settings, "SETTINGS_PATH", root / "paths.json")
    monkeypatch.setattr(settings, "LEGACY_SETTINGS_PATH", legacy)
    monkeypatch.setattr(sys, "argv", ["windows_install.py", "--apps-root", str(root), "--release-tag", "v1.0.0"])
    calls = []
    def configure(selected, tag):
        assert (root / ".openalma-root").exists()
        assert settings.read_paths()["unknown"] == 7
        calls.append((selected, tag))
    monkeypatch.setattr(windows_install, "configure", configure)
    windows_install.main()
    assert calls == [(saved.resolve(), "v1.0.0")]
    assert not saved.exists(), "storage preparation must not claim the saved custom root"


def test_custom_owned_root_upgrade_with_unowned_settings_storage(tmp_path, monkeypatch):
    storage = tmp_path / "private"
    storage.mkdir()
    sentinel = storage / "unrelated.txt"
    sentinel.write_text("keep")
    (storage / "logs").mkdir()
    root = tmp_path / "custom-apps"
    assert setup_install._write_root_marker(root)
    legacy = tmp_path / "legacy.json"
    choices = {"apps_root": str(root), "release_channel": "prerelease", "unknown": {"keep": True}}
    original = json.dumps(choices).encode()
    legacy.write_bytes(original)
    monkeypatch.setattr(settings.sys, "platform", "win32")
    monkeypatch.setattr(settings, "SETTINGS_ROOT", storage)
    monkeypatch.setattr(settings, "SETTINGS_PATH", storage / "paths.json")
    monkeypatch.setattr(settings, "LEGACY_SETTINGS_PATH", legacy)
    monkeypatch.setattr(settings, "PACKAGED_VERSION_PATH", tmp_path / ".openalma-version")
    monkeypatch.setattr(sys, "argv", ["windows_install.py", "--apps-root", str(storage), "--release-tag", "v1.0.0"])
    windows_install.main()
    assert settings.read_paths() == choices
    assert not (storage / ".openalma-root").exists()
    assert sentinel.read_text() == "keep"
    assert (storage / "logs").is_dir()
    assert legacy.with_suffix(".json.orig").read_bytes() == original
    assert not legacy.exists()
    assert (root / windows_install.RELEASE_FILE).read_text().strip() == "v1.0.0"
    settings.prepare_storage()
    with pytest.raises(ValueError, match="Refusing to claim nonempty Apps root"):
        windows_install.configure(storage, "v1.0.0")


def test_remove_everything_accepts_utf8_recorded_root(tmp_path, monkeypatch):
    root = tmp_path / "José" / "OpenAlma"
    root.mkdir(parents=True)
    (root / windows_install.OWNER_FILE).write_text(str(root) + "\n", encoding="utf-8")
    settings_path = tmp_path / "config" / "paths.json"
    settings_path.parent.mkdir()
    settings_path.write_text(json.dumps({"apps_root": str(root)}) + "\n", encoding="utf-8")
    neighbor = settings_path.parent / "unrelated.txt"
    neighbor.write_text("keep")
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    (workspace / "keep.txt").touch()
    settings.BROWSER_PROFILE_PATH.mkdir()
    (settings.BROWSER_PROFILE_PATH / "cookies").touch()
    state_dir = tmp_path / "state" / "logs"
    state_dir.mkdir(parents=True)
    (state_dir / "launcher.log").write_text("old log")
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
    assert settings_path.parent.is_dir()
    assert not settings_path.exists()
    assert neighbor.read_text() == "keep"
    assert (workspace / "keep.txt").exists()
    assert not settings.BROWSER_PROFILE_PATH.exists()
    assert calls[0][1]["onexc"] is not None
    assert unrelated.exists()
    assert not (state_dir / "launcher.log").exists()


@pytest.mark.parametrize("failure", ["child", "directory", "external-log", "profile"])
def test_remove_everything_can_retry_partial_deletion(tmp_path, monkeypatch, failure):
    root = settings.SETTINGS_ROOT if failure in {"child", "directory"} else tmp_path / "apps"
    assert setup_install._write_root_marker(root)
    preferences = {"apps_root": str(root), "unknown": {"preserve": True}}
    settings.write_paths(preferences)
    (root / "payload.txt").write_text("fixture data")
    settings.LAUNCHER_LOG_PATH.write_text("fixture log")
    marker = root / windows_install.OWNER_FILE
    locked = True
    if failure in {"child", "profile"}:
        if failure == "profile":
            settings.BROWSER_PROFILE_PATH.mkdir()
        real_rmtree = windows_remove.shutil.rmtree

        def remove(path, *args, **kwargs):
            target = root if failure == "child" else settings.BROWSER_PROFILE_PATH
            if Path(path) == target and locked:
                if failure == "child":
                    marker.unlink()
                    settings.SETTINGS_PATH.unlink()
                raise PermissionError("fixture locked child")
            return real_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(windows_remove.shutil, "rmtree", remove)
    elif failure == "directory":
        real_rmdir = windows_remove.os.rmdir
        real_chmod = windows_remove.os.chmod
        # Windows chmod does not remove directory traversal permission as POSIX does.
        monkeypatch.setattr(windows_remove.os, "chmod", lambda path, mode:
                            None if Path(path) == root else real_chmod(path, mode))

        def remove(path, *args, **kwargs):
            if Path(path) == root and locked:
                raise PermissionError("fixture locked directory")
            return real_rmdir(path, *args, **kwargs)

        monkeypatch.setattr(windows_remove.os, "rmdir", remove)
    else:
        real_unlink = Path.unlink

        def remove(path, *args, **kwargs):
            if path == settings.LAUNCHER_LOG_PATH and locked:
                settings.SETTINGS_PATH.unlink(missing_ok=True)
                raise PermissionError("fixture locked external log")
            return real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", remove)

    with pytest.raises(PermissionError, match="fixture locked"):
        windows_remove.remove_everything()
    assert marker.read_text(encoding="utf-8").strip() == str(root)
    assert settings.read_paths() == preferences
    assert setup_install._write_root_marker(root), "reinstall must still recognize its owned root"
    locked = False
    windows_remove.remove_everything()
    assert not root.exists()
    assert not settings.SETTINGS_PATH.exists()
    assert not settings.LAUNCHER_LOG_PATH.exists()


def test_remove_everything_cleans_only_known_external_files(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    assert setup_install._write_root_marker(root)
    assert setup_install._write_root_marker(settings.SETTINGS_ROOT)
    workspace = settings.SETTINGS_ROOT / "workspace"
    workspace.mkdir()
    (workspace / "fictional-work.txt").write_text("keep external workspace")
    settings.write_paths({"apps_root": str(root), "workspace": str(workspace)})
    legacy = settings.LEGACY_SETTINGS_PATH
    legacy.parent.mkdir()
    legacy.write_text("old active settings")
    backups = [legacy.with_name(legacy.name + suffix) for suffix in (".orig", "_2.orig", "_10.orig")]
    for path in backups:
        path.write_text("retired settings")
    unrelated = legacy.with_name("paths.json.notes.orig")
    unrelated.write_text("keep unrelated file")
    old_log = settings.SETTINGS_ROOT / "logs/launcher.log"
    old_log.parent.mkdir()
    old_log.write_text("old launcher log")
    neighbor = old_log.parent / "unrelated.log"
    neighbor.write_text("keep unrelated log")
    cache = windows_remove.LAUNCHER_UPDATE_DIR
    cache.mkdir()
    installers = [cache / name for name in ("OpenAlma-v0.1.21-Windows.exe", "OpenAlma-v0.1.22-Windows.exe.part")]
    for path in installers:
        path.write_text("fictional installer")
    other_download = cache / "other-app.exe"
    other_download.write_text("keep unrelated download")
    malformed = [cache / name for name in ("OpenAlma-v1.2.3--notes-Windows.exe", "OpenAlma-v1.2.3-.-Windows.exe")]
    for path in malformed:
        path.write_text("not a generated installer name")

    windows_remove.remove_everything()

    assert not root.exists()
    assert not legacy.exists() and not any(path.exists() for path in backups)
    assert not old_log.exists() and not any(path.exists() for path in installers)
    assert unrelated.read_text() == "keep unrelated file"
    assert neighbor.read_text() == "keep unrelated log"
    assert other_download.read_text() == "keep unrelated download"
    assert all(path.exists() for path in malformed)
    assert (workspace / "fictional-work.txt").read_text() == "keep external workspace"


@pytest.mark.parametrize("location", ["root", "profile"])
def test_remove_everything_does_not_chmod_external_link_targets(tmp_path, monkeypatch, location):
    # Match Windows' rmtree backend rather than POSIX's nested fd callbacks.
    monkeypatch.setattr(windows_remove.shutil, "_use_fd_functions", False)
    root = tmp_path / "apps"
    assert setup_install._write_root_marker(root)
    settings.write_paths({"apps_root": str(root)})
    workspace = tmp_path / "external-workspace"
    workspace.mkdir()
    (workspace / "keep.txt").write_text("keep external work")
    mode = workspace.stat().st_mode
    link = root / "workspace-link" if location == "root" else settings.BROWSER_PROFILE_PATH
    try:
        link.symlink_to(workspace, target_is_directory=True)
    except OSError:
        pytest.skip("This environment cannot create a directory symlink")
    real_unlink = windows_remove.os.unlink
    locked = True

    def unlink(path, *args, **kwargs):
        if Path(path).name == link.name and locked:
            raise PermissionError("fixture locked symlink")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(windows_remove.os, "unlink", unlink)
    with pytest.raises(PermissionError, match="fixture locked symlink"):
        windows_remove.remove_everything()
    assert workspace.stat().st_mode == mode
    assert (workspace / "keep.txt").read_text() == "keep external work"
    locked = False
    windows_remove.remove_everything()
    assert workspace.stat().st_mode == mode
    assert (workspace / "keep.txt").read_text() == "keep external work"


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


def test_candidate_installer_version_uses_validated_environment_not_script_interpolation():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/windows-installer.yml"
    job = yaml.safe_load(path.read_text())["jobs"]["build"]
    select = next(step["run"] for step in job["steps"] if step.get("name") == "Select installer version")
    build = next(step["run"] for step in job["steps"] if step.get("name") == "Build installer")
    assert r"\Av[0-9]+\.[0-9]+\.[0-9]+\z" in select
    assert '$env:BUILD_REF_NAME' in select and "'v0.0.0-dev'" in select
    assert '"INSTALLER_VERSION=$tag"' in select
    assert '$tag = $env:INSTALLER_VERSION' in build
    assert '$env:BUILD_REF_TYPE -eq "tag" -or $env:CANDIDATE_VERSION' in build
    assert '${{ inputs.' not in select + build and '${{ github.ref_' not in select + build
