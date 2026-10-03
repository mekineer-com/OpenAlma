"""Entry point for the OpenAlma launcher."""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import uvicorn
import psutil

import browser
import settings

try:
    import app as launcher_app
except (OSError, ValueError) as exc:
    if settings.os.name != "nt":
        import html
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", prefix="openalma-startup-", suffix=".html", encoding="utf-8", delete=False) as page:
            page.write(f"<!doctype html><title>OpenAlma</title><h1>OpenAlma could not start</h1><pre>{html.escape(str(exc))}</pre>")
        browser.open_app(Path(page.name).as_uri())
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
        with socket.socket() as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return True
            except OSError:
                time.sleep(0.1)
    return False


def _watch_browser_and_stop(
    chrome: subprocess.Popen | psutil.Process,
    server: uvicorn.Server,
) -> None:
    try:
        chrome.wait()
    finally:
        server.should_exit = True


def _browser_profile() -> Path:
    profile = settings.SETTINGS_PATH.parent / "chromium-profile"
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def _browser_target(url: str) -> tuple[int, str] | None:
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
        return port, target["id"]
    except (OSError, ValueError, json.JSONDecodeError, IndexError, StopIteration):
        return None


def _activate_existing_browser(url: str) -> bool:
    target = _browser_target(url)
    if target is None:
        return False
    port, target_id = target
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/json/activate/{urllib.parse.quote(target_id, safe='')}",
            data=b"",
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=1):
            return True
    except OSError:
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
    chrome = owner if owner is not None and _activate_existing_browser(url) else _open_chromium(url, chromium)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAlma launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    if _existing_launcher(args.host, args.port):
        _open_existing_launcher(url)
        return

    config = uvicorn.Config(
        launcher_app.app, host=args.host, port=args.port, log_level="info", access_log=False
    )
    server = uvicorn.Server(config)
    launcher_app.app.state.request_shutdown = lambda: setattr(server, "should_exit", True)

    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(args.host, args.port, url, server),
            daemon=True,
        ).start()

    server.run()


if __name__ == "__main__":
    main()
