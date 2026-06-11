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
import shlex
import shutil
import signal
import subprocess
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from settings import apps_root as _resolve_apps_root

HERMES_HOME = Path.home() / ".hermes"
STATE_DIR = Path.home() / ".cache" / "memu-stack-launcher"
STARTUP_GRACE_SECONDS = 4.0
MEMU_SERVER_PORT = 8099


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
            port=MEMU_SERVER_PORT,
            adopt_pid_path=root / "mcp-memu-server" / ".memu-server.pid",
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
            env={
                "PYTHONPATH": ".",
                "GATEWAY_ALLOW_ALL_USERS": "true",
                "WHATSAPP_MODE": "bot",
                "WHATSAPP_ALLOWED_USERS": "*",
            },
            adopt_pid_path=HERMES_HOME / "gateway.pid",
            adopt_pid_parser=_parse_gateway_pid,
        ),
        ServiceSpec(
            name="sillytavern",
            label="SillyTavern",
            cmd=["bash", "start.sh"],
            cwd=root / "sillytavern" / "SillyTavern",
            log_path=STATE_DIR / "sillytavern.log",
            pid_path=STATE_DIR / "sillytavern.pid",
            supports_terminal=True,
            port=8001,
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


def _proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    if not raw:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()


def _proc_cwd(pid: int) -> Path | None:
    try:
        return Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return None


def _is_zombie(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    parts = stat.split()
    return len(parts) > 2 and parts[2] == "Z"


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    if _is_zombie(pid):
        return False
    return True


def _matches_service_process(spec: ServiceSpec, pid: int) -> bool:
    cmd = _proc_cmdline(pid).lower()
    cwd = _proc_cwd(pid)
    cwd_matches = cwd is not None and cwd == spec.cwd
    if spec.name == "memu-server":
        return cwd_matches and ("run.py" in cmd or ("uvicorn" in cmd and "app.main:app" in cmd))
    if spec.name == "hermes-gateway":
        if not cwd_matches:
            return False
        return "gateway.run" in cmd or "hermes gateway run" in cmd
    if spec.name == "sillytavern":
        return "server.js" in cmd or "start.sh" in cmd
    return False


def _within_startup_grace(spec: ServiceSpec) -> bool:
    try:
        age = time.time() - spec.pid_path.stat().st_mtime
    except OSError:
        return False
    return age <= STARTUP_GRACE_SECONDS


def _terminal_command(cmd: list[str]) -> list[str] | None:
    # Alpine LXQt default first; then common Linux terminal wrappers.
    candidates: list[tuple[str, list[str]]] = [
        ("qterminal", ["qterminal", "-e", *cmd]),
        ("x-terminal-emulator", ["x-terminal-emulator", "-e", *cmd]),
        ("lxterminal", ["lxterminal", "-e", shlex.join(cmd)]),
        ("xfce4-terminal", ["xfce4-terminal", "--command", shlex.join(cmd)]),
        ("konsole", ["konsole", "-e", *cmd]),
        ("gnome-terminal", ["gnome-terminal", "--", *cmd]),
        ("xterm", ["xterm", "-e", *cmd]),
    ]
    for binary, terminal_cmd in candidates:
        if shutil.which(binary):
            return terminal_cmd
    return None


def _hermes_python(root: Path) -> Path:
    for candidate in (
        root / ".venv" / "bin" / "python3",
        root / "hermes-agent" / ".venv" / "bin" / "python3",
        root / "hermes-agent" / "venv" / "bin" / "python3",
    ):
        if candidate.exists():
            return candidate
    return Path(shutil.which("python3") or "python3")


def launch_whatsapp_bridge_pairing() -> bool:
    root = _resolve_apps_root()
    if root is None:
        return False
    hermes_script = root / "hermes-agent" / "hermes"
    if not hermes_script.exists():
        return False
    cmd = [str(_hermes_python(root)), str(hermes_script), "whatsapp"]
    terminal_cmd = _terminal_command(cmd)
    if terminal_cmd is None:
        return False
    env = {
        **os.environ,
        "WHATSAPP_MODE": "bot",
        "WHATSAPP_ALLOWED_USERS": os.environ.get("WHATSAPP_ALLOWED_USERS", "*"),
    }
    subprocess.Popen(
        terminal_cmd,
        cwd=str(root / "hermes-agent"),
        env=env,
        start_new_session=True,
    )
    return True


def _spawn_background(spec: ServiceSpec, env: dict[str, str]) -> subprocess.Popen[bytes]:
    log = spec.log_path.open("ab")
    try:
        return subprocess.Popen(
            spec.cmd, cwd=str(spec.cwd), env=env,
            stdout=log, stderr=log, start_new_session=True,
        )
    finally:
        log.close()


def _adopt(spec: ServiceSpec) -> None:
    """If launcher has no pid and an external one is alive, copy it in."""
    if _read_pid(spec.pid_path) is not None:
        return
    candidate = _read_adopt_pid(spec)
    if (
        candidate is not None
        and _is_alive(candidate)
        and _matches_service_process(spec, candidate)
    ):
        spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
        spec.pid_path.write_text(str(candidate))
        return
    if spec.port is not None:
        candidate = _port_listener_pid(spec.port)
    if (
        candidate is not None
        and _is_alive(candidate)
        and _matches_service_process(spec, candidate)
    ):
        spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
        spec.pid_path.write_text(str(candidate))


def is_running(spec: ServiceSpec) -> bool:
    _adopt(spec)
    pid = _read_pid(spec.pid_path)
    if pid is not None and _is_alive(pid):
        if not _matches_service_process(spec, pid):
            _clear_pid(spec)
            return False
        # Port-bound services can be alive briefly before listener bind;
        # keep them "running" during startup grace to prevent duplicate starts.
        if spec.port is not None:
            listener_pid = _port_listener_pid(spec.port)
            if listener_pid is None:
                if _within_startup_grace(spec):
                    return True
                _clear_pid(spec)
                return False
            if listener_pid != pid:
                if _is_alive(listener_pid) and _matches_service_process(spec, listener_pid):
                    spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
                    spec.pid_path.write_text(str(listener_pid))
                    return True
                _clear_pid(spec)
                return False
        return True

    if spec.port is not None:
        listener_pid = _port_listener_pid(spec.port)
        if (
            listener_pid is not None
            and _is_alive(listener_pid)
            and _matches_service_process(spec, listener_pid)
        ):
            spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
            spec.pid_path.write_text(str(listener_pid))
            return True

    _clear_pid(spec)
    return False


def _read_gateway_state() -> dict:
    try:
        data = json.loads((HERMES_HOME / "gateway_state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def memorize_pending(soul_id: str) -> dict:
    """Read memU's pending-memorize snapshot; {} when unreachable or malformed."""
    query = urllib.parse.urlencode({"soul_id": soul_id})
    url = f"http://127.0.0.1:{MEMU_SERVER_PORT}/diag/memorize/pending?{query}"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _child_status_parts(name: str, data: object) -> dict[str, str] | None:
    if not isinstance(data, dict):
        return None
    state = str(data.get("state") or data.get("status") or "unknown")
    detail_bits = []
    mode = data.get("mode")
    if mode:
        detail_bits.append(f"mode {mode}")
    error = data.get("error")
    if error:
        detail_bits.append(str(error))
    return {
        "name": name,
        "state": state,
        "detail": "; ".join(detail_bits),
    }


def status(spec: ServiceSpec) -> dict:
    running = is_running(spec)
    pid = _read_pid(spec.pid_path) if running else None
    state = "running" if running else "stopped"
    label = "● running" if running else "○ stopped"
    detail = ""
    children: list[dict[str, str]] = []
    actions: list[str] = []

    if spec.name == "hermes-gateway" and running:
        gateway_state = _read_gateway_state()
        if gateway_state.get("pid") != pid:
            gateway_state = {}
        platforms = gateway_state.get("platforms") if isinstance(gateway_state, dict) else None
        whatsapp = platforms.get("whatsapp") if isinstance(platforms, dict) else None
        if isinstance(whatsapp, dict):
            whatsapp_state = str(whatsapp.get("state") or "").strip().lower()
            if whatsapp_state in {"healthy", "connected"}:
                state = "healthy"
                label = "● healthy"
            elif whatsapp_state == "starting":
                state = "starting"
                label = "◐ starting"
            elif whatsapp_state:
                state = "degraded"
                label = "▲ degraded"
            detail = f"WhatsApp {whatsapp_state}" if whatsapp_state else ""
            for child_name in ("bridge", "web_source", "soul_history"):
                child = _child_status_parts(child_name.replace("_", "-"), whatsapp.get(child_name))
                if child is not None:
                    children.append(child)
                    if child_name == "bridge" and child.get("state") == "setup_needed":
                        actions.append("pair_whatsapp_bridge")
        else:
            state = "starting"
            label = "◐ starting"
            detail = "waiting for Hermes status"

    return {
        "running": running,
        "state": state,
        "status_label": label,
        "detail": detail,
        "children": children,
        "actions": actions,
    }


def start(spec: ServiceSpec, *, show_terminal: bool = False) -> None:
    if is_running(spec):
        return
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    spec.log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, **spec.env}
    if show_terminal and spec.supports_terminal:
        full_cmd = _terminal_command(spec.cmd)
        if full_cmd is not None:
            proc = subprocess.Popen(
                full_cmd, cwd=str(spec.cwd), env=env, start_new_session=True
            )
        else:
            proc = _spawn_background(spec, env)
    else:
        proc = _spawn_background(spec, env)
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
        # If a service has its own external pidfile contract (for example
        # mcp-memu-server's single-instance guard), we must wait for process exit
        # before returning; otherwise an immediate restart can be rejected even
        # though the port is already free.
        if (
            spec.adopt_pid_path is None
            and spec.port is not None
            and _port_listener_pid(spec.port) is None
        ):
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
