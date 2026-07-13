import json
import os
import sys
import time
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

    assert "hermes-gateway" not in names
    assert "channels-daemon" in names
    assert "whatsapp-bridge" not in names
    assert "whatsapp-web-source" not in names
    assert labels == {
        "memu-server": "memU Server",
        "atomic": "Atomic Mind Map",
        "channels-daemon": "Hermes Channels",
        "sillytavern": "SillyTavern",
    }


def test_atomic_service_is_managed_by_launcher(tmp_path, monkeypatch):
    root = tmp_path / "apps"
    for name in ("mcp-memu-server", "atomic", "hermes-channels", "sillytavern"):
        (root / name).mkdir(parents=True)
    monkeypatch.setattr(services, "_resolve_apps_root", lambda: root)

    spec = next(s for s in services.all_services() if s.name == "atomic")

    assert spec.label == "Atomic Mind Map"
    assert spec.cwd == root / "atomic"
    assert spec.port == 1420
    assert spec.cmd[:2] == ["sh", "-c"]
    assert "npm run dev:server" in spec.cmd[2]


def test_atomic_start_command_uses_channels_config_identity():
    cmd = services._atomic_start_command({"user_id": "Test User", "soul_id": "Test Soul"})

    assert 'ATOMIC_SERVER_BIN="${ATOMIC_SERVER_BIN:-$PWD/target/server/atomic-server}"' in cmd
    assert 'token_output=$("$ATOMIC_SERVER_BIN" token create --name openalma-launcher)' in cmd
    assert "cargo run" not in cmd
    assert "MEMU_USER_ID='Test User'" in cmd
    assert "MEMU_SOUL_ID='Test Soul'" in cmd
    assert 'RUST_LOG="warn,atomic_server=warn,atomic_core=warn"' in cmd
    assert "MEMU_USER_ID:-Marcos" not in cmd
    assert "MEMU_SOUL_ID:-Siri" not in cmd
    assert "fiif" not in cmd


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


def test_memorize_status_uses_active_soul_and_user(monkeypatch):
    pytest.importorskip("fastapi")
    import app as launcher_app  # noqa: PLC0415

    seen = {}
    monkeypatch.setattr(launcher_app.soul, "read_active_soul_id", lambda: "Siri")
    monkeypatch.setattr(launcher_app.soul, "read_active_user_id", lambda: "Marcos")
    monkeypatch.setattr(
        launcher_app.services,
        "memorize_pending",
        lambda soul_id, user_id: seen.setdefault((soul_id, user_id), {"threshold": 6000}),
    )

    assert launcher_app.memorize_status() == {"threshold": 6000}
    assert ("Siri", "Marcos") in seen


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

    class Result:
        stdout = 'users:(("python",pid=123,fd=7))'

    def fake_run(*_args, **_kwargs):
        calls.append(True)
        return Result()

    monkeypatch.setattr(services, "_PORT_PID_CACHE", {})
    monkeypatch.setattr(services.subprocess, "run", fake_run)

    assert services._port_listener_pid(8099) == 123
    assert services._port_listener_pid(8099) == 123

    assert len(calls) == 1


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
        label="memU Server",
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
        label="memU Server",
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
        label="memU Server",
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
