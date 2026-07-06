"""Lifecycle management for memU local-stack services.

The launcher tracks its own pidfile per service in ``~/.cache/openalma-launcher/``.
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
from dataclasses import dataclass, field
from pathlib import Path

from policy import CHANNELS_HOME as _CHANNELS_HOME
from settings import apps_root as _resolve_apps_root

STATE_DIR = Path.home() / ".cache" / "openalma-launcher"
STARTUP_GRACE_SECONDS = 4.0
MEMU_SERVER_PORT = 8099
PROCESS_SCAN_CACHE_SECONDS = 10.0
PORT_PID_CACHE_SECONDS = 5.0
_PROCESS_SCAN_CACHE: dict[tuple[str, str, str], tuple[float, list[int]]] = {}
_PORT_PID_CACHE: dict[int, tuple[float, int | None]] = {}


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


@dataclass(frozen=True)
class RuntimeState:
    verified_pids: tuple[int, ...] = ()
    service_pids: tuple[int, ...] = ()
    child_pids: tuple[int, ...] = ()
    pid: int | None = None
    port_pid: int | None = None
    running: bool = False
    stuck: bool = False
    orphaned: bool = False
    port_blocked: bool = False


def _resolve_memu_server_pid_path(root: Path) -> Path:
    config_path = root / "mcp-memu-server" / "config.json"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return root / "mcp-memu-server" / ".memu-server.pid"
    pid_file = raw.get("pid_file") if isinstance(raw, dict) else None
    if not isinstance(pid_file, str) or not pid_file.strip():
        return root / "mcp-memu-server" / ".memu-server.pid"
    path = Path(pid_file).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (root / "mcp-memu-server" / path).resolve()


def _atomic_start_command() -> str:
    return r'''
LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/openalma"
TOKEN_FILE="$LOG_DIR/atomic-token"
API_URL="${ATOMIC_SERVER_URL:-http://127.0.0.1:8080}"
mkdir -p "$LOG_DIR"
token=""
if [ -s "$TOKEN_FILE" ]; then
    token=$(sed -n '1p' "$TOKEN_FILE")
fi
if [ -z "$token" ]; then
    token_output=$(cargo run -p atomic-server -- token create --name openalma-launcher)
    token=$(printf '%s\n' "$token_output" | awk '/Token:/ {print $2; exit}')
fi
[ -n "$token" ]
printf '%s\n' "$token" > "$TOKEN_FILE"
export MEMU_SERVER_URL="${MEMU_SERVER_URL:-http://127.0.0.1:8099}"
export MEMU_USER_ID="${MEMU_USER_ID:-Marcos}"
export MEMU_SOUL_ID="${MEMU_SOUL_ID:-Siri}"
export VITE_ATOMIC_SERVER_URL="$API_URL"
export VITE_ATOMIC_AUTH_TOKEN="$token"
exec npm run dev:server
'''.strip()


def all_services() -> list[ServiceSpec]:
    root = _resolve_apps_root()
    if root is None:
        return []
    return [
        ServiceSpec(
            name="memu-server",
            label="memU Server",
            cmd=[str(root / "mcp-memu-server" / ".venv" / "bin" / "python3"), "run.py"],
            cwd=root / "mcp-memu-server",
            log_path=Path("/tmp/memu-server.out"),
            pid_path=STATE_DIR / "memu-server.pid",
            port=MEMU_SERVER_PORT,
            adopt_pid_path=_resolve_memu_server_pid_path(root),
        ),
        ServiceSpec(
            name="atomic",
            label="Atomic Mind Map",
            cmd=["sh", "-c", _atomic_start_command()],
            cwd=root / "atomic",
            log_path=Path.home() / ".local" / "state" / "openalma" / "atomic.log",
            pid_path=STATE_DIR / "atomic.pid",
            port=1420,
        ),
        ServiceSpec(
            name="channels-daemon",
            label="Hermes Channels",
            cmd=[shutil.which("python3") or "python3", "-m", "gateway.daemon"],
            cwd=root / "channels",
            log_path=Path("/tmp/channels-daemon.log"),
            pid_path=STATE_DIR / "channels-daemon.pid",
            env={
                "WHATSAPP_MODE": "bot",
                "WHATSAPP_ALLOWED_USERS": "*",
            },
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
    try:
        return int(text.strip())
    except ValueError:
        return None


_PORT_PID_RE = re.compile(r"pid=(\d+)")


def _port_listener_pid(port: int) -> int | None:
    now = time.monotonic()
    cached = _PORT_PID_CACHE.get(port)
    if cached is not None and now - cached[0] < PORT_PID_CACHE_SECONDS:
        return cached[1]
    try:
        result = subprocess.run(
            ["ss", "-tlnpH", f"sport = :{port}"],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = _PORT_PID_RE.search(result.stdout)
    pid = int(m.group(1)) if m else None
    _PORT_PID_CACHE[port] = (now, pid)
    return pid


def _clear_port_cache(spec: ServiceSpec) -> None:
    if spec.port is not None:
        _PORT_PID_CACHE.pop(spec.port, None)


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
    if spec.name == "channels-daemon":
        return cwd_matches and "gateway.daemon" in cmd
    if spec.name == "sillytavern":
        return cwd_matches and ("server.js" in cmd or "start.sh" in cmd)
    if spec.name == "atomic":
        return cwd_matches and (
            "npm run dev:server" in cmd
            or "scripts/dev-server.js" in cmd
            or "atomic-server" in cmd
            or "vite" in cmd
        )
    return False


def _channels_whatsapp_child_markers() -> list[tuple[Path, tuple[str, ...]]]:
    whatsapp_home = _CHANNELS_HOME / "whatsapp"
    session_path = whatsapp_home / "session"
    web_source_db = whatsapp_home / "web_source.db"
    web_source_status = whatsapp_home / "web_source_status.json"
    return [
        (
            session_path / "bridge.pid",
            ("bridge.js", "--session", str(session_path)),
        ),
        (
            whatsapp_home / "web_source.pid",
            (
                "source-daemon.js",
                "--db",
                str(web_source_db),
                "--status",
                str(web_source_status),
            ),
        ),
    ]


def _cmdline_has_markers(pid: int, markers: tuple[str, ...]) -> bool:
    cmd = _proc_cmdline(pid).lower()
    return bool(cmd) and all(marker.lower() in cmd for marker in markers)


def _matches_managed_process(spec: ServiceSpec, pid: int) -> bool:
    if _matches_service_process(spec, pid):
        return True
    if spec.name == "channels-daemon":
        return _matches_channels_child_process(pid)
    return False


def _matches_channels_child_process(pid: int) -> bool:
    return any(_cmdline_has_markers(pid, markers) for _pidfile, markers in _channels_whatsapp_child_markers())


def _scan_service_pids(spec: ServiceSpec) -> list[int]:
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _is_alive(pid) and _matches_managed_process(spec, pid):
            pids.append(pid)
    return pids


def _scan_service_pids_cached(spec: ServiceSpec) -> list[int]:
    key = (spec.name, str(spec.cwd), str(spec.pid_path))
    now = time.monotonic()
    cached = _PROCESS_SCAN_CACHE.get(key)
    if cached is not None and now - cached[0] < PROCESS_SCAN_CACHE_SECONDS:
        return cached[1]
    pids = _scan_service_pids(spec)
    _PROCESS_SCAN_CACHE[key] = (now, pids)
    return pids


def _verified_pid_candidates(spec: ServiceSpec) -> list[int]:
    candidates: list[int] = []
    for pid in (_read_pid(spec.pid_path), _read_adopt_pid(spec)):
        if pid is not None:
            candidates.append(pid)
    if spec.port is not None:
        listener_pid = _port_listener_pid(spec.port)
        if listener_pid is not None:
            candidates.append(listener_pid)
    if spec.name == "channels-daemon":
        for pidfile, _markers in _channels_whatsapp_child_markers():
            pid = _read_pid(pidfile)
            if pid is not None:
                candidates.append(pid)
    verified: list[int] = []
    seen: set[int] = set()
    for pid in candidates:
        if pid in seen:
            continue
        seen.add(pid)
        if _is_alive(pid) and _matches_managed_process(spec, pid):
            verified.append(pid)
    if not verified:
        for pid in _scan_service_pids_cached(spec):
            if pid in seen:
                continue
            seen.add(pid)
            if _is_alive(pid) and _matches_managed_process(spec, pid):
                verified.append(pid)
    return verified


def _remember_verified_pid(spec: ServiceSpec, pid: int) -> None:
    spec.pid_path.parent.mkdir(parents=True, exist_ok=True)
    if _read_pid(spec.pid_path) == pid:
        return
    spec.pid_path.write_text(str(pid))


def _clear_dead_pidfile(path: Path) -> None:
    pid = _read_pid(path)
    if pid is None or not _is_alive(pid):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


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


def _spawn_background(spec: ServiceSpec, env: dict[str, str]) -> subprocess.Popen[bytes]:
    log = spec.log_path.open("ab")
    try:
        return subprocess.Popen(
            spec.cmd, cwd=str(spec.cwd), env=env,
            stdout=log, stderr=log, start_new_session=True,
        )
    finally:
        log.close()


def is_running(spec: ServiceSpec) -> bool:
    return _runtime_state(spec).running


def _runtime_state(spec: ServiceSpec) -> RuntimeState:
    verified = _verified_pid_candidates(spec)
    service_pids = tuple(pid for pid in verified if _matches_service_process(spec, pid))
    child_pids = tuple(
        pid for pid in verified if (
            spec.name == "channels-daemon" and _matches_channels_child_process(pid)
        )
    )
    port_pid = _port_listener_pid(spec.port) if spec.port is not None else None
    port_blocked = (
        port_pid is not None
        and _is_alive(port_pid)
        and not _matches_managed_process(spec, port_pid)
    )
    if not verified:
        _clear_pid(spec)
        if spec.adopt_pid_path is not None:
            _clear_dead_pidfile(spec.adopt_pid_path)
        return RuntimeState(port_pid=port_pid, port_blocked=port_blocked)

    pid = verified[0]
    _remember_verified_pid(spec, pid)
    if spec.name == "channels-daemon" and not service_pids and child_pids:
        return RuntimeState(
            verified_pids=tuple(verified),
            service_pids=service_pids,
            child_pids=child_pids,
            pid=pid,
            port_pid=port_pid,
            orphaned=True,
            port_blocked=port_blocked,
        )
    if spec.port is None or (port_pid is not None and not port_blocked):
        return RuntimeState(
            verified_pids=tuple(verified),
            service_pids=service_pids,
            child_pids=child_pids,
            pid=pid,
            port_pid=port_pid,
            running=True,
            port_blocked=port_blocked,
        )
    running = _within_startup_grace(spec)
    return RuntimeState(
        verified_pids=tuple(verified),
        service_pids=service_pids,
        child_pids=child_pids,
        pid=pid,
        port_pid=port_pid,
        running=running,
        stuck=not running,
        orphaned=False,
        port_blocked=port_blocked,
    )


def _read_channels_config() -> dict:
    try:
        data = json.loads((_CHANNELS_HOME / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    return default if value is None else bool(value)


def _channels_bridge_health(config: dict | None = None) -> dict:
    port = (config or _read_channels_config()).get("bridge_port", 3000)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 3000
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_channels_web_source_status() -> dict:
    try:
        data = json.loads((_CHANNELS_HOME / "whatsapp" / "web_source_status.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def whatsapp_pair_status() -> dict:
    config = _read_channels_config()
    bridge = _channels_bridge_health(config)
    web_source = _read_channels_web_source_status()
    bridge_paired = bool(bridge.get("paired")) or str(bridge.get("status") or "").strip().lower() == "connected"
    web_source_state = str(web_source.get("state") or "").strip().lower()
    web_source_paired = web_source_state == "ready" or (not web_source and (_CHANNELS_HOME / "whatsapp" / "wwebjs_auth").exists())
    return {
        "bridge": {
            "paired": bridge_paired,
            "qr": None if bridge_paired or not isinstance(bridge.get("qr"), str) else bridge.get("qr"),
        },
        "websource": {
            "paired": web_source_paired,
            "qr": None if web_source_paired or not isinstance(web_source.get("qr"), str) else web_source.get("qr"),
        },
    }


def memorize_pending(soul_id: str, user_id: str = "") -> dict:
    """Read memU's pending-memorize snapshot; {} when unreachable or malformed."""
    memu_server = next((svc for svc in all_services() if svc.name == "memu-server"), None)
    port = memu_server.port if memu_server and memu_server.port else MEMU_SERVER_PORT
    params = {"soul_id": soul_id}
    if user_id:
        params["user_id"] = user_id
    query = urllib.parse.urlencode(params)
    url = f"http://127.0.0.1:{port}/diag/memorize/pending?{query}"
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
    runtime = _runtime_state(spec)
    running = runtime.running
    stuck = runtime.stuck
    orphaned = runtime.orphaned
    blocked = runtime.port_blocked
    state = (
        "blocked" if blocked
        else ("orphaned" if orphaned else ("stuck" if stuck else ("running" if running else "stopped")))
    )
    label = (
        "■ blocked" if blocked
        else ("▲ orphaned" if orphaned else ("▲ stuck" if stuck else ("● running" if running else "○ stopped")))
    )
    detail = ""
    children: list[dict[str, str]] = []
    if blocked:
        detail = f"port {spec.port} is held by PID {runtime.port_pid}"
    elif orphaned:
        detail = "service stopped; child process still running"

    if spec.name == "channels-daemon" and running:
        channels_config = _read_channels_config()
        web_source_enabled = _coerce_bool(channels_config.get("web_source_enabled"), True)
        bridge = _channels_bridge_health(channels_config)
        web_source = _read_channels_web_source_status()
        bridge_state = str(bridge.get("status") or "").strip().lower()
        web_source_state = str(web_source.get("state") or "").strip().lower()
        if bridge:
            child = _child_status_parts("bridge", bridge)
            children.append(child or {"name": "bridge", "state": bridge_state or "unknown", "detail": ""})
        else:
            children.append({"name": "bridge", "state": "unknown", "detail": "health unavailable"})
        if web_source_enabled:
            if web_source:
                child = _child_status_parts("web-source", web_source)
                children.append(child or {"name": "web-source", "state": web_source_state or "unknown", "detail": ""})
            else:
                children.append({"name": "web-source", "state": "unknown", "detail": "status unavailable"})

        web_source_ok = (not web_source_enabled) or web_source_state == "ready"
        web_source_starting = web_source_state in {"starting", "pairing", "authenticated"}
        if bridge_state == "connected" and web_source_ok:
            state = "healthy"
            label = "● healthy"
        elif bridge_state in {"connecting", "starting"} or web_source_starting:
            state = "starting"
            label = "◐ starting"
        elif bridge_state or web_source_state:
            state = "degraded"
            label = "▲ degraded"
        else:
            state = "starting"
            label = "◐ starting"
        detail = f"WhatsApp bridge {bridge_state or 'unknown'}"

    return {
        "running": running,
        "stuck": stuck,
        "orphaned": orphaned,
        "blocked": blocked,
        "supports_terminal": spec.supports_terminal,
        "startable": not running and not stuck and not orphaned and not blocked,
        "stoppable": running or stuck or orphaned,
        "state": state,
        "status_label": label,
        "detail": detail,
        "children": children,
    }


def start(spec: ServiceSpec, *, show_terminal: bool = False) -> None:
    _clear_port_cache(spec)
    runtime = _runtime_state(spec)
    if runtime.running or runtime.stuck or runtime.orphaned or runtime.port_blocked:
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
    _clear_port_cache(spec)


def _signal_pid(pid: int, sig: signal.Signals) -> None:
    pgid = None
    if hasattr(os, "getpgid") and hasattr(os, "killpg"):
        try:
            pgid = os.getpgid(pid)
        except OSError:
            pgid = None
    if pgid == pid:
        os.killpg(pgid, sig)
    else:
        os.kill(pid, sig)


def stop(spec: ServiceSpec, *, timeout: float = 10.0) -> None:
    _clear_port_cache(spec)
    pids = _verified_pid_candidates(spec)
    if not pids:
        _clear_pid(spec)
        if spec.adopt_pid_path is not None:
            _clear_dead_pidfile(spec.adopt_pid_path)
        return
    for pid in pids:
        try:
            _signal_pid(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            continue
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _verified_pid_candidates(spec):
            break
        time.sleep(0.1)
    else:
        for pid in _verified_pid_candidates(spec):
            try:
                _signal_pid(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                continue
    _clear_pid(spec)
    if spec.adopt_pid_path is not None:
        _clear_dead_pidfile(spec.adopt_pid_path)
    _clear_port_cache(spec)


def _clear_pid(spec: ServiceSpec) -> None:
    try:
        spec.pid_path.unlink()
    except FileNotFoundError:
        pass
