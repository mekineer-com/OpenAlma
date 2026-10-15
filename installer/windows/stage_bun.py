"""Prepare installer-only Bun files and separate corresponding-source assets."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "launcher"))

import settings  # noqa: E402
import setup_install  # noqa: E402


def download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, target.open("wb") as output:
        shutil.copyfileobj(response, output)


def git_source(repository: str, revision: str, target: Path) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        subprocess.run(["git", "init", "--bare", temporary], check=True)
        subprocess.run(["git", "fetch", "--depth=1", "--no-tags", repository, revision],
                       cwd=temporary, check=True)
        if setup_install._git_output(["git", "rev-parse", "FETCH_HEAD"], Path(temporary)) != revision:
            raise RuntimeError("Git source does not match the pinned revision")
        subprocess.run(["git", "archive", "--format=tar.gz", f"--prefix={revision}/",
                        f"--output={target.resolve()}", revision], cwd=temporary, check=True)


def stage_rust(packaging: Path, sources: Path, licenses) -> None:
    # ponytail: frozen runtime inventory; rederive from Windows Cargo.lock when Bun is upgraded.
    entries = json.loads((packaging / "bun-rust-sources.json").read_text(encoding="utf-8"))
    if not entries:
        return
    with tempfile.TemporaryDirectory() as temporary, tarfile.open(
        sources / "bun-lolhtml-runtime-source.tar.gz", "w:gz",
    ) as bundle:
        for entry in entries:
            name = f"{entry['crate']}-{entry['version']}"
            archive = Path(temporary) / f"{name}.crate"
            url = f"https://static.crates.io/crates/{entry['crate']}/{archive.name}"
            download(url, archive)
            with archive.open("rb") as content:
                if hashlib.file_digest(content, "sha256").hexdigest() != entry["checksum"]:
                    raise RuntimeError(f"Rust source checksum mismatch: {name}")
            with tarfile.open(archive, "r:gz") as package:
                for path in entry["licenses"]:
                    try:
                        member = package.getmember(f"{name}/{path}")
                    except KeyError as exc:
                        raise RuntimeError(f"Missing Rust license material: {name}/{path}") from exc
                    if not member.isfile() or not member.size:
                        raise RuntimeError(f"Empty Rust license material: {name}/{path}")
                    text = package.extractfile(member).read().decode("utf-8")
                    if not text.strip():
                        raise RuntimeError(f"Empty Rust license material: {name}/{path}")
                    licenses.write(f"\n{'=' * 72}\n{url}#{path}\n{'=' * 72}\n{text}\n")
            bundle.add(archive, arcname=archive.name)


def stage(root: Path) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Stage the Windows runtime on Windows to verify native execution")
    packaging = root / "installer/windows"
    payload = root / "launcher/runtime/bun"
    sources = packaging / "output/bun-sources"
    payload.mkdir(parents=True, exist_ok=True)
    sources.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((packaging / "bun-sources.json").read_text(encoding="utf-8"))
    headers = {"Accept": "application/vnd.github.raw+json"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    binary = payload / "bun.exe"
    setup_install._install_bun(root, sys.stdout, destination=binary)
    revision = subprocess.run([str(binary), "--revision"], capture_output=True, text=True,
                              check=True, timeout=10).stdout.strip()
    if revision != f"{setup_install.BUN_VERSION}+{manifest[0]['revision'][:9]}":
        raise RuntimeError("Bundled Bun revision does not match the corresponding source")
    license_path = payload / "BUN-LICENSES.txt"
    with license_path.open("w", encoding="utf-8", newline="\n") as licenses:
        for entry in manifest:
            for name in entry["licenses"]:
                url = f"https://api.github.com/repos/{entry['repository']}/contents/{name}?ref={entry['revision']}"
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                    text = response.read().decode("utf-8")
                if not text.strip():
                    raise RuntimeError(f"Empty license material: {url}")
                licenses.write(f"\n{'=' * 72}\n{url}\n{'=' * 72}\n{text}\n")
            if entry.get("source"):
                archive = sources / f"{entry['name']}-{entry['revision']}-source.tar.gz"
                if entry["name"] == "webkit":
                    # GitHub blocks archive creation for this tree; fetch no history or tags.
                    git_source(f"https://github.com/{entry['repository']}.git", entry["revision"], archive)
                else:
                    download(f"https://codeload.github.com/{entry['repository']}/tar.gz/{entry['revision']}",
                             archive)
                print(f"Source archive: {archive.name}: {archive.stat().st_size} bytes", flush=True)
                if archive.stat().st_size >= 2 * 1024 ** 3:
                    raise RuntimeError(f"Source archive exceeds GitHub's release asset limit: {archive.name}")
                required = {entry["licenses"][0]}
                with tarfile.open(archive, "r|gz") as package:
                    for member in package:
                        if member.isfile() and member.size:
                            required.discard(member.name.partition("/")[2])
                if required:
                    raise RuntimeError(f"Incomplete source archive: {archive.name}")
        stage_rust(packaging, sources, licenses)
    for name in ("bun-sources.json", "bun-rust-sources.json", "BUN-REBUILD.md"):
        shutil.copyfile(packaging / name, sources / name)
    notice = (
        f"OpenAlma includes the official unmodified Bun {revision} as a separate executable.\n"
        "Bun includes statically linked JavaScriptCore/WebKit and TinyCC.\n"
        "Their applicable licenses and other third-party notices are in BUN-LICENSES.txt.\n"
        "This software is based in part on the work of the Independent JPEG Group.\n"
        "You may modify/rebuild/relink Bun with modified LGPL components under their licenses;\n"
        "OpenAlma imposes no additional restriction on those rights.\n"
        "The matching source archives, bun-sources.json, bun-rust-sources.json and\n"
        "BUN-REBUILD.md must accompany\n"
        "the installer at https://github.com/mekineer-com/OpenAlma/releases .\n"
        "They are separate downloads, not prerequisites for installing or running OpenAlma.\n"
    )
    with binary.open("rb") as executable:
        notice += f"Bun executable SHA256: {hashlib.file_digest(executable, 'sha256').hexdigest()}\n"
    (payload / "BUN-SOURCE.txt").write_text(notice, encoding="utf-8")
    shutil.copyfile(payload / "BUN-SOURCE.txt", sources / "BUN-SOURCE.txt")
    shutil.copyfile(license_path, sources / license_path.name)
    with (sources / "BUN-SHA256SUMS").open("w", encoding="ascii", newline="\n") as sums:
        for path in sorted(sources.iterdir()):
            if path.name == "BUN-SHA256SUMS":
                continue
            with path.open("rb") as content:
                digest = hashlib.file_digest(content, "sha256").hexdigest()
            sums.write(f"{digest}  {path.name}\n")
    if settings.bun_binary(root) != binary:
        raise RuntimeError("The launcher did not select its bundled Bun")


if __name__ == "__main__":
    stage(ROOT)
