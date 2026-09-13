import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import setup_install  # noqa: E402


def _manifest(**entry_changes):
    mcp = {
        "repository": "https://github.com/mekineer-com/mcp-memu-server.git",
        "ref": "v1.0.0",
        "destination": "mcp-memu-server",
    }
    mcp.update(entry_changes)
    return {
        "schema_version": 1,
        "services": {
            "memu-server": {
                "repositories": [
                    mcp,
                    {
                        "repository": "https://github.com/mekineer-com/memU.git",
                        "ref": "v1.0.0",
                        "destination": "memu",
                    },
                ],
            },
        },
    }


def test_manifest_requires_safe_exact_core_entries(tmp_path):
    parsed = setup_install.validate_manifest(_manifest(), tmp_path)
    assert [entry["destination"] for entry in parsed["memu-server"]] == ["mcp-memu-server", "memu"]

    with pytest.raises(setup_install.SetupError, match="Unsafe destination"):
        setup_install.validate_manifest(_manifest(destination="../outside"), tmp_path)
    with pytest.raises(setup_install.SetupError, match="Unsupported repository URL"):
        setup_install.validate_manifest(_manifest(repository="file:///tmp/source"), tmp_path)
    invalid = _manifest()
    invalid["extra"] = True
    with pytest.raises(setup_install.SetupError, match="only schema_version and services"):
        setup_install.validate_manifest(invalid, tmp_path)

    unexpected = _manifest()
    unexpected["services"]["atomic"] = {
        "repositories": [{
            "repository": "https://github.com/kenforthewin/atomic.git",
            "ref": "v1.0.0",
            "destination": "somewhere-else",
        }],
    }
    with pytest.raises(setup_install.SetupError, match="unexpected destinations for atomic"):
        setup_install.validate_manifest(unexpected, tmp_path)

    unexpected = _manifest()
    unexpected["services"]["iris-server"] = {
        "repositories": [{
            "repository": "https://github.com/mekineer-com/iris.git",
            "ref": "v1.0.0",
            "destination": "iris-somewhere-else",
        }],
    }
    with pytest.raises(setup_install.SetupError, match="unexpected destinations for iris-server"):
        setup_install.validate_manifest(unexpected, tmp_path)


def test_discover_release_rejects_prerelease(tmp_path, monkeypatch):
    monkeypatch.setattr(
        setup_install,
        "_request_json",
        lambda _url: {"tag_name": "v1.0.0", "draft": False, "prerelease": True},
    )

    with pytest.raises(setup_install.SetupError, match="No supported stable"):
        setup_install.discover_release(tmp_path)


def test_iris_uses_its_independent_stable_release(tmp_path, monkeypatch):
    monkeypatch.setattr(
        setup_install,
        "_request_json",
        lambda url: {"tag_name": "v2.0.0", "draft": False, "prerelease": False},
    )

    assert setup_install.iris_release_entry(tmp_path) == {
        "repository": "https://github.com/mekineer-com/iris.git",
        "ref": "v2.0.0",
        "destination": "mentra-os/miniapps/openalma",
    }

    monkeypatch.setattr(setup_install.settings, "LAUNCHER_DIR", tmp_path / "launcher")
    with pytest.raises(setup_install.SetupError, match="Unsafe destination"):
        setup_install.iris_release_entry(tmp_path)


def test_write_config_sets_shared_paths_once(tmp_path):
    server = tmp_path / "mcp-memu-server"
    server.mkdir()
    example = _manifest()
    example = {
        "memu": {"path": "wrong"},
        "storage": {
            "resources_dir": "wrong",
            "metadata_store": {"dsn": "wrong"},
            "sqlite_dir": "wrong",
        },
        "unrelated": {"keep": True},
    }
    (server / "config.example.json").write_text(json.dumps(example), encoding="utf-8")

    setup_install._write_config(tmp_path)
    created = json.loads((server / "config.json").read_text(encoding="utf-8"))
    assert created["memu"]["path"] == "../memu/src"
    assert created["storage"] == {
        "resources_dir": "../memu/resources",
        "metadata_store": {"dsn": "../memu/sqlite/memu.db"},
        "sqlite_dir": "../memu/sqlite",
    }
    assert created["unrelated"] == {"keep": True}

    (server / "config.example.json").write_text("{}", encoding="utf-8")
    setup_install._write_config(tmp_path)
    assert json.loads((server / "config.json").read_text(encoding="utf-8")) == created

    created["memu"]["path"] = str(tmp_path / "custom-memu")
    (server / "config.json").write_text(json.dumps(created), encoding="utf-8")
    assert setup_install._config_ready(tmp_path) is True


def test_clone_failure_removes_only_current_staging_directory(tmp_path, monkeypatch):
    entry = {
        "repository": "https://github.com/mekineer-com/memU.git",
        "ref": "v1.0.0",
        "destination": "memu",
    }
    monkeypatch.setattr(
        setup_install,
        "_run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "git")),
    )

    with pytest.raises(subprocess.CalledProcessError):
        setup_install._clone(entry, tmp_path, None)

    assert list(tmp_path.glob(".openalma-memu-*")) == []
    assert not (tmp_path / "memu").exists()


def test_clone_reports_crash_left_staging_without_deleting_it(tmp_path):
    leftover = tmp_path / ".openalma-memu-old"
    leftover.mkdir()
    entry = {
        "repository": "https://github.com/mekineer-com/memU.git",
        "ref": "v1.0.0",
        "destination": "memu",
    }

    with pytest.raises(setup_install.SetupError, match="Inspect and remove"):
        setup_install._clone(entry, tmp_path, None)

    assert leftover.exists()


def test_clone_publishes_and_reuses_exact_tagged_checkout(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    commands = (
        ["git", "init", "-q"],
        ["git", "config", "user.name", "Fictional Developer"],
        ["git", "config", "user.email", "fictional@example.invalid"],
    )
    for command in commands:
        subprocess.run(command, cwd=source, check=True)
    (source / "README.md").write_text("fictional fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=source, check=True)
    subprocess.run(["git", "tag", "v1.0.0"], cwd=source, check=True)
    root = tmp_path / "apps"
    root.mkdir()
    entry = {"repository": str(source), "ref": "v1.0.0", "destination": "memu"}

    with (tmp_path / "install.log").open("w", encoding="utf-8") as log:
        setup_install._clone(entry, root, log)
        setup_install._clone(entry, root, log)

    assert (root / "memu" / "README.md").read_text(encoding="utf-8") == "fictional fixture\n"
    assert not list(root.glob(".openalma-memu-*"))


def test_begin_core_install_reuses_active_operation(tmp_path, monkeypatch):
    started = threading.Event()
    finish = threading.Event()

    def fake_install(_operation):
        started.set()
        finish.wait(timeout=2)

    monkeypatch.setattr(setup_install, "_OPERATION", None)
    monkeypatch.setattr(setup_install, "_prerequisite_issue", lambda _root: "")
    monkeypatch.setattr(setup_install, "_install_core", fake_install)

    first = setup_install.begin_core_install(tmp_path)
    assert started.wait(timeout=1)
    second = setup_install.begin_core_install(tmp_path)
    with pytest.raises(setup_install.SetupError, match="already running"):
        setup_install.begin_core_install(tmp_path / "other")
    finish.set()
    setup_install._OPERATION.thread.join(timeout=1)

    assert first["state"] == "running"
    assert second["state"] == "running"


def test_core_retry_reuses_recorded_release(tmp_path, monkeypatch):
    operation = setup_install.InstallOperation(service_name="memu-server", root=tmp_path)
    manifest = {"memu-server": [{"destination": "memu"}]}
    writes = []
    monkeypatch.setattr(setup_install, "_OPERATION", operation)
    monkeypatch.setattr(setup_install, "install_log_path", lambda _name: tmp_path / "install.log")
    (tmp_path / ".openalma-release").write_text("v1.0.0\n", encoding="utf-8")
    monkeypatch.setattr(setup_install.settings, "read_paths", lambda: {
        "apps_root": str(tmp_path), "openalma_release_tag": "v1.0.0", "other": True,
    })
    monkeypatch.setattr(setup_install.settings, "write_paths", lambda value: writes.append(value.copy()))
    monkeypatch.setattr(setup_install, "recorded_manifest", lambda _root: manifest)
    monkeypatch.setattr(setup_install, "discover_release", lambda _root: pytest.fail("retry rescanned newest"))
    monkeypatch.setattr(setup_install, "_clone", lambda *_args: None)
    monkeypatch.setattr(setup_install, "_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(setup_install, "_write_config", lambda _root: None)
    monkeypatch.setattr(setup_install, "core_issue", lambda _root: "")

    setup_install._install_core(operation)

    assert writes == [{
        "apps_root": str(tmp_path), "other": True,
    }]
    assert operation.state == "ready"


def test_release_selection_belongs_to_each_apps_root(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    setup_install._write_recorded_release(first, "v1.0.0")

    assert setup_install.read_recorded_release(first) == "v1.0.0"
    assert setup_install.read_recorded_release(second) is None


def test_windows_package_shim_uses_comspec(monkeypatch):
    monkeypatch.setattr(setup_install.shutil, "which", lambda _tool: r"C:\Tools\bun.cmd")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")

    command = setup_install._package_command("bun", "install", "--frozen-lockfile", windows=True)

    assert command[:4] == [r"C:\Windows\System32\cmd.exe", "/d", "/s", "/c"]
    assert "bun.cmd" in command[4]


def test_optional_status_stops_at_real_manual_prerequisite(tmp_path, monkeypatch):
    atomic = tmp_path / "atomic"
    (atomic / "node_modules/vite").mkdir(parents=True)
    (atomic / "node_modules/vite/package.json").write_text("{}", encoding="utf-8")
    (atomic / "package.json").write_text(json.dumps({"devDependencies": {"vite": "1"}}), encoding="utf-8")
    monkeypatch.setattr(setup_install, "_OPERATION", None)
    monkeypatch.setattr(setup_install.shutil, "which", lambda _tool: "/usr/bin/npm")

    status = setup_install.optional_setup_status("atomic", tmp_path)

    assert status["status_label"] == "Installation incomplete"
    assert status["action_kind"] is None
    assert "compile guidance" in status["detail"]


def test_partial_node_modules_is_not_setup_complete(tmp_path):
    package = tmp_path / "client"
    (package / "node_modules").mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({"dependencies": {"missing-package": "1"}}), encoding="utf-8")

    assert setup_install._node_dependencies_ready(package) is False


def test_optional_status_allows_clone_before_missing_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_install, "_OPERATION", None)
    monkeypatch.setattr(setup_install.shutil, "which", lambda _tool: None)

    status = setup_install.optional_setup_status("channels-daemon", tmp_path)

    assert status["status_label"] == "Not installed"
    assert status["action_kind"] == "install"


def test_sillytavern_can_start_before_integration_setup_finishes(tmp_path):
    stock = tmp_path / "sillytavern/SillyTavern"
    (stock / "node_modules").mkdir(parents=True)
    (stock / "package.json").write_text(json.dumps({"dependencies": {}}), encoding="utf-8")
    (stock / "server.js").write_text("", encoding="utf-8")

    assert setup_install.start_issue("sillytavern", tmp_path) == ""
    assert "memU server plugin" in setup_install.optional_issue("sillytavern", tmp_path)


def test_optional_worker_uses_shared_clone_and_command_pipeline(tmp_path, monkeypatch):
    operation = setup_install.InstallOperation(service_name="sillytavern", root=tmp_path)
    cloned = []
    commands = []
    stock = {
        "repository": "https://github.com/SillyTavern/SillyTavern.git",
        "ref": "1.0.0",
        "destination": "sillytavern/SillyTavern",
    }
    plugin = {
        "repository": "https://github.com/mekineer-com/hermes-channels.git",
        "ref": "v1.0.0",
        "destination": "sillytavern/SillyTavern/plugins/memu-plugin",
    }
    monkeypatch.setattr(setup_install, "_OPERATION", operation)
    monkeypatch.setattr(setup_install, "install_log_path", lambda _name: tmp_path / "install.log")
    monkeypatch.setattr(setup_install, "_optional_entries", lambda _name, _root: [plugin, stock])
    monkeypatch.setattr(setup_install, "_clone", lambda item, _root, _log: cloned.append(item))
    monkeypatch.setattr(setup_install, "_optional_tool_issue", lambda _name: "")
    monkeypatch.setattr(setup_install, "_optional_commands", lambda _name, _root: [(["npm", "ci"], tmp_path)])
    monkeypatch.setattr(setup_install, "_run", lambda command, **_kwargs: commands.append(command))
    monkeypatch.setattr(setup_install, "optional_issue", lambda _name, _root: "")

    setup_install._install_optional(operation)

    assert cloned == [stock, plugin]
    assert commands == [["npm", "ci"]]
    assert operation.state == "ready"


def test_install_lock_excludes_another_process_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(setup_install, "INSTALL_LOCK", tmp_path / "install.lock")
    handle = setup_install._acquire_install_lock()
    try:
        with pytest.raises(setup_install.SetupError, match="already running"):
            setup_install._acquire_install_lock()
    finally:
        setup_install._release_install_lock(handle)


def test_operation_worker_reports_early_failure_and_releases_lock(tmp_path, monkeypatch):
    operation = setup_install.InstallOperation(service_name="atomic", root=tmp_path, lock_handle=object())
    released = []
    monkeypatch.setattr(setup_install, "_OPERATION", operation)
    monkeypatch.setattr(setup_install, "_release_install_lock", lambda handle: released.append(handle))

    setup_install._operation_worker(operation, lambda _operation: (_ for _ in ()).throw(OSError("log failure")))

    assert operation.state == "error"
    assert operation.detail == "log failure"
    assert released == [operation.lock_handle]
