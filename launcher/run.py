"""Entry point for the OpenAlma launcher."""
from __future__ import annotations

import argparse
import socket
import subprocess
import tempfile
import threading
import time

import uvicorn

import app as launcher_app
import browser


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
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
    chromium = browser.find_chromium()
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
