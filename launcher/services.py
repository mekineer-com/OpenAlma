"""Lifecycle management for memU local-stack services.

The launcher tracks its own pidfile per service in ``~/.cache/memu-stack-launcher/``.
If a service was started externally (terminal, tmux, plugin), the launcher adopts
it on first sight via either the service's own pidfile or its listening port.
After adoption the service is "managed" and Stop works normally.

The apps-root path (parent of the four sibling repos) is resolved by
``settings.apps_root()`` — user override first, then auto-discovery
relative to the launcher's own directory, otherwise None.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from settings import apps_root as _resolve_apps_root

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = Path.home() / ".cache" / "memu-stack-launcher"


@dataclass
class ServiceSpec:
    name: str
    label: str
    cmd: list[str]
    cwd: Path
    log_path: Path
    pid_path: Path
    env: dict[str, str] = field(default_factory=dict)
    supports_terminal: bool = False
    port: int | None = None
    adopt_pid_path: Path | None = None
    adopt_pid_parser: Callable[[str], int | None] | None = None


def _parse_gateway_pid(text: str) -> int | None:
    try:
        data = json.loads(text)
    except (ValueError, json.JSONDecodeError):
        return None
    pid = data.get("pid") if isinstance(data, dict) else None
    return pid if isinstance(pid, int) and pid > 0 else None


def all_services() -> list[ServiceSpec]:
    root = _resolve_apps_root()
    if root is None:
        return []
    return [
        ServiceSpec(
            name="memu-server",
            label="mcp-memu-server",
            cmd=[str(root / "mcp-memu-server" / ".venv" / "bin" / "python3"), "run.py"],
            cwd=root / "mcp-memu-server",
            log_path=Path("/tmp/memu-server.out"),
            pid_path=STATE_DIR / "memu-server.pid",
            port=8099,
            adopt_pid_path=root / "memu" / ".memu-server.pid",
        ),
        ServiceSpec(
            name="hermes-gateway",
            label="hermes-agent gateway",
            cmd=[
                str(root / ".venv" / "bin" / "python3"),
                "-c",
                "from gateway.run import main; main()",
            ],
            cwd=root / "hermes-agent",
            log_path=Path("/tmp/hermes-gateway.log"),
            pid_path=STATE_DIR / "hermes-gateway.pid",
            env={"PYTHONPATH": ".", "GATEWAY_ALLOW_ALL_USERS": "true"},
            adopt_pid_path=HERMES_HOME / "gateway.pid",
            adopt_pid_parser=_parse_gateway_pid,
        ),
        ServiceSpec(
            name="whatsapp-bridge",
            label="WhatsApp bridge",
            cmd=[
                "node", "bridge.js",
                "--port", "3000",
                "--session", str(HERMES_HOME / "whatsapp" / "session"),
                "--mode", "self-chat",
            ],
            cwd=root / "hermes-agent" / "scripts" / "whatsapp-bridge",
            log_path=STATE_DIR / "whatsapp-bridge.log",
            pid_path=STATE_DIR / "whatsapp-bridge.pid",
            port=3000,
        ),
        ServiceSpec(
            name="sillytavern",
            label="SillyTavern",
            cmd=["bash", "start.sh"],
            cwd=root / "sillytavern" / "SillyTavern",
            log_path=STATE_DIR / "sillytavern.log",
            pid_path=STATE_DIR / "sillytavern.pid",
            supports_terminal=True,
            port=8000,
        ),
    ]


def _read_pid(pid_path: Path) -> int | None:
    try:
        return int(pid_path.read_text().strip())
    except (OSError, ValueError):
        return None


def _read_adopt_pid(spec: ServiceSpec) -> int | None:
    if spec.adopt_pid_path is None:
        return None
    try:
        text = spec.adopt_pid_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if spec.adopt_pid_parser is not None:
        return spec.adopt_pid_parser(text)
    try:
        return int(text.strip())
    except ValueError:
        return None


_PORT_PID_RE = re.compile(r"pid=(\d+)")


def _port_listener_pid(port: int) -> int | None:
    try:
        result = subprocess.run(
            ["ss", "-tlnpH", f"sport = :{port}"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _PORT_PID_RE.search(result.stdout)
    return int(m.group(1)) if m else None


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _adopt(spec: ServiceSpec) -> None:
    """If launcher has no pid and an external one is alive, copy it in."""
    if _read_pid(spec.pid_path) is not None:
        return
    candidate = _read_adopt_pid(spec)
    if candidate is None and spec.port is not None:
        candidate = _port_listener_pid(spec.port)
    if candidate is not None and _is_alive(candidate):
        spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
        spec.pid_path.write_text(str(candidate))


def is_running(spec: ServiceSpec) -> bool:
    _adopt(spec)
    pid = _read_pid(spec.pid_path)
    if pid is not None and _is_alive(pid):
        return True
    _clear_pid(spec)
    return False


def start(spec: ServiceSpec, *, show_terminal: bool = False) -> None:
    if is_running(spec):
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **spec.env}
    if show_terminal and spec.supports_terminal:
        full_cmd = ["x-terminal-emulator", "-e", *spec.cmd]
        proc = subprocess.Popen(
            full_cmd, cwd=str(spec.cwd), env=env, start_new_session=True
        )
    else:
        log = spec.log_path.open("ab")
        proc = subprocess.Popen(
            spec.cmd, cwd=str(spec.cwd), env=env,
            stdout=log, stderr=log, start_new_session=True,
        )
    spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
    spec.pid_path.write_text(str(proc.pid))


def stop(spec: ServiceSpec, *, timeout: float = 10.0) -> None:
    pid = _read_pid(spec.pid_path)
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _clear_pid(spec)
        return
    except PermissionError:
        return
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_alive(pid):
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    _clear_pid(spec)


def _clear_pid(spec: ServiceSpec) -> None:
    try:
        spec.pid_path.unlink()
    except FileNotFoundError:
        pass
