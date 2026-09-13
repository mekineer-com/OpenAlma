import json
import os
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import services  # noqa: E402


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
    assert open_urls["sillytavern"] == "http://127.0.0.1:8001"
    assert next(spec for spec in specs if spec.name == "sillytavern").cmd[-2:] == [
        "server.js", "--browserLaunchEnabled=false",
    ]


def test_services_can_be_built_for_pending_root(tmp_path):
    specs = services.services_for_root(tmp_path)

    assert [spec.name for spec in specs] == [
        "memu-server", "iris-server", "atomic", "channels-daemon", "sillytavern",
    ]
    assert specs[0].cwd == tmp_path / "mcp-memu-server"
    assert services.is_installed(specs[0]) is False


def test_iris_server_is_managed_by_launcher(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)
    monkeypatch.setattr(services, "_CHANNELS_HOME", tmp_path / "channels_data")

    specs = services.all_services()
    spec = next(s for s in specs if s.name == "iris-server")
    channels = next(s for s in specs if s.name == "channels-daemon")

    assert spec.cwd == root / "mentra-os" / "miniapps" / "openalma"
    assert spec.cmd[-1] == "scripts/release-private.mjs"
    assert spec.env["PATH"].split(":", 1)[0].endswith("/.bun/bin")
    assert spec.port == 6789
    assert channels.env["CHANNELS_HOME"] == str(tmp_path / "channels_data")


def test_optional_service_install_marker_controls_visibility(tmp_path):
    marker = tmp_path / "client" / "package.json"
    spec = services.ServiceSpec("client", "Client", [], tmp_path, tmp_path / "log", tmp_path / "pid", install_marker=marker)

    assert services.is_installed(spec) is False
    marker.parent.mkdir()
    marker.touch()
    assert services.is_installed(spec) is True


def test_host_prerequisites_ignore_uninstalled_optional_clients(tmp_path, monkeypatch):
    for path in (
        "openalma/launcher/run.py",
        "mcp-memu-server/run.py",
        "memu/pyproject.toml",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).touch()
    venv_python = tmp_path / "mcp-memu-server/.venv/bin/python3"
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(sys.executable)
    monkeypatch.setattr(services.shutil, "which", lambda command: f"/usr/bin/{command}")

    result = services.host_prerequisites(tmp_path, tmp_path / "missing-os-release")

    assert result["ready"] is True
    assert result["rows"][1]["detail"] == "Ready"
    assert result["rows"][2]["detail"] == "Ready"


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
    assert spec.env["ATOMIC_SERVER_BIN"].endswith("target/server/atomic-server")


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


def test_owner_request_uses_shared_mcp_transport(monkeypatch):
    seen = {}

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


def test_memorize_status_uses_active_soul_and_shared_owner(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    import app as launcher_app  # noqa: PLC0415

    seen = {}
    config = tmp_path / "channels.json"
    config.write_text(json.dumps({"soul_id": "Fictional Soul", "user_id": "Wrong User"}))
    monkeypatch.setattr(launcher_app.soul, "CHANNELS_CONFIG_PATH", config)
    monkeypatch.setattr(launcher_app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(
        launcher_app.services,
        "memorize_pending",
        lambda soul_id, user_id: seen.setdefault((soul_id, user_id), {"threshold": 6000}),
    )

    assert launcher_app.memorize_status() == {"threshold": 6000}
    assert ("Fictional Soul", "Fictional Owner") in seen


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
    monkeypatch.setattr(services, "_proc_cmdline", lambda _pid: "node server.js")

    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: tmp_path / "other")
    assert services._matches_service_process(spec, 123) is False

    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: spec.cwd)
    assert services._matches_service_process(spec, 123) is True


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


def test_status_reports_stuck_for_verified_process_without_port(tmp_path, monkeypatch):
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
    old = time.time() - services.STARTUP_GRACE_SECONDS - 1
    os.utime(spec.pid_path, (old, old))
    monkeypatch.setattr(services, "is_running", lambda _spec: False)
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [123])
    monkeypatch.setattr(services, "_port_listener_pid", lambda _port: None)

    status = services.status(spec)

    assert status["running"] is False
    assert status["state"] == "stuck"
    assert status["status_label"] == "▲ stuck"
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


def test_stop_status_shows_force_only_with_failure_evidence(tmp_path):
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
    finally:
        with services._STOP_LOCK:
            services._STOP_THREADS.pop(spec.name, None)
            services._STOP_STARTED.pop(spec.name, None)
    assert stuck["force_stoppable"] is True


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

    with pytest.raises(RuntimeError, match="no graceful Windows shutdown"):
        services.stop(spec)
    assert services._stop_status(spec, {"running": True, "stuck": False})["force_stoppable"] is True


def test_stop_requests_unlimited_memu_drain_without_signaling(tmp_path, monkeypatch):
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
        "timeout": 2,
    }


def test_elapsed_graceful_stop_exposes_manual_force_for_any_service(tmp_path, monkeypatch):
    monkeypatch.setattr(services, "FORCE_STOP_RECOVERY_SECONDS", 30)
    for name in ("memu-server", "channels-daemon", "iris-server"):
        spec = services.ServiceSpec(name, name, [], tmp_path, tmp_path / "log", tmp_path / "pid")
        with services._STOP_LOCK:
            services._STOP_THREADS[name] = services.threading.current_thread()
            services._STOP_STARTED[name] = services.time.monotonic() - 31
        try:
            status = services._stop_status(spec, {"running": True, "stuck": False})
            assert status["force_stoppable"] is True
            assert "still running" in status["detail"]
        finally:
            with services._STOP_LOCK:
                services._STOP_THREADS.pop(name, None)
                services._STOP_STARTED.pop(name, None)


def test_channels_daemon_in_all_services(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    for name in ("mcp-memu-server", "hermes-channels"):
        (root / name).mkdir(parents=True)
    (root / "sillytavern" / "SillyTavern").mkdir(parents=True)
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)

    names = [spec.name for spec in services.all_services()]

    assert "channels-daemon" in names


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


def test_channels_daemon_verified_pids_include_whatsapp_children(tmp_path, monkeypatch):
    channels_home = tmp_path / "channels_data"
    whatsapp_home = channels_home / "whatsapp"
    session_path = whatsapp_home / "session"
    session_path.mkdir(parents=True)
    (session_path / "bridge.pid").write_text("41", encoding="utf-8")
    (whatsapp_home / "web_source.pid").write_text("42", encoding="utf-8")
    monkeypatch.setattr(services, "_CHANNELS_HOME", channels_home)
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda pid: pid in {41, 42})

    def cmdline(pid):
        if pid == 41:
            return f"node bridge.js --port 3000 --session {session_path} --mode self-chat"
        if pid == 42:
            return (
                "node source-daemon.js "
                f"--db {whatsapp_home / 'web_source.db'} "
                f"--status {whatsapp_home / 'web_source_status.json'}"
            )
        return ""

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
