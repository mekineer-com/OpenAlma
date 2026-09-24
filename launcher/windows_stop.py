"""Stop a verified local OpenAlma launcher before Windows install/upgrade."""
from __future__ import annotations

import argparse
import json
import socket
import time
import urllib.request

HOST = "127.0.0.1"
PORT = 8765
BASE_URL = f"http://{HOST}:{PORT}"


def _port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def stop(require_update_ready: bool = False) -> int:
    if not _port_open():
        return 0
    try:
        with urllib.request.urlopen(f"{BASE_URL}/launcher/identity", timeout=2) as response:
            identity = json.loads(response.read().decode("utf-8"))
        if identity != {"application": "openalma-launcher", "protocol": 1}:
            return 12
        if require_update_ready:
            with urllib.request.urlopen(f"{BASE_URL}/launcher/update-readiness", timeout=5) as response:
                readiness = json.loads(response.read().decode("utf-8"))
            if readiness.get("application") != "openalma-launcher":
                return 12
            if readiness.get("active_services"):
                return 11
        request = urllib.request.Request(f"{BASE_URL}/launcher/quit", data=b"", method="POST")
        with urllib.request.urlopen(request, timeout=2):
            pass
    except Exception:
        return 12
    deadline = time.time() + 10
    while _port_open():
        if time.time() >= deadline:
            return 13
        time.sleep(0.1)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-update-ready", action="store_true")
    args = parser.parse_args()
    raise SystemExit(stop(args.require_update_ready))


if __name__ == "__main__":
    main()
