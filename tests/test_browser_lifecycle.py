import sys
from pathlib import Path
from types import SimpleNamespace

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
