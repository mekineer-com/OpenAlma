import json
import os
import subprocess
import sys
import threading
from types import SimpleNamespace
import time
import venv
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import services  # noqa: E402


@pytest.mark.parametrize("operation", ["read", "write"])
def test_pid_cleanup_waits_for_file_handles(tmp_path, monkeypatch, operation):
    spec = services.ServiceSpec("fixture", "Fixture", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    spec.pid_path.write_text("123")
    opened, release, attempting, done = (threading.Event() for _ in range(4))
    errors = []
    method = "read_text" if operation == "read" else "write_text"
    original = getattr(Path, method)

    def held_io(path, *args, **kwargs):
        opened.set()
        assert release.wait(2)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, method, held_io)

    def work():
        try:
            if operation == "read":
                services._read_pid(spec.pid_path)
            else:
                services._remember_verified_pid(spec, 456)
        except Exception as exc:
            errors.append(exc)

    def cleanup():
        attempting.set()
        try:
            services._clear_pid(spec)
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()

    worker, cleaner = threading.Thread(target=work), threading.Thread(target=cleanup)
    worker.start()
    try:
        assert opened.wait(2)
        cleaner.start()
        assert attempting.wait(2)
        assert not done.wait(0.05)
    finally:
        release.set()
        worker.join(2)
        if cleaner.ident is not None:
            cleaner.join(2)
    assert not worker.is_alive() and not cleaner.is_alive()
    assert errors == []
    assert not spec.pid_path.exists()


def test_pid_cleanup_does_not_hide_permission_errors(tmp_path, monkeypatch):
    def denied(_path):
        raise PermissionError("Fixture file permission")

    monkeypatch.setattr(Path, "unlink", denied)
    with pytest.raises(PermissionError, match="Fixture file permission"):
        services._clear_pid(SimpleNamespace(pid_path=tmp_path / "pid"))


@pytest.fixture
def iris_preparation(tmp_path, monkeypatch):
    import app
    from threading import Event, Lock

    config = tmp_path / "mcp-memu-server/config.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"mentra": {}}))
    status = {"state": "ready", "installations": [{"device_session_id": "fictional-phone",
              "host_reporting": True, "host": {"host_package": "com.mentra.mentra.openalma"}}]}
    calls = []
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.setup_install, "_OPERATIONS", {})
    monkeypatch.setattr(app.setup_install, "core_issue", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(services, "_IRIS_INSTALL_LOCK", Lock())
    monkeypatch.setattr(services, "_read_mentra_status", lambda _port: status)
    monkeypatch.setattr(services, "raise_if_stopping", lambda _spec: None)
    monkeypatch.setattr(services, "raise_if_iris_installer_busy", lambda _spec: None)
    monkeypatch.setattr(app.setup_install, "optional_issue", lambda *_args: "Missing Iris checkout")
    monkeypatch.setattr(app.setup_install, "release_issue", lambda *_args, **_kwargs: "")
    monkeypatch.setattr(app.setup_install, "_iris_workspace_issue", lambda _root: "")
    monkeypatch.setattr(app.setup_install, "_OPERATION", None)
    def begin(name, root, **kwargs):
        calls.append((name, root))
        operation = app.setup_install.InstallOperation(service_name=name, root=root)
        app.setup_install._OPERATIONS[name] = operation
        return operation
    monkeypatch.setattr(app.setup_install, "begin_optional_install", begin)
    return app, tmp_path, config, status, calls, Event()


def test_connected_phone_prepares_once_without_installing_on_phone(iris_preparation, monkeypatch):
    app, root, _config, _status, calls, stop = iris_preparation
    monkeypatch.setattr(services, "start", lambda *_args, **_kwargs: pytest.fail("Preparation must not install on a phone"))
    app._prepare_iris_if_needed(stop)
    app._prepare_iris_if_needed(stop)
    assert calls == [("iris-server", root)]
    assert app.setup_install.operation_status(root, "iris-server")["state"] == "running"


@pytest.mark.parametrize("block", ["stale", "unavailable", "core", "recovery", "ready", "shutdown"])
def test_iris_automatic_preparation_defers_when_not_eligible(iris_preparation, monkeypatch, block):
    app, root, config, status, calls, stop = iris_preparation
    if block == "stale":
        status["installations"][0]["host_reporting"] = False
    elif block == "unavailable":
        status["state"] = "unavailable"
    elif block == "core":
        monkeypatch.setattr(app.setup_install, "release_issue", lambda *_args: "Core update required first")
    elif block == "recovery":
        (root / app.setup_install.RECOVERY_FILE).touch()
    elif block == "ready":
        monkeypatch.setattr(app.setup_install, "optional_issue", lambda *_args: "")
    else:
        stop.set()
    if block in {"stale", "unavailable", "shutdown"}:
        monkeypatch.setattr(app.setup_install, "release_issue", lambda *_args: pytest.fail("No release Git checks before an eligible phone"))
    app._prepare_iris_if_needed(stop)
    assert calls == [] and app.setup_install.operation_status(root, "iris-server")["state"] == "idle"


def test_opening_setup_does_not_prepare_without_a_reported_phone(iris_preparation, monkeypatch):
    from fastapi.testclient import TestClient
    app, root, _config, status, calls, stop = iris_preparation
    status["installations"] = []
    monkeypatch.setattr(app, "_setup_aware_status", lambda *_args, **_kwargs: {"installations": [], "setup": {"ready": False, "rows": []}})
    assert TestClient(app.app, base_url="http://127.0.0.1").get("/iris").status_code == 200
    app._prepare_iris_if_needed(stop)
    assert not calls


def test_preparation_conflict_defers_without_latching_failure(iris_preparation, monkeypatch):
    app, root, _config, _status, calls, stop = iris_preparation
    with services._IRIS_INSTALL_LOCK:
        app._prepare_iris_if_needed(stop)
    assert not calls
    begin = app.setup_install.begin_optional_install
    monkeypatch.setattr(app.setup_install, "begin_optional_install", lambda *_args, **_kwargs: (_ for _ in ()).throw(app.setup_install.SetupConflict("Other installation")))
    app._prepare_iris_if_needed(stop)
    assert app.setup_install.operation_status(root, "iris-server")["state"] == "idle"
    monkeypatch.setattr(app.setup_install, "begin_optional_install", begin)
    app._prepare_iris_if_needed(stop)
    assert calls == [("iris-server", root)]


def test_phone_install_rechecks_preparation_under_iris_lock(tmp_path, monkeypatch):
    import app
    from threading import Lock

    monkeypatch.setattr(services, "_IRIS_INSTALL_LOCK", Lock())
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    def blocked(_name):
        assert services._IRIS_INSTALL_LOCK.locked()
        raise app.HTTPException(status_code=409, detail="Preparation running")
    monkeypatch.setattr(app, "_require_startable_setup", blocked)
    monkeypatch.setattr(services, "iris_installation_request", lambda **_kwargs: pytest.fail("Must not reserve a ticket"))
    with pytest.raises(app.HTTPException, match="Preparation running"):
        app._start_iris_install(spec, "fictional-phone", "com.mentra.mentra.openalma")
    assert not services._IRIS_INSTALL_LOCK.locked()


def test_iris_status_keeps_phone_discovery_available_without_checkout(iris_preparation, monkeypatch):
    from fastapi.testclient import TestClient
    app, root, _config, status, _calls, _stop = iris_preparation
    spec = services.ServiceSpec("iris-server", "Iris", [], root, root / "log", root / "pid", install_marker=root / "missing")
    monkeypatch.setattr(services, "all_services", lambda: [spec])
    monkeypatch.setattr(services, "status", lambda _spec: {"running": False, **status})
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda *_args: {"ready": False, "state": "setup", "action_kind": "install"})
    response = TestClient(app.app, base_url="http://127.0.0.1").get("/service/iris-server/status")
    assert response.status_code == 200
    assert response.json()["installations"][0]["device_session_id"] == "fictional-phone"
    assert response.json()["ready"] is False


def test_preparation_watcher_survives_discovery_errors(iris_preparation, monkeypatch, caplog):
    app, _root, _config, _status, _calls, _stop = iris_preparation
    turns = []
    class Stop:
        def wait(self, _seconds):
            return len(turns) >= 2
    def prepare(_stop):
        turns.append(True)
        if len(turns) == 1:
            raise OSError("Fictional discovery failure")
    monkeypatch.setattr(app, "_prepare_iris_if_needed", prepare)
    app._watch_iris_preparation(Stop())
    assert len(turns) == 2
    assert "Fictional discovery failure" in caplog.text


@pytest.mark.parametrize("failed", [False, True])
def test_stock_install_prepares_transparently_before_phone_work(iris_preparation, monkeypatch, failed):
    app, root, _config, _status, _calls, _stop = iris_preparation
    steps = []
    spec = services.ServiceSpec("iris-server", "Iris", [], root, root / "log", root / "pid")
    operation = app.setup_install.InstallOperation(service_name="iris-server", root=root,
                                                  state="error" if failed else "ready", detail="Fictional preparation failure")
    class Thread:
        def join(self):
            steps.append("prepared")
    operation.thread = Thread()
    monkeypatch.setattr(app, "_find_service", lambda _name: spec)
    monkeypatch.setattr(app, "_require_startable_setup", lambda _name: (_ for _ in ()).throw(app.HTTPException(status_code=409, detail="Missing tools")))
    monkeypatch.setattr(app, "_begin_iris_preparation", lambda _root: operation)
    monkeypatch.setattr(services, "services_for_root", lambda _root: [spec])
    monkeypatch.setattr(services, "_MENTRA_READINESS_CACHE", {str(root): (services.time.monotonic(), {"ready": False})})
    def start(*_args, **_kwargs):
        assert services._MENTRA_READINESS_CACHE == {}
        steps.append("phone-install")
    monkeypatch.setattr(app, "_start_iris_install", start)
    if failed:
        with pytest.raises(app.HTTPException, match="Fictional preparation failure"):
            app.iris_install("", "")
        assert steps == ["prepared"]
    else:
        assert app.iris_install("", "").status_code == 303
        assert steps == ["prepared", "phone-install"]


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"threshold": 5000}'


def test_hermes_gateway_is_retired_from_launcher_services(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    for name in ("mcp-memu-server", "atomic", "hermes-channels", "sillytavern"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)

    specs = services.all_services()
    names = [spec.name for spec in specs]
    labels = {spec.name: spec.label for spec in specs}
    open_urls = {spec.name: spec.open_url for spec in specs}

    assert "hermes-gateway" not in names
    assert "channels-daemon" in names
    assert "whatsapp-bridge" not in names
    assert "whatsapp-web-source" not in names
    assert labels == {
        "memu-server": "memU Server",
        "iris-server": "Mentra Iris",
        "atomic": "Atomic Mind Map",
        "channels-daemon": "Hermes Channels",
        "sillytavern": "SillyTavern",
    }
    assert open_urls["atomic"] == "http://127.0.0.1:1420"
    assert open_urls["sillytavern"] == "http://127.0.0.1:8000"
    assert next(spec for spec in specs if spec.name == "sillytavern").port == 8000
    assert next(spec for spec in specs if spec.name == "sillytavern").cmd[-2:] == [
        "server.js", "--browserLaunchEnabled=false",
    ]
    assert next(spec for spec in specs if spec.name == "sillytavern").env == {
        "SILLYTAVERN_ENABLESERVERPLUGINS": "true",
        "SILLYTAVERN_ENABLESERVERPLUGINSAUTOUPDATE": "false",
        "MEMU_SERVER_PATH": str(root / "mcp-memu-server"),
        "MEMU_SERVER_MANAGED": "launcher",
    }


def test_services_can_be_built_for_pending_root(tmp_path):
    specs = services.services_for_root(tmp_path)

    assert [spec.name for spec in specs] == [
        "memu-server", "iris-server", "atomic", "channels-daemon", "sillytavern",
    ]
    assert specs[0].cwd == tmp_path / "mcp-memu-server"
    assert services.is_installed(specs[0]) is False


def test_iris_server_is_managed_by_launcher(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    bun = root / ".tools" / "bun"
    monkeypatch.setattr(services.settings, "bun_binary", lambda _root: bun)
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")

    specs = services.all_services()
    spec = next(s for s in specs if s.name == "iris-server")
    channels = next(s for s in specs if s.name == "channels-daemon")

    assert spec.cwd == root / "mentra-os" / "miniapps" / "openalma"
    assert spec.cmd[-1] == "scripts/release-private.mjs"
    assert spec.cmd[0] == str(bun)
    assert Path(spec.env["PATH"].split(services.os.pathsep, 1)[0]) == bun.parent
    assert spec.port == 6789
    assert channels.env["CHANNELS_HOME"] == str(tmp_path / "channels_data")


@pytest.mark.parametrize("stage,host_package", [
    (stage, host) for stage in ("bundle", "download", "spawn", "stop", "force_stop")
    for host in ("com.mentra.mentra", "com.mentra.mentra.openalma")
] + [("cleanup", "com.mentra.mentra")])
def test_iris_install_target_cleanup(tmp_path, monkeypatch, stage, host_package):
    import app as launcher_app

    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    target = {"device_session_id": "stock-test", "host_package": host_package, "display_name": "stock_01"}
    reservation = {"installation_ticket": "stock-ticket", "device_session_id": "stock-test", "display_name": "stock_01", "user_id": "TestOwner"}
    prepared = {**target, **reservation} if host_package == "com.mentra.mentra" else target
    requests = []

    def installation_request(device_session_id="", display_name=None, *, reserve=False):
        requests.append((device_session_id, reserve))
        if not reserve and stage == "cleanup":
            raise OSError("Fictional ticket cleanup failure")
        return reservation if reserve else {"ok": True}

    monkeypatch.setattr(services, "iris_installation_request", installation_request)
    target_path = tmp_path / "build/release-private-status.json"
    monkeypatch.setattr(launcher_app, "_find_service", lambda _name: spec)
    monkeypatch.setattr(launcher_app, "_require_startable_setup", lambda _name: None)
    monkeypatch.setattr(services, "mentra_readiness", lambda: {"ready": True})
    monkeypatch.setattr(services, "STATE_DIR", tmp_path)
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState())
    monkeypatch.setattr(services, "_iris_build_env", lambda *_args: {})
    monkeypatch.setattr(services, "_read_mentra_status", lambda *_args, **_kwargs: {
        "state": "ready", "installations": [{**target, **({"host": {"host_package": host_package}} if host_package == "com.mentra.mentra.openalma" else {})}],
    })
    monkeypatch.setattr(services, "_iris_release_candidate", lambda _spec: (
        services.IRIS_PACKAGE, "0.1.0", None if stage == "bundle" else "https://example.invalid/iris.zip", "available",
    ))

    def download(*_args):
        assert services._IRIS_INSTALL_LOCK.locked()
        assert json.loads(target_path.read_text()) == prepared
        if stage == "download":
            raise OSError("Fictional download failure")
        if stage in {"stop", "force_stop"}:
            getattr(services, stage)(spec)
        return tmp_path / "iris.zip"

    def spawn(_spec, env):
        assert stage in {"spawn", "cleanup"}
        assert services._IRIS_INSTALL_LOCK.locked()
        assert json.loads(target_path.read_text()) == prepared
        assert env["MENTRA_RELEASE_BUNDLE"] == str(tmp_path / "iris.zip")
        raise OSError("Fictional spawn failure")

    monkeypatch.setattr(services, "_download_iris_release", download)
    monkeypatch.setattr(services, "_spawn_background", spawn)

    message = "Published Iris bundle unavailable" if stage == "bundle" else "Iris installation cancelled" if stage in {"stop", "force_stop"} else f"Fictional {'spawn' if stage == 'cleanup' else stage} failure"
    with pytest.raises(launcher_app.HTTPException, match=message) as error:
        launcher_app.iris_install("stock-test", host_package)
    assert error.value.status_code == (409 if stage in {"stop", "force_stop"} else 400)
    assert not target_path.exists()
    assert not spec.pid_path.exists()
    assert not target_path.with_suffix(".tmp").exists()
    assert not services._IRIS_INSTALL_LOCK.locked()
    assert requests == ([("stock-test", True), ("stock-ticket", False)] if host_package == "com.mentra.mentra" else [])
    assert target["device_session_id"] == "stock-test"


def test_iris_repair_bundle_choices_do_not_require_latest_github(tmp_path, monkeypatch):
    from zipfile import ZipFile
    spec = services.ServiceSpec("iris-server", "Iris", ["/fictional/bun"], tmp_path, tmp_path / "log", tmp_path / "pid")
    manifest = {"packageName": services.IRIS_PACKAGE, "version": "0.1.12",
                "name": "Test Iris", "hardwareRequirements": [],
                "entry": {"background": "background/index.js", "ui": "ui/index.html"}}

    def write_bundle(path, data=manifest):
        with ZipFile(path, "w") as bundle:
            bundle.writestr("miniapp.json", json.dumps(data))
            bundle.writestr("background/index.js", "background")
            bundle.writestr("ui/index.html", "ui")

    monkeypatch.setattr(services, "STATE_DIR", tmp_path)
    monkeypatch.setattr(services.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0))
    original = tmp_path / "original.zip"
    write_bundle(original)
    monkeypatch.setattr(services, "iris_repair_releases", lambda: pytest.fail("ZIP/source must bypass GitHub"))
    uploaded = services.prepare_iris_repair(spec, "zip", "", "", BytesIO(original.read_bytes()))
    assert services._validate_iris_repair_bundle(uploaded, spec) == manifest
    source = tmp_path / "source"
    source.mkdir()
    (source / "miniapp.json").write_text(json.dumps(manifest))

    def build(command, **kwargs):
        if "validateManifest" in command[2]:
            assert json.loads(kwargs["input"]) == manifest
            return subprocess.CompletedProcess(command, 0)
        assert command[-2:] == [str(source), str(tmp_path / "iris-repair")]
        assert kwargs["cwd"] == spec.cwd
        write_bundle(tmp_path / "iris-repair" / f"{services.IRIS_PACKAGE}-0.1.12.zip")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(services.subprocess, "run", build)
    assert services.prepare_iris_repair(spec, "source", "", str(source), None).exists()
    monkeypatch.setattr(services, "iris_repair_releases", lambda: {"0.1.12": "https://example.invalid/iris.zip"})
    monkeypatch.setattr(services, "_download_iris_release", lambda url, package, version: original)
    assert services.prepare_iris_repair(spec, "github", "0.1.12", "", None) == original
    write_bundle(original, {**manifest, "packageName": "wrong-package"})
    with pytest.raises(ValueError, match="valid package"):
        services.prepare_iris_repair(spec, "zip", "", "", BytesIO(original.read_bytes()))


def test_iris_repair_preserves_target_lock_and_rechecks_sitting(tmp_path, monkeypatch):
    import app as launcher_app
    monkeypatch.setattr(launcher_app, "_require_startable_setup", lambda _name: None)
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    target = {"device_session_id": "test-phone", "host_package": "com.mentra.mentra.openalma"}
    busy = False
    calls = []
    monkeypatch.setattr(services, "raise_if_stopping", lambda _spec: None)
    monkeypatch.setattr(services, "raise_if_iris_installer_busy", lambda _spec: None)
    monkeypatch.setattr(services, "mentra_readiness", lambda: {"ready": True})

    def selected(device, host):
        assert (device, host) == (target["device_session_id"], target["host_package"])
        if busy:
            raise launcher_app.HTTPException(409, "Stop Iris")
        return target.copy()

    def prepare(*_args):
        assert services._IRIS_INSTALL_LOCK.locked()
        return tmp_path / "local.zip"

    monkeypatch.setattr(launcher_app, "_iris_install_target", selected)
    monkeypatch.setattr(services, "prepare_iris_repair", prepare)
    monkeypatch.setattr(services, "start", lambda _spec, **kwargs: calls.append(kwargs))
    launcher_app._start_iris_install(spec, **target, repair_options=("zip", "", ""))
    assert calls == [{"install_target": target, "bundle_path": tmp_path / "local.zip"}]
    assert not services._IRIS_INSTALL_LOCK.locked()

    def prepare_while_sitting_starts(*_args):
        nonlocal busy
        busy = True
        return tmp_path / "local.zip"

    monkeypatch.setattr(services, "prepare_iris_repair", prepare_while_sitting_starts)
    with pytest.raises(launcher_app.HTTPException, match="Stop Iris"):
        launcher_app._start_iris_install(spec, **target, repair_options=("source", "", ""))
    assert len(calls) == 1 and not services._IRIS_INSTALL_LOCK.locked()


def test_iris_repair_upload_and_source_are_explicit_posts(tmp_path, monkeypatch):
    import app as launcher_app
    from fastapi.testclient import TestClient
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(launcher_app, "_find_service", lambda _name: spec)
    monkeypatch.setattr(launcher_app, "_require_startable_setup", lambda _name: None)
    calls = []

    def start(_spec, device, host, **kwargs):
        calls.append((device, host, kwargs["repair_options"], kwargs["upload"].read() if kwargs["upload"] else None))

    monkeypatch.setattr(launcher_app, "_start_iris_install", start)
    client = TestClient(launcher_app.app, base_url="http://127.0.0.1")
    target = {"device_session_id": "test-phone", "host_package": "com.mentra.mentra.openalma"}
    response = client.post("/iris/install", data={**target, "repair_source": "zip"},
                           files={"bundle_file": ("development.zip", b"zip bytes")}, follow_redirects=False)
    assert response.status_code == 303
    assert calls[-1] == ("test-phone", target["host_package"], ("zip", "", ""), b"zip bytes")
    response = client.post("/iris/install", data={**target, "repair_source": "source", "source_folder": str(tmp_path)},
                           files={"bundle_file": ("", b"")}, follow_redirects=False)
    assert response.status_code == 303
    assert calls[-1][:3] == ("test-phone", target["host_package"], ("source", "", str(tmp_path)))
    count = len(calls)
    response = client.post("/iris/install", data={**target, "repair": "true"}, follow_redirects=False)
    assert response.status_code == 400 and len(calls) == count
    response = client.post("/iris/install", data=target,
                           files={"bundle_file": ("development.zip", b"zip bytes")}, follow_redirects=False)
    assert response.status_code == 400 and len(calls) == count


def test_iris_repair_installer_uses_selected_bundle_not_github(tmp_path, monkeypatch):
    from types import SimpleNamespace
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    bundle = tmp_path / "local.zip"
    monkeypatch.setattr(services, "STATE_DIR", tmp_path)
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState())
    monkeypatch.setattr(services, "raise_if_stopping", lambda _spec: None)
    monkeypatch.setattr(services, "_iris_build_env", lambda *_args: {})
    monkeypatch.setattr(services, "_iris_release_candidate", lambda _spec: pytest.fail("Local Repair must bypass latest release"))
    monkeypatch.setattr(services, "_clear_port_cache", lambda _spec: None)
    seen = []
    monkeypatch.setattr(services, "_spawn_background", lambda _spec, env: (seen.append(env), SimpleNamespace(pid=4242))[1])
    services.start(spec, install_target={"device_session_id": "test-phone"}, bundle_path=bundle)
    assert seen[0]["MENTRA_RELEASE_BUNDLE"] == str(bundle)
    row = services._iris_product_status(services.RuntimeState(), {
        "installed_package": services.IRIS_PACKAGE, "installed_version": "0.1.12",
        "host": {"host_package": "com.mentra.mentra.openalma"},
    }, services.IRIS_PACKAGE, "", {"ready": True})
    assert row["repair_available"] and row["action_label"] == "Repair"


def test_iris_address_save_refuses_busy_setup_and_uses_the_running_server_writer(tmp_path, monkeypatch):
    import app as launcher_app
    from fastapi.testclient import TestClient

    path = tmp_path / "mcp-memu-server/config.json"
    path.parent.mkdir()
    original = {"llm": {"api_key": "fictional-secret"}, "other": "keep"}
    path.write_text(json.dumps(original))
    specs = [services.ServiceSpec(name, name, [], tmp_path, tmp_path / f"{name}.log", tmp_path / f"{name}.pid")
             for name in ("memu-server", "iris-server")]
    runtime = {spec.name: services.RuntimeState() for spec in specs}
    calls = []
    monkeypatch.setattr(launcher_app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(services, "all_services", lambda: specs)
    monkeypatch.setattr(services, "_runtime_state", lambda spec: runtime[spec.name])

    def save_in_server(route, payload):
        assert services._IRIS_INSTALL_LOCK.locked()
        assert route == "/config" and payload == {"mentra": {"public_base_url": "http://10.77.0.1"}}
        calls.append(payload)
        current = json.loads(path.read_text())
        current["llm"]["api_key"] = "newer-fictional-secret"
        current.update(payload)
        path.write_text(json.dumps(current))
        return {"ok": True}

    monkeypatch.setattr(services, "_mcp_request", save_in_server)
    client = TestClient(launcher_app.app, base_url="http://127.0.0.1")
    def save():
        return client.post("/iris/address", data={"public_base_url": "http://10.77.0.1"}, follow_redirects=False)

    with services._IRIS_INSTALL_LOCK:
        assert save().status_code == 409
    for busy in (services.RuntimeState(running=True), services.RuntimeState(stuck=True)):
        runtime["iris-server"] = busy
        assert save().status_code == 409
    assert json.loads(path.read_text()) == original and not calls
    assert not Path(str(path) + ".orig").exists()
    runtime["iris-server"] = services.RuntimeState(port_blocked=True)
    runtime["memu-server"] = services.RuntimeState(running=True)
    assert save().status_code == 303
    assert json.loads(path.read_text()) == {"llm": {"api_key": "newer-fictional-secret"}, "other": "keep",
                                         "mentra": {"public_base_url": "http://10.77.0.1"}}
    assert json.loads(Path(str(path) + ".orig").read_text()) == original
    assert len(calls) == 1 and not services._IRIS_INSTALL_LOCK.locked()
    monkeypatch.setattr(services, "_mcp_request", lambda *_args: (_ for _ in ()).throw(OSError("Fictional outage")))
    before = path.read_text()
    assert save().status_code == 400
    assert path.read_text() == before
    runtime["memu-server"] = services.RuntimeState()
    monkeypatch.setattr(launcher_app.os, "fsync", lambda *_args: (_ for _ in ()).throw(OSError("Fictional sync failure")))
    assert save().status_code == 400
    assert path.read_text() == before and not services._IRIS_INSTALL_LOCK.locked()
    assert sorted(path.parent.iterdir()) == [path, *sorted(path.parent.glob("config.json*.orig"))]


def test_iris_address_save_refuses_invalid_config_without_rewriting_it(tmp_path, monkeypatch):
    import app as launcher_app
    from fastapi.testclient import TestClient

    path = tmp_path / "mcp-memu-server/config.json"
    path.parent.mkdir()
    monkeypatch.setattr(launcher_app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: tmp_path)
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState())
    monkeypatch.setattr(launcher_app, "_setup_aware_status", lambda _spec, root, **_kwargs: {
        "setup": services.mentra_readiness(root),
    })
    def unexpected_probe(*_args, **_kwargs):
        pytest.fail("Invalid config must not trigger readiness probes")
    monkeypatch.setattr(services, "_mentra_http_status", unexpected_probe)
    client = TestClient(launcher_app.app, base_url="http://127.0.0.1", raise_server_exceptions=False)
    for value, detail in ((b"[]", "JSON object"), (b"null", "JSON object"), (b"\xff", "decode")):
        path.write_bytes(value)
        services._MENTRA_READINESS_CACHE.clear()
        with monkeypatch.context() as readiness_patch:
            readiness_patch.setattr(services, "_runtime_state", unexpected_probe)
            readiness_patch.setattr(services, "all_services", unexpected_probe)
            readiness = services._mentra_readiness_uncached(tmp_path)
        assert readiness == {
            "ready": False, "step": "config", "rows": [],
            "reason": "Cannot read mcp config.json" if value == b"\xff" else "mcp config.json must be a JSON object",
        }
        assert services.all_services()[0].adopt_pid_path == path.parent / ".memu-server.pid"
        response = client.post("/iris/address", data={"public_base_url": "http://10.77.0.1"})
        assert response.status_code == 400
        assert detail in response.json()["detail"]
        assert path.read_bytes() == value
        assert list(path.parent.iterdir()) == [path]
        assert not services._IRIS_INSTALL_LOCK.locked()
        page = client.get("/iris")
        assert page.status_code == 200
        assert readiness["reason"] in page.text


def test_iris_install_rechecks_readiness_before_reserving_or_starting(tmp_path, monkeypatch):
    import app as launcher_app
    monkeypatch.setattr(launcher_app, "_require_startable_setup", lambda _name: None)

    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState())
    monkeypatch.setattr(services, "mentra_readiness", lambda: {"ready": False, "reason": "Restart memU Server"})
    monkeypatch.setattr(services, "iris_installation_request", lambda *_args, **_kwargs: pytest.fail("Unready setup must not reserve"))
    monkeypatch.setattr(services, "start", lambda *_args, **_kwargs: pytest.fail("Unready setup must not start"))
    with pytest.raises(ValueError, match="Restart memU Server"):
        launcher_app._start_iris_install(spec, "", "")
    assert not services._IRIS_INSTALL_LOCK.locked()


def test_iris_status_tracks_target_not_lock_and_preserves_rows_on_outage(tmp_path, monkeypatch):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState())
    monkeypatch.setattr(services, "mentra_readiness", lambda: {"ready": True})
    mentra = {"state": "ready", "installations": [{"device_session_id": "stock-test"}]}
    monkeypatch.setattr(services, "_read_mentra_status", lambda *_args, **_kwargs: mentra)
    monkeypatch.setattr(services, "_iris_release_candidate", lambda _spec: (
        services.IRIS_PACKAGE, "0.1.0", None, "none",
    ))
    with services._IRIS_INSTALL_LOCK:
        forgotten = services.status(spec)
        assert forgotten["starting"] is False
        assert forgotten["state"] != "starting"
        assert forgotten["installations"] == []
        assert "release_device_session_id" not in forgotten

        target_path = tmp_path / "build/release-private-status.json"
        target_path.parent.mkdir()
        target_path.write_text(json.dumps({"installation_ticket": "stock-ticket", "device_session_id": ""}))
        preparing = services.status(spec)
        assert preparing["starting"] is True
        assert preparing["action_kind"] == "stop"
        assert preparing["action_label"] == "Cancel"
        assert preparing["installations"] == []
        assert preparing["release_device_session_id"] == ""
        assert preparing["release_installation_ticket"] == "stock-ticket"

        mentra["installations"] = [{"device_session_id": "stock-test", "display_name": "Keep my name",
                                   "package_name": services.IRIS_PACKAGE, "version": "0.1.0"}]
        target_path.write_text(json.dumps({"installation_ticket": "update-ticket", "device_session_id": "stock-test"}))
        update = services.status(spec)
        assert update["release_device_session_id"] == "stock-test"
        assert update["installations"][0]["state"] == "starting"
        assert update["installations"][0]["display_name"] == "Keep my name"

        target_path.write_text(json.dumps({"installation_ticket": "stock-ticket", "device_session_id": ""}))
        mentra["installations"].append({"device_session_id": "new-app", "display_name": "stock_02",
                                      "installation_ticket": "stock-ticket", "package_name": services.IRIS_PACKAGE})
        correlated = services.status(spec)
        assert correlated["release_device_session_id"] == "new-app"
        assert len(correlated["installations"]) == 2
        assert correlated["installations"][1]["state"] == "starting"

    assert services.status(spec)["starting"] is False

    mentra["installations"] = [{"device_session_id": "stock-test"}]
    mentra["installations"][0]["package_name"] = services.IRIS_PACKAGE
    assert len(services.status(spec)["installations"]) == 1
    mentra["installations"] = [{"device_session_id": "fork-test", "host": {"host_package": "com.mentra.mentra.openalma"}}]
    assert len(services.status(spec)["installations"]) == 1

    mentra = {"state": "unavailable", "detail": "Fictional outage"}
    unavailable = services.status(spec)
    assert unavailable["state"] == "unavailable"
    assert unavailable["detail"] == "Fictional outage"
    assert "installations" not in unavailable

    mentra = {"state": "stopped", "installations": [{"device_session_id": "stock-test",
              "package_name": services.IRIS_PACKAGE}]}
    monkeypatch.setattr(services, "mentra_readiness", lambda: {"ready": False, "step": "server"})
    stopped = services.status(spec)
    assert stopped["detail"] == "Start memU Server in Services"
    assert stopped["installations"][0]["detail"] == ""
    mentra["installations"][0]["seen_at"] = time.time() - 3600
    assert services.status(spec)["installations"][0]["detail"].startswith("Last reached server")
    monkeypatch.setattr(services, "mentra_readiness", lambda: {"ready": True})

    mentra = {"state": "ready"}
    assert services.status(spec)["installations"] == []

    mentra = {"state": "active", "sessions": [{"device_session_id": "forgotten-app", "soul_id": "Fictional Soul"}]}
    row = services.status(spec)["installations"][0]
    assert row["device_session_id"] == "forgotten-app"
    assert row["soul_id"] == "Fictional Soul"
    assert row["active"] is True
    assert row["metadata_known"] is False
    assert row["startable"] is False
    assert row["installed_version"] is None


@pytest.mark.parametrize("target", ["stock-test", ""])
def test_iris_forget_protects_installer_target_and_receipt(tmp_path, monkeypatch, target):
    import app as launcher_app

    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "all_services", lambda: [spec])
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState(running=True))
    monkeypatch.setattr(services, "_iris_release_record", lambda _spec: {
        "device_session_id": target, "installation_ticket": "stock-ticket",
    })
    monkeypatch.setattr(services, "_read_mentra_status", lambda *_args: {"installations": [
        {"device_session_id": "stock-test", "installation_ticket": "stock-ticket"},
    ]})
    monkeypatch.setattr(services, "iris_installation_request", lambda *_args: pytest.fail("must not forget installer target"))
    with pytest.raises(launcher_app.HTTPException, match="Finish or stop") as error:
        launcher_app.iris_forget("stock-test")
    assert error.value.status_code == 409
    assert not services._IRIS_INSTALL_LOCK.locked()


def test_optional_service_install_marker_controls_visibility(tmp_path):
    marker = tmp_path / "client" / "package.json"
    spec = services.ServiceSpec("client", "Client", [], tmp_path, tmp_path / "log", tmp_path / "pid", install_marker=marker)

    assert services.is_installed(spec) is False
    marker.parent.mkdir()
    marker.touch()
    assert services.is_installed(spec) is True


def test_host_prerequisites_ignore_uninstalled_optional_clients(tmp_path, monkeypatch):
    for path in (
        "mcp-memu-server/run.py",
        "memu/pyproject.toml",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).touch()
    venv.EnvBuilder(with_pip=False).create(tmp_path / "mcp-memu-server/.venv")
    monkeypatch.setattr(services.shutil, "which", lambda command: f"/usr/bin/{command}")

    result = services.host_prerequisites(tmp_path, tmp_path / "missing-os-release")

    assert result["ready"] is True
    assert result["rows"][1]["detail"] == "Ready"
    assert result["rows"][2]["detail"] == "Ready"


def test_host_prerequisites_without_apps_root_still_render():
    result = services.host_prerequisites(None)

    assert result["ready"] is False
    assert "memU Server" in result["rows"][1]["detail"]


def test_atomic_service_is_managed_by_launcher(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    for name in ("mcp-memu-server", "atomic", "hermes-channels", "sillytavern"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)

    spec = next(s for s in services.all_services() if s.name == "atomic")

    assert spec.label == "Atomic Mind Map"
    assert spec.cwd == root / "atomic"
    assert spec.port == 1420
    assert spec.open_url == "http://127.0.0.1:1420"
    assert spec.cmd[-2:] == ["scripts/dev-server.js", "--production"]
    assert Path(spec.env["ATOMIC_SERVER_BIN"]) == services._atomic_server_binary(root)


def test_atomic_service_uses_existing_debug_binary(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    debug = root / "atomic/target/debug" / ("atomic-server.exe" if services.os.name == "nt" else "atomic-server")
    debug.parent.mkdir(parents=True)
    debug.touch()
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)

    spec = next(s for s in services.all_services() if s.name == "atomic")

    assert spec.env["ATOMIC_SERVER_BIN"] == str(debug)


def test_memorize_pending_sends_user_id(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(services, "all_services", lambda: [])
    monkeypatch.setattr(services.urllib.request, "urlopen", fake_urlopen)

    out = services.memorize_pending("Fictional Soul", "Fictional User")
    query = parse_qs(urlparse(seen["url"]).query)

    assert out == {"threshold": 5000}
    assert query == {"soul_id": ["Fictional Soul"], "user_id": ["Fictional User"]}
    assert seen["timeout"] == 2


def test_memorize_pending_surfaces_owner_conflict(monkeypatch):
    error = services.urllib.error.HTTPError(
        "http://localhost", 409, "Conflict", {}, BytesIO(b'{"detail":"OpenAlma owner mismatch"}'),
    )
    monkeypatch.setattr(services, "all_services", lambda: [])
    monkeypatch.setattr(services.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    assert services.memorize_pending("Fictional Soul") == {"error": "OpenAlma owner mismatch"}


def test_retry_consolidation_uses_encoded_owner_and_scope(monkeypatch):
    seen = {}

    def fake_request(path, payload=None):
        seen.update(path=path, payload=payload)
        return {"status": "accepted"}

    monkeypatch.setattr(services, "_mcp_request", fake_request)

    assert services.retry_consolidation(
        "chat:fictional/one", "Fictional Soul", "Fictional User"
    ) == {"status": "accepted"}
    assert seen == {
        "path": "/conversation/chat%3Afictional%2Fone/consolidation/retry",
        "payload": {
            "user": {"user_id": "Fictional User", "soul_id": "Fictional Soul"}
        },
    }


def test_owner_request_uses_shared_mcp_transport(monkeypatch):
    seen = {}
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port, **_kwargs: 123)

    class Response(_FakeResponse):
        def read(self):
            return b'{"user_id":"Fictional User","created":true}'

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        return Response()

    monkeypatch.setattr(services.urllib.request, "urlopen", fake_urlopen)

    assert services.create_owner(" Fictional User ") == "Fictional User"
    assert seen == {
        "url": "http://127.0.0.1:8099/owner",
        "body": {"user_id": "Fictional User"},
        "timeout": 2,
    }


def test_memorize_status_lists_all_souls_without_hermes(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import app as launcher_app  # noqa: PLC0415

    seen = {}
    config = tmp_path / "channels.json"
    config.write_text(json.dumps({"soul_id": "Fictional Soul", "user_id": "Wrong User"}))
    monkeypatch.setattr(launcher_app.soul, "CHANNELS_CONFIG_PATH", config)
    monkeypatch.setattr(launcher_app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(launcher_app.services, "list_souls", lambda: ["Fictional Soul", "Other Soul"])
    monkeypatch.setattr(
        launcher_app.services,
        "memorize_pending",
        lambda soul_id, user_id: seen.setdefault((soul_id, user_id), {"threshold": 6000}),
    )

    assert launcher_app.memorize_status() == {"souls": [
        {"threshold": 6000, "soul_id": "Fictional Soul"},
        {"threshold": 6000, "soul_id": "Other Soul"},
    ]}
    assert ("Fictional Soul", "Fictional Owner") in seen
    assert ("Other Soul", "Fictional Owner") in seen


def test_memorize_retry_uses_diagnostic_conversation(monkeypatch):
    pytest.importorskip("fastapi")
    import app as launcher_app  # noqa: PLC0415

    seen = {}
    monkeypatch.setattr(launcher_app.soul, "read_active_soul_id", lambda: "Fictional Soul")
    monkeypatch.setattr(launcher_app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(launcher_app.services, "list_souls", lambda: ["Fictional Soul"])
    monkeypatch.setattr(
        launcher_app.services,
        "memorize_pending",
        lambda *_args: {
            "consolidation_state": "error",
            "retry_operation": "consolidation",
            "retry_conversation_id": "fictional:chat",
        },
    )
    monkeypatch.setattr(
        launcher_app.services,
        "retry_consolidation",
        lambda conversation_id, soul_id, user_id: seen.update(
            conversation_id=conversation_id,
            soul_id=soul_id,
            user_id=user_id,
        )
        or {"status": "accepted"},
    )

    assert launcher_app.memorize_retry("Fictional Soul") == {"status": "accepted"}
    assert seen == {
        "conversation_id": "fictional:chat",
        "soul_id": "Fictional Soul",
        "user_id": "Fictional Owner",
    }


def test_memorize_retry_rejects_non_error_state(monkeypatch):
    pytest.importorskip("fastapi")
    import app as launcher_app  # noqa: PLC0415

    monkeypatch.setattr(launcher_app.soul, "read_active_soul_id", lambda: "Fictional Soul")
    monkeypatch.setattr(launcher_app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(launcher_app.services, "list_souls", lambda: ["Fictional Soul"])
    monkeypatch.setattr(
        launcher_app.services,
        "memorize_pending",
        lambda *_args: {
            "consolidation_state": "overdue",
            "retry_conversation_id": "fictional:chat",
        },
    )

    with pytest.raises(launcher_app.HTTPException, match="ready to retry"):
        launcher_app.memorize_retry("Fictional Soul")


def test_memorize_retry_targets_failed_row_not_hermes(monkeypatch):
    import app as launcher_app
    seen = []
    monkeypatch.setattr(launcher_app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(launcher_app.services, "list_souls", lambda: ["Failed Soul", "Other Soul"])
    monkeypatch.setattr(launcher_app.soul, "read_active_soul_id", lambda: pytest.fail("Retry must not use Hermes"))
    monkeypatch.setattr(launcher_app.services, "memorize_pending", lambda *_args: {"retry_operation": "memorize"})
    monkeypatch.setattr(launcher_app.services, "retry_memorize", lambda sid, uid: seen.append((sid, uid)) or {"ok": True})
    assert launcher_app.memorize_retry("Failed Soul") == {"ok": True}
    assert seen == [("Failed Soul", "Fictional Owner")]


def test_memorize_status_reports_owner_transport_failure(monkeypatch):
    import app as launcher_app
    def unavailable():
        raise services.OwnerServiceUnavailable("Owner service unavailable")
    monkeypatch.setattr(services, "read_owner", unavailable)
    assert launcher_app.memorize_status() == {"souls": [], "error": "Owner service unavailable"}


def test_service_action_spinner_confirmation_and_error_display():
    template = Path(__file__).resolve().parents[1] / "launcher/templates/index.html"
    subprocess.run(["node", "-e", r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const text = fs.readFileSync(process.argv[1], 'utf8');
const script = text.slice(text.indexOf('var pendingStarts = {}'), text.indexOf('function actionHtml('));
(async () => {
  for (const scenario of ['start', 'start-failed', 'decline', 'confirm', 'force']) {
    const urls = [], alerts = []; let polls = 0;
    const context = {
      document: {addEventListener: () => {}},
      Date, confirm: () => ['confirm', 'force'].includes(scenario), alert: x => alerts.push(x), pollStatus: () => polls++,
      fetch: async url => {
        urls.push(url);
        const status = scenario === 'start' ? 200 : scenario === 'start-failed' || urls.length === 2 ? 409 : 428;
        return {status, ok: status === 200, json: async () => ({detail: 'Service message'})};
      },
    };
    vm.createContext(context); vm.runInContext(script, context);
    const action = scenario.startsWith('start') ? 'start' : scenario === 'force' ? 'force-stop' : 'stop';
    await context.svcAction('test', action, {
      closest: () => ({querySelector: () => ({innerHTML: ''})}),
    });
    assert.equal(polls, 1);
    assert.equal(Boolean(context.pendingStarts.test), scenario === 'start');
    assert.equal(urls.length, ['confirm', 'force'].includes(scenario) ? 2 : 1);
    assert.equal(alerts.length, ['confirm', 'force', 'start-failed'].includes(scenario) ? 1 : 0);
    if (scenario === 'confirm') assert(urls[1].endsWith('?confirm_unknown=true'));
    if (scenario === 'force') assert(urls[1].endsWith('?confirmed=true'));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
''', str(template)], check=True, capture_output=True, text=True)
    subprocess.run(["node", "-e", r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const text = fs.readFileSync(process.argv[1], 'utf8');
const context = {esc: String};
vm.createContext(context);
vm.runInContext(text.slice(text.indexOf('function actionHtml('), text.indexOf('function pollStatus(')), context);
const failed = context.actionHtml('memu-server', {state: 'running', running: true, stoppable: true, force_stoppable: true});
assert(failed.includes("'stop'")); assert(failed.includes("'force-stop'"));
const starting = context.actionHtml('memu-server', {state: 'starting', running: true, stoppable: true, open_url: 'http://fictional/'});
assert(starting.includes('spinner')); assert(starting.includes("'stop'"));
assert(!starting.includes('Force Stop')); assert(!starting.includes('openService'));
const failedStarting = context.actionHtml('memu-server', {state: 'starting', stoppable: true, force_stoppable: true});
assert(failedStarting.includes("'stop'")); assert(failedStarting.includes("'force-stop'"));
for (const state of ['running', 'starting']) {
  const blocked = context.actionHtml('memu-server', {state, stop_blocked: true, force_stoppable: true});
  assert(blocked.includes('disabled')); assert(!blocked.includes('Force Stop'));
}
''', str(template)], check=True, capture_output=True, text=True)
    from jinja2 import Environment

    actions = template.read_text(encoding="utf-8").split('<td class="svc-actions">', 1)[1].split('</td>', 1)[0]
    renderer = Environment(autoescape=True).from_string(actions)
    for state in ("starting", "running"):
        html = renderer.render(s={"name": "memu-server", "state": state, "running": True,
                                 "stoppable": True, "force_stoppable": state == "running"})
        assert "'stop'" in html
        assert ("Force Stop" in html) == (state == "running")
    failed_starting = renderer.render(s={"name": "memu-server", "state": "starting",
                                       "stoppable": True, "force_stoppable": True})
    assert "'stop'" in failed_starting and "'force-stop'" in failed_starting
    blocked_starting = renderer.render(s={"name": "memu-server", "state": "starting",
                                        "stop_blocked": True, "force_stoppable": True})
    assert "disabled" in blocked_starting and "Force Stop" not in blocked_starting


def test_memu_server_uses_configured_pidfile_for_adoption(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    server_dir = root / "mcp-memu-server"
    memu_dir = root / "memu"
    server_dir.mkdir(parents=True)
    memu_dir.mkdir()
    (root / "hermes-channels").mkdir()
    (root / "sillytavern" / "SillyTavern").mkdir(parents=True)
    (server_dir / "config.json").write_text(
        json.dumps({"pid_file": "../memu/.memu-server.pid"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)

    spec = next(s for s in services.all_services() if s.name == "memu-server")

    assert spec.adopt_pid_path == (memu_dir / ".memu-server.pid").resolve()


def test_sillytavern_match_requires_expected_cwd(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="sillytavern",
        label="SillyTavern",
        cmd=[],
        cwd=tmp_path / "SillyTavern",
        log_path=tmp_path / "st.log",
        pid_path=tmp_path / "st.pid",
    )
    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: pytest.fail("Unrelated cwd must not read the command line"))
    for cwd in (None, tmp_path / "other"):
        monkeypatch.setattr(services, "_proc_cwd", lambda _pid: cwd)
        assert services._matches_service_process(spec, 123) is False

    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: "node server.js")
    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: spec.cwd)
    assert services._matches_service_process(spec, 123) is True
    for command in ("less server.js", "node other.js --note server.js", "cat start.sh"):
        monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: command)
        assert services._matches_service_process(spec, 123) is False


@pytest.mark.parametrize("command, expected", [
    ("python3 run.py", True), ("python3 -m uvicorn app.main:app", True),
    ("uvicorn app.main:app --port 8099", True),
    ("less run.py", False), ("python3 other.py --note run.py", False),
    ("python3 -c 'print(\"run.py\")'", False),
    ("'C:\\Python312\\python.exe' run.py", True),
])
def test_memu_match_requires_actual_entry_point(tmp_path, monkeypatch, command, expected):
    spec = services.ServiceSpec("memu-server", "memU", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: tmp_path)
    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: command)
    assert services._matches_service_process(spec, 123) is expected


def test_atomic_match_requires_expected_cwd(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="atomic",
        label="Atomic Mind Map",
        cmd=[],
        cwd=tmp_path / "atomic",
        log_path=tmp_path / "atomic.log",
        pid_path=tmp_path / "atomic.pid",
    )
    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: "node scripts/dev-server.js")

    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: tmp_path / "other")
    assert services._matches_service_process(spec, 123) is False

    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: spec.cwd)
    assert services._matches_service_process(spec, 123) is True
    for command in (
        "npm run dev:server",
        "node node_modules/vite/bin/vite.js --host 127.0.0.1",
        "/apps/atomic/target/debug/atomic-server serve --bind 127.0.0.1",
    ):
        monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: command)
        assert services._matches_service_process(spec, 123) is True
    for command in (
        "cargo build -j1 -p atomic-server",
        "rustc --crate-name atomic_server crates/atomic-server/src/main.rs -o target/debug/atomic-server",
        "node node_modules/vite/bin/vite.js build",
    ):
        monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: command)
        assert services._matches_service_process(spec, 123) is False


@pytest.mark.parametrize("age, expected", [(10, "starting"), (31, "stuck")])
def test_status_reports_stuck_for_verified_process_without_port(tmp_path, monkeypatch, age, expected):
    spec = services.ServiceSpec(
        name="memu-server",
        label="memU Server",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "server.pid",
        port=8099,
    )
    spec.pid_path.write_text("123", encoding="utf-8")
    old = time.time() - age
    os.utime(spec.pid_path, (old, old))
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [123])
    monkeypatch.setattr(services, "_matches_service_process", lambda *_args: True)
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port: None)
    monkeypatch.setattr(services, "_read_mentra_status", lambda *_args: {"busy": False})

    status = services.status(spec)

    assert status["running"] is (expected == "starting")
    assert status["state"] == expected
    assert status["status_label"] == ("◐ starting" if expected == "starting" else "▲ stuck")
    assert status["startable"] is False
    assert status["stoppable"] is True


def test_status_reports_blocked_for_nonmatching_port_listener(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="memu-server",
        label="memU Server",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "server.pid",
        port=8099,
    )
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port: 999)
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda _pid: True)
    monkeypatch.setattr(services, "_matches_managed_process", lambda _spec, _pid: False)

    status = services.status(spec)

    assert status["running"] is False
    assert status["state"] == "blocked"
    assert status["status_label"] == "■ blocked"
    assert status["startable"] is False
    assert status["stoppable"] is False
    assert "port 8099 is held by PID 999" == status["detail"]


def test_iris_installer_recognizes_its_cli_listener(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        "iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid", port=6789,
    )
    cli = tmp_path / "node_modules/@mentra/miniapp-cli/src/index.ts"
    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: tmp_path)
    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: f'bun "{cli}" release --port 6789')
    monkeypatch.setattr(services, "_is_alive", lambda _pid: True)
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [123])
    monkeypatch.setattr(services, "_remember_verified_pid", lambda *_args: None)
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port: 456)

    assert services._matches_service_process(spec, 456)
    runtime = services._runtime_state(spec)
    assert runtime.running and not runtime.port_blocked
    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: 'bun /unrelated/index.ts release')
    assert not services._matches_service_process(spec, 456)


def test_verified_service_remains_running_when_port_owner_is_unavailable(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        "memu-server", "memU Server", [], tmp_path, tmp_path / "log", tmp_path / "pid", port=8099,
    )
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [123])
    monkeypatch.setattr(services, "_matches_service_process", lambda _spec, _pid: True)
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port: services.UNKNOWN_PORT_PID)

    runtime = services._runtime_state(spec)

    assert runtime.running is True
    assert runtime.port_blocked is False


def test_start_does_not_spawn_when_port_is_blocked(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="memu-server",
        label="memU Server",
        cmd=["false"],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "server.pid",
        port=8099,
    )
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port: 999)
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda _pid: True)
    monkeypatch.setattr(services, "_matches_managed_process", lambda _spec, _pid: False)
    spawned = []
    monkeypatch.setattr(services, "_spawn_background", lambda *_args: spawned.append(True))

    services.start(spec)

    assert spawned == []


def test_start_does_not_spawn_over_stuck_verified_process(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="memu-server",
        label="memU Server",
        cmd=["false"],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "server.pid",
        port=8099,
    )
    spec.pid_path.write_text("123", encoding="utf-8")
    old = time.time() - services.STARTUP_GRACE_SECONDS - 1
    os.utime(spec.pid_path, (old, old))
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [123])
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port: None)
    spawned = []
    monkeypatch.setattr(services, "_spawn_background", lambda *_args: spawned.append(True))

    services.start(spec)

    assert spawned == []
    assert spec.pid_path.read_text(encoding="utf-8") == "123"


def test_status_throttles_fallback_process_scan(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")
    spec = services.ServiceSpec(
        name="channels-daemon",
        label="Hermes Channels",
        cmd=[],
        cwd=tmp_path / "hermes-channels",
        log_path=tmp_path / "channels.log",
        pid_path=tmp_path / "channels.pid",
    )
    calls = []
    monkeypatch.setattr(services, "_PROCESS_SCAN_CACHE", {})
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: calls.append(True) or [])

    services.status(spec)
    services.status(spec)

    assert len(calls) == 1


def test_verified_pids_scan_when_pidfile_candidate_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")
    spec = services.ServiceSpec(
        name="channels-daemon",
        label="Hermes Channels",
        cmd=[],
        cwd=tmp_path / "hermes-channels",
        log_path=tmp_path / "channels.log",
        pid_path=tmp_path / "channels.pid",
    )
    spec.pid_path.write_text("11", encoding="utf-8")
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: [22])
    monkeypatch.setattr(services, "_is_alive", lambda pid: pid == 22)
    monkeypatch.setattr(services, "_matches_managed_process", lambda _spec, pid: pid == 22)

    assert services._verified_pid_candidates(spec) == [22]


def test_port_listener_lookup_is_cached(monkeypatch):
    calls = []

    def fake_connections(*_args, **_kwargs):
        calls.append(True)
        return [type("Connection", (), {
            "status": services.psutil.CONN_LISTEN,
            "laddr": ("127.0.0.1", 8099),
            "pid": 123,
        })()]

    monkeypatch.setattr(services, "_PORT_PID_CACHE", {})
    monkeypatch.setattr(services.psutil, "net_connections", fake_connections)

    assert services._port_listener_pid(8099) == 123
    assert services._port_listener_pid(8099) == 123

    assert len(calls) == 1


@pytest.mark.parametrize("listener", ["absent", "present", "unknown_pid", "query_failure"])
@pytest.mark.parametrize("mentra", [False, True])
def test_offline_http_is_skipped_only_after_fresh_listener_absence(monkeypatch, listener, mentra):
    port = services.MEMU_SERVER_PORT
    monkeypatch.setattr(services, "_PORT_PID_CACHE", {port: (time.monotonic(), 123 if listener == "absent" else None)})

    def connections(**_kwargs):
        if listener == "query_failure":
            raise services.psutil.AccessDenied()
        return [] if listener == "absent" else [SimpleNamespace(
            status=services.psutil.CONN_LISTEN, laddr=("127.0.0.1", port),
            pid=None if listener == "unknown_pid" else 123,
        )]

    calls = []
    monkeypatch.setattr(services.psutil, "net_connections", connections)
    monkeypatch.setattr(services.urllib.request, "urlopen", lambda *_args, **_kwargs: calls.append(True) or BytesIO(b'{"state":"ready"}'))
    if mentra:
        result = services._read_mentra_status(port)
        assert result["state"] == ("unavailable" if listener == "absent" else "ready")
    elif listener == "absent":
        with pytest.raises(ConnectionRefusedError):
            services._mcp_request("/owner")
    else:
        assert services._mcp_request("/owner") == {"state": "ready"}
    assert len(calls) == (0 if listener == "absent" else 1)


def test_force_kill_process_tree_starts_with_supervisor(monkeypatch):
    calls = []
    child = type("Process", (), {
        "pid": 45,
        "kill": lambda self: calls.append(("kill", 45)),
    })()
    process = type("Process", (), {
        "pid": 44,
        "children": lambda self, recursive: [child],
        "kill": lambda self: calls.append(("kill", 44)),
    })()
    monkeypatch.setattr(services.psutil, "Process", lambda pid: process)

    services._kill_process_tree(44)

    assert calls == [("kill", 44), ("kill", 45)]


def test_force_kill_reports_permission_denied(monkeypatch):
    def deny(_self):
        raise services.psutil.AccessDenied(44)

    process = type("Process", (), {
        "pid": 44,
        "children": lambda self, recursive: [],
        "kill": deny,
    })()
    monkeypatch.setattr(services.psutil, "Process", lambda pid: process)

    with pytest.raises(PermissionError, match=r"PID\(s\): 44"):
        services._kill_process_tree(44)


def test_stop_signals_service_owners_and_waits_in_background(tmp_path, monkeypatch):
    adopt_pid = tmp_path / "server-owned.pid"
    adopt_pid.write_text("11", encoding="utf-8")
    spec = services.ServiceSpec(
        name="atomic",
        label="Atomic",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "launcher.pid",
        adopt_pid_path=adopt_pid,
    )
    spec.pid_path.write_text("10", encoding="utf-8")
    stopped = False

    def verified(_spec):
        return [] if stopped else [10, 11]

    signaled = []
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(
            verified_pids=(10, 11), service_pids=(10, 11), running=True,
        ),
    )
    monkeypatch.setattr(services, "_verified_pid_candidates", verified)
    monkeypatch.setattr(services.os, "kill", lambda pid, sig: signaled.append((pid, sig)))
    monkeypatch.setattr(services, "_is_alive", lambda _pid: False)
    monkeypatch.setattr(services.os, "name", "posix")

    services.stop(spec)

    assert signaled == [(10, services.signal.SIGTERM), (11, services.signal.SIGTERM)]
    with services._STOP_LOCK:
        thread = services._STOP_THREADS[spec.name]
    assert thread.is_alive()

    stopped = True
    thread.join(timeout=1)
    assert not spec.pid_path.exists()
    assert not adopt_pid.exists()


def test_start_reports_active_stop_cleanup(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    with services._STOP_LOCK:
        services._STOP_THREADS[spec.name] = services.threading.current_thread()
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: pytest.fail("start raced stop cleanup"))
    try:
        with pytest.raises(services.ServiceStoppingError, match="still stopping"):
            services.start(spec)
    finally:
        with services._STOP_LOCK:
            services._STOP_THREADS.pop(spec.name, None)


@pytest.mark.parametrize("name", ["atomic", "iris-server"])
def test_start_rechecks_stop_reservation_before_spawn(tmp_path, monkeypatch, name):
    spec = services.ServiceSpec(name, name, [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "STATE_DIR", tmp_path)
    monkeypatch.setattr(services, "_STOP_LOCK", services.threading.Lock())
    monkeypatch.setattr(services, "_STOP_THREADS", {})
    monkeypatch.setattr(services, "_STOP_STARTED", {})
    monkeypatch.setattr(services, "_STOP_ERRORS", {})
    monkeypatch.setattr(services, "_IRIS_INSTALL_CANCELLED", services.threading.Event())
    prepared = []
    spawned = []

    def runtime(_spec):
        assert not services._STOP_LOCK.locked()
        # Stop wins admission after Start's initial guard and runtime snapshot.
        with services._STOP_LOCK:
            services._STOP_STARTED[name] = services.time.monotonic()
        return services.RuntimeState()

    def build_env(*_args):
        assert not services._STOP_LOCK.locked()
        prepared.append("env")
        return {}

    def download(*_args):
        assert not services._STOP_LOCK.locked()
        assert (tmp_path / "build/release-private-status.json").exists()
        prepared.append("download")
        return tmp_path / "fixture.zip"

    monkeypatch.setattr(services, "_runtime_state", runtime)
    monkeypatch.setattr(services, "_iris_build_env", build_env)
    monkeypatch.setattr(services, "_iris_release_candidate", lambda _spec: (
        services.IRIS_PACKAGE, "0.1.0", "https://example.invalid/fixture.zip", "available",
    ))
    monkeypatch.setattr(services, "_download_iris_release", download)
    monkeypatch.setattr(services, "_spawn_background", lambda *_args: (
        spawned.append(True) or SimpleNamespace(pid=4242)
    ))

    with pytest.raises(services.ServiceStoppingError, match="still stopping"):
        services.start(spec, install_target={"device_session_id": "fixture-phone"})

    assert not spawned
    assert not spec.pid_path.exists()
    assert prepared == (["env", "download"] if name == "iris-server" else [])
    assert not (tmp_path / "build/release-private-status.json").exists()
    assert not (tmp_path / "build/release-private-status.tmp").exists()


def test_stop_status_shows_force_only_with_failure_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(services.os, "name", "posix")
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    with services._STOP_LOCK:
        services._STOP_THREADS[spec.name] = services.threading.current_thread()
        services._STOP_STARTED[spec.name] = services.time.monotonic()
    try:
        result = services._stop_status(spec, {"state": "running", "stuck": False})
    finally:
        with services._STOP_LOCK:
            services._STOP_THREADS.pop(spec.name, None)
            services._STOP_STARTED.pop(spec.name, None)

    assert result["state"] == "stopping"
    assert result["force_stoppable"] is False

    with services._STOP_LOCK:
        services._STOP_THREADS[spec.name] = services.threading.current_thread()
        services._STOP_STARTED[spec.name] = services.time.monotonic()
    try:
        stuck = services._stop_status(spec, {"state": "stuck", "stuck": True})
        with services._STOP_LOCK:
            services._STOP_STARTED[spec.name] -= services.FORCE_STOP_RECOVERY_SECONDS
        delayed = services._stop_status(spec, {"state": "stuck", "stuck": True})
    finally:
        with services._STOP_LOCK:
            services._STOP_THREADS.pop(spec.name, None)
            services._STOP_STARTED.pop(spec.name, None)
    assert stuck["force_stoppable"] is False
    assert delayed["force_stoppable"] is True


def test_stop_leaves_live_nonmatching_service_pidfile(tmp_path, monkeypatch):
    adopt_pid = tmp_path / "server-owned.pid"
    adopt_pid.write_text("99", encoding="utf-8")
    spec = services.ServiceSpec(
        name="memu-server",
        label="memU Server",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "launcher.pid",
        adopt_pid_path=adopt_pid,
    )
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda pid: pid == 99)

    services.stop(spec)

    assert adopt_pid.exists()


def test_force_stop_kills_only_verified_matching_pids(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="atomic",
        label="Atomic",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "launcher.pid",
    )
    calls = {"count": 0}

    def verified(_spec):
        calls["count"] += 1
        return [20] if calls["count"] == 1 else []

    monkeypatch.setattr(services, "_verified_pid_candidates", verified)
    killed = []
    monkeypatch.setattr(services, "_kill_process_tree", killed.append)

    services.force_stop(spec)

    assert killed == [20]


def test_failed_force_stop_keeps_retry_evidence(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [20])
    monkeypatch.setattr(
        services, "_kill_process_tree",
        lambda _pid: (_ for _ in ()).throw(PermissionError("Fictional permission failure")),
    )

    with pytest.raises(PermissionError, match="Fictional permission failure"):
        services.force_stop(spec)

    status = services._stop_status(spec, {"running": True, "stuck": False})
    assert status["force_stoppable"] is True
    assert "Fictional permission failure" in status["detail"]
    with services._STOP_LOCK:
        services._STOP_ERRORS.pop(spec.name, None)


def test_force_stop_survivors_keep_retry_evidence_but_stale_error_does_not(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [20])
    monkeypatch.setattr(services, "_kill_process_tree", lambda _pid: None)

    with pytest.raises(RuntimeError, match="Could not force stop PID"):
        services.force_stop(spec, timeout=0)

    assert services._stop_status(spec, {"running": True, "stuck": False})["force_stoppable"] is True
    stopped = services._stop_status(spec, {"running": False, "stuck": False, "orphaned": False})
    assert stopped["force_stoppable"] is False
    with services._STOP_LOCK:
        services._STOP_ERRORS.pop(spec.name, None)


def test_stop_refuses_fake_graceful_shutdown_on_windows(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(verified_pids=(20,), service_pids=(20,), running=True),
    )
    monkeypatch.setattr(services.os, "name", "nt")
    monkeypatch.setattr(services, "_request_windows_shutdown", lambda *_args: (_ for _ in ()).throw(RuntimeError("No private console")))

    with pytest.raises(RuntimeError, match="No private console"):
        services.stop(spec)
    assert services._stop_status(spec, {"running": True, "stuck": False})["force_stoppable"] is True


@pytest.mark.parametrize("name", ["atomic", "channels-daemon", "sillytavern", "iris-server"])
def test_windows_stop_dispatch_is_not_repeated_or_forced(tmp_path, monkeypatch, name):
    monkeypatch.setattr(services, "_STOP_THREADS", {})
    monkeypatch.setattr(services, "_STOP_STARTED", {})
    spec = services.ServiceSpec(name, name, [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState(
        verified_pids=(100,), service_pids=(100,), running=True,
    ))
    monkeypatch.setattr(services.os, "name", "nt")
    calls = []

    def request(_spec, pids):
        calls.append(pids)
        services.stop(spec)

    monkeypatch.setattr(services, "_request_windows_shutdown", request)
    monkeypatch.setattr(services, "_start_stop_waiter", lambda _spec: calls.append("wait"))
    monkeypatch.setattr(services, "_kill_process_tree", lambda *_args: pytest.fail("Ordinary Stop must not kill"))
    services.stop(spec)
    assert calls == [(100,), "wait"]
    assert name in services._STOP_STARTED


def test_windows_shutdown_requests_only_outer_verified_supervisors(tmp_path, monkeypatch):
    spec = services.ServiceSpec("channels-daemon", "Channels", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    root = SimpleNamespace(pid=100, parents=lambda: [], create_time=lambda: 12.5)
    child = SimpleNamespace(pid=101, parents=lambda: [root], create_time=lambda: 13)
    monkeypatch.setattr(services.psutil, "Process", lambda pid: {100: root, 101: child}[pid])
    monkeypatch.setattr(services, "_matches_service_process", lambda *_args: True)
    calls = []
    monkeypatch.setattr(services.subprocess, "run", lambda command, **_kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0, stderr=""),
    )[0])
    services._request_windows_shutdown(spec, (101, 100))
    assert len(calls) == 1 and calls[0][-2:] == ["100", "12.5"]


def test_partial_windows_stop_keeps_waiting_without_resending(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_STOP_THREADS", {})
    monkeypatch.setattr(services, "_STOP_STARTED", {})
    monkeypatch.setattr(services, "_STOP_ERRORS", {})
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState(
        verified_pids=(10, 20), service_pids=(10, 20), running=True,
    ))
    monkeypatch.setattr(services.psutil, "Process", lambda pid: SimpleNamespace(
        pid=pid, parents=lambda: [], create_time=lambda: 1, is_running=lambda: True,
    ))
    monkeypatch.setattr(services, "_matches_service_process", lambda *_args: True)
    monkeypatch.setattr(services, "hidden_process_kwargs", lambda: {})
    calls = []

    def dispatch(command, **_kwargs):
        calls.append(command[-2])
        return SimpleNamespace(returncode=int(command[-2] == "20"), stderr="Fixture refusal")

    monkeypatch.setattr(services.subprocess, "run", dispatch)
    monkeypatch.setattr(services.os, "name", "nt")
    monkeypatch.setattr(services, "_start_stop_waiter", lambda _spec: services._STOP_THREADS.update(
        {spec.name: services.threading.current_thread()},
    ))
    with pytest.raises(services.PartialStopError, match="Fixture refusal"):
        services.stop(spec)
    services.stop(spec)
    assert calls == ["10", "20"]
    assert not services._stop_status(spec, {"running": True})["force_stoppable"]
    services._STOP_STARTED[spec.name] -= services.FORCE_STOP_RECOVERY_SECONDS
    assert services._stop_status(spec, {"running": True})["force_stoppable"]


def test_stop_handoff_cannot_clear_a_later_reservation(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_STOP_THREADS", {})
    monkeypatch.setattr(services, "_STOP_STARTED", {})
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState(
        verified_pids=(10,), service_pids=(10,), running=True,
    ))
    monkeypatch.setattr(services.os, "name", "nt")
    monkeypatch.setattr(services, "_request_windows_shutdown", lambda *_args: None)
    monkeypatch.setattr(services, "_start_stop_waiter", lambda _spec: services._STOP_STARTED.update(
        {spec.name: 12345},
    ))
    services.stop(spec)
    assert services._STOP_STARTED[spec.name] == 12345


def test_sent_stop_is_not_repeated_if_waiter_thread_cannot_start(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(services, "_STOP_THREADS", {})
    monkeypatch.setattr(services, "_STOP_STARTED", {})
    monkeypatch.setattr(services, "_STOP_ERRORS", {})
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState(
        verified_pids=(10,), service_pids=(10,), running=True,
    ))
    monkeypatch.setattr(services.os, "name", "nt")
    sent = []
    monkeypatch.setattr(services, "_request_windows_shutdown", lambda *_args: sent.append(True))

    class BrokenThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("Fixture thread unavailable")

    monkeypatch.setattr(services.threading, "Thread", BrokenThread)
    with pytest.raises(RuntimeError, match="thread unavailable"):
        services.stop(spec)
    services.stop(spec)
    assert sent == [True] and spec.name in services._STOP_STARTED
    assert spec.name not in services._STOP_THREADS
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [])
    services.force_stop(spec)
    assert spec.name not in services._STOP_STARTED


@pytest.mark.parametrize("first_request_fails", [False, True])
def test_stop_requests_unlimited_memu_drain_without_signaling(tmp_path, monkeypatch, first_request_fails):
    spec = services.ServiceSpec(
        "memu-server", "memU Server", [], tmp_path, tmp_path / "log", tmp_path / "pid",
    )
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(verified_pids=(20,), service_pids=(20,), running=True),
    )
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [])
    monkeypatch.setattr(services, "_read_mentra_status", lambda *_args: {"busy": False})
    monkeypatch.setattr(services, "_request_memu_shutdown", lambda: True)
    monkeypatch.setattr(services, "_kill_process_tree", lambda *_args: pytest.fail("unexpected force"))

    if first_request_fails:
        monkeypatch.setattr(services, "_request_memu_shutdown", lambda: False)
        with pytest.raises(RuntimeError, match="shutdown was not confirmed"):
            services.stop(spec)
        status = services._stop_status(spec, {"running": True, "stoppable": True})
        assert status["stoppable"] is True
        assert status["force_stoppable"] is True
        assert "retry Stop" in status["detail"]
        monkeypatch.setattr(services, "_request_memu_shutdown", lambda: True)
    services.stop(spec)
    with services._STOP_LOCK:
        thread = services._STOP_THREADS.get(spec.name)
    if thread is not None:
        thread.join(timeout=1)


def test_memu_shutdown_request_has_no_drain_deadline(monkeypatch):
    seen = {}

    def urlopen(request, timeout):
        seen["body"] = json.loads(request.data)
        seen["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(services.urllib.request, "urlopen", urlopen)

    assert services._request_memu_shutdown() is True
    assert seen == {
        "body": {
            "requested_by": "openalma-launcher",
            "reason": "launcher stop",
            "max_wait_sec": 0,
        },
        "timeout": 10,
    }


@pytest.mark.parametrize("elapsed", [14.9, 15.0, 30.0])
def test_elapsed_graceful_stop_exposes_manual_force_for_any_service(tmp_path, monkeypatch, elapsed):
    assert services.FORCE_STOP_RECOVERY_SECONDS == 15
    monkeypatch.setattr(services.time, "monotonic", lambda: 100)
    for name in ("memu-server", "channels-daemon", "iris-server", "atomic", "sillytavern"):
        spec = services.ServiceSpec(name, name, [], tmp_path, tmp_path / "log", tmp_path / "pid")
        with services._STOP_LOCK:
            services._STOP_THREADS[name] = services.threading.current_thread()
            services._STOP_STARTED[name] = 100 - elapsed
        try:
            status = services._stop_status(spec, {"running": True, "stuck": False})
            assert status["force_stoppable"] is (elapsed >= 15)
            assert status["state"] == "stopping" and not status["startable"]
            assert services._STOP_THREADS[name] is services.threading.current_thread()
            if elapsed >= 15:
                assert status["status_label"] == "Still finishing…"
                assert "Force Stop is available" in status["detail"]
        finally:
            with services._STOP_LOCK:
                services._STOP_THREADS.pop(name, None)
                services._STOP_STARTED.pop(name, None)


def test_channels_daemon_match_requires_cwd_and_gateway_module(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="channels-daemon",
        label="Hermes Channels",
        cmd=[],
        cwd=tmp_path / "hermes-channels",
        log_path=tmp_path / "channels.log",
        pid_path=tmp_path / "channels.pid",
    )
    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: "python3 -m gateway.daemon")

    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: tmp_path / "other")
    assert services._matches_service_process(spec, 123) is False

    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: spec.cwd)
    assert services._matches_service_process(spec, 123) is True


@pytest.mark.parametrize("pidfiles", [True, False])
def test_channels_daemon_verified_pids_include_whatsapp_children(tmp_path, monkeypatch, pidfiles):
    channels_home = tmp_path / "channels_data"
    whatsapp_home = channels_home / "whatsapp"
    session_path = whatsapp_home / "session"
    session_path.mkdir(parents=True)
    if pidfiles:
        (session_path / "bridge.pid").write_text("41", encoding="utf-8")
        (whatsapp_home / "web_source.pid").write_text("42", encoding="utf-8")
    monkeypatch.setattr(services, "_CHANNELS_HOME", channels_home)
    monkeypatch.setattr(services, "_PROCESS_SCAN_CACHE", {})
    monkeypatch.setattr(services.psutil, "process_iter", lambda _attrs: [
        type("Process", (), {"pid": pid})() for pid in (41, 42, 43, 44)
    ])
    def alive(pid):
        assert pid != 43, "Unrelated processes must not need liveness inspection"
        return pid in {41, 42}
    monkeypatch.setattr(services, "_is_alive", alive)
    reads = []

    def cmdline(pid):
        reads.append(pid)
        if pid in {41, 44}:
            return f"node bridge.js --port 3000 --session {session_path} --mode self-chat"
        if pid == 42:
            return (
                "node source-daemon.js "
                f"--db {whatsapp_home / 'web_source.db'} "
                f"--status {whatsapp_home / 'web_source_status.json'}"
            )
        return f"node bridge.js --db {whatsapp_home / 'web_source.db'} --status {whatsapp_home / 'web_source_status.json'}"

    monkeypatch.setattr(services, "_proc_cmdline", cmdline)
    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: None)
    spec = services.ServiceSpec(
        name="channels-daemon",
        label="Hermes Channels",
        cmd=[],
        cwd=tmp_path / "hermes-channels",
        log_path=tmp_path / "channels.log",
        pid_path=tmp_path / "channels.pid",
    )

    assert services._verified_pid_candidates(spec) == [41, 42]
    assert reads.count(41) == reads.count(42) == (1 if pidfiles else 2)
    if not pidfiles:
        assert reads.count(43) == reads.count(44) == 1


def test_channels_needs_soul_selection_before_start(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path)
    monkeypatch.setattr(services, "_runtime_state", lambda _spec: services.RuntimeState())
    monkeypatch.setattr(services, "_spawn_background", lambda *_args, **_kwargs: pytest.fail("Must not start before setup"))
    spec = services.ServiceSpec("channels-daemon", "Hermes", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    status = services.status(spec)
    assert status["action_kind"] == "settings" and not status["startable"]
    with pytest.raises(ValueError, match="Choose a Soul in Setup"):
        services.start(spec)
    (tmp_path / "config.json").write_text(json.dumps({"soul_id": "Fictional Soul"}))
    assert services.status(spec)["startable"]


def test_channels_daemon_status_uses_bridge_and_web_source_health(tmp_path, monkeypatch):
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(
            verified_pids=(111,),
            service_pids=(111,),
            pid=111,
            running=True,
        ),
    )
    monkeypatch.setattr(services, "_channels_bridge_health", lambda _config=None: {"status": "connected", "mode": "bot"})
    monkeypatch.setattr(services, "_read_channels_web_source_status", lambda: {"state": "pairing"})
    spec = services.ServiceSpec(
        name="channels-daemon",
        label="Hermes Channels",
        cmd=[],
        cwd=tmp_path / "hermes-channels",
        log_path=tmp_path / "channels.log",
        pid_path=tmp_path / "channels.pid",
    )

    status = services.status(spec)

    assert status["state"] == "starting"
    assert status["status_label"] == "◐ starting"
    assert status["children"] == [
        {"name": "bridge", "state": "connected", "detail": "mode bot"},
        {"name": "web-source", "state": "pairing", "detail": ""},
    ]


def test_channels_daemon_status_requests_pairing_when_qr_is_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(pid=111, running=True),
    )
    monkeypatch.setattr(
        services,
        "_channels_bridge_health",
        lambda _config=None: {"status": "connecting", "qr": "scan-me"},
    )
    monkeypatch.setattr(services, "_read_channels_web_source_status", lambda: {})
    spec = services.ServiceSpec(
        name="channels-daemon",
        label="Hermes Channels",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "channels.log",
        pid_path=tmp_path / "channels.pid",
    )

    status = services.status(spec)

    assert status["state"] == "pairing"
    assert status["status_label"] == "Pairing required"
    assert status["pairing_required"] is True


def test_channels_daemon_hides_stale_child_status_during_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(pid=111, running=True),
    )
    monkeypatch.setattr(services, "_within_startup_grace", lambda _spec: True)
    monkeypatch.setattr(
        services,
        "_channels_bridge_health",
        lambda _config=None: pytest.fail("stale bridge status read during startup"),
    )
    spec = services.ServiceSpec(
        name="channels-daemon",
        label="Hermes Channels",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "channels.log",
        pid_path=tmp_path / "channels.pid",
    )

    status = services.status(spec)

    assert status["state"] == "starting"
    assert status["detail"] == "Starting WhatsApp services"
    assert status["children"] == []
