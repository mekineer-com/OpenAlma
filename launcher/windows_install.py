"""State setup used by the packaged Windows installer."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import settings

_TAG = re.compile(r"v[A-Za-z0-9][A-Za-z0-9._-]{0,126}")
OWNER_FILE = ".openalma-installer-root"
RELEASE_FILE = ".openalma-release"


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
    if not release.exists():
        release.write_text(release_tag + "\n", encoding="utf-8")

    paths = settings.read_paths()
    paths["apps_root"] = str(apps_root)
    settings.write_paths(paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apps-root", type=Path, required=True)
    parser.add_argument("--release-tag", required=True)
    args = parser.parse_args()
    configure(args.apps_root, args.release_tag)


if __name__ == "__main__":
    main()
