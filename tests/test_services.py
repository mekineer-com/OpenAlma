import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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


def test_whatsapp_bridge_is_not_a_normal_stack_service(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    for name in ("mcp-memu-server", "hermes-agent", "sillytavern"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)

    names = [spec.name for spec in services.all_services()]

    assert "hermes-gateway" in names
    assert "whatsapp-bridge" not in names
    assert "whatsapp-web-source" not in names


def test_memorize_pending_sends_user_id(monkeypatch):
    seen = {}

    def fake_urlopen(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(services, "all_services", lambda: [])
    monkeypatch.setattr(services.urllib.request, "urlopen", fake_urlopen)

    out = services.memorize_pending("Siri", "Marcos")
    query = parse_qs(urlparse(seen["url"]).query)

    assert out == {"threshold": 5000}
    assert query == {"soul_id": ["Siri"], "user_id": ["Marcos"]}
    assert seen["timeout"] == 2


def test_memu_server_uses_configured_pidfile_for_adoption(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    server_dir = root / "mcp-memu-server"
    memu_dir = root / "memu"
    server_dir.mkdir(parents=True)
    memu_dir.mkdir()
    (root / "hermes-agent").mkdir()
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


def test_status_reports_stuck_for_verified_process_without_port(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="memu-server",
        label="mcp-memu-server",
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
        label="mcp-memu-server",
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


def test_start_does_not_spawn_when_port_is_blocked(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="memu-server",
        label="mcp-memu-server",
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
        label="mcp-memu-server",
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


def test_hermes_gateway_verified_pids_include_whatsapp_children(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    session_path = hermes_home / "whatsapp" / "session"
    session_path.mkdir(parents=True)
    whatsapp_home = hermes_home / "whatsapp"
    (session_path / "bridge.pid").write_text("31", encoding="utf-8")
    (whatsapp_home / "web_source.pid").write_text("32", encoding="utf-8")
    monkeypatch.setattr(services, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda pid: pid in {31, 32})

    def cmdline(pid):
        if pid == 31:
            return f"node bridge.js --port 3000 --session {session_path} --mode bot"
        if pid == 32:
            return (
                "node source-daemon.js "
                f"--db {whatsapp_home / 'web_source.db'} "
                f"--status {whatsapp_home / 'web_source_status.json'}"
            )
        return ""

    monkeypatch.setattr(services, "_proc_cmdline", cmdline)
    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: None)
    spec = services.ServiceSpec(
        name="hermes-gateway",
        label="hermes-agent gateway",
        cmd=[],
        cwd=tmp_path / "hermes-agent",
        log_path=tmp_path / "gateway.log",
        pid_path=tmp_path / "gateway.pid",
    )

    assert services._verified_pid_candidates(spec) == [31, 32]


def test_hermes_child_only_state_is_orphaned_and_stoppable(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    session_path = hermes_home / "whatsapp" / "session"
    session_path.mkdir(parents=True)
    (session_path / "bridge.pid").write_text("31", encoding="utf-8")
    monkeypatch.setattr(services, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda pid: pid == 31)
    monkeypatch.setattr(
        services,
        "_proc_cmdline",
        lambda pid: f"node bridge.js --session {session_path}" if pid == 31 else "",
    )
    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: None)
    spec = services.ServiceSpec(
        name="hermes-gateway",
        label="hermes-agent gateway",
        cmd=[],
        cwd=tmp_path / "hermes-agent",
        log_path=tmp_path / "gateway.log",
        pid_path=tmp_path / "gateway.pid",
    )

    status = services.status(spec)

    assert status["running"] is False
    assert status["orphaned"] is True
    assert status["state"] == "orphaned"
    assert status["startable"] is False
    assert status["stoppable"] is True


def test_hermes_child_markers_follow_configured_whatsapp_paths(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    custom_session = tmp_path / "wa-session"
    custom_status = tmp_path / "wa" / "status.json"
    custom_db = tmp_path / "wa" / "source.db"
    custom_session.mkdir()
    custom_status.parent.mkdir()
    (hermes_home / "config.yaml").write_text(
        "\n".join([
            "whatsapp:",
            f"  session_path: {custom_session}",
            f"  web_source_db: {custom_db}",
            f"  web_source_status: {custom_status}",
            "  bridge_script: /opt/custom/bridge.js",
            "  web_source_script: /opt/custom/source-daemon.js",
            "",
        ]),
        encoding="utf-8",
    )
    (custom_session / "bridge.pid").write_text("31", encoding="utf-8")
    custom_status.with_name("web_source.pid").write_text("32", encoding="utf-8")
    monkeypatch.setattr(services, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(services, "_scan_service_pids", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda pid: pid in {31, 32})

    def cmdline(pid):
        if pid == 31:
            return f"node /opt/custom/bridge.js --session {custom_session}"
        if pid == 32:
            return f"node /opt/custom/source-daemon.js --db {custom_db} --status {custom_status}"
        return ""

    monkeypatch.setattr(services, "_proc_cmdline", cmdline)
    monkeypatch.setattr(services, "_proc_cwd", lambda _pid: None)
    spec = services.ServiceSpec(
        name="hermes-gateway",
        label="hermes-agent gateway",
        cmd=[],
        cwd=tmp_path / "hermes-agent",
        log_path=tmp_path / "gateway.log",
        pid_path=tmp_path / "gateway.pid",
    )

    assert services._verified_pid_candidates(spec) == [31, 32]


def test_signal_pid_uses_process_group_for_group_leader(monkeypatch):
    calls = []
    monkeypatch.setattr(services.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(services.os, "killpg", lambda pgid, sig: calls.append(("pg", pgid, sig)))
    monkeypatch.setattr(services.os, "kill", lambda pid, sig: calls.append(("pid", pid, sig)))

    services._signal_pid(44, services.signal.SIGTERM)

    assert calls == [("pg", 44, services.signal.SIGTERM)]


def test_stop_terminates_all_verified_pids_and_clears_dead_pidfiles(tmp_path, monkeypatch):
    adopt_pid = tmp_path / "server-owned.pid"
    adopt_pid.write_text("11", encoding="utf-8")
    spec = services.ServiceSpec(
        name="memu-server",
        label="mcp-memu-server",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "launcher.pid",
        adopt_pid_path=adopt_pid,
    )
    spec.pid_path.write_text("10", encoding="utf-8")
    calls = {"count": 0}

    def verified(_spec):
        calls["count"] += 1
        return [10, 11] if calls["count"] == 1 else []

    killed = []
    monkeypatch.setattr(services, "_verified_pid_candidates", verified)
    monkeypatch.setattr(services.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(services, "_is_alive", lambda _pid: False)

    services.stop(spec, timeout=1)

    assert killed == [(10, services.signal.SIGTERM), (11, services.signal.SIGTERM)]
    assert not spec.pid_path.exists()
    assert not adopt_pid.exists()


def test_stop_leaves_live_nonmatching_service_pidfile(tmp_path, monkeypatch):
    adopt_pid = tmp_path / "server-owned.pid"
    adopt_pid.write_text("99", encoding="utf-8")
    spec = services.ServiceSpec(
        name="memu-server",
        label="mcp-memu-server",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "launcher.pid",
        adopt_pid_path=adopt_pid,
    )
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [])
    monkeypatch.setattr(services, "_is_alive", lambda pid: pid == 99)

    services.stop(spec, timeout=0)

    assert adopt_pid.exists()


def test_stop_escalates_only_verified_matching_pids(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="memu-server",
        label="mcp-memu-server",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "server.log",
        pid_path=tmp_path / "launcher.pid",
    )
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [20])
    killed = []
    monkeypatch.setattr(services.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    services.stop(spec, timeout=0)

    assert killed == [(20, services.signal.SIGTERM), (20, services.signal.SIGKILL)]


def test_hermes_gateway_status_uses_whatsapp_degraded_state(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "gateway_state.json").write_text(
        json.dumps({
            "pid": 111,
            "platforms": {
                "whatsapp": {
                    "state": "degraded",
                    "bridge": {"state": "ready", "mode": "bot"},
                    "web_source": {"state": "degraded", "error": "writer exited"},
                    "soul_history": {"state": "degraded", "error": "history failed"},
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(services, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(
            verified_pids=(111,),
            service_pids=(111,),
            child_pids=(),
            pid=111,
            port_pid=None,
            running=True,
            stuck=False,
            orphaned=False,
            port_blocked=False,
        ),
    )
    spec = services.ServiceSpec(
        name="hermes-gateway",
        label="hermes-agent gateway",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "gateway.log",
        pid_path=tmp_path / "gateway.pid",
    )

    status = services.status(spec)

    assert status["running"] is True
    assert status["state"] == "degraded"
    assert status["status_label"] == "▲ degraded"
    assert status["children"] == [
        {"name": "bridge", "state": "ready", "detail": "mode bot"},
        {"name": "web-source", "state": "degraded", "detail": "writer exited"},
        {"name": "soul-history", "state": "degraded", "detail": "history failed"},
    ]


def test_hermes_gateway_status_ignores_stale_runtime_pid(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    (hermes_home / "gateway_state.json").write_text(
        json.dumps({
            "pid": 111,
            "platforms": {
                "whatsapp": {
                    "state": "healthy",
                    "bridge": {"state": "ready", "mode": "bot"},
                }
            },
        }),
        encoding="utf-8",
    )
    pid_path = tmp_path / "gateway.pid"
    pid_path.write_text("222", encoding="utf-8")
    monkeypatch.setattr(services, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(
        services,
        "_runtime_state",
        lambda _spec: services.RuntimeState(
            verified_pids=(222,),
            service_pids=(222,),
            child_pids=(),
            pid=222,
            port_pid=None,
            running=True,
            stuck=False,
            orphaned=False,
            port_blocked=False,
        ),
    )
    spec = services.ServiceSpec(
        name="hermes-gateway",
        label="hermes-agent gateway",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "gateway.log",
        pid_path=pid_path,
    )

    status = services.status(spec)

    assert status["running"] is True
    assert status["state"] == "starting"
    assert status["status_label"] == "◐ starting"
    assert status["detail"] == "waiting for Hermes status"


def test_status_json_includes_supports_terminal(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        name="sillytavern",
        label="SillyTavern",
        cmd=[],
        cwd=tmp_path,
        log_path=tmp_path / "st.log",
        pid_path=tmp_path / "st.pid",
        supports_terminal=True,
    )
    monkeypatch.setattr(services, "_verified_pid_candidates", lambda _spec: [])

    assert services.status(spec)["supports_terminal"] is True
