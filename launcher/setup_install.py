"""Incremental repository setup owned by the launcher process."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import settings

OPENALMA_RELEASE_URL = "https://api.github.com/repos/mekineer-com/OpenAlma/releases/latest"
OPENALMA_RAW_URL = "https://raw.githubusercontent.com/mekineer-com/OpenAlma/{tag}/release-components.json"
RELEASE_TAG_KEY = "openalma_release_tag"
KNOWN_SERVICES = {"memu-server", "iris-server", "atomic", "channels-daemon", "sillytavern"}
CORE_DESTINATIONS = {"mcp-memu-server", "memu"}
INSTALL_LOG = Path.home() / ".cache" / "openalma-launcher" / "memu-server-install.log"
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "OpenAlma-launcher"}


class SetupError(ValueError):
    pass


@dataclass
class InstallOperation:
    root: Path
    state: str = "running"
    step: str = "Starting"
    detail: str = ""
    thread: threading.Thread | None = field(default=None, repr=False)


_LOCK = threading.RLock()
_OPERATION: InstallOperation | None = None


def _request_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=_HEADERS), timeout=15) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SetupError("No supported stable OpenAlma release is available") from exc
        raise SetupError(f"GitHub release request failed (HTTP {exc.code})") from exc
    except (OSError, ValueError) as exc:
        raise SetupError("GitHub release data is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise SetupError("GitHub release data is invalid")
    return value


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def validate_manifest(value: object, root: Path) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "services"}:
        raise SetupError("Release manifest must contain only schema_version and services")
    if value["schema_version"] != 1 or not isinstance(value["services"], dict):
        raise SetupError("Unsupported release manifest schema")
    services = value["services"]
    if not set(services).issubset(KNOWN_SERVICES):
        raise SetupError("Release manifest contains an unknown service")

    root = root.resolve()
    openalma = settings.LAUNCHER_DIR.parent.resolve()
    parsed: dict[str, list[dict[str, str]]] = {}
    destinations: set[str] = set()
    for service_name, service in services.items():
        if not isinstance(service, dict) or set(service) != {"repositories"}:
            raise SetupError(f"Invalid release manifest service: {service_name}")
        repositories = service["repositories"]
        if not isinstance(repositories, list) or not repositories:
            raise SetupError(f"Release manifest has no repositories for {service_name}")
        parsed[service_name] = []
        for entry in repositories:
            if not isinstance(entry, dict) or set(entry) != {"repository", "ref", "destination"}:
                raise SetupError(f"Invalid repository entry for {service_name}")
            if any(not isinstance(entry[key], str) or not entry[key].strip() for key in entry):
                raise SetupError(f"Blank repository entry for {service_name}")
            repository = entry["repository"].strip()
            url = urllib.parse.urlsplit(repository)
            if url.scheme != "https" or url.hostname != "github.com":
                raise SetupError(f"Unsupported repository URL for {service_name}")
            destination_text = entry["destination"].strip()
            relative = Path(destination_text)
            if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
                raise SetupError(f"Unsafe destination for {service_name}: {destination_text}")
            destination = (root / relative).resolve()
            if not _is_within(destination, root) or _is_within(destination, openalma) or _is_within(openalma, destination):
                raise SetupError(f"Unsafe destination for {service_name}: {destination_text}")
            normalized = relative.as_posix()
            if normalized in destinations:
                raise SetupError(f"Duplicate release destination: {normalized}")
            destinations.add(normalized)
            parsed[service_name].append({
                "repository": repository,
                "ref": entry["ref"].strip(),
                "destination": normalized,
            })

    core = parsed.get("memu-server", [])
    if {entry["destination"] for entry in core} != CORE_DESTINATIONS:
        raise SetupError("Release manifest must declare mcp-memu-server and memu core repositories")
    return parsed


def discover_release(root: Path) -> tuple[str, dict[str, list[dict[str, str]]]]:
    release = _request_json(OPENALMA_RELEASE_URL)
    tag = release.get("tag_name")
    if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not tag.strip():
        raise SetupError("No supported stable OpenAlma release is available")
    encoded_tag = urllib.parse.quote(tag.strip(), safe="")
    manifest = _request_json(OPENALMA_RAW_URL.format(tag=encoded_tag))
    return tag.strip(), validate_manifest(manifest, root)


def _run(command: list[str], *, cwd: Path | None, log: Any) -> None:
    printable = " ".join(command)
    log.write(f"\n$ {printable}\n")
    log.flush()
    subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, text=True, check=True)


def _git_output(command: list[str], cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError(f"Git verification failed: {' '.join(command)}") from exc


def _normalized_repository(value: str) -> str:
    return value.rstrip("/").removesuffix(".git").casefold()


def _remote_commit(repository: str, ref: str) -> str:
    output = _git_output([
        "git", "ls-remote", "--exit-code", repository,
        f"refs/tags/{ref}", f"refs/tags/{ref}^{{}}",
    ])
    refs = {parts[1]: parts[0] for line in output.splitlines() if len(parts := line.split()) == 2}
    commit = refs.get(f"refs/tags/{ref}^{{}}") or refs.get(f"refs/tags/{ref}")
    if not commit:
        raise SetupError(f"Release tag does not exist: {ref}")
    return commit


def _matching_checkout(destination: Path, repository: str, ref: str) -> bool:
    if not (destination / ".git").is_dir():
        return False
    origin = _git_output(["git", "remote", "get-url", "origin"], destination)
    head = _git_output(["git", "rev-parse", "HEAD"], destination)
    return _normalized_repository(origin) == _normalized_repository(repository) and head == _remote_commit(repository, ref)


def _clone(entry: dict[str, str], root: Path, log: Any) -> None:
    destination = root / entry["destination"]
    repository = entry["repository"]
    ref = entry["ref"]
    if destination.exists():
        if _matching_checkout(destination, repository, ref):
            log.write(f"Reusing {destination}\n")
            return
        raise SetupError(f"Move or remove conflicting destination: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    leftovers = sorted(destination.parent.glob(f".openalma-{destination.name}-*"))
    if leftovers:
        raise SetupError(f"Inspect and remove the previous temporary checkout: {leftovers[0]}")
    temporary = Path(tempfile.mkdtemp(prefix=f".openalma-{destination.name}-", dir=destination.parent))
    try:
        _run(["git", "clone", "--depth", "1", "--branch", ref, repository, str(temporary)], cwd=None, log=log)
        if not _matching_checkout(temporary, repository, ref):
            raise SetupError(f"Cloned checkout did not match {repository} at {ref}")
        temporary.rename(destination)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def _venv_python(root: Path) -> Path:
    return root / "mcp-memu-server" / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")


def _sqlite_extension(root: Path) -> Path:
    suffix = {"Windows": ".dll", "Darwin": ".dylib"}.get(platform.system(), ".so")
    return root / "memu" / "src" / "memu" / "database" / "sqlite" / f"vec0{suffix}"


def _config_ready(root: Path) -> bool:
    try:
        config = json.loads((root / "mcp-memu-server" / "config.json").read_text(encoding="utf-8"))
        storage = config["storage"]
        values = (
            config["memu"]["path"], storage["resources_dir"],
            storage["metadata_store"]["dsn"], storage["sqlite_dir"],
        )
        return all(isinstance(value, str) and value.strip() for value in values)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _configured_memu_path(root: Path) -> Path:
    config = json.loads((root / "mcp-memu-server" / "config.json").read_text(encoding="utf-8"))
    path = Path(config["memu"]["path"]).expanduser()
    return path.resolve() if path.is_absolute() else (root / "mcp-memu-server" / path).resolve()


def core_issue(root: Path, *, verify_runtime: bool = True) -> str:
    checks = (
        (root / "mcp-memu-server" / "run.py", "mcp-memu-server checkout"),
        (root / "memu" / "pyproject.toml", "memU checkout"),
        (_venv_python(root), "Python environment"),
        (_sqlite_extension(root), "sqlite-vec extension"),
    )
    for path, label in checks:
        if not path.exists():
            return f"Missing {label}"
    if not _config_ready(root):
        return "Missing or incomplete mcp-memu-server config.json"
    if not verify_runtime:
        return ""
    python = str(_venv_python(root))
    try:
        memu_path = str(_configured_memu_path(root))
        subprocess.run(
            [
                python, "-c",
                f"import importlib.metadata, sys; sys.path.insert(0, {memu_path!r}); import memu; "
                "importlib.metadata.version('memu-server')",
            ],
            capture_output=True, text=True, timeout=10, check=True,
        )
        subprocess.run(
            [python, root / "memu" / "scripts" / "install-sqlite-vec.py", "--validate", _sqlite_extension(root)],
            capture_output=True, text=True, timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "Core Python packages or sqlite-vec validation failed"
    return ""


def _write_config(root: Path) -> None:
    target = root / "mcp-memu-server" / "config.json"
    if target.exists():
        return
    source = root / "mcp-memu-server" / "config.example.json"
    try:
        config = json.loads(source.read_text(encoding="utf-8"))
        config["memu"]["path"] = "../memu/src"
        config["storage"]["resources_dir"] = "../memu/resources"
        config["storage"]["metadata_store"]["dsn"] = "../memu/sqlite/memu.db"
        config["storage"]["sqlite_dir"] = "../memu/sqlite"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SetupError("Cannot create config.json from config.example.json") from exc
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if target.exists():
        temporary.unlink()
    else:
        temporary.replace(target)


def _set_operation(**values: str) -> None:
    with _LOCK:
        if _OPERATION is not None:
            for key, value in values.items():
                setattr(_OPERATION, key, value)


def _install_core(operation: InstallOperation) -> None:
    INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        with INSTALL_LOG.open("w", encoding="utf-8") as log:
            _set_operation(step="Finding supported release")
            tag, manifest = discover_release(operation.root)
            paths = settings.read_paths()
            paths.update(apps_root=str(operation.root), **{RELEASE_TAG_KEY: tag})
            settings.write_paths(paths)

            for entry in manifest["memu-server"]:
                _set_operation(step=f"Installing {entry['destination']}")
                _clone(entry, operation.root, log)

            _set_operation(step="Creating Python environment")
            _run(
                [sys.executable, "-m", "venv", "--system-site-packages", str(operation.root / "mcp-memu-server" / ".venv")],
                cwd=None, log=log,
            )
            python = str(_venv_python(operation.root))
            _set_operation(step="Installing core Python packages")
            _run([
                python, "-m", "pip", "install", "-e", str(operation.root / "mcp-memu-server"),
                "-e", str(operation.root / "memu"),
            ], cwd=None, log=log)
            _set_operation(step="Installing sqlite-vec")
            _run([python, "scripts/install-sqlite-vec.py"], cwd=operation.root / "memu", log=log)
            _write_config(operation.root)
            issue = core_issue(operation.root)
            if issue:
                raise SetupError(issue)
        _set_operation(state="ready", step="Core prepared", detail="Quit and restart OpenAlma to activate it")
    except Exception as exc:
        _set_operation(state="error", step="Installation failed", detail=str(exc))


def _prerequisite_issue(root: Path) -> str:
    if sys.version_info[:2] != (3, 12):
        return "Run the OpenAlma launcher with Python 3.12"
    if shutil.which("git") is None:
        return "Install Git before installing core"
    try:
        import venv  # noqa: F401, PLC0415
    except ImportError:
        return "Install Python 3.12 venv support"
    if not root.is_dir():
        return "Choose an existing Apps-root directory"
    if not os.access(root, os.W_OK):
        return "The Apps-root directory is not writable"
    return ""


def begin_core_install(root: Path) -> dict[str, Any]:
    global _OPERATION
    root = root.resolve()
    issue = _prerequisite_issue(root)
    if issue:
        raise SetupError(issue)
    with _LOCK:
        if _OPERATION is not None and _OPERATION.thread is not None and _OPERATION.thread.is_alive():
            if _OPERATION.root != root:
                raise SetupError(f"Core installation is already running in {_OPERATION.root}")
            return operation_status(root)
        operation = InstallOperation(root=root)
        thread = threading.Thread(
            target=_install_core, args=(operation,), name="openalma-core-install", daemon=False,
        )
        operation.thread = thread
        _OPERATION = operation
        thread.start()
    return operation_status(root)


def operation_status(root: Path) -> dict[str, Any]:
    with _LOCK:
        operation = _OPERATION
        if operation is None or operation.root != root.resolve():
            return {"state": "idle", "step": "", "detail": ""}
        return {"state": operation.state, "step": operation.step, "detail": operation.detail}


def setup_status(root: Path) -> dict[str, Any]:
    operation = operation_status(root)
    if operation["state"] == "running":
        return {
            "state": "setup", "status_label": "Installing core", "detail": operation["step"],
            "startable": False, "install_running": True,
        }
    issue = core_issue(root)
    if not issue:
        return {
            "state": "setup", "status_label": "Core prepared", "detail": "Restart OpenAlma to activate it",
            "startable": False, "restart_required": True,
        }
    detail = operation["detail"] if operation["state"] == "error" else issue
    present = (root / "mcp-memu-server" / "run.py").exists()
    prerequisite = _prerequisite_issue(root)
    return {
        "state": "setup", "status_label": "Installation incomplete" if present else "Not installed",
        "detail": prerequisite or detail, "startable": False,
        "action_kind": None if prerequisite else "install",
        "action_label": "Continue Install" if present else "Install",
    }


def install_log() -> str:
    try:
        return INSTALL_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
