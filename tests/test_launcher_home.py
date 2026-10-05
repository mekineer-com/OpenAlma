import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import app  # noqa: E402
import services  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_memorize_status(monkeypatch):
    monkeypatch.setattr(app.services, "memorize_pending", lambda *_args, **_kwargs: {})


def test_malformed_channels_config_keeps_home_available(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text("{broken", encoding="utf-8")
    other = services.ServiceSpec(
        "atomic",
        "Atomic Mind Map",
        [],
        tmp_path,
        tmp_path / "atomic.log",
        tmp_path / "atomic.pid",
    )
    monkeypatch.setattr(app.soul, "CHANNELS_CONFIG_PATH", config)
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.policy, "ensure_channel_settings", lambda _chats: ({}, "excluded"))
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [other])
    monkeypatch.setattr(app.services, "is_installed", lambda _spec: True)
    monkeypatch.setattr(app.services, "status", lambda _spec: {"state": "stopped"})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    response = TestClient(app.app, base_url="http://127.0.0.1").get("/")

    assert response.status_code == 200
    assert "Atomic Mind Map" in response.text
    assert "Channels configuration needs repair" not in response.text
    assert "Channels configuration needs repair" in TestClient(app.app, base_url="http://127.0.0.1").get("/hermes").text
    assert config.read_text(encoding="utf-8") == "{broken"


def test_fresh_root_shows_core_install_without_runtime_status(tmp_path, monkeypatch):
    monkeypatch.setattr(app.settings, "apps_root", lambda: None)
    monkeypatch.setattr(app.settings, "setup_apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "status", lambda _spec: pytest.fail("runtime status must not run"))
    monkeypatch.setattr(app.setup_install, "setup_status", lambda _root: {
        "state": "setup", "status_label": "Not installed", "detail": "Missing core",
        "startable": False, "action_kind": "install", "action_label": "Install",
    })

    response = TestClient(app.app, base_url="http://127.0.0.1").get("/")

    assert response.status_code == 200
    assert "memU Server" in response.text
    assert 'action="/install/memu-server"' in response.text
    assert "Hermes Channels" in response.text
    assert "disabled" in response.text


def test_launcher_quit_uses_server_callback(monkeypatch):
    called = []
    monkeypatch.setattr(app.app.state, "request_shutdown", lambda: called.append(True), raising=False)

    response = TestClient(app.app, base_url="http://127.0.0.1").post("/launcher/quit")

    assert response.json() == {"ok": True}
    assert called == [True]


def test_launcher_mutations_reject_foreign_browser_origins(monkeypatch):
    called = []
    monkeypatch.setattr(app.app.state, "request_shutdown", lambda: called.append(True), raising=False)
    client = TestClient(app.app, base_url="http://127.0.0.1:8765")
    for headers in [
        {"origin": "https://foreign.example", "sec-fetch-site": "same-origin"},
        {"origin": "null"}, {"sec-fetch-site": "cross-site"}, {"host": "foreign.example"},
    ]:
        assert client.post("/launcher/quit", headers=headers).status_code == 403
    assert not called
    assert client.post("/launcher/quit").status_code == 200
    assert client.post("/launcher/quit", headers={"origin": "http://127.0.0.1:8765",
                                                 "sec-fetch-site": "same-origin"}).status_code == 200
    monkeypatch.setattr(app.app.state, "launcher_host", "lan.example", raising=False)
    configured = TestClient(app.app, base_url="http://lan.example:8765")
    assert configured.post("/launcher/quit", headers={"origin": "http://lan.example:8765"}).status_code == 200
    assert len(called) == 3


def test_launcher_identity_and_favicon_are_available():
    client = TestClient(app.app, base_url="http://127.0.0.1")

    assert client.get("/launcher/identity").json() == {
        "application": "openalma-launcher", "protocol": 1,
    }
    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
    assert "<svg" in favicon.text


def test_settings_shows_managed_embedding_model(tmp_path, monkeypatch):
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.settings, "setup_apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.settings, "read_paths", lambda: {})
    monkeypatch.setattr(app.settings, "next_apps_root", lambda _raw: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [])
    monkeypatch.setattr(app.services, "mentra_readiness", lambda _root: pytest.fail("general Settings must not load Iris"))
    monkeypatch.setattr(app.services, "host_prerequisites", lambda _root: {"rows": []})

    html = TestClient(app.app, base_url="http://127.0.0.1").get("/settings").text

    assert '<select id="embedding-model" disabled>' in html
    assert '<option selected>gemini-embedding-2</option>' in html
    assert "Iris &amp; Phone Setup" not in html and 'id="pair-panel"' not in html


def test_client_setup_pages_keep_qr_dependencies_and_shared_header(tmp_path, monkeypatch):
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [])
    monkeypatch.setattr(app.services, "mentra_readiness", lambda _root: {"enabled": False})
    monkeypatch.setattr(app.services, "list_souls", lambda: ["TestSoul"])
    monkeypatch.setattr(app.soul, "CHANNELS_CONFIG_PATH", tmp_path / "missing-config.json")
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.policy, "read_default_policy", lambda: "excluded")
    client = TestClient(app.app, base_url="http://127.0.0.1")
    for page in ("/hermes", "/iris"):
        response = client.get(page)
        assert response.status_code == 200
        assert '/static/vendor/qrcode.min.js' in response.text
        assert '/static/launcher.js' in response.text
        assert '/static/window-position.js' in response.text
        assert 'aria-label="OpenAlma"' in response.text
        assert 'class="client-heading"' in response.text
        assert f'/static/{page[1:]}-logo.svg' in response.text
        for link in ("https://openalma.org", "https://github.com/mekineer-com/OpenAlma", "https://discord.gg/MyhGFhdN3b"):
            assert f'href="{link}"' in response.text
        assert 'aria-label="OpenAlma community"' in response.text
    assert 'id="pair-panel"' in client.get("/hermes").text
    assert 'id="pair-panel"' not in client.get("/iris").text


def test_policy_save_returns_to_hermes(monkeypatch):
    saved = []
    monkeypatch.setattr(app.policy, "write_default_policy", lambda value: saved.append(value))
    response = TestClient(app.app, base_url="http://127.0.0.1").post("/policy", data={"default_policy": "excluded"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/hermes"
    assert saved == ["excluded"]


def test_launcher_saves_window_position(tmp_path, monkeypatch):
    monkeypatch.setattr(app.settings, "SETTINGS_PATH", tmp_path / "paths.json")

    response = TestClient(app.app, base_url="http://127.0.0.1").post("/launcher/window-position?x=321&y=123")

    assert response.json() == {"ok": True}
    assert app.settings.read_paths()["window_position"] == {"x": 321, "y": 123}


@pytest.mark.parametrize("contents", ['{"apps_root":"/fictional/stack",}', '[]'])
def test_position_save_does_not_overwrite_invalid_settings(tmp_path, monkeypatch, contents):
    path = tmp_path / "paths.json"
    path.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(app.settings, "SETTINGS_PATH", path)
    with pytest.raises(ValueError):
        TestClient(app.app, base_url="http://127.0.0.1").post("/launcher/window-position?x=321&y=123")
    assert path.read_text(encoding="utf-8") == contents


def test_update_readiness_names_active_services(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic Mind Map", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {"running": True})

    response = TestClient(app.app, base_url="http://127.0.0.1").get("/launcher/update-readiness")

    assert response.json() == {
        "application": "openalma-launcher", "active_services": ["Atomic Mind Map"],
    }


def test_launcher_log_uses_launcher_log_path(tmp_path, monkeypatch):
    log = tmp_path / "launcher.log"
    log.write_text("launcher started\n", encoding="utf-8")
    monkeypatch.setattr(app.settings, "LAUNCHER_LOG_PATH", log)

    response = TestClient(app.app, base_url="http://127.0.0.1").get("/logs/launcher")

    assert response.status_code == 200
    assert "launcher started" in response.text


def test_active_core_enables_optional_install_actions(tmp_path, monkeypatch):
    specs = services.services_for_root(tmp_path)
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: specs)
    monkeypatch.setattr(app.setup_install, "core_issue", lambda _root: "")
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda name, _root: {
        "ready": False, "state": "setup", "status_label": "Not installed",
        "detail": "Missing checkout", "startable": False,
        "action_kind": "install", "action_label": "Install",
    })
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    response = TestClient(app.app, base_url="http://127.0.0.1").get("/")

    assert response.status_code == 200
    for name in ("iris-server", "atomic", "channels-daemon", "sillytavern"):
        assert f'action="/install/{name}"' in response.text


def test_live_service_keeps_stop_while_setup_is_incomplete():
    row = app._row_with_setup({
        "state": "running", "running": True, "stoppable": True,
    }, {
        "install_setup": True, "detail": "Installation incomplete", "action_kind": "install",
    })

    assert row["stoppable"] is True
    assert row["detail"] == "Installation incomplete"
    assert "install_setup" not in row


def test_stopped_incomplete_service_poll_returns_install_state(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    setup = {
        "ready": False, "state": "setup", "install_setup": True,
        "action_kind": "install", "detail": "Installation incomplete",
    }
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda _name, _root: setup)
    monkeypatch.setattr(app.services, "status", lambda _spec: {"state": "stopped", "running": False})

    assert app._setup_aware_status(spec, tmp_path) == setup


def test_live_and_blocked_services_do_not_run_core_setup_checks(tmp_path, monkeypatch):
    spec = services.ServiceSpec("memu-server", "memU", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.setup_install, "core_issue", lambda *_args, **_kwargs: pytest.fail("live runtime must skip setup checks"))

    for runtime in ({"state": "running", "running": True}, {"state": "blocked", "blocked": True}):
        monkeypatch.setattr(app.services, "status", lambda _spec, value=runtime: value.copy())
        assert app._setup_aware_status(spec, tmp_path) == runtime

    verified = []
    monkeypatch.setattr(app.services, "status", lambda _spec: {"state": "stopped", "running": False})
    monkeypatch.setattr(
        app.setup_install, "core_issue",
        lambda _root, *, verify_runtime=True: verified.append(verify_runtime) or "",
    )
    app._setup_aware_status(spec, tmp_path, verify_runtime=False)
    assert verified == [False]


def test_optional_install_refresh_skips_core_runtime_validation(tmp_path, monkeypatch):
    core = services.ServiceSpec("memu-server", "memU", [], tmp_path, tmp_path / "core.log", tmp_path / "core.pid")
    atomic = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "atomic.log", tmp_path / "atomic.pid")
    verified = []
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [core, atomic])
    monkeypatch.setattr(app.services, "is_installed", lambda _spec: True)
    monkeypatch.setattr(app.services, "status", lambda _spec: {"state": "stopped", "running": False})
    monkeypatch.setattr(
        app.setup_install, "operation_status",
        lambda _root, name="memu-server": {"state": "running" if name == "atomic" else "idle"},
    )
    monkeypatch.setattr(
        app.setup_install, "core_issue",
        lambda _root, *, verify_runtime=True: verified.append(verify_runtime) or "Missing runtime",
    )
    monkeypatch.setattr(
        app.setup_install, "setup_status",
        lambda _root, **_kwargs: {"state": "setup", "detail": "Missing runtime"},
    )
    monkeypatch.setattr(
        app.setup_install, "optional_setup_status",
        lambda _name, _root: {"ready": False, "install_running": True, "state": "setup", "detail": "Installing"},
    )
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    response = TestClient(app.app, base_url="http://127.0.0.1").get("/")

    assert response.status_code == 200
    assert verified == [False]


def test_connected_iris_counts_as_active_runtime():
    assert app._runtime_active({"state": "active", "active": True}) is True


def test_iris_runtime_setup_state_is_not_an_install_row(tmp_path, monkeypatch):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(
        app.setup_install, "optional_setup_status", lambda _name, _root: {"ready": True, "guidance": ""},
    )
    monkeypatch.setattr(app.services, "status", lambda _spec: {"state": "setup", "action_kind": "settings"})

    status = app._setup_aware_status(spec, tmp_path)

    assert status == {"state": "setup", "action_kind": "settings"}
    assert "install_setup" not in status


def test_uninstalled_iris_opens_phone_client_section_for_openalma_host(tmp_path, monkeypatch):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {
        "state": "stopped",
        "installed_package": None,
        "open_not_installed": True,
        "action_kind": "settings",
        "detail": "Not yet verified",
    })
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda *_args: {"ready": True, "guidance": ""})
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    html = TestClient(app.app, base_url="http://127.0.0.1").get("/").text

    assert '<details class="not-installed" open>' in html
    assert 'href="/iris">Setup</a>' in html
    assert 'data-service="iris-server"' not in html


def test_phone_reported_iris_is_a_service(tmp_path, monkeypatch):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {
        "state": "ready", "installed_package": "com.openalma.mentra",
    })
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda *_args: {"ready": True, "guidance": ""})
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    html = TestClient(app.app, base_url="http://127.0.0.1").get("/").text

    assert 'data-service="iris-server"' in html
    assert "Not installed (" not in html


def test_start_route_rejects_incomplete_setup(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    started = []
    monkeypatch.setattr(app, "_find_service", lambda _name: spec)
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.setup_install, "start_issue", lambda _name, _root: "Missing Atomic binary")
    monkeypatch.setattr(app.services, "start", lambda _spec: started.append(True))

    response = TestClient(app.app, base_url="http://127.0.0.1").post("/service/atomic/start")

    assert response.status_code == 409
    assert started == []


def test_open_route_uses_default_browser_tab(tmp_path, monkeypatch):
    spec = services.ServiceSpec(
        "sillytavern", "SillyTavern", [], tmp_path, tmp_path / "log", tmp_path / "pid",
        open_url="http://127.0.0.1:8001",
    )
    opened = []
    monkeypatch.setattr(app, "_find_service", lambda _name: spec)
    monkeypatch.setattr(app.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    response = TestClient(app.app, base_url="http://127.0.0.1").post("/service/sillytavern/open")

    assert response.json() == {"ok": True}
    assert opened == ["http://127.0.0.1:8001"]


def test_install_route_rejects_live_service(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    begun = []
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "services_for_root", lambda _root: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {"running": True})
    monkeypatch.setattr(app.setup_install, "begin_optional_install", lambda *_args: begun.append(True))

    response = TestClient(app.app, base_url="http://127.0.0.1").post("/install/atomic")

    assert response.status_code == 409
    assert begun == []


def test_install_conflict_returns_http_409(tmp_path, monkeypatch):
    spec = services.ServiceSpec("atomic", "Atomic", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "services_for_root", lambda _root: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {"running": False})
    monkeypatch.setattr(
        app.setup_install, "begin_optional_install",
        lambda *_args: (_ for _ in ()).throw(app.setup_install.SetupConflict("already running")),
    )

    response = TestClient(app.app, base_url="http://127.0.0.1").post("/install/atomic")

    assert response.status_code == 409


def test_recovery_route_reuses_update_readiness(tmp_path, monkeypatch):
    begun = []
    monkeypatch.setattr(app.settings, "setup_apps_root", lambda: tmp_path)
    monkeypatch.setattr(
        app, "launcher_update_readiness",
        lambda: {"application": app.LAUNCHER_ID, "active_services": []},
    )
    monkeypatch.setattr(app.setup_install, "begin_core_recovery", lambda root: begun.append(root))

    response = TestClient(app.app, base_url="http://127.0.0.1").post("/install/memu-server/recover", follow_redirects=False)

    assert response.status_code == 303
    assert begun == [tmp_path]


def test_runtime_to_install_poll_reloads_the_page():
    template = Path(__file__).resolve().parents[1] / "launcher/templates/index.html"
    text = template.read_text(encoding="utf-8")

    assert "data.install_setup && row.dataset.runtime === 'true'" in text
    assert "if (!data.install_setup) row.dataset.runtime = 'true'" in text
    assert "data.action_kind === 'install'" in text
    assert "location.reload();" in text


def test_unavailable_mcp_poll_refreshes_dependent_sections():
    template = Path(__file__).resolve().parents[1] / "launcher/templates/index.html"
    text = template.read_text(encoding="utf-8")

    assert "{% if owner_error or soul_error %}" in text
    assert "{% if owner_error %}/owner{% else %}/souls{% endif %}" in text
    assert "setInterval(pollMemorize, 10000)" in text


def test_owner_readiness_endpoint_tracks_owner_service(monkeypatch):
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")

    assert TestClient(app.app, base_url="http://127.0.0.1").get("/owner").json() == {"user_id": "Fictional Owner"}
