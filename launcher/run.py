"""Entry point for the memU stack launcher."""
from __future__ import annotations

import argparse
import socket
import subprocess
import threading
import time

import uvicorn

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


def _watch_browser_and_stop(chrome: subprocess.Popen, server: uvicorn.Server) -> None:
    """Quit the launcher when the chromium app window closes.

    With --user-data-dir, the chromium process is the launcher's own;
    closing its only window causes the process to exit. The launcher
    follows it down so the Python process doesn't outlive the UI and
    silently hold the port for next launch.
    """
    chrome.wait()
    server.should_exit = True


def main() -> None:
    parser = argparse.ArgumentParser(description="memU stack launcher")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"

    config = uvicorn.Config("app:app", host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)

    if not args.no_browser:
        def _open() -> None:
            if not _wait_for_port(args.host, args.port):
                return
            chrome = browser.open_app(url)
            if chrome is not None:
                threading.Thread(
                    target=_watch_browser_and_stop,
                    args=(chrome, server),
                    daemon=True,
                ).start()

        threading.Thread(target=_open, daemon=True).start()

    server.run()


if __name__ == "__main__":
    main()
