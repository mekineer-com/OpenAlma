import importlib.util
import json
import hashlib
import tarfile
from io import BytesIO, StringIO
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

spec = importlib.util.spec_from_file_location(
    "stage_bun", Path(__file__).resolve().parents[1] / "installer/windows/stage_bun.py",
)
stage_bun = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage_bun)


@pytest.mark.parametrize("failure", [None, "notice", "source"])
def test_bun_packaging_separates_payload_and_sources(tmp_path, monkeypatch, failure):
    packaging = tmp_path / "installer/windows"
    packaging.mkdir(parents=True)
    manifest = [
        {"name": name, "repository": f"fictional/{name}", "revision": "a" * 40,
         "source": True, "licenses": ["LICENSE"]}
        for name in ("bun", "webkit", "tinycc")
    ]
    (packaging / "bun-sources.json").write_text(json.dumps(manifest), encoding="utf-8")
    (packaging / "bun-rust-sources.json").write_text("[]", encoding="utf-8")
    (packaging / "BUN-REBUILD.md").write_text("Fictional rebuild instructions", encoding="utf-8")
    binary = tmp_path / "launcher/runtime/bun/bun.exe"
    monkeypatch.setattr(stage_bun.sys, "platform", "win32")
    staged = []

    def install(_root, _log, *, destination):
        staged.append(destination)
        destination.write_bytes(b"fictional executable")

    monkeypatch.setattr(stage_bun.setup_install, "_install_bun", install)
    monkeypatch.setattr(stage_bun.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="1.3.14+aaaaaaaaa"))
    monkeypatch.setattr(stage_bun.settings, "bun_binary", lambda _root: binary)
    monkeypatch.setattr(stage_bun.urllib.request, "urlopen", lambda *_args, **_kwargs: BytesIO(
        b"" if failure == "notice" else b"Copyright and license permission",
    ))

    def download(_url, path):
        with tarfile.open(path, "w:gz") as archive:
            if failure != "source":
                entry = tarfile.TarInfo("fictional-source/LICENSE")
                entry.size = 7
                archive.addfile(entry, BytesIO(b"License"))

    monkeypatch.setattr(stage_bun, "download", download)
    monkeypatch.setattr(stage_bun, "git_source", lambda _repository, _revision, path: download("", path))
    if failure:
        with pytest.raises(RuntimeError, match="Empty license|Incomplete source"):
            stage_bun.stage(tmp_path)
        return
    stage_bun.stage(tmp_path)
    assert staged == [binary]
    assert {path.name for path in binary.parent.iterdir()} == {"bun.exe", "BUN-LICENSES.txt", "BUN-SOURCE.txt"}
    sources = packaging / "output/bun-sources"
    assert len(list(sources.glob("*-source.tar.gz"))) == 3
    assert (sources / "BUN-REBUILD.md").read_text() == "Fictional rebuild instructions"
    assert json.loads((sources / "bun-sources.json").read_text()) == manifest
    assert "Copyright and license permission" in (binary.parent / "BUN-LICENSES.txt").read_text()
    sums = (sources / "BUN-SHA256SUMS").read_text()
    for line in sums.splitlines():
        expected, name = line.split("  ", 1)
        assert hashlib.sha256((sources / name).read_bytes()).hexdigest() == expected
    assert "BUN-LICENSES.txt" in sums and "webkit-" in sums
    assert "OpenAlma/releases" in (binary.parent / "BUN-SOURCE.txt").read_text()


@pytest.mark.parametrize("wrong_revision", [False, True])
def test_git_source_archives_only_verified_pinned_commit(tmp_path, monkeypatch, wrong_revision):
    git = stage_bun.subprocess
    source = tmp_path / "source"
    source.mkdir()
    git.run(["git", "init", str(source)], check=True, capture_output=True)
    license = source / "LICENSE"
    for text in ("Pinned fictional source", "Later fictional source"):
        license.write_bytes((text + "\n").encode("utf-8"))
        git.run(["git", "-c", "core.autocrlf=false", "add", "LICENSE"], cwd=source, check=True)
        git.run(["git", "-c", "user.name=Test Builder", "-c", "user.email=test@example.invalid",
                 "commit", "-m", "Fictional source"], cwd=source, check=True, capture_output=True)
        if text.startswith("Pinned"):
            pinned = stage_bun.setup_install._git_output(["git", "rev-parse", "HEAD"], source)
    temporary = tmp_path / "bare"
    git.run(["git", "init", "--bare", str(temporary)], check=True, capture_output=True)
    git.run(["git", "config", "core.autocrlf", "true"], cwd=temporary, check=True)
    monkeypatch.setattr(stage_bun.tempfile, "TemporaryDirectory", lambda: nullcontext(str(temporary)))
    if wrong_revision:
        monkeypatch.setattr(stage_bun.setup_install, "_git_output", lambda *_args: "0" * 40)
    target = tmp_path / "source.tar.gz"
    if wrong_revision:
        with pytest.raises(RuntimeError, match="does not match the pinned revision"):
            stage_bun.git_source(str(source), pinned, target)
        assert not target.exists()
        return
    stage_bun.git_source(str(source), pinned, target)
    assert stage_bun.setup_install._git_output(["git", "rev-list", "--count", "FETCH_HEAD"], temporary) == "1"
    with tarfile.open(target, "r:gz") as archive:
        assert archive.getnames() == [pinned, f"{pinned}/LICENSE"]
        assert archive.extractfile(f"{pinned}/LICENSE").read() == b"Pinned fictional source\n"


def test_windows_workflow_stages_runtime_and_keeps_sources_outside_inno_payload():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/windows-installer.yml").read_text()
    inno = (root / "installer/windows/OpenAlma.iss").read_text()
    assert workflow.index("python installer/windows/stage_bun.py") < workflow.index("- name: Build installer")
    assert "path: installer/windows/output/bun-sources/" in workflow
    assert workflow.count("if-no-files-found: error") == 2
    assert 'Source: "..\\..\\launcher\\*"' in inno
    assert "bun-sources" not in inno


@pytest.mark.parametrize("failure", [None, "checksum", "notice"])
def test_rust_runtime_notice_sources_are_verified_and_bundled(tmp_path, monkeypatch, failure):
    packaging = tmp_path / "packaging"
    sources = tmp_path / "sources"
    packaging.mkdir()
    sources.mkdir()
    stream = BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        for path, data in {"LICENSE": b"Fictional license", "COPYRIGHT": b"Fictional attribution"}.items():
            if failure == "notice" and path == "COPYRIGHT":
                continue
            entry = tarfile.TarInfo(f"fixture-runtime-1.0.0/{path}")
            entry.size = len(data)
            archive.addfile(entry, BytesIO(data))
    contents = stream.getvalue()
    manifest = [{"crate": "fixture-runtime", "version": "1.0.0",
                 "checksum": "0" * 64 if failure == "checksum" else hashlib.sha256(contents).hexdigest(),
                 "licenses": ["LICENSE", "COPYRIGHT"]}]
    (packaging / "bun-rust-sources.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(stage_bun, "download", lambda _url, target: target.write_bytes(contents))
    notices = StringIO()
    if failure:
        with pytest.raises(RuntimeError, match="checksum mismatch|Missing Rust license"):
            stage_bun.stage_rust(packaging, sources, notices)
        return
    stage_bun.stage_rust(packaging, sources, notices)
    assert "Fictional license" in notices.getvalue() and "Fictional attribution" in notices.getvalue()
    with tarfile.open(sources / "bun-lolhtml-runtime-source.tar.gz") as archive:
        assert archive.getnames() == ["fixture-runtime-1.0.0.crate"]
        assert archive.extractfile(archive.getmembers()[0]).read() == contents


def test_candidate_installer_version_uses_validated_environment_not_script_interpolation():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/windows-installer.yml"
    job = yaml.safe_load(path.read_text())["jobs"]["build"]
    select = next(step["run"] for step in job["steps"] if step.get("name") == "Select installer version")
    build = next(step["run"] for step in job["steps"] if step.get("name") == "Build installer")
    assert r"\Av[0-9]+\.[0-9]+\.[0-9]+\z" in select
    assert '$env:BUILD_REF_NAME' in select and "'v0.0.0-dev'" in select
    assert '"INSTALLER_VERSION=$tag"' in select
    assert '$tag = $env:INSTALLER_VERSION' in build
    assert '$env:BUILD_REF_TYPE -eq "tag" -or $env:CANDIDATE_VERSION' in build
    assert '${{ inputs.' not in select + build and '${{ github.ref_' not in select + build
