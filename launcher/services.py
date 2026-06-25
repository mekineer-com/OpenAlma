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
            adopt_pid_path=_resolve_memu_server_pid_path(root),
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
        return cwd_matches and ("server.js" in cmd or "start.sh" in cmd)
    return False


def _strip_simple_yaml_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if value[0] in {"'", '"'} and value[-1:] == value[0]:
        return value[1:-1]
    return value


def _read_hermes_whatsapp_config() -> dict[str, str]:
    """Read the flat `whatsapp:` config keys the launcher needs for pid matching."""
    try:
        lines = (HERMES_HOME / "config.yaml").read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    out: dict[str, str] = {}
    in_whatsapp = False
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            key = line.split(":", 1)[0].strip()
            in_whatsapp = key == "whatsapp"
            continue
        if not in_whatsapp or not line.startswith("  "):
            continue
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        if raw_value.strip():
            out[key.strip()] = _strip_simple_yaml_value(raw_value)
    return out


def _configured_path(config: dict[str, str], key: str, default: Path) -> Path:
    raw = config.get(key)
    if not raw:
        return default
    return Path(raw).expanduser()


def _hermes_whatsapp_child_markers() -> list[tuple[Path, tuple[str, ...]]]:
    whatsapp_home = HERMES_HOME / "whatsapp"
    config = _read_hermes_whatsapp_config()
    session_path = _configured_path(config, "session_path", whatsapp_home / "session")
    web_source_db = _configured_path(config, "web_source_db", whatsapp_home / "web_source.db")
    web_source_status = _configured_path(
        config,
        "web_source_status",
        whatsapp_home / "web_source_status.json",
    )
    bridge_script = _strip_simple_yaml_value(config.get("bridge_script", "bridge.js"))
    web_source_script = _strip_simple_yaml_value(config.get("web_source_script", "source-daemon.js"))
    return [
        (
            session_path / "bridge.pid",
            (bridge_script, "--session", str(session_path)),
        ),
        (
            web_source_status.with_name("web_source.pid"),
            (
                web_source_script,
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
    if spec.name != "hermes-gateway":
        return False
    return _matches_hermes_child_process(pid)


def _matches_hermes_child_process(pid: int) -> bool:
    return any(_cmdline_has_markers(pid, markers) for _pidfile, markers in _hermes_whatsapp_child_markers())


def _scan_service_pids(spec: ServiceSpec) -> list[int]:
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _is_alive(pid) and _matches_managed_process(spec, pid):
            pids.append(pid)
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
    candidates.extend(_scan_service_pids(spec))
    if spec.name == "hermes-gateway":
        for pidfile, _markers in _hermes_whatsapp_child_markers():
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


def is_running(spec: ServiceSpec) -> bool:
    return _runtime_state(spec).running


def _runtime_state(spec: ServiceSpec) -> RuntimeState:
    verified = _verified_pid_candidates(spec)
    service_pids = tuple(pid for pid in verified if _matches_service_process(spec, pid))
    child_pids = tuple(pid for pid in verified if spec.name == "hermes-gateway" and _matches_hermes_child_process(pid))
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
    if spec.name == "hermes-gateway" and not service_pids and child_pids:
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


def _read_gateway_state() -> dict:
    try:
        data = json.loads((HERMES_HOME / "gateway_state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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
    actions: list[str] = []
    if blocked:
        detail = f"port {spec.port} is held by PID {runtime.port_pid}"
    elif orphaned:
        detail = "gateway stopped; WhatsApp child process still running"

    if spec.name == "hermes-gateway" and running:
        gateway_state = _read_gateway_state()
        if gateway_state.get("pid") != runtime.pid:
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
        "actions": actions,
    }


def start(spec: ServiceSpec, *, show_terminal: bool = False) -> None:
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


def _clear_pid(spec: ServiceSpec) -> None:
    try:
        spec.pid_path.unlink()
    except FileNotFoundError:
        pass
