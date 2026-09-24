"""Incremental repository setup owned by the launcher process."""
from __future__ import annotations

import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import settings
from process_flags import hidden_process_kwargs
from windows_install import release_version

OPENALMA_RELEASE_URL = "https://api.github.com/repos/mekineer-com/OpenAlma/releases/latest"
OPENALMA_RELEASES_URL = "https://api.github.com/repos/mekineer-com/OpenAlma/releases?per_page=20"
OPENALMA_RAW_URL = "https://raw.githubusercontent.com/mekineer-com/OpenAlma/{tag}/release-components.json"
IRIS_RELEASE_URL = "https://api.github.com/repos/mekineer-com/iris/releases/latest"
RELEASE_TAG_FILE = ".openalma-release"
ROOT_MARKER_FILE = ".openalma-root"
PENDING_RELEASE_TAG_FILE = ".openalma-update-release"
RECOVERY_FILE = ".openalma-update-recovery.json"
UPDATE_BACKUP_DIR = ".openalma-update-backups"
IRIS_RELEASE_TAG_FILE = ".openalma-iris-release"
KNOWN_SERVICES = {"memu-server", "iris-server", "atomic", "channels-daemon", "sillytavern"}
OPTIONAL_SERVICES = KNOWN_SERVICES - {"memu-server"}
CORE_DESTINATIONS = {"mcp-memu-server", "memu"}
EXPECTED_DESTINATIONS = {
    "memu-server": CORE_DESTINATIONS,
    "channels-daemon": {"hermes-channels"},
    "atomic": {"atomic"},
    "iris-server": {"mentra-os/miniapps/openalma"},
    "sillytavern": {
        "sillytavern/SillyTavern",
        "sillytavern/SillyTavern/plugins/memu-plugin",
        "sillytavern/SillyTavern/data/default-user/extensions/memu-extension",
    },
}
_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "OpenAlma-launcher"}


class SetupError(ValueError):
    pass


class SetupConflict(SetupError):
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
_RELEASE_ISSUE_CACHE: dict[tuple[str, str, str], tuple[float, str]] = {}
_LAUNCHER_UPDATE_CACHE: tuple[float, dict[str, str] | None] | None = None
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


def validate_manifest(
    value: object, root: Path, release_tag: str | None = None,
) -> dict[str, list[dict[str, str]]]:
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
            ref = entry["ref"].strip()
            if ref == "$OPENALMA_RELEASE_TAG":
                if release_tag is None:
                    raise SetupError("Release manifest tag placeholder has no selected release")
                ref = release_tag
            parsed[service_name].append({
                "repository": repository,
                "ref": ref,
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
    return tag.strip(), validate_manifest(manifest, root, tag.strip())


def recorded_manifest(root: Path) -> dict[str, list[dict[str, str]]]:
    tag = read_recorded_release(root)
    if tag is None:
        raise SetupError("The core installation has no recorded OpenAlma release")
    encoded_tag = urllib.parse.quote(tag, safe="")
    return validate_manifest(_request_json(OPENALMA_RAW_URL.format(tag=encoded_tag)), root, tag)


def read_recorded_release(root: Path) -> str | None:
    return _read_release(root, RELEASE_TAG_FILE)


def read_pending_release(root: Path) -> str | None:
    return _read_release(root, PENDING_RELEASE_TAG_FILE)


def read_packaged_release() -> str | None:
    try:
        return settings.PACKAGED_VERSION_PATH.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def launcher_update() -> dict[str, str] | None:
    global _LAUNCHER_UPDATE_CACHE
    current = read_packaged_release()
    if current is None or current.endswith("-dev"):
        return None
    if _LAUNCHER_UPDATE_CACHE and time.monotonic() - _LAUNCHER_UPDATE_CACHE[0] < 600:
        return _LAUNCHER_UPDATE_CACHE[1]
    update = None
    try:
        request = urllib.request.Request(OPENALMA_RELEASES_URL, headers=_HEADERS)
        with urllib.request.urlopen(request, timeout=3) as response:
            releases = json.loads(response.read().decode("utf-8"))
        if not isinstance(releases, list):
            raise ValueError("Invalid GitHub releases response")
        installed = next(release for release in releases if release.get("tag_name") == current)
        candidates = []
        for release in releases:
            tag = str(release.get("tag_name") or "")
            if release.get("draft") or bool(release.get("prerelease")) != bool(installed.get("prerelease")):
                continue
            if release_version(tag) <= release_version(current):
                continue
            expected = f"OpenAlma-{tag}-Windows.exe"
            asset = next((item for item in release.get("assets") or [] if item.get("name") == expected), None)
            if asset and asset.get("browser_download_url"):
                candidates.append((release_version(tag), tag, str(asset["browser_download_url"])))
        if candidates:
            _version, tag, url = max(candidates)
            update = {"tag": tag, "url": url}
    except (OSError, ValueError, StopIteration, TypeError):
        update = None
    _LAUNCHER_UPDATE_CACHE = (time.monotonic(), update)
    return update


def _read_release(root: Path, filename: str) -> str | None:
    try:
        tag = (root / filename).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SetupError(f"Cannot read {root / filename}") from exc
    if not tag or any(character.isspace() for character in tag):
        raise SetupError(f"Invalid release tag in {root / filename}")
    return tag


def _write_recorded_release(root: Path, tag: str) -> None:
    _write_release(root, RELEASE_TAG_FILE, tag)


def _write_root_marker(root: Path) -> None:
    _write_release(root, ROOT_MARKER_FILE, str(root.resolve()))


def _write_release(root: Path, filename: str, tag: str) -> None:
    target = root / filename
    temporary = root / f"{filename}.{os.getpid()}.tmp"
    try:
        temporary.write_text(tag + "\n", encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def iris_release_entry(root: Path) -> dict[str, str]:
    _validated_destination(root, "mentra-os/miniapps/openalma", "iris-server")
    tag = _read_release(root, IRIS_RELEASE_TAG_FILE)
    if tag is None:
        release = _request_json(IRIS_RELEASE_URL)
        tag = release.get("tag_name")
        if release.get("draft") or release.get("prerelease") or not isinstance(tag, str) or not tag.strip():
            raise SetupError("No supported stable Iris release is available")
        tag = tag.strip()
        _write_release(root, IRIS_RELEASE_TAG_FILE, tag)
    return {
        "repository": "https://github.com/mekineer-com/iris.git",
        "ref": tag,
        "destination": "mentra-os/miniapps/openalma",
    }


def _run(command: list[str], *, cwd: Path | None, log: Any) -> None:
    printable = " ".join(command)
    log.write(f"\n$ {printable}\n")
    log.flush()
    subprocess.run(
        command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, text=True, check=True,
        **hidden_process_kwargs(),
    )


def _git_output(command: list[str], cwd: Path | None = None) -> str:
    try:
        return subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=30, check=True,
            **hidden_process_kwargs(),
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


def _local_matching_checkout(destination: Path, repository: str, ref: str) -> bool:
    if not (destination / ".git").is_dir():
        return False
    try:
        origin = _git_output(["git", "remote", "get-url", "origin"], destination)
        head = _git_output(["git", "rev-parse", "HEAD"], destination)
        tagged = _git_output(["git", "rev-list", "-n", "1", ref], destination)
        dirty = _git_output(["git", "status", "--porcelain", "--untracked-files=no"], destination)
    except SetupError:
        return False
    return _normalized_repository(origin) == _normalized_repository(repository) and head == tagged and not dirty


def packaged_manifest(root: Path) -> dict[str, list[dict[str, str]]] | None:
    tag = read_packaged_release()
    if tag is None:
        return None
    try:
        value = json.loads(settings.PACKAGED_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SetupError("Packaged OpenAlma release manifest is unavailable") from exc
    return validate_manifest(value, root, tag)


def release_issue(service_name: str, root: Path, *, refresh: bool = False) -> str:
    manifest = packaged_manifest(root)
    if manifest is None or service_name == "iris-server" or service_name not in manifest:
        return ""
    packaged = read_packaged_release() or ""
    cache_key = (service_name, str(root.resolve()), packaged)
    cached = _RELEASE_ISSUE_CACHE.get(cache_key)
    if not refresh and cached and time.monotonic() - cached[0] < 10:
        return cached[1]
    if (root / RECOVERY_FILE).exists():
        return "Core update recovery is required; view the installation log"
    core_mismatch = any(
        (root / entry["destination"]).exists()
        and not _local_matching_checkout(root / entry["destination"], entry["repository"], entry["ref"])
        for entry in manifest["memu-server"]
    )
    if service_name != "memu-server" and core_mismatch:
        issue = "Core update required before this client can start"
    else:
        mismatched = [
            Path(entry["destination"]).name
            for entry in manifest[service_name]
            if (root / entry["destination"]).exists()
            and not _local_matching_checkout(root / entry["destination"], entry["repository"], entry["ref"])
        ]
        issue = f"Update required: {', '.join(mismatched)}" if mismatched else ""
    _RELEASE_ISSUE_CACHE[cache_key] = (time.monotonic(), issue)
    return issue


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


def _managed_checkout_state(entry: dict[str, str], root: Path) -> tuple[Path, str]:
    destination = root / entry["destination"]
    if not (destination / ".git").is_dir():
        raise SetupError(f"Managed checkout is missing: {destination}")
    origin = _git_output(["git", "remote", "get-url", "origin"], destination)
    if _normalized_repository(origin) != _normalized_repository(entry["repository"]):
        raise SetupError(f"Repository origin does not match: {destination}. Nothing was changed.")
    if _git_output(["git", "status", "--porcelain", "--untracked-files=no"], destination):
        raise SetupError(f"Repository has tracked edits: {destination}. Nothing was changed.")
    return destination, _git_output(["git", "rev-parse", "HEAD"], destination)


def _checkout_release(entry: dict[str, str], destination: Path, log: Any) -> None:
    ref = entry["ref"]
    _run(["git", "fetch", "--depth", "1", "origin", "tag", ref], cwd=destination, log=log)
    _run(["git", "checkout", "--detach", ref], cwd=destination, log=log)
    if not _local_matching_checkout(destination, entry["repository"], ref):
        raise SetupError(f"Checkout did not reach release {ref}: {destination}")


def _sqlite_directory(root: Path) -> Path:
    config_path = root / "mcp-memu-server" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        storage = config["storage"]
        raw = str(storage.get("sqlite_dir") or "").strip()
        if not raw:
            raw = str((storage.get("metadata_store") or {}).get("dsn") or "")
            raw = raw.removeprefix("sqlite:///")
            raw = str(Path(raw).parent)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SetupError("Cannot resolve the configured SQLite directory") from exc
    path = Path(raw).expanduser()
    return path.resolve() if path.is_absolute() else (config_path.parent / path).resolve()


def _backup_databases(root: Path, old_tag: str, new_tag: str) -> Path:
    databases = _soul_databases(root)
    required = sum(
        path.stat().st_size + sum(
            sidecar.stat().st_size for suffix in ("-wal", "-shm")
            if (sidecar := Path(str(path) + suffix)).exists()
        )
        for path in databases
    )
    parent = root / UPDATE_BACKUP_DIR
    parent.mkdir(parents=True, exist_ok=True)
    reserve = max(64 * 1024 * 1024, required // 10)
    if shutil.disk_usage(parent).free < required + reserve:
        raise SetupError("Not enough free space for the pre-update database backup")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = parent / f"{old_tag}-to-{new_tag}-{timestamp}"
    backup.mkdir()
    for database in databases:
        with (
            closing(sqlite3.connect(database)) as source,
            closing(sqlite3.connect(backup / database.name)) as target,
        ):
            source.backup(target)
    return backup


def _soul_databases(root: Path) -> list[Path]:
    config_path = root / "mcp-memu-server" / "config.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        raw = str(config["storage"]["metadata_store"]["dsn"]).removeprefix("sqlite:///")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SetupError("Cannot resolve the configured base database") from exc
    base = Path(raw).expanduser()
    if not base.is_absolute():
        base = (config_path.parent / base).resolve()
    return sorted(
        path for path in _sqlite_directory(root).glob("*.db")
        if not path.name.startswith(".")
        and not path.is_symlink()
        and path.is_file()
        and path.resolve() != base
    )


def _restore_databases(root: Path, backup: Path) -> None:
    sqlite_dir = _sqlite_directory(root)
    for source_path in sorted(backup.glob("*.db")):
        destination = sqlite_dir / source_path.name
        temporary = destination.with_name(f".{destination.name}.restore.tmp")
        temporary.unlink(missing_ok=True)
        try:
            with (
                closing(sqlite3.connect(source_path)) as source,
                closing(sqlite3.connect(temporary)) as target,
            ):
                source.backup(target)
            temporary.replace(destination)
            for suffix in ("-wal", "-shm"):
                Path(str(destination) + suffix).unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)


def _refresh_core(root: Path, log: Any) -> None:
    python = str(_venv_python(root))
    _run([
        python, "-m", "pip", "install", "--disable-pip-version-check",
        "-e", str(root / "mcp-memu-server"), "-e", str(root / "memu"),
    ], cwd=None, log=log)
    _run([python, "scripts/install-sqlite-vec.py"], cwd=root / "memu", log=log)


def _prune_update_backups(root: Path) -> None:
    successful = sorted(
        (path for path in (root / UPDATE_BACKUP_DIR).iterdir() if (path / "SUCCESS").exists()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in successful[3:]:
        shutil.rmtree(old)


def _update_core(
    operation: InstallOperation,
    tag: str,
    manifest: dict[str, list[dict[str, str]]],
    log: Any,
) -> None:
    old_tag = read_recorded_release(operation.root)
    if old_tag is None:
        raise SetupError("Installed core release is not recorded")
    entries = manifest["memu-server"]
    states = [_managed_checkout_state(entry, operation.root) for entry in entries]
    backup = _backup_databases(operation.root, old_tag, tag)
    recovery = operation.root / RECOVERY_FILE
    recovery.write_text(json.dumps({
        "from": old_tag,
        "to": tag,
        "backup": str(backup),
        "commits": {entry["destination"]: head for entry, (_path, head) in zip(entries, states)},
    }, indent=2) + "\n", encoding="utf-8")
    migration_started = False
    committed = False
    try:
        for entry, (destination, _head) in zip(entries, states):
            _set_operation(operation, step=f"Updating {entry['destination']}")
            _checkout_release(entry, destination, log)
        _set_operation(operation, step="Refreshing core Python packages")
        _refresh_core(operation.root, log)
        _set_operation(operation, step="Migrating soul databases")
        migration_started = True
        _run(
            [str(_venv_python(operation.root)), "migrate_release.py"],
            cwd=operation.root / "mcp-memu-server", log=log,
        )
        issue = core_issue(operation.root)
        if issue:
            raise SetupError(issue)
        _write_recorded_release(operation.root, tag)
        committed = True
        recovery.unlink()
        (operation.root / PENDING_RELEASE_TAG_FILE).unlink(missing_ok=True)
        _RELEASE_ISSUE_CACHE.clear()
        (backup / "SUCCESS").write_text("ok\n", encoding="utf-8")
        try:
            _prune_update_backups(operation.root)
        except OSError:
            pass
    except Exception as update_error:
        if committed:
            raise SetupError(
                f"Core updated but final state cleanup failed; retry before starting: {update_error}"
            ) from update_error
        rollback_errors = []
        if migration_started:
            try:
                _restore_databases(operation.root, backup)
            except Exception as exc:
                rollback_errors.append(f"database restore failed: {exc}")
        if not rollback_errors:
            for entry, (destination, head) in zip(entries, states):
                try:
                    _run(["git", "checkout", "--detach", head], cwd=destination, log=log)
                except Exception as exc:
                    rollback_errors.append(f"code restore failed for {entry['destination']}: {exc}")
            if not rollback_errors:
                try:
                    _refresh_core(operation.root, log)
                except Exception as exc:
                    rollback_errors.append(f"environment restore failed: {exc}")
        if not rollback_errors:
            recovery.unlink(missing_ok=True)
        detail = f"Core update failed: {update_error}"
        if rollback_errors:
            detail += "; recovery required: " + "; ".join(rollback_errors)
        raise SetupError(detail) from update_error


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
            **hidden_process_kwargs(),
        )
        subprocess.run(
            [python, root / "memu" / "scripts" / "install-sqlite-vec.py", "--validate", _sqlite_extension(root)],
            capture_output=True, text=True, timeout=10, check=True,
            **hidden_process_kwargs(),
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
            tag = read_recorded_release(operation.root)
            pending_tag = read_pending_release(operation.root)
            if pending_tag is not None:
                manifest = packaged_manifest(operation.root)
                if manifest is None or read_packaged_release() != pending_tag:
                    raise SetupError("Pending core update does not match the packaged launcher")
                _update_core(operation, pending_tag, manifest, log)
                paths["apps_root"] = str(operation.root)
                settings.write_paths(paths)
                _set_operation(
                    operation, state="ready", step="Core updated", detail="Start memU Server when ready",
                )
                return
            if tag is not None:
                manifest = packaged_manifest(operation.root) or recorded_manifest(operation.root)
            else:
                tag, manifest = discover_release(operation.root)
                _write_recorded_release(operation.root, tag)
            _write_root_marker(operation.root)
            paths["apps_root"] = str(operation.root)
            paths.pop("openalma_release_tag", None)
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


def _package_command(tool: str, *arguments: str, windows: bool | None = None) -> list[str]:
    windows = os.name == "nt" if windows is None else windows
    executable = shutil.which(tool) or tool
    if not windows or Path(executable).suffix.casefold() not in {".bat", ".cmd"}:
        return [executable, *arguments]
    command = subprocess.list2cmdline([executable, *arguments])
    return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command]


def _npm_command(*arguments: str) -> list[str]:
    return _package_command("npm", *arguments)


def _bun_command(*arguments: str) -> list[str]:
    return _package_command("bun", *arguments)


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
        binary = settings.atomic_server_binary(root)
        if not binary.exists():
            return "Missing Atomic server binary; follow the compile guidance"
    return ""


def start_issue(service_name: str, root: Path) -> str:
    if operation_status(root, service_name)["state"] == "running":
        return f"{service_name} installation is still running"
    if _active_install_owner() == (service_name, str(root.resolve())):
        return f"{service_name} installation is still running"
    if issue := release_issue(service_name, root, refresh=True):
        return issue
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
        return [(_bun_command("install", "--frozen-lockfile"), root / "mentra-os/miniapps/openalma")]
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
    states: list[tuple[Path, str]] = []
    entries: list[dict[str, str]] = []
    try:
        log_path = install_log_path(operation.service_name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8") as log:
            _set_operation(operation, step="Loading release selection")
            entries = sorted(
                _optional_entries(operation.service_name, operation.root),
                key=lambda entry: len(Path(entry["destination"]).parts),
            )
            states = [
                _managed_checkout_state(entry, operation.root)
                for entry in entries if (operation.root / entry["destination"]).exists()
            ]
            state_by_path = {path: head for path, head in states}
            for entry in entries:
                _set_operation(operation, step=f"Installing {entry['destination']}")
                destination = operation.root / entry["destination"]
                if destination in state_by_path:
                    if not _local_matching_checkout(destination, entry["repository"], entry["ref"]):
                        _checkout_release(entry, destination, log)
                else:
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
        _RELEASE_ISSUE_CACHE.clear()
        _set_operation(operation, state="ready", step="Installation complete", detail=detail)
    except Exception as exc:
        rollback_errors = []
        for destination, head in states:
            try:
                _run(["git", "checkout", "--detach", head], cwd=destination, log=log)
            except Exception as rollback_error:
                rollback_errors.append(str(rollback_error))
        detail = str(exc)
        if rollback_errors:
            detail += "; rollback failed: " + "; ".join(rollback_errors)
        _set_operation(operation, state="error", step="Installation failed", detail=detail)


def _lock_handle(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_handle(handle: Any) -> None:
    if os.name == "nt":
        import msvcrt  # noqa: PLC0415

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl  # noqa: PLC0415

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _acquire_install_lock(service_name: str, root: Path) -> Any:
    INSTALL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    handle = INSTALL_LOCK.open("a+b")
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    try:
        _lock_handle(handle)
    except OSError as exc:
        handle.close()
        raise SetupConflict("Another OpenAlma installation is already running") from exc
    try:
        handle.seek(1)
        handle.truncate()
        handle.write(json.dumps({"service": service_name, "root": str(root.resolve())}).encode("utf-8"))
        handle.flush()
    except OSError:
        _unlock_handle(handle)
        handle.close()
        raise
    return handle


def _active_install_owner() -> tuple[str, str] | None:
    try:
        handle = INSTALL_LOCK.open("a+b")
    except OSError:
        return None
    try:
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        try:
            _lock_handle(handle)
        except OSError:
            handle.seek(1)
            try:
                owner = json.loads(handle.read().decode("utf-8"))
                return str(owner["service"]), str(owner["root"])
            except (OSError, ValueError, KeyError, TypeError):
                return None
        _unlock_handle(handle)
        return None
    finally:
        handle.close()


def _release_install_lock(handle: Any) -> None:
    try:
        _unlock_handle(handle)
    finally:
        handle.close()


def _operation_worker(operation: InstallOperation, target: Any) -> None:
    try:
        target(operation)
    except Exception as exc:
        _set_operation(operation, state="error", step="Installation failed", detail=str(exc))
    finally:
        _release_install_lock(operation.lock_handle)


def _begin_operation(service_name: str, root: Path, target: Any) -> dict[str, Any]:
    global _OPERATION
    with _LOCK:
        if _OPERATION is not None and _OPERATION.thread is not None and _OPERATION.thread.is_alive():
            if _OPERATION.root != root or _OPERATION.service_name != service_name:
                raise SetupConflict(f"{_OPERATION.service_name} installation is already running")
            return operation_status(root, service_name)
        lock_handle = _acquire_install_lock(service_name, root)
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
            _OPERATION = None
            _release_install_lock(lock_handle)
            raise
    return operation_status(root, service_name)


def begin_core_install(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if (root / RECOVERY_FILE).exists():
        raise SetupError("Core update recovery is required; view the installation log")
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


def setup_status(
    root: Path, *, verify_runtime: bool = True, known_issue: str | None = None,
) -> dict[str, Any]:
    operation = operation_status(root)
    if operation["state"] == "running":
        return {
            "state": "setup", "install_setup": True,
            "status_label": "Installing core", "detail": operation["step"],
            "startable": False, "install_running": True,
        }
    present = (root / "mcp-memu-server" / "run.py").exists()
    if (root / RECOVERY_FILE).exists():
        return {
            "state": "blocked", "install_setup": True,
            "status_label": "Recovery required",
            "detail": operation["detail"] or "View the core installation log",
            "startable": False, "action_kind": None,
        }
    pending = read_pending_release(root)
    if pending is not None and present:
        return {
            "state": "update", "install_setup": True,
            "status_label": "Update required",
            "detail": operation["detail"] if operation["state"] == "error" else f"Core release {pending} is ready",
            "startable": False, "action_kind": "install",
            "action_label": "Retry" if operation["state"] == "error" else "Update",
        }
    if present and release_issue("memu-server", root):
        return {
            "state": "blocked", "install_setup": True,
            "status_label": "Update state incomplete",
            "detail": "Re-run the matching OpenAlma installer",
            "startable": False, "action_kind": None,
        }
    issue = known_issue if known_issue is not None else core_issue(root, verify_runtime=verify_runtime)
    if not issue:
        return {
            "state": "setup", "install_setup": True,
            "status_label": "Core prepared", "detail": "Restart OpenAlma to activate it",
            "startable": False, "restart_required": True,
        }
    detail = operation["detail"] if operation["state"] == "error" else issue
    prerequisite = _prerequisite_issue(root)
    return {
        "state": "setup", "install_setup": True,
        "status_label": "Installation incomplete" if present else "Not installed",
        "detail": prerequisite or detail, "startable": False,
        "action_kind": None if prerequisite else "install",
        "action_label": (
            "Retry" if operation["state"] == "error" else ("Continue Install" if present else "Install")
        ),
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
    if update_issue := release_issue(service_name, root):
        core_blocked = update_issue.startswith("Core update required")
        return {
            "ready": False, "state": "update", "install_setup": True,
            "status_label": "Waiting for core update" if core_blocked else "Update required",
            "detail": operation["detail"] if operation["state"] == "error" else update_issue,
            "startable": False, "action_kind": None if core_blocked else "install",
            "action_label": "" if core_blocked else ("Retry" if operation["state"] == "error" else "Update"),
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
        "action_label": (
            "Retry" if operation["state"] == "error"
            else ("Continue Install" if checkout_present else "Install")
        ),
    }


def install_log(service_name: str) -> str:
    try:
        return install_log_path(service_name).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
