"""Entry point for the OpenAlma launcher."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request

import uvicorn

import app as launcher_app
import browser


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
        raise RuntimeError("Stop these OpenAlma services before updating: " + ", ".join(active))
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
    chrome: subprocess.Popen,
    server: uvicorn.Server,
    profile: tempfile.TemporaryDirectory,
) -> None:
    """Quit the launcher when the chromium app window closes.

    With --user-data-dir, the chromium process is the launcher's own;
    closing its only window causes the process to exit. The launcher
    follows it down so the Python process doesn't outlive the UI and
    silently hold the port for next launch.
    """
    try:
        chrome.wait()
    finally:
        profile.cleanup()
        server.should_exit = True


def _open_browser_when_ready(host: str, port: int, url: str, server: uvicorn.Server) -> None:
    if not _wait_for_port(host, port):
        return
    chromium = None if os.name == "nt" else browser.find_chromium()
    if chromium is None:
        browser.open_app(url)
        return
    profile = tempfile.TemporaryDirectory(prefix="openalma-browser-")
    try:
        chrome = browser.open_app(url, chromium, profile.name)
    except Exception:
        profile.cleanup()
        raise
    if chrome is not None:
        threading.Thread(
            target=_watch_browser_and_stop,
            args=(chrome, server, profile),
            daemon=True,
        ).start()


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAlma launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    if _existing_launcher(args.host, args.port):
        browser.open_app(url)
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
