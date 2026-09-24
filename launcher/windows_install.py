"""State setup used by the packaged Windows installer."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import settings

_TAG = re.compile(r"v[A-Za-z0-9][A-Za-z0-9._-]{0,126}")
_VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)(?:[-.][A-Za-z0-9][A-Za-z0-9._-]*)?")
OWNER_FILE = ".openalma-root"
RELEASE_FILE = ".openalma-release"
PENDING_RELEASE_FILE = ".openalma-update-release"


def release_version(release_tag: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(release_tag)
    if match is None:
        raise ValueError("OpenAlma release tag must start with vMAJOR.MINOR.PATCH")
    return tuple(map(int, match.groups()))


def _known_releases(apps_root: Path) -> list[tuple[tuple[int, int, int], str]]:
    releases = []
    for path in (
        apps_root / RELEASE_FILE,
        apps_root / PENDING_RELEASE_FILE,
        settings.PACKAGED_VERSION_PATH,
    ):
        try:
            tag = path.read_text(encoding="utf-8").strip()
            releases.append((release_version(tag), tag))
        except FileNotFoundError:
            pass
    return releases


def compare_release(apps_root: Path, release_tag: str) -> int:
    target = release_version(release_tag)
    installed = _known_releases(apps_root)
    if not installed:
        return 0
    current, current_tag = max(installed)
    if target == current and release_tag != current_tag:
        raise ValueError("OpenAlma release tags with the same version must match exactly")
    return (target > current) - (target < current)


def selected_apps_root(fallback: Path) -> Path:
    stored = settings.read_paths().get("apps_root")
    return Path(stored).expanduser().resolve() if isinstance(stored, str) and stored.strip() else fallback.resolve()


def configure(apps_root: Path, release_tag: str) -> None:
    if _TAG.fullmatch(release_tag) is None:
        raise ValueError("Invalid OpenAlma release tag")
    apps_root = apps_root.resolve()
    marker = apps_root / OWNER_FILE
    if apps_root.exists() and any(apps_root.iterdir()) and not marker.exists():
        raise ValueError(f"Refusing to claim nonempty Apps root: {apps_root}")
    apps_root.mkdir(parents=True, exist_ok=True)
    if marker.exists() and marker.read_text(encoding="utf-8").strip() != str(apps_root):
        raise ValueError("OpenAlma Apps-root ownership marker does not match")

    marker.write_text(str(apps_root) + "\n", encoding="utf-8")
    release = apps_root / RELEASE_FILE
    pending = apps_root / PENDING_RELEASE_FILE
    core_complete = (
        (apps_root / "mcp-memu-server" / "run.py").exists()
        and (apps_root / "memu" / "pyproject.toml").exists()
        and (apps_root / "mcp-memu-server" / "config.json").exists()
    )
    comparison = compare_release(apps_root, release_tag)
    if comparison < 0:
        raise ValueError("OpenAlma cannot downgrade an installed release")
    if not release.exists() or not core_complete:
        release.write_text(release_tag + "\n", encoding="utf-8")
        pending.unlink(missing_ok=True)
    else:
        core_comparison = (
            release_version(release_tag)
            > release_version(release.read_text(encoding="utf-8").strip())
        )
        if core_comparison:
            pending.write_text(release_tag + "\n", encoding="utf-8")
        else:
            pending.unlink(missing_ok=True)

    settings.PACKAGED_VERSION_PATH.write_text(release_tag + "\n", encoding="utf-8")

    paths = settings.read_paths()
    paths["apps_root"] = str(apps_root)
    settings.write_paths(paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apps-root", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--compare-release", action="store_true")
    args = parser.parse_args()
    apps_root = selected_apps_root(args.apps_root)
    if args.compare_release:
        try:
            comparison = compare_release(apps_root, args.release_tag)
        except (OSError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(3) from None
        if comparison < 0:
            print("OpenAlma cannot downgrade an installed release", file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(10 if comparison > 0 else 0)
    configure(apps_root, args.release_tag)


if __name__ == "__main__":
    main()
