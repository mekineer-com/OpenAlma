import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import browser  # noqa: E402
import run  # noqa: E402


def test_chromium_profile_persists_after_browser_exit(tmp_path, monkeypatch):
    launched = {}
    chrome = SimpleNamespace(wait=lambda: launched.setdefault("waited", True))
    server = SimpleNamespace(should_exit=False)
    settings_path = tmp_path / "settings" / "paths.json"

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            launched["thread"] = (target, args, daemon)

        def start(self):
            launched["started"] = True

    def open_app(*args):
        launched["args"] = args
        return chrome

    monkeypatch.setattr(run, "_wait_for_port", lambda *_args: True)
    monkeypatch.setattr(run.browser, "find_chromium", lambda: "chromium")
    monkeypatch.setattr(run.settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(run.browser, "open_app", open_app)
    monkeypatch.setattr(run.threading, "Thread", FakeThread)

    run._open_browser_when_ready("127.0.0.1", 8765, "http://127.0.0.1:8765", server)

    profile = settings_path.parent / "chromium-profile"
    assert launched["args"] == ("http://127.0.0.1:8765", "chromium", profile)
    assert profile.is_dir()
    target, args, daemon = launched["thread"]
    assert daemon is True
    target(*args)
    assert launched["waited"] is True
    assert profile.is_dir()
    assert server.should_exit is True


def test_browser_launch_includes_isolated_profile(tmp_path, monkeypatch):
    launched = {}
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kwargs: launched.update(args=args, kwargs=kwargs) or object())

    browser.open_app("http://127.0.0.1:8765", "chromium", tmp_path)

    assert f"--user-data-dir={tmp_path}" in launched["args"]
    assert launched["kwargs"]["start_new_session"] is True


def test_find_chromium_uses_standard_windows_install_path(tmp_path, monkeypatch):
    chrome = tmp_path / "Google/Chrome/Application/chrome.exe"
    chrome.parent.mkdir(parents=True)
    chrome.touch()

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("PROGRAMFILES", raising=False)
    monkeypatch.delenv("PROGRAMFILES(X86)", raising=False)

    assert browser._find_windows_chromium() == str(chrome)


def test_default_browser_is_fallback_when_chromium_is_unavailable(monkeypatch):
    opened = []
    monkeypatch.setattr(run, "_wait_for_port", lambda *_args: True)
    monkeypatch.setattr(run.browser, "find_chromium", lambda: None)
    monkeypatch.setattr(run.browser, "open_app", lambda url: opened.append(url))

    run._open_browser_when_ready("127.0.0.1", 8765, "http://127.0.0.1:8765", object())

    assert opened == ["http://127.0.0.1:8765"]


def test_existing_launcher_reuses_profile_without_stopping_server(tmp_path, monkeypatch):
    launched = {}
    chrome = SimpleNamespace(wait=lambda: launched.setdefault("waited", True))
    settings_path = tmp_path / "settings" / "paths.json"

    monkeypatch.setattr(run.browser, "find_chromium", lambda: "chromium")
    monkeypatch.setattr(run.settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(
        run,
        "_watch_browser_and_stop",
        lambda *_args: pytest.fail("repeated launch must not install a server shutdown watcher"),
    )
    monkeypatch.setattr(
        run.browser,
        "open_app",
        lambda *args: launched.setdefault("args", args) and chrome,
    )

    run._open_existing_launcher("http://127.0.0.1:8765")

    assert launched["args"] == (
        "http://127.0.0.1:8765",
        "chromium",
        settings_path.parent / "chromium-profile",
    )
    assert launched["waited"] is True


def test_cold_start_waits_up_to_thirty_seconds():
    assert run._wait_for_port.__defaults__ == (30.0,)


def test_windows_wrapper_reports_uvicorn_system_exit():
    wrapper = (Path(__file__).resolve().parents[1] / "launcher/windows_start.pyw").read_text(encoding="utf-8")

    assert "except (Exception, SystemExit)" in wrapper
    assert "OpenAlma could not start" in wrapper
    assert '{"--prepare-update", "--stop-existing"}.intersection(sys.argv)' in wrapper
    assert "raise SystemExit(11)" in wrapper


def test_existing_launcher_requires_exact_identity(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return json.dumps({"application": "openalma-launcher", "protocol": 1}).encode()

    monkeypatch.setattr(run, "_port_open", lambda *_args: True)
    monkeypatch.setattr(run.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    assert run._existing_launcher("127.0.0.1", 8765) is True

    Response.read = lambda _self: b'{"application":"other"}'
    with pytest.raises(RuntimeError, match="another program"):
        run._existing_launcher("127.0.0.1", 8765)


def test_installer_stop_waits_for_launcher_port_release(monkeypatch):
    states = iter((True, True, False))
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(run, "_existing_launcher", lambda *_args: True)
    monkeypatch.setattr(run, "_port_open", lambda *_args: next(states))
    monkeypatch.setattr(run.urllib.request, "urlopen", lambda request, **_kwargs: requests.append(request) or Response())
    monkeypatch.setattr(run.time, "sleep", lambda _seconds: None)

    run.stop_existing(timeout=1)

    assert requests[0].full_url.endswith("/launcher/quit")


def test_update_preparation_refuses_active_services(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"application":"openalma-launcher","active_services":["memU Server"]}'

    monkeypatch.setattr(run, "_existing_launcher", lambda *_args: True)
    monkeypatch.setattr(run.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(run, "stop_existing", lambda *_args: pytest.fail("active services must block update"))

    with pytest.raises(RuntimeError, match="memU Server"):
        run.prepare_update()


def test_update_preparation_reuses_local_readiness_when_launcher_is_closed(monkeypatch):
    monkeypatch.setattr(run, "_existing_launcher", lambda *_args: False)
    monkeypatch.setattr(
        run.launcher_app, "launcher_update_readiness",
        lambda: {"application": run.launcher_app.LAUNCHER_ID, "active_services": ["Hermes Channels"]},
    )
    monkeypatch.setattr(run, "stop_existing", lambda *_args: pytest.fail("closed launcher needs no stop"))

    with pytest.raises(RuntimeError, match="Hermes Channels"):
        run.prepare_update()
