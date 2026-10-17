import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import browser  # noqa: E402
import run  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(run.settings, "BROWSER_PROFILE_PATH", tmp_path / "old-config/chromium-profile")


def test_simultaneous_launches_reuse_the_winning_server(tmp_path):
    script = '''
import sys, types
from fastapi import FastAPI
import settings
from pathlib import Path
settings.SETTINGS_PATH = Path(sys.argv[2]) / "paths.json"
import run
app = FastAPI()
run.launcher_app = types.SimpleNamespace(app=app, LAUNCHER_ID="openalma-launcher")
@app.get("/launcher/identity")
def identity():
    return {"application": "openalma-launcher", "protocol": 1}
@app.post("/launcher/quit")
def quit():
    app.state.request_shutdown()
    return {"ok": True}
existing = run._existing_launcher
checked = False
def gate(host, port):
    global checked
    value = existing(host, port)
    if not checked:
        checked = True
        assert not value
        print("ready", flush=True)
        sys.stdin.readline()
    return value
run._existing_launcher = gate
sys.argv = ["run.py", "--port", sys.argv[1], "--no-browser"]
run.main()
'''
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    processes = []
    try:
        for _ in range(2):
            processes.append(subprocess.Popen([sys.executable, "-u", "-c", script, str(port), str(tmp_path)],
                cwd=Path(run.__file__).parent, env={**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            assert process.stdout.readline().strip() == "ready"
        for process in processes:
            process.stdin.write("\n")
            process.stdin.flush()
        deadline = time.monotonic() + 10
        while all(process.poll() is None for process in processes) and time.monotonic() < deadline:
            time.sleep(0.02)
        failures = [process.stderr.read() for process in processes if process.poll() not in (None, 0)]
        assert sum(process.poll() == 0 for process in processes) == 1, failures
        assert sum(process.poll() is None for process in processes) == 1
        with run.urllib.request.urlopen(f"http://127.0.0.1:{port}/launcher/identity") as response:
            assert json.load(response) == {"application": "openalma-launcher", "protocol": 1}
        request = run.urllib.request.Request(f"http://127.0.0.1:{port}/launcher/quit", data=b"", method="POST")
        run.urllib.request.urlopen(request, timeout=2).close()
        for process in processes:
            assert process.wait(timeout=5) == 0
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux application-menu entry")
def test_linux_shortcut_uses_real_paths_and_desktop_escaping(tmp_path, monkeypatch):
    root = tmp_path / 'fictional "user" $50%'
    root.mkdir()
    root.joinpath("openalma.desktop").write_bytes(Path(run.__file__).with_name("openalma.desktop").read_bytes())
    monkeypatch.setattr(run, "__file__", str(root / "run.py"))
    monkeypatch.setattr(run.sys, "executable", str(root / ".venv/bin/python"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    target = run._install_shortcut()
    entry = target.read_text()
    assert target == tmp_path / "data/applications/openalma.desktop"
    assert "@EXEC@" not in entry and "@ICON@" not in entry
    assert f"Icon={root / 'memu-icon.png'}\n" in entry
    assert "50%%" in entry and r'\\$' in entry and r'\\"' in entry
    validator = run.browser.shutil.which("desktop-file-validate")
    if validator:
        subprocess.run([validator, str(target)], check=True)


def test_chromium_profile_persists_after_browser_exit(tmp_path, monkeypatch):
    launched = {}
    chrome = SimpleNamespace(wait=lambda: launched.setdefault("waited", True))
    server = SimpleNamespace(should_exit=False)
    settings_path = tmp_path / "settings" / "paths.json"
    settings_path.parent.mkdir()
    settings_path.write_text(
        '{"window_position":{"x":321,"y":123},"window_size":{"width":552,"height":661}}\n',
        encoding="utf-8",
    )

    class FakeThread:
        def __init__(self, *, target, args, daemon):
            launched["thread"] = (target, args, daemon)

        def start(self):
            launched["started"] = True

    def open_app(*args, **kwargs):
        launched["args"] = args
        launched["kwargs"] = kwargs
        return chrome

    monkeypatch.setattr(run, "_wait_for_port", lambda *_args: True)
    monkeypatch.setattr(run.browser, "find_chromium", lambda: "chromium")
    monkeypatch.setattr(run.browser, "profile_process", lambda _profile: None)
    monkeypatch.setattr(run.settings, "SETTINGS_PATH", settings_path)
    monkeypatch.setattr(run.browser, "open_app", open_app)
    monkeypatch.setattr(run.threading, "Thread", FakeThread)

    run._open_browser_when_ready("127.0.0.1", 8765, "http://127.0.0.1:8765", server)

    profile = run.settings.BROWSER_PROFILE_PATH
    assert profile.parent != settings_path.parent
    assert launched["args"] == ("http://127.0.0.1:8765/?openalma_app=1", "chromium", profile)
    assert launched["kwargs"] == {"width": 552, "height": 661, "position": (321, 123)}
    assert profile.is_dir()
    target, args, daemon = launched["thread"]
    assert daemon is True
    target(*args)
    assert launched["waited"] is True
    assert profile.is_dir()
    assert server.should_exit is True


@pytest.mark.parametrize("activated, alive", [(True, True), (False, True), (False, False)])
def test_restarted_launcher_watches_existing_profile_owner(tmp_path, monkeypatch, activated, alive):
    events = []
    server = SimpleNamespace(should_exit=False)
    owner = SimpleNamespace(wait=lambda: events.append("owner exited"), is_running=lambda: alive)
    monkeypatch.setattr(run, "_browser_profile", lambda: tmp_path / "profile")
    monkeypatch.setattr(run, "_wait_for_port", lambda *_args: True)
    monkeypatch.setattr(run.browser, "find_chromium", lambda: "chromium")
    monkeypatch.setattr(run.browser, "profile_process", lambda _profile: owner if not any(event.endswith("exited") for event in events) else None)
    def activate(_url, *, reload=False):
        assert reload is True
        return activated
    monkeypatch.setattr(run, "_activate_existing_browser", activate)
    def open_chromium(*_args):
        assert not activated
        events.append("forwarded")
        return SimpleNamespace(wait=lambda: pytest.fail("must not watch the forwarding child") if alive else events.append("new browser exited"))
    monkeypatch.setattr(run, "_open_chromium", open_chromium)

    class Thread:
        def __init__(self, *, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            assert not server.should_exit
            self.target(*self.args)

    monkeypatch.setattr(run.threading, "Thread", Thread)
    run._open_browser_when_ready("127.0.0.1", 8765, "http://127.0.0.1:8765", server)
    assert events == (["owner exited"] if activated else ["forwarded", "owner exited" if alive else "new browser exited"])
    assert server.should_exit


def test_profile_lookup_excludes_other_profiles_and_renderer_processes(tmp_path, monkeypatch):
    args = [f"--user-data-dir={tmp_path}"]
    owner = SimpleNamespace(info={"cmdline": args})
    processes = [
        SimpleNamespace(info={"cmdline": None}),
        SimpleNamespace(info={"cmdline": args + ["--type=renderer"]}),
        SimpleNamespace(info={"cmdline": ["--user-data-dir=/another/profile"]}),
        owner,
    ]
    monkeypatch.setattr(browser.psutil, "process_iter", lambda _attrs: processes)
    assert browser.profile_process(tmp_path) is owner


def test_browser_watcher_follows_replacement_before_stopping(tmp_path, monkeypatch):
    server = SimpleNamespace(should_exit=False)
    events = []

    def wait_for_owner():
        assert not server.should_exit
        events.append("window closed")

    bootstrap = SimpleNamespace(wait=lambda: events.append("bootstrap exited"))
    owner = SimpleNamespace(wait=wait_for_owner)
    owners = iter([owner, None])
    monkeypatch.setattr(run, "_browser_profile", lambda: tmp_path)
    monkeypatch.setattr(run.browser, "profile_process", lambda _profile: next(owners))

    run._watch_browser_and_stop(bootstrap, server)

    assert events == ["bootstrap exited", "window closed"]
    assert server.should_exit


@pytest.mark.parametrize("failure", ["wait", "lookup"])
def test_browser_observation_failure_does_not_stop_server(tmp_path, monkeypatch, failure):
    server = SimpleNamespace(should_exit=False)

    def unavailable():
        raise OSError("Fictional observation failure")

    chrome = SimpleNamespace(wait=unavailable if failure == "wait" else lambda: None)
    monkeypatch.setattr(run, "_browser_profile", lambda: tmp_path)
    monkeypatch.setattr(run.browser, "profile_process", lambda _profile: unavailable())

    with pytest.raises(OSError, match="observation failure"):
        run._watch_browser_and_stop(chrome, server)
    assert not server.should_exit


def test_browser_launch_includes_isolated_profile(tmp_path, monkeypatch):
    launched = {}
    monkeypatch.setattr(browser.subprocess, "Popen", lambda args, **kwargs: launched.update(args=args, kwargs=kwargs) or object())

    browser.open_app("http://127.0.0.1:8765", "chromium", tmp_path, position=(321, 123))

    assert f"--user-data-dir={tmp_path}" in launched["args"]
    assert "--remote-debugging-address=127.0.0.1" in launched["args"]
    assert "--remote-debugging-port=0" in launched["args"]
    assert "--disable-background-mode" in launched["args"]
    assert "--window-size=600,740" in launched["args"]
    assert "--window-position=321,123" in launched["args"]
    assert not any(arg.startswith("--force-device-scale-factor=") for arg in launched["args"])
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
    monkeypatch.setattr(run.settings, "read_paths", lambda: {})
    monkeypatch.setattr(
        run,
        "_watch_browser_and_stop",
        lambda *_args: pytest.fail("repeated launch must not install a server shutdown watcher"),
    )
    monkeypatch.setattr(
        run.browser,
        "open_app",
        lambda *args, **kwargs: launched.update(args=args, kwargs=kwargs) or chrome,
    )

    run._open_existing_launcher("http://127.0.0.1:8765")

    assert launched["args"] == (
        "http://127.0.0.1:8765/?openalma_app=1",
        "chromium",
        run.settings.BROWSER_PROFILE_PATH,
    )
    assert launched["kwargs"] == {"position": None}
    assert launched["waited"] is True


@pytest.mark.parametrize("restarted", [False, True])
@pytest.mark.parametrize("page_path", ["/settings", "/launcher/quit"])
def test_existing_launcher_activates_open_window_without_launching(tmp_path, monkeypatch, restarted, page_path):
    profile = tmp_path / "chromium-profile"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text("41234\n/devtools/browser/id\n", encoding="utf-8")
    requests = []
    messages = []
    owner = SimpleNamespace(wait=lambda: messages.append("owner exited"), is_running=lambda: True)
    server = SimpleNamespace(should_exit=False)

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def send(self, message):
            messages.append(json.loads(message))

        def recv(self, *, timeout):
            assert timeout == 1
            return '{"id":1,"result":{}}'

    def connect(url, **kwargs):
        assert restarted, "activating a running launcher must preserve unsaved forms"
        assert url == "ws://127.0.0.1:41234/devtools/page/target%2Fid"
        assert kwargs == {"open_timeout": 1, "close_timeout": 1}
        return Client()

    class Thread:
        def __init__(self, *, target, args, daemon):
            assert args == (owner, server)
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    class Response:
        def __init__(self, body=b""):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return self.body

    def urlopen(request, **_kwargs):
        requests.append(request)
        url = request.full_url if isinstance(request, run.urllib.request.Request) else request
        if url.endswith("/json/list"):
            return Response(json.dumps([{
                "id": "target/id",
                "type": "page",
                "url": "http://127.0.0.1:8765" + page_path,
            }]).encode())
        return Response()

    monkeypatch.setattr(run.browser, "find_chromium", lambda: "chromium")
    monkeypatch.setattr(run, "_browser_profile", lambda: profile)
    monkeypatch.setattr(run.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(run, "connect", connect)
    monkeypatch.setattr(run, "_wait_for_port", lambda *_args: True)
    monkeypatch.setattr(run.browser, "profile_process", lambda _profile: owner if "owner exited" not in messages else None)
    monkeypatch.setattr(run.threading, "Thread", Thread)
    monkeypatch.setattr(
        run,
        "_open_chromium",
        lambda *_args: pytest.fail("an activated launcher must not open another window"),
    )

    if restarted:
        run._open_browser_when_ready("127.0.0.1", 8765, "http://127.0.0.1:8765", server)
    else:
        run._open_existing_launcher("http://127.0.0.1:8765")

    activation = requests[-1]
    assert activation.full_url == "http://127.0.0.1:41234/json/activate/target%2Fid"
    assert activation.method == "PUT"
    command = {"id": 1, "method": "Page.reload"} if page_path == "/settings" else {
        "id": 1, "method": "Page.navigate", "params": {"url": "http://127.0.0.1:8765/?openalma_app=1"},
    }
    assert messages == ([command, "owner exited"] if restarted else [])
    assert server.should_exit is restarted


@pytest.mark.parametrize("reply", [
    '{"id":1,"error":{"message":"Reload failed"}}', 'invalid JSON', '[]',
    TimeoutError("Reload timed out"), run.WebSocketException("Disconnected"),
])
def test_browser_reload_reports_failure(monkeypatch, reply):
    monkeypatch.setattr(run, "_browser_target", lambda _url: (41234, "target", "http://127.0.0.1:8765/settings"))

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def send(self, message):
            assert json.loads(message) == {"id": 1, "method": "Page.reload"}

        def recv(self, *, timeout):
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(run.urllib.request, "urlopen", lambda *_args, **_kwargs: Client())
    monkeypatch.setattr(run, "connect", lambda *_args, **_kwargs: Client())

    assert run._activate_existing_browser("http://127.0.0.1:8765", reload=True) is False


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
