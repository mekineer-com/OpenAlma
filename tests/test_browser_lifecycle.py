import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import browser  # noqa: E402
import run  # noqa: E402


def test_chromium_profile_lives_until_browser_exit(tmp_path, monkeypatch):
    launched = {}
    profile = SimpleNamespace(name=str(tmp_path / "profile"), cleaned=False)
    profile.cleanup = lambda: setattr(profile, "cleaned", True)
    chrome = SimpleNamespace(wait=lambda: launched.setdefault("waited", True))
    server = SimpleNamespace(should_exit=False)

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
    monkeypatch.setattr(run.tempfile, "TemporaryDirectory", lambda **_kwargs: profile)
    monkeypatch.setattr(run.browser, "open_app", open_app)
    monkeypatch.setattr(run.threading, "Thread", FakeThread)

    run._open_browser_when_ready("127.0.0.1", 8765, "http://127.0.0.1:8765", server)

    assert launched["args"] == ("http://127.0.0.1:8765", "chromium", profile.name)
    assert profile.cleaned is False
    target, args, daemon = launched["thread"]
    assert daemon is True
    target(*args)
    assert launched["waited"] is True
    assert profile.cleaned is True
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


def test_existing_launcher_still_uses_chromium_app_mode(tmp_path, monkeypatch):
    launched = {}
    chrome = SimpleNamespace(wait=lambda: launched.setdefault("waited", True))

    class FakeTemporaryDirectory:
        def __enter__(self):
            return str(tmp_path / "profile")

        def __exit__(self, *_args):
            pass

    monkeypatch.setattr(run.browser, "find_chromium", lambda: "chromium")
    monkeypatch.setattr(
        run.browser,
        "open_app",
        lambda *args: launched.setdefault("args", args) and chrome,
    )
    monkeypatch.setattr(
        run.tempfile,
        "TemporaryDirectory",
        lambda **_kwargs: FakeTemporaryDirectory(),
    )

    run._open_existing_launcher("http://127.0.0.1:8765")

    assert launched["args"] == (
        "http://127.0.0.1:8765",
        "chromium",
        str(tmp_path / "profile"),
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
