import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import app  # noqa: E402
import services  # noqa: E402


@pytest.fixture(autouse=True)
def _no_live_status(monkeypatch):
    def offline(*_args, **_kwargs):
        raise OSError("Network disabled in launcher home tests")
    monkeypatch.setattr(app.services.urllib.request, "urlopen", offline)
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
    for spec in services.services_for_root(tmp_path):
        assert f'data-service="{spec.name}" data-installed="false"' in response.text
    assert 'data-service="atomic" data-installed="false" data-runtime="false"' in response.text


def test_home_groups_iris_by_reported_phones_not_checkout(tmp_path, monkeypatch):
    iris = services.ServiceSpec("iris-server", "Mentra Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [iris])
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: [])
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda *_args: {"ready": True, "guidance": ""})
    monkeypatch.setattr(app.services, "status", lambda _spec: {"installations": [], "state": "ready"})
    client = TestClient(app.app, base_url="http://127.0.0.1")
    assert 'data-service="iris-server" data-installed="false"' in client.get("/").text
    monkeypatch.setattr(app.services, "status", lambda _spec: {
        "installations": [{"device_session_id": "fictional-phone", "host_reporting": True}], "state": "ready",
    })
    assert 'data-service="iris-server" data-installed="true"' in client.get("/").text


def test_echo_install_is_one_time_and_shared_between_browsers(tmp_path, monkeypatch):
    path = tmp_path / "paths.json"
    path.write_text(json.dumps({"release_channel": "stable", "window_position": {"x": 1, "y": 2}}), encoding="utf-8")
    monkeypatch.setattr(app.settings, "SETTINGS_PATH", path)
    monkeypatch.setattr(app.settings, "apps_root", lambda: None)
    monkeypatch.setattr(app.settings, "setup_apps_root", lambda: None)
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: [])
    monkeypatch.setattr(app.setup_install, "launcher_update", lambda: None)
    written = []
    write_paths = app.settings.write_paths

    def record_write(paths):
        written.append(paths.copy())
        write_paths(paths)

    monkeypatch.setattr(app.settings, "write_paths", record_write)
    client = TestClient(app.app, base_url="http://127.0.0.1")
    assert 'action="/echo/enable"' in client.get("/").text
    response = client.post("/echo/enable", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/"
    assert app.settings.read_paths() == {
        "release_channel": "stable", "window_position": {"x": 1, "y": 2}, "echo_enabled": True,
    }
    assert client.post("/echo/enable", follow_redirects=False).status_code == 303
    assert len(written) == 1
    home = TestClient(app.app, base_url="http://127.0.0.1").get("/").text
    assert '<tr id="echo-row" data-installed="true">' in home
    assert 'action="/echo/enable"' not in home
    assert '>Installed</button>' not in home and '>Update</button>' not in home
    assert 'href="/echo">Setup</a>' in home


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
    for method in ("get", "head"):
        assert getattr(client, method)("/launcher/identity", headers={"host": "foreign.example"}).status_code == 403
    assert client.get("/launcher/identity", headers={"origin": "https://foreign.example", "sec-fetch-site": "cross-site"}).status_code == 200
    assert client.post("/launcher/quit").status_code == 200
    assert client.post("/launcher/quit", headers={"origin": "http://127.0.0.1:8765",
                                                 "sec-fetch-site": "same-origin"}).status_code == 200
    monkeypatch.setattr(app.app.state, "launcher_host", "LAN.Example", raising=False)
    configured = TestClient(app.app, base_url="http://lan.example:8765")
    assert configured.post("/launcher/quit", headers={"origin": "http://lan.example:8765"}).status_code == 200
    assert configured.get("/launcher/identity").status_code == 200
    assert len(called) == 3


def test_client_setup_pages_keep_qr_dependencies_and_shared_header(tmp_path, monkeypatch):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    installations = [
        {"device_session_id": "stock-test", "display_name": "Stock test",
         "host_package": "com.mentra.mentra", "status_label": "Stock-only status",
         "detail": "Stock-only detail", "soul_id": "Stock Soul"},
        {"device_session_id": "fork-test", "display_name": "Fork test",
         "host_package": "com.mentra.mentra.openalma", "status_label": "Fork-only status",
         "detail": "Fork-only detail", "soul_id": "Fork Soul",
         "host_reporting": True,
         "action_kind": "start", "action_label": "Install", "startable": True},
    ]
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {
        "installations": installations, "running": True,
        "release_device_session_id": "stock-test", "release_host_package": "com.mentra.mentra",
        "release_uri": "miniapp://fixture.invalid/stock", "status_label": "Stock installer active",
    })
    monkeypatch.setattr(app.services, "mentra_readiness", lambda _root: {"enabled": True, "ready": True, "rows": []})
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda *_args: {"ready": True, "guidance": ""})
    monkeypatch.setattr(app.services, "list_souls", lambda: ["TestSoul"])
    monkeypatch.setattr(app.soul, "CHANNELS_CONFIG_PATH", tmp_path / "missing-config.json")
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.policy, "read_default_policy", lambda: "excluded")
    client = TestClient(app.app, base_url="http://127.0.0.1")
    for page in ("/hermes", "/iris", "/iris?device_session_id=stock-test", "/iris?device_session_id=fork-test"):
        response = client.get(page)
        assert response.status_code == 200
        assert '/static/vendor/qrcode.min.js' in response.text
        assert '/static/launcher.js' in response.text
        assert '/static/window-position.js' in response.text
        assert 'aria-label="OpenAlma"' in response.text
        assert 'class="client-heading"' in response.text
        assert f'/static/{page[1:].split("?", 1)[0]}-logo.svg' in response.text
        for link in ("https://openalma.org", "https://github.com/mekineer-com/OpenAlma", "https://discord.gg/MyhGFhdN3b"):
            assert f'href="{link}"' in response.text
        assert 'aria-label="OpenAlma community"' in response.text
        if page.startswith("/iris"):
            visible = response.text.split('<script src="/static/vendor/qrcode.min.js">', 1)[0]
            assert "OpenAlma Mentra" in visible
            assert "choose OpenAlma if Android offers sign-in apps" not in visible
            assert "First connect your phone and server through WireGuard or another trusted private connection" in visible
            assert "Connection help" not in visible
            assert "Saving the address does not configure" not in visible
            assert '>Iris installer</h3>' not in visible
            assert "only Mentra routes through your private proxy" not in visible
            assert "they do not check your phone" not in visible
            assert "For first installation, Iris receives this address automatically" not in visible
            assert "Devices allowed to reach this endpoint" not in visible
            steps = visible.split('id="iris-address-busy"', 1)[1].split('<ol class="tight">', 1)[1].split('</ol>', 1)[0]
            assert steps.count('<li>') == 5
            assert steps.count('href="/">main page</a>') == 1
            assert 'Install OpenAlma Mentra: <button class="btn qr-inline"' in steps
            assert 'Enter the server address into Mentra.' in steps
            assert 'id="mentra-apk-popup"' in visible
            assert 'Click Install beside your phone on the <a href="/">main page</a> to install Iris.' in steps
            assert 'or you open Setup' not in visible
            assert 'automatically after OpenAlma Mentra reports your phone.' in visible
            assert 'For Stock Mentra, clicking Install below prepares the tools first.' in visible
            stock = ""
            if page.endswith('=fork-test'):
                assert 'id="iris-stock-installation"' not in visible
                assert 'href="https://play.google.com/store/apps/details?id=com.mentra.mentra"' not in visible
            else:
                stock = visible.split('<details id="iris-stock-installation"', 1)[1].split('</details>', 1)[0]
                assert '<summary class="iris-section">Stock Mentra installation</summary>' in stock
                app_heading = '>App status</h3>' if '?device_session_id=' in page else '>App installations</h3>'
                assert visible.index(app_heading) < visible.index('<summary class="iris-section">Stock Mentra installation</summary>')
                assert 'href="https://play.google.com/store/apps/details?id=com.mentra.mentra"' in stock
                assert "and sign in" in stock
                assert "Miniapp Developer Settings" in stock
                assert "Choose or create a Soul on the phone" in stock
            assert 'id="iris-installer-status"' not in stock
            assert 'id="iris-action-error"' not in stock
            selected = next((row for row in installations if page.endswith("=" + row["device_session_id"])), None)
            for row in installations:
                if row is selected:
                    assert f'data-device-session-id="{row["device_session_id"]}"' in visible
                    assert row["status_label"] in visible
                    assert row["detail"] in visible
                    assert row["soul_id"] in visible
                else:
                    assert f'data-device-session-id="{row["device_session_id"]}"' not in visible
                    assert row["status_label"] not in visible
                    assert row["detail"] not in visible
                    assert row["soul_id"] not in visible
            if selected:
                assert f'<h2>{selected["display_name"]} setup</h2>' in visible
                assert '>Install Iris in Stock Mentra</button>' not in visible
                forget = visible.split('data-forget>', 1)[1].split('</form>', 1)[0]
                assert 'disabled' in forget
            else:
                assert '>Install Iris in Stock Mentra</button>' in stock
                for row in installations:
                    assert f'href="/iris?device_session_id={row["device_session_id"]}"' in visible
            assert ('id="iris-install-qr"' in visible) == (selected is not installations[1])
            assert ("Stock installer active" in visible) == (selected is not installations[1])
            assert ('id="iris-install-qr"' in stock) == (selected is not installations[1])
            assert ('open' in stock.split('>', 1)[0]) == (selected is not installations[1])
    installations[1]["host_reporting"] = False
    visible = client.get("/iris?device_session_id=fork-test").text
    assert 'disabled' not in visible.split('data-forget>', 1)[1].split('</form>', 1)[0]
    installations[1]["metadata_known"] = False
    visible = client.get("/iris?device_session_id=fork-test").text
    assert 'App details unavailable (version unknown), Iris not yet reported' in visible
    assert client.get("/iris?device_session_id=unknown-app").status_code == 404
    for release_state, message in (
        ("unavailable", "GitHub releases unavailable."),
        ("none", "No GitHub release published."),
        ("invalid", "No supported stable Iris ZIP found in recent GitHub releases."),
    ):
        monkeypatch.setattr(services, "status", lambda _spec, state=release_state: {
            "github_status": state, "installations": [], "available_package": services.IRIS_PACKAGE,
            "available_version": "",
        })
        visible = client.get("/iris").text
        assert message in visible
        assert ' selected.' not in visible
        assert 'disabled' in visible.split('id="iris-install-form">', 1)[1].split('</form>', 1)[0]
    monkeypatch.setattr(services, "status", lambda _spec: {
        "installations": [], "available_package": services.IRIS_PACKAGE, "available_version": "0.1.0",
    })
    visible = client.get("/iris").text
    assert 'disabled' not in visible.split('id="iris-install-form">', 1)[1].split('</form>', 1)[0]
    assert 'open' not in visible.split('<details id="iris-stock-installation"', 1)[1].split('>', 1)[0]
    for state in ("running", "starting", "stuck", "orphaned"):
        monkeypatch.setattr(services, "status", lambda _spec, state=state: {
            "installations": installations, state: True, "stoppable": True,
            "release_device_session_id": "stock-test", "release_host_package": "com.mentra.mentra",
        })
        for page in ("/iris", "/iris?device_session_id=stock-test"):
            visible = client.get(page).text
            stock = visible.split('<details id="iris-stock-installation"', 1)[1].split('</details>', 1)[0]
            assert 'open' in stock.split('>', 1)[0]
            assert '>Cancel</button>' in visible and '>Cancel</button>' not in stock
    monkeypatch.setattr(services, "status", lambda _spec: {
        "installations": installations, "running": True, "force_stoppable": True,
        "release_device_session_id": "fork-test", "release_host_package": "com.mentra.mentra.openalma",
    })
    for page in ("/iris", "/iris?device_session_id=fork-test"):
        visible = client.get(page).text
        stock = visible.split('<details id="iris-stock-installation"', 1)[1].split('</details>', 1)[0] if page == '/iris' else ''
        assert 'open' not in stock.split('>', 1)[0]
        assert "Bring the targeted OpenAlma Mentra app to the foreground" in visible
        assert "Bring the targeted OpenAlma Mentra app to the foreground" not in stock
        assert '>Force Stop</button>' in visible and '>Force Stop</button>' not in stock
    with pytest.MonkeyPatch.context() as unavailable:
        unavailable.setattr(services, "status", lambda _spec: {"state": "unavailable"})
        assert client.get("/iris?device_session_id=stock-test").status_code == 503
        visible = client.get("/iris").text
        assert 'disabled' in visible.split('id="iris-install-form">', 1)[1].split('</form>', 1)[0]
        assert 'Iris app status is unavailable.' in visible
    assert 'id="pair-panel"' in client.get("/hermes").text
    assert 'id="pair-panel"' not in client.get("/iris").text


@pytest.mark.parametrize("device_session_id,host_package,target", [
    ("stock-test", "com.mentra.mentra", "/iris?device_session_id=stock-test"),
    ("fork-test", "com.mentra.mentra.openalma", "/iris?device_session_id=fork-test"),
    ("", "", "/iris"),
])
def test_iris_install_redirect_preserves_provided_target(tmp_path, monkeypatch, device_session_id, host_package, target):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    started = []
    monkeypatch.setattr(app, "_find_service", lambda _name, **_kwargs: spec)
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.setup_install, "start_issue", lambda *_args: "")
    monkeypatch.setattr(app.setup_install, "optional_issue", lambda *_args: "")
    monkeypatch.setattr(app.setup_install, "release_issue", lambda *_args: "")
    monkeypatch.setattr(app, "_start_iris_install", lambda *args: started.append(args))

    response = TestClient(app.app, base_url="http://127.0.0.1").post(
        "/iris/install", data={"device_session_id": device_session_id, "host_package": host_package},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == target
    assert started == [(spec, device_session_id, host_package)]


@pytest.mark.parametrize("mentra", [None, {"enabled": True, "public_base_url": "http://10.77.0.1"}])
def test_iris_address_save_preserves_config_and_backs_up(tmp_path, monkeypatch, mentra):
    import json
    path = tmp_path / "mcp-memu-server/config.json"
    path.parent.mkdir()
    original = json.dumps({"other": "keep", **({"mentra": mentra} if mentra is not None else {})}) + "\n"
    path.write_text(original)
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [])
    monkeypatch.setattr(app.services, "_runtime_state", lambda _spec: services.RuntimeState())
    client = TestClient(app.app, base_url="http://127.0.0.1")
    for address in ("http://bad host", "http://server:99999", "http://user@server", "ftp://server", "http://server/path",
                    "http://127.0.0.1:8099", "http://127.2.3.4", "http://[::1]:8099",
                    "http://localhost:8099", "http://LOCALHOST.:8099"):
        assert client.post("/iris/address", data={"public_base_url": address}).status_code == 400
    assert path.read_text() == original
    for address in ("http://100.90.1.2", "https://server.example", "https://8.8.8.8"):
        assert client.post("/iris/address", data={"public_base_url": address}, follow_redirects=False).status_code == 303
        assert json.loads(path.read_text()) == {"mentra": {**(mentra or {}), "public_base_url": address}, "other": "keep"}
    assert Path(str(path) + ".orig").read_text() == original
    assert json.loads(Path(str(path) + "2.orig").read_text())["mentra"]["public_base_url"] == "http://100.90.1.2"


def test_policy_save_returns_to_hermes(monkeypatch):
    saved = []
    monkeypatch.setattr(app.policy, "write_channel_settings", lambda updates, *, default_policy: saved.append((updates, default_policy)))
    response = TestClient(app.app, base_url="http://127.0.0.1").post("/policy", data={"default_policy": "excluded"}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/hermes"
    assert saved == [({}, "excluded")]


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


@pytest.mark.parametrize("install_running", [False, True])
def test_update_readiness_names_active_services(tmp_path, monkeypatch, install_running):
    spec = services.ServiceSpec("atomic", "Atomic Mind Map", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {"running": True})

    monkeypatch.setattr(app.setup_install, "INSTALL_LOCK", tmp_path / "install.lock")
    handle = app.setup_install._acquire_install_lock("memu-server", tmp_path) if install_running else None
    try:
        response = TestClient(app.app, base_url="http://127.0.0.1").get("/launcher/update-readiness")
        active = ["Atomic Mind Map"]
        if install_running:
            active.append("Installation in progress (wait for it to finish)")
        assert response.json() == {"application": "openalma-launcher", "active_services": active}
    finally:
        if handle is not None:
            app.setup_install._release_install_lock(handle)


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
    monkeypatch.setattr(app.setup_install, "core_issue", lambda _root, **_kwargs: "")
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
    assert 'action="/install/iris-server"' not in response.text
    parent = response.text.split('<tr data-service="iris-server"', 1)[1].split('</tr>', 1)[0]
    assert '>apk on github</a>' in parent
    assert '>QR</button>' in parent and '>Setup</a>' in parent
    assert '<form' not in parent and '>Install</button>' not in parent
    for name in ("atomic", "channels-daemon", "sillytavern"):
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

    assert status == {"state": "setup", "action_kind": "settings", "preparation_attempted": False}
    assert "install_setup" not in status


@pytest.mark.parametrize("setup", [
    {"ready": False, "status_label": "Installing", "install_running": True, "detail": "Dependencies"},
    {"ready": False, "status_label": "Installation incomplete", "detail": "Missing dependencies"},
    {"ready": False, "status_label": "Preparation failed", "detail": "Download failed",
     "action_kind": "install", "action_label": "Retry"},
    {"ready": True, "guidance": ""},
])
@pytest.mark.parametrize("runtime", [{}, {"blocked": True, "detail": "Free installer port 6789"},
                                     {"starting": True}, {"state": "stopping"},
                                     {"running": True}, {"stuck": True}, {"orphaned": True}])
def test_iris_page_and_poll_share_setup_status(tmp_path, monkeypatch, setup, runtime):
    import json
    import re
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    row = {"device_session_id": "fork-test", "display_name": "Test Phone",
           "host_package": "com.mentra.mentra.openalma", "action_kind": "start",
           "action_label": "Repair", "startable": True, "repair_available": True,
           "automatic_host": True,
           "installed_version": "0.2.0"}
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "is_installed", lambda _spec: True)
    monkeypatch.setattr(app.services, "iris_repair_releases", lambda: {})
    monkeypatch.setattr(app.services, "status", lambda _spec: {
        "status_label": "Host ready", "installations": [row],
        "available_package": services.IRIS_PACKAGE, "available_version": "0.1.0",
        "setup": {"enabled": True, "ready": True, "rows": []},
        **runtime,
    })
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda *_args: setup)
    client = TestClient(app.app, base_url="http://127.0.0.1")
    for url in ("/iris", "/iris?device_session_id=fork-test&repair=1"):
        html = client.get(url).text
        initial = json.JSONDecoder().raw_decode(html.split("const initialStatus = ", 1)[1])[0]
        assert initial == client.get("/service/iris-server/status").json()
        retry = html.split('<form id="iris-preparation-retry"', 1)[1].split('</form>', 1)[0]
        show_retry = initial.get("ready") is False and not initial.get("install_running") and (
            initial.get("preparation_attempted") or initial.get("action_kind") == "install" and initial.get("action_label") == "Retry"
        )
        assert ('hidden' not in retry.split('>', 1)[0]) == show_retry
        assert 'action="/install/iris-server"' in retry
        assert '>Retry</button>' in retry and '>Install</button>' not in retry
        if initial.get("ready") is False and not initial.get("blocked"):
            assert initial["detail"] in html.split('id="iris-installer-status"', 1)[1].split('</p>', 1)[0]
        script = '<script src="/static/iris-services.js"></script>'
        assert html.index(script) < html.index("const initialStatus = ")
        if not runtime and setup["ready"] and url == "/iris":
            shared = client.get("/static/iris-services.js")
            assert shared.status_code == 200
            assert "function irisInstallDisabled(data, prepare = false)" in shared.text
        install = html.split('action="/iris/install"', 1)[1].split("</form>", 1)[0]
        disabled = bool(runtime) or bool(setup.get("install_running")) or (
            not setup["ready"] and (url != "/iris" or setup.get("action_kind") != "install")
        )
        assert bool(re.search(r'<button[^>]*disabled', install)) == disabled
        address = html.split('class="iris-address">', 1)[1].split("</form>", 1)[0]
        busy = any(runtime.get(key) for key in ("running", "starting", "stuck", "orphaned"))
        assert bool(re.search(r'<button[^>]*disabled', address)) == busy
        hint = html.split('id="iris-address-busy"', 1)[1].split(">", 1)[0]
        assert ("hidden" in hint) == (not busy)
        if runtime.get("blocked"):
            assert runtime["detail"] in html.split('id="iris-installer-status"', 1)[1].split("</p>", 1)[0]
        if "device_session_id" in url:
            assert '>Repair</button>' in install
            assert html.count('>Repair</button>') == 1
            assert '>Repair</a>' not in html
            repair_form = html.split('class="iris-repair"', 1)[1].split('</form>', 1)[0]
            assert repair_form.index('>Repair</button>') < repair_form.index('name="repair_source"')
            assert 'Repair from' not in html
            assert html.index('>Forget</button>') < html.index('class="iris-repair"')


@pytest.mark.parametrize("setup_ready", [False, True])
@pytest.mark.parametrize("ready, running, attempted, show_retry", [
    (False, False, True, True),
    (False, True, True, False),
    (False, False, False, False),
    (True, False, True, False),
])
def test_iris_preparation_retry_uses_admission_latch_after_operation_replaced(tmp_path, monkeypatch, ready, running, attempted, show_retry, setup_ready):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    status = {"ready": ready, "install_running": running, "preparation_attempted": attempted,
              "action_kind": "install", "action_label": "Continue Install", "installations": [],
              "available_package": services.IRIS_PACKAGE, "available_version": "0.1.12",
              "setup": {"enabled": True, "ready": setup_ready, "step": 'release', "rows": []}}
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app, "_setup_aware_status", lambda *_args, **_kwargs: status)
    html = TestClient(app.app, base_url="http://127.0.0.1").get("/iris").text
    retry = html.split('<form id="iris-preparation-retry"', 1)[1].split('</form>', 1)[0]
    assert ('hidden' not in retry.split('>', 1)[0]) == show_retry
    assert 'href="/install/iris-server/logs"' in retry
    assert '>Retry</button>' in retry and '>Install</button>' not in retry
    stock = html.split('id="iris-install-form"', 1)[1].split('</form>', 1)[0]
    assert ('disabled' in stock) == running


def test_iris_repair_success_follows_status_redirect():
    import subprocess
    script = r"""
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8');
let submitting=false, statusAvailable=true, actionError={}, destination='';
const location={assign:url=>destination=url,reload:()=>{throw new Error('Must leave the Repair chooser');}};
const fetch=async()=>({ok:true,redirected:true,url:'/iris?device_session_id=test-phone'});
eval(source.slice(source.indexOf('async function irisRequest'),source.indexOf('function irisAction')));
(async()=>{await irisRequest('/iris/install',{},null);assert.equal(destination,'/iris?device_session_id=test-phone');})();
"""
    path = Path(__file__).resolve().parents[1] / "launcher/templates/iris.html"
    subprocess.run(["node", "-e", script, str(path)], check=True, timeout=10)


def test_iris_status_consumer_node_checks():
    import subprocess
    path = Path(__file__).resolve().parents[1] / "launcher/static/iris-services.test.cjs"
    subprocess.run(["node", "--test", str(path)], check=True, timeout=10)


def test_uninstalled_iris_opens_phone_client_section_for_openalma_host(tmp_path, monkeypatch):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {
        "state": "stopped",
        "installed_package": None,
        "action_kind": "settings",
        "detail": "Not yet verified",
    })
    monkeypatch.setattr(app.setup_install, "optional_setup_status", lambda *_args: {"ready": True, "guidance": ""})
    monkeypatch.setattr(app.policy, "list_whatsapp_chats", lambda: [])
    monkeypatch.setattr(app.policy, "read_channel_settings", lambda: {})
    monkeypatch.setattr(app.services, "read_owner", lambda: "Fictional Owner")
    monkeypatch.setattr(app.services, "list_souls", lambda: ["Fictional Soul"])

    html = TestClient(app.app, base_url="http://127.0.0.1").get("/").text

    assert 'href="/iris">Setup</a>' in html
    assert 'data-service="iris-server"' in html


def test_phone_reported_iris_is_a_service(tmp_path, monkeypatch):
    spec = services.ServiceSpec("iris-server", "Iris", [], tmp_path, tmp_path / "log", tmp_path / "pid")
    monkeypatch.setattr(app.settings, "apps_root", lambda: tmp_path)
    monkeypatch.setattr(app.services, "all_services", lambda: [spec])
    monkeypatch.setattr(app.services, "status", lambda _spec: {
        "state": "ready", "installations": [{"device_session_id": "stock-test", "display_name": "Phone"}],
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
    client = TestClient(app.app, base_url="http://127.0.0.1")
    assert client.post("/open-url", data={"url": "https://example.org/guide"}).status_code == 200
    assert opened[-1] == "https://example.org/guide"
    for url in ("miniapp://release?url=http%3A%2F%2Fprivate.example", "javascript:alert(1)", "file:///private/secret", "https://[bad"):
        before = len(opened)
        assert client.post("/open-url", data={"url": url}).status_code == 400
        assert len(opened) == before
    before = len(opened)
    assert client.post("/open-url", data={"url": "https://example.org"}, headers={"Origin": "https://other.example"}).status_code == 403
    assert len(opened) == before


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
