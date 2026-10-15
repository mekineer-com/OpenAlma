"""Entry point for the OpenAlma launcher."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path


def _show_startup_error(exc: BaseException) -> None:
    if sys.platform != "linux" or "--no-browser" in sys.argv:
        return
    import html
    import tempfile
    import webbrowser

    with tempfile.NamedTemporaryFile(mode="w", prefix="openalma-startup-", suffix=".html", encoding="utf-8", delete=False) as page:
        page.write(f"<!doctype html><title>OpenAlma</title><h1>OpenAlma could not start</h1><pre>{html.escape(str(exc))}</pre><p>Run python3.12 run.py in a terminal for details.</p>")
    webbrowser.open(Path(page.name).as_uri())


def _bootstrap() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("OpenAlma requires Python 3.12; run this file with python3.12")
    environment = Path(__file__).resolve().parent / ".venv"
    python = environment / "bin" / "python"
    ready = environment / ".openalma-ready"
    requirements = environment.parent / "requirements.txt"
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not ready.exists() or ready.read_text() != fingerprint:
        import venv

        print("Preparing OpenAlma's Python environment...", flush=True)
        if not python.exists():
            venv.EnvBuilder(with_pip=True).create(environment)
        subprocess.run([str(python), "-m", "ensurepip", "--upgrade"], check=True)
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements)],
            check=True,
        )
        ready.write_text(fingerprint)
    if Path(sys.prefix) != environment:
        os.execv(str(python), [str(python), str(Path(__file__).resolve()), *sys.argv[1:]])


if __name__ == "__main__" and sys.platform == "linux":
    try:
        _bootstrap()
    except (Exception, SystemExit) as exc:
        _show_startup_error(exc)
        raise

try:
    import uvicorn
    import psutil
    from websockets.exceptions import WebSocketException
    from websockets.sync.client import connect

    import browser
    import settings
    import app as launcher_app
except Exception as exc:
    _show_startup_error(exc)
    raise


class ActiveServicesError(RuntimeError):
    pass


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _existing_launcher(host: str, port: int) -> bool:
    if not _port_open(host, port):
        return False
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/launcher/identity", timeout=2) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Port {port} is in use by another program") from exc
    if value != {"application": launcher_app.LAUNCHER_ID, "protocol": 1}:
        raise RuntimeError(f"Port {port} is in use by another program")
    return True


def stop_existing(host: str = "127.0.0.1", port: int = 8765, timeout: float = 10.0) -> None:
    if not _existing_launcher(host, port):
        return
    request = urllib.request.Request(f"http://{host}:{port}/launcher/quit", data=b"", method="POST")
    with urllib.request.urlopen(request, timeout=2):
        pass
    deadline = time.time() + timeout
    while _port_open(host, port):
        if time.time() >= deadline:
            raise RuntimeError("OpenAlma did not exit; close it and retry the installer")
        time.sleep(0.1)


def prepare_update(host: str = "127.0.0.1", port: int = 8765) -> None:
    running = _existing_launcher(host, port)
    if running:
        with urllib.request.urlopen(f"http://{host}:{port}/launcher/update-readiness", timeout=5) as response:
            value = json.loads(response.read().decode("utf-8"))
    else:
        value = launcher_app.launcher_update_readiness()
    if value.get("application") != launcher_app.LAUNCHER_ID:
        raise RuntimeError("The running process is not OpenAlma Launcher")
    active = value.get("active_services")
    if active:
        raise ActiveServicesError("Stop these OpenAlma services before updating: " + ", ".join(active))
    if running:
        stop_existing(host, port)


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.1)
    return False


def _watch_browser_and_stop(
    chrome: subprocess.Popen | psutil.Process,
    server: uvicorn.Server,
) -> None:
    while chrome is not None:
        chrome.wait()
        # Edge may replace its bootstrap process while the app window stays open.
        chrome = browser.profile_process(_browser_profile())
    server.should_exit = True


def _browser_profile() -> Path:
    profile = settings.SETTINGS_PATH.parent / "chromium-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def _browser_target(url: str) -> tuple[int, str, str] | None:
    try:
        port = int((_browser_profile() / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()[0])
        if not 0 < port < 65_536:
            return None
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
            targets = json.loads(response.read().decode("utf-8"))
        origin = urllib.parse.urlsplit(url)
        target = next(
            row for row in targets
            if isinstance(row, dict)
            and row.get("type") == "page"
            and urllib.parse.urlsplit(str(row.get("url") or ""))[:2] == origin[:2]
            and isinstance(row.get("id"), str)
        )
        return port, target["id"], target["url"]
    except (OSError, ValueError, json.JSONDecodeError, IndexError, StopIteration):
        return None


def _activate_existing_browser(url: str, *, reload: bool = False) -> bool:
    target = _browser_target(url)
    if target is None:
        return False
    port, target_id, page_url = target
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/activate/{urllib.parse.quote(target_id, safe='')}",
            data=b"",
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=1):
            pass
        if reload:
            with connect(
                f"ws://127.0.0.1:{port}/devtools/page/{urllib.parse.quote(target_id, safe='')}",
                open_timeout=1, close_timeout=1,
            ) as client:
                # Do not reload the form's POST response and submit Quit again.
                command = {"id": 1, "method": "Page.reload"}
                if urllib.parse.urlsplit(page_url).path == "/launcher/quit":
                    command = {"id": 1, "method": "Page.navigate", "params": {"url": f"{url.rstrip('/')}/?openalma_app=1"}}
                client.send(json.dumps(command))
                reply = json.loads(client.recv(timeout=1))
                return isinstance(reply, dict) and reply.get("id") == 1 and "result" in reply and "error" not in reply
        return True
    except (OSError, ValueError, WebSocketException):
        return False


def _window_position() -> tuple[int, int] | None:
    position = settings.read_paths().get("window_position")
    if not isinstance(position, dict):
        return None
    try:
        return int(position["x"]), int(position["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _window_size() -> tuple[int, int] | None:
    size = settings.read_paths().get("window_size")
    if not isinstance(size, dict):
        return None
    try:
        return int(size["width"]), int(size["height"])
    except (KeyError, TypeError, ValueError):
        return None


def _open_chromium(url: str, chromium: str) -> subprocess.Popen | None:
    size = _window_size()
    return browser.open_app(
        f"{url.rstrip('/')}/?openalma_app=1",
        chromium,
        _browser_profile(),
        **({"width": size[0], "height": size[1]} if size else {}),
        position=_window_position(),
    )


def _open_browser_when_ready(host: str, port: int, url: str, server: uvicorn.Server) -> None:
    if not _wait_for_port(host, port):
        return
    chromium = browser.find_chromium()
    if chromium is None:
        browser.open_app(url)
        return
    owner = browser.profile_process(_browser_profile())
    chrome = owner if owner is not None and _activate_existing_browser(url, reload=True) else _open_chromium(url, chromium)
    chrome = owner if owner is not None and owner.is_running() else chrome
    if chrome is not None:
        threading.Thread(
            target=_watch_browser_and_stop,
            args=(chrome, server),
            daemon=True,
        ).start()


def _open_existing_launcher(url: str) -> None:
    chromium = browser.find_chromium()
    if chromium is None:
        browser.open_app(url)
        return
    if _activate_existing_browser(url):
        return
    chrome = _open_chromium(url, chromium)
    if chrome is not None:
        chrome.wait()


def _install_shortcut() -> Path:
    def quote(value: Path) -> str:
        # Desktop entries unescape strings before parsing Exec; this is not shell quoting.
        text = str(value).replace("%", "%%")
        for char in ('\\', '"', '`', '$'):
            text = text.replace(char, "\\" + char)
        return '"' + text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t") + '"'

    root = Path(__file__).resolve().parent
    entry = root.joinpath("openalma.desktop").read_text(encoding="utf-8")
    entry = entry.replace("@EXEC@", f"{quote(Path(sys.executable))} {quote(root / 'run.py')}")
    icon = str(root / "memu-icon.png").replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    entry = entry.replace("@ICON@", icon)
    target = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications/openalma.desktop"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(entry, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAlma launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--install-shortcut", action="store_true", help="Install the Linux application-menu shortcut")
    args = parser.parse_args()

    if args.install_shortcut:
        if sys.platform != "linux":
            parser.error("--install-shortcut is for Linux; Windows uses its installer shortcut")
        print(_install_shortcut())
        return

    url = f"http://{args.host}:{args.port}"

    if _existing_launcher(args.host, args.port):
        if not args.no_browser:
            _open_existing_launcher(url)
        return

    launcher_app.app.state.launcher_host = args.host
    config = uvicorn.Config(
        launcher_app.app, host=args.host, port=args.port, log_level="info", access_log=False
    )
    server = uvicorn.Server(config)
    launcher_app.app.state.request_shutdown = lambda: setattr(server, "should_exit", True)

    family = socket.AF_INET6 if ":" in args.host else socket.AF_INET
    with socket.socket(family) as listener:
        # Windows reuse permits competing listeners; reserve this launcher's port.
        option = socket.SO_EXCLUSIVEADDRUSE if os.name == "nt" else socket.SO_REUSEADDR
        listener.setsockopt(socket.SOL_SOCKET, option, 1)
        try:
            listener.bind((args.host, args.port))
            listener.listen(config.backlog)
        except OSError:
            if not _wait_for_port(args.host, args.port) or not _existing_launcher(args.host, args.port):
                raise
            if not args.no_browser:
                _open_existing_launcher(url)
            return
        if not args.no_browser:
            threading.Thread(
                target=_open_browser_when_ready,
                args=(args.host, args.port, url, server),
                daemon=True,
            ).start()
        server.run(sockets=[listener])


if __name__ == "__main__":
    try:
        main()
    except (Exception, SystemExit) as exc:
        if not isinstance(exc, SystemExit) or exc.code not in (None, 0):
            _show_startup_error(exc)
        raise
