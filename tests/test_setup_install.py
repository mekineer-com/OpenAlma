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


def test_discover_release_rejects_prerelease(tmp_path, monkeypatch):
    monkeypatch.setattr(
        setup_install,
        "_request_json",
        lambda _url: {"tag_name": "v1.0.0", "draft": False, "prerelease": True},
    )

    with pytest.raises(setup_install.SetupError, match="No supported stable"):
        setup_install.discover_release(tmp_path)


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
