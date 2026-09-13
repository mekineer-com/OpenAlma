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
IRIS_RELEASE_URL = "https://api.github.com/repos/mekineer-com/iris/releases/latest"
RELEASE_TAG_KEY = "openalma_release_tag"
KNOWN_SERVICES = {"memu-server", "iris-server", "atomic", "channels-daemon", "sillytavern"}
OPTIONAL_SERVICES = KNOWN_SERVICES - {"memu-server"}
CORE_DESTINATIONS = {"mcp-memu-server", "memu"}
EXPECTED_DESTINATIONS = {
    "memu-server": CORE_DESTINATIONS,
    "channels-daemon": {"hermes-channels"},
    "atomic": {"atomic"},
    "sillytavern": {
        "sillytavern/SillyTavern",
        "sillytavern/SillyTavern/plugins/memu-plugin",
        "sillytavern/SillyTavern/data/default-user/extensions/memu-extension",
    },
}
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "OpenAlma-launcher"}


class SetupError(ValueError):
    pass


@dataclass
class InstallOperation:
    service_name: str
    root: Path
    state: str = "running"
    step: str = "Starting"
    detail: str = ""
    thread: threading.Thread | None = field(default=None, repr=False)
    lock_handle: Any = field(default=None, repr=False)


_LOCK = threading.RLock()
_OPERATION: InstallOperation | None = None
INSTALL_LOCK = Path.home() / ".cache" / "openalma-launcher" / "install.lock"


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


def _validated_destination(root: Path, destination_text: str, service_name: str) -> tuple[Path, str]:
    relative = Path(destination_text)
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise SetupError(f"Unsafe destination for {service_name}: {destination_text}")
    root = root.resolve()
    destination = (root / relative).resolve()
    openalma = settings.LAUNCHER_DIR.parent.resolve()
    if not _is_within(destination, root) or _is_within(destination, openalma) or _is_within(openalma, destination):
        raise SetupError(f"Unsafe destination for {service_name}: {destination_text}")
    return destination, relative.as_posix()


def validate_manifest(value: object, root: Path) -> dict[str, list[dict[str, str]]]:
    if not isinstance(value, dict) or set(value) != {"schema_version", "services"}:
        raise SetupError("Release manifest must contain only schema_version and services")
    if value["schema_version"] != 1 or not isinstance(value["services"], dict):
        raise SetupError("Unsupported release manifest schema")
    services = value["services"]
    if not set(services).issubset(KNOWN_SERVICES):
        raise SetupError("Release manifest contains an unknown service")

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
            if url.scheme != "https" or url.hostname != "github.com" or url.username or url.password:
                raise SetupError(f"Unsupported repository URL for {service_name}")
            destination_text = entry["destination"].strip()
            _destination, normalized = _validated_destination(root, destination_text, service_name)
            if normalized in destinations:
                raise SetupError(f"Duplicate release destination: {normalized}")
            destinations.add(normalized)
            parsed[service_name].append({
                "repository": repository,
                "ref": entry["ref"].strip(),
                "destination": normalized,
            })

    for service_name, expected in EXPECTED_DESTINATIONS.items():
        if service_name not in parsed:
            if service_name == "memu-server":
                raise SetupError("Release manifest must declare mcp-memu-server and memu core repositories")
            continue
        if {entry["destination"] for entry in parsed[service_name]} != expected:
            raise SetupError(f"Release manifest has unexpected destinations for {service_name}")
    return parsed


def discover_release(root: Path) -> tuple[str, dict[str, list[dict[str, str]]]]:
    release = _request_json(OPENALMA_RELEASE_URL)
    tag = release.get("tag_name")
    if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not tag.strip():
        raise SetupError("No supported stable OpenAlma release is available")
    encoded_tag = urllib.parse.quote(tag.strip(), safe="")
    manifest = _request_json(OPENALMA_RAW_URL.format(tag=encoded_tag))
    return tag.strip(), validate_manifest(manifest, root)


def recorded_manifest(root: Path) -> dict[str, list[dict[str, str]]]:
    tag = settings.read_paths().get(RELEASE_TAG_KEY)
    if not isinstance(tag, str) or not tag.strip():
        raise SetupError("The core installation has no recorded OpenAlma release")
    encoded_tag = urllib.parse.quote(tag.strip(), safe="")
    return validate_manifest(_request_json(OPENALMA_RAW_URL.format(tag=encoded_tag)), root)


def iris_release_entry(root: Path) -> dict[str, str]:
    release = _request_json(IRIS_RELEASE_URL)
    tag = release.get("tag_name")
    if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not tag.strip():
        raise SetupError("No supported stable Iris release is available")
    _validated_destination(root, "mentra-os/miniapps/openalma", "iris-server")
    return {
        "repository": "https://github.com/mekineer-com/iris.git",
        "ref": tag.strip(),
        "destination": "mentra-os/miniapps/openalma",
    }


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


def install_log_path(service_name: str) -> Path:
    return Path.home() / ".cache" / "openalma-launcher" / f"{service_name}-install.log"


def _set_operation(operation: InstallOperation, **values: str) -> None:
    with _LOCK:
        if _OPERATION is operation:
            for key, value in values.items():
                setattr(operation, key, value)


def _install_core(operation: InstallOperation) -> None:
    try:
        log_path = install_log_path(operation.service_name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            _set_operation(operation, step="Finding supported release")
            paths = settings.read_paths()
            tag = paths.get(RELEASE_TAG_KEY)
            if isinstance(tag, str) and tag.strip():
                tag = tag.strip()
                manifest = recorded_manifest(operation.root)
            else:
                tag, manifest = discover_release(operation.root)
            paths.update(apps_root=str(operation.root), **{RELEASE_TAG_KEY: tag})
            settings.write_paths(paths)

            for entry in manifest["memu-server"]:
                _set_operation(operation, step=f"Installing {entry['destination']}")
                _clone(entry, operation.root, log)

            _set_operation(operation, step="Creating Python environment")
            _run(
                [sys.executable, "-m", "venv", "--system-site-packages", str(operation.root / "mcp-memu-server" / ".venv")],
                cwd=None, log=log,
            )
            python = str(_venv_python(operation.root))
            _set_operation(operation, step="Installing core Python packages")
            _run([
                python, "-m", "pip", "install", "-e", str(operation.root / "mcp-memu-server"),
                "-e", str(operation.root / "memu"),
            ], cwd=None, log=log)
            _set_operation(operation, step="Installing sqlite-vec")
            _run([python, "scripts/install-sqlite-vec.py"], cwd=operation.root / "memu", log=log)
            _write_config(operation.root)
            issue = core_issue(operation.root)
            if issue:
                raise SetupError(issue)
        _set_operation(
            operation, state="ready", step="Core prepared", detail="Quit and restart OpenAlma to activate it",
        )
    except Exception as exc:
        _set_operation(operation, state="error", step="Installation failed", detail=str(exc))


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


def _npm_command(*arguments: str) -> list[str]:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"
    if os.name != "nt":
        return [npm, *arguments]
    command = subprocess.list2cmdline([npm, *arguments])
    return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]


def _iris_workspace_issue(root: Path) -> str:
    parent_package = root / "mentra-os" / "package.json"
    if not parent_package.exists():
        return ""
    try:
        workspaces = json.loads(parent_package.read_text(encoding="utf-8")).get("workspaces", [])
    except (OSError, ValueError, AttributeError):
        return "Cannot read the enclosing MentraOS package.json"
    if "miniapps/*" in workspaces and "!miniapps/openalma" not in workspaces:
        return "Exclude !miniapps/openalma from the enclosing MentraOS workspaces before installing Iris dependencies"
    return ""


def _node_dependencies_ready(directory: Path, *, include_dev: bool = False) -> bool:
    try:
        package = json.loads((directory / "package.json").read_text(encoding="utf-8"))
        names = list((package.get("dependencies") or {}).keys())
        if include_dev:
            names.extend((package.get("devDependencies") or {}).keys())
    except (OSError, ValueError, AttributeError):
        return False
    modules = directory / "node_modules"
    return modules.is_dir() and all((modules.joinpath(*name.split("/")) / "package.json").exists() for name in names)


def optional_issue(service_name: str, root: Path) -> str:
    repositories = {
        "channels-daemon": (
            ("hermes-channels/gateway/daemon.py", "Hermes Channels checkout"),
        ),
        "iris-server": (
            ("mentra-os/miniapps/openalma/miniapp.json", "Iris checkout"),
        ),
        "atomic": (
            ("atomic/package.json", "Atomic checkout"),
        ),
        "sillytavern": (
            ("sillytavern/SillyTavern/server.js", "SillyTavern checkout"),
            ("sillytavern/SillyTavern/plugins/memu-plugin/dist/index.js", "memU server plugin"),
            (
                "sillytavern/SillyTavern/data/default-user/extensions/memu-extension/dist/index.js",
                "memU SillyTavern extension",
            ),
        ),
    }
    for relative, label in repositories.get(service_name, ()):
        if not (root / relative).exists():
            return f"Missing {label}"
    dependency_checks = {
        "channels-daemon": (
            (root / "hermes-channels/bridge", False, "bridge dependencies"),
            (root / "hermes-channels/web-source", False, "web-source dependencies"),
        ),
        "iris-server": ((root / "mentra-os/miniapps/openalma", False, "Iris dependencies"),),
        "atomic": ((root / "atomic", True, "Atomic dependencies"),),
        "sillytavern": (
            (root / "sillytavern/SillyTavern", False, "SillyTavern dependencies"),
            (root / "sillytavern/SillyTavern/plugins/memu-plugin", False, "memU plugin dependencies"),
        ),
    }
    for directory, include_dev, label in dependency_checks.get(service_name, ()):
        if not _node_dependencies_ready(directory, include_dev=include_dev):
            return f"Missing {label}"
    if service_name == "atomic":
        binary = root / "atomic/target/server" / ("atomic-server.exe" if os.name == "nt" else "atomic-server")
        if not binary.exists():
            return "Missing Atomic server binary; follow the compile guidance"
    return ""


def start_issue(service_name: str, root: Path) -> str:
    if service_name == "memu-server":
        return core_issue(root)
    if service_name == "sillytavern":
        if not (root / "sillytavern/SillyTavern/server.js").exists():
            return "Missing SillyTavern checkout"
        if not _node_dependencies_ready(root / "sillytavern/SillyTavern"):
            return "Missing SillyTavern dependencies"
        return ""
    return optional_issue(service_name, root)


def _optional_entries(service_name: str, root: Path) -> list[dict[str, str]]:
    if service_name == "iris-server":
        return [iris_release_entry(root)]
    manifest = recorded_manifest(root)
    try:
        return manifest[service_name]
    except KeyError as exc:
        raise SetupError(f"The selected OpenAlma release does not include {service_name}") from exc


def _optional_commands(service_name: str, root: Path) -> list[tuple[list[str], Path]]:
    if service_name == "channels-daemon":
        return [
            (_npm_command("ci"), root / "hermes-channels" / "bridge"),
            (_npm_command("ci"), root / "hermes-channels" / "web-source"),
        ]
    if service_name == "iris-server":
        return [([shutil.which("bun") or "bun", "install", "--frozen-lockfile"], root / "mentra-os/miniapps/openalma")]
    if service_name == "atomic":
        return [(_npm_command("ci"), root / "atomic")]
    if service_name == "sillytavern":
        return [
            (_npm_command("ci"), root / "sillytavern/SillyTavern"),
            (_npm_command("ci", "--omit=dev"), root / "sillytavern/SillyTavern/plugins/memu-plugin"),
        ]
    raise SetupError(f"Unknown optional service: {service_name}")


def _optional_tool_issue(service_name: str) -> str:
    tool = "bun" if service_name == "iris-server" else "npm"
    return "" if shutil.which(tool) else f"Install {tool} to finish {service_name} setup"


def _install_optional(operation: InstallOperation) -> None:
    try:
        log_path = install_log_path(operation.service_name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            _set_operation(operation, step="Loading release selection")
            entries = sorted(
                _optional_entries(operation.service_name, operation.root),
                key=lambda entry: len(Path(entry["destination"]).parts),
            )
            for entry in entries:
                _set_operation(operation, step=f"Installing {entry['destination']}")
                _clone(entry, operation.root, log)
            issue = _optional_tool_issue(operation.service_name)
            if issue:
                raise SetupError(issue)
            if operation.service_name == "iris-server" and (issue := _iris_workspace_issue(operation.root)):
                raise SetupError(issue)
            for command, cwd in _optional_commands(operation.service_name, operation.root):
                _set_operation(operation, step=f"Installing dependencies in {cwd.name}")
                _run(command, cwd=cwd, log=log)
            issue = optional_issue(operation.service_name, operation.root)
            if issue and operation.service_name != "atomic":
                raise SetupError(issue)
        detail = optional_issue(operation.service_name, operation.root)
        _set_operation(operation, state="ready", step="Installation complete", detail=detail)
    except Exception as exc:
        _set_operation(operation, state="error", step="Installation failed", detail=str(exc))


def _acquire_install_lock() -> Any:
    INSTALL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = INSTALL_LOCK.open("a+b")
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise SetupError("Another OpenAlma installation is already running") from exc
    return handle


def _release_install_lock(handle: Any) -> None:
    try:
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl  # noqa: PLC0415

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _operation_worker(operation: InstallOperation, target: Any) -> None:
    try:
        target(operation)
    except BaseException as exc:
        _set_operation(operation, state="error", step="Installation failed", detail=str(exc))
    finally:
        _release_install_lock(operation.lock_handle)


def _begin_operation(service_name: str, root: Path, target: Any) -> dict[str, Any]:
    global _OPERATION
    with _LOCK:
        if _OPERATION is not None and _OPERATION.thread is not None and _OPERATION.thread.is_alive():
            if _OPERATION.root != root or _OPERATION.service_name != service_name:
                raise SetupError(f"{_OPERATION.service_name} installation is already running")
            return operation_status(root, service_name)
        lock_handle = _acquire_install_lock()
        operation = InstallOperation(service_name=service_name, root=root, lock_handle=lock_handle)
        thread = threading.Thread(
            target=_operation_worker, args=(operation, target),
            name=f"openalma-{service_name}-install", daemon=False,
        )
        operation.thread = thread
        _OPERATION = operation
        try:
            thread.start()
        except Exception:
            _release_install_lock(lock_handle)
            raise
    return operation_status(root, service_name)


def begin_core_install(root: Path) -> dict[str, Any]:
    root = root.resolve()
    issue = _prerequisite_issue(root)
    if issue:
        raise SetupError(issue)
    return _begin_operation("memu-server", root, _install_core)


def begin_optional_install(service_name: str, root: Path) -> dict[str, Any]:
    if service_name not in OPTIONAL_SERVICES:
        raise SetupError(f"Unknown optional service: {service_name}")
    root = root.resolve()
    if issue := core_issue(root):
        raise SetupError(f"Install core first: {issue}")
    return _begin_operation(service_name, root, _install_optional)


def operation_status(root: Path, service_name: str = "memu-server") -> dict[str, Any]:
    with _LOCK:
        operation = _OPERATION
        if operation is None or operation.root != root.resolve() or operation.service_name != service_name:
            return {"state": "idle", "step": "", "detail": ""}
        return {"state": operation.state, "step": operation.step, "detail": operation.detail}


def setup_status(root: Path) -> dict[str, Any]:
    operation = operation_status(root)
    if operation["state"] == "running":
        return {
            "state": "setup", "install_setup": True,
            "status_label": "Installing core", "detail": operation["step"],
            "startable": False, "install_running": True,
        }
    issue = core_issue(root)
    if not issue:
        return {
            "state": "setup", "install_setup": True,
            "status_label": "Core prepared", "detail": "Restart OpenAlma to activate it",
            "startable": False, "restart_required": True,
        }
    detail = operation["detail"] if operation["state"] == "error" else issue
    present = (root / "mcp-memu-server" / "run.py").exists()
    prerequisite = _prerequisite_issue(root)
    return {
        "state": "setup", "install_setup": True,
        "status_label": "Installation incomplete" if present else "Not installed",
        "detail": prerequisite or detail, "startable": False,
        "action_kind": None if prerequisite else "install",
        "action_label": "Continue Install" if present else "Install",
    }


def _optional_repositories_complete(service_name: str, root: Path) -> bool:
    markers = {
        "channels-daemon": ("hermes-channels/gateway/daemon.py",),
        "iris-server": ("mentra-os/miniapps/openalma/miniapp.json",),
        "atomic": ("atomic/package.json",),
        "sillytavern": (
            "sillytavern/SillyTavern/server.js",
            "sillytavern/SillyTavern/plugins/memu-plugin/dist/index.js",
            "sillytavern/SillyTavern/data/default-user/extensions/memu-extension/dist/index.js",
        ),
    }
    return all((root / path).exists() for path in markers[service_name])


def optional_setup_status(service_name: str, root: Path) -> dict[str, Any]:
    if service_name not in OPTIONAL_SERVICES:
        raise SetupError(f"Unknown optional service: {service_name}")
    operation = operation_status(root, service_name)
    if operation["state"] == "running":
        return {
            "ready": False, "state": "setup", "install_setup": True, "status_label": "Installing",
            "detail": operation["step"], "startable": False, "install_running": True,
        }
    issue = optional_issue(service_name, root)
    if not issue:
        guidance = "Enable server plugins in SillyTavern configuration" if service_name == "sillytavern" else ""
        return {"ready": True, "guidance": guidance}

    present = _optional_repositories_complete(service_name, root)
    manual = _optional_tool_issue(service_name) or (
        _iris_workspace_issue(root) if service_name == "iris-server" else ""
    )
    if service_name == "atomic" and present and _node_dependencies_ready(root / "atomic", include_dev=True):
        manual = issue
    detail = operation["detail"] if operation["state"] == "error" else (manual or issue)
    action = not present or not manual
    primary = {
        "channels-daemon": "hermes-channels/gateway/daemon.py",
        "iris-server": "mentra-os/miniapps/openalma/miniapp.json",
        "atomic": "atomic/package.json",
        "sillytavern": "sillytavern/SillyTavern/server.js",
    }[service_name]
    checkout_present = (root / primary).exists()
    startable = service_name == "sillytavern" and not start_issue(service_name, root)
    return {
        "ready": False,
        "state": "setup",
        "install_setup": True,
        "status_label": "Installation incomplete" if checkout_present else "Not installed",
        "detail": detail,
        "startable": startable,
        "action_kind": "install" if action else None,
        "action_label": "Continue Install" if checkout_present else "Install",
    }


def install_log(service_name: str) -> str:
    try:
        return install_log_path(service_name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
