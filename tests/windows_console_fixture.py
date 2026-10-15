"""Native, disposable service-console check; never starts installed applications."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def wait_for(predicate, timeout=10):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= end:
            raise AssertionError("Disposable fixture did not reach its expected state")
        time.sleep(0.05)


def main():
    if os.name != "nt":
        raise SystemExit("Run this fixture on Windows")
    launcher = Path(__file__).resolve().parents[1] / "launcher"
    with tempfile.TemporaryDirectory(prefix="openalma-stop-fixture-") as temporary:
        home = Path(temporary)
        Path.home = classmethod(lambda _cls: home)
        sys.path.insert(0, str(launcher))
        import services

        node = services.shutil.which("node")
        if not node:
            raise RuntimeError("The native fixture needs Node")
        javascript = """import fs from 'node:fs';
const directory=process.env.FIXTURE_HOME;
let stopping=false;
process.on('SIGINT',()=>{
 fs.appendFileSync(directory+'/signals','interrupt\\n');
 if(stopping)return;stopping=true;
 setTimeout(()=>{fs.writeFileSync(directory+'/finished','clean');process.exit(0)},Number(process.env.FIXTURE_DELAY));
});
fs.writeFileSync(directory+'/ready','ready');setInterval(()=>{},100);
"""
        python = """import os,signal,time
from pathlib import Path
p=Path(os.environ['FIXTURE_HOME'])
def finish(*args):
 with (p/'signals').open('a') as out:out.write('interrupt\\n')
 time.sleep(float(os.environ['FIXTURE_DELAY'])/1000)
 (p/'finished').write_text('clean')
 raise SystemExit(0)
signal.signal(signal.SIGINT,finish)
(p/'ready').write_text('ready')
while True:time.sleep(.1)
"""
        cases = [("atomic", node, "scripts/dev-server.js", javascript),
                 ("sillytavern", node, "server.js", javascript),
                 ("channels-daemon", sys.executable, "gateway/daemon.py", python)]
        if len(sys.argv) > 1:
            cases.append(("iris-server", sys.argv[1], "scripts/release-private.mjs", javascript))
        for name, executable, script, text in cases:
            directory = home / name
            path = directory / script
            path.parent.mkdir(parents=True)
            path.write_text(text, encoding="utf-8")
            if executable == node:
                (directory / "package.json").write_text('{"type":"module"}')
            command = ([executable, "-m", "gateway.daemon"] if name == "channels-daemon"
                       else [executable, script])
            spec = services.ServiceSpec(name, name, command, directory, directory / "log", directory / "pid")
            env = {**os.environ, "FIXTURE_HOME": str(directory), "FIXTURE_DELAY": "300"}
            child = services._spawn_background(spec, env)
            spec.pid_path.write_text(str(child.pid))
            try:
                wait_for(lambda: (directory / "ready").exists())
                services.stop(spec)
                services.stop(spec)
                wait_for(lambda: child.poll() is not None)
                wait_for(lambda: name not in services._STOP_THREADS)
                assert child.returncode == 0, (directory / "log").read_text()
                assert (directory / "finished").read_text() == "clean"
                assert (directory / "signals").read_text().count("interrupt") == 1
                print(name, "cooperative cleanup completed; repeated Stop did not resend", flush=True)
            finally:
                if child.poll() is None:
                    services.force_stop(spec)
                    child.wait(timeout=5)

        directory = home / "slow"
        directory.mkdir()
        (directory / "server.js").write_text(javascript)
        (directory / "package.json").write_text('{"type":"module"}')
        spec = services.ServiceSpec("sillytavern", "Slow fixture", [node, "server.js"], directory,
                                    directory / "log", directory / "pid")
        child = services._spawn_background(spec, {**os.environ, "FIXTURE_HOME": str(directory), "FIXTURE_DELAY": "17000"})
        spec.pid_path.write_text(str(child.pid))
        try:
            wait_for(lambda: (directory / "ready").exists())
            helper = launcher / "windows_console.py"
            stale = subprocess.run(
                [sys.executable, str(helper), str(child.pid),
                 str(services.psutil.Process(child.pid).create_time() + 1)],
                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=5,
            )
            assert stale.returncode and child.poll() is None and not (directory / "signals").exists()
            joined = home / "joined"
            joiner = subprocess.Popen(
                [sys._base_executable, "-c",
                 "import ctypes,sys,time;from pathlib import Path;k=ctypes.windll.kernel32;"
                 "k.FreeConsole();assert k.AttachConsole(int(sys.argv[1]));"
                 "k.SetConsoleCtrlHandler(None,True);Path(sys.argv[2]).touch();time.sleep(60)",
                 str(child.pid), str(joined)],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                wait_for(joined.exists)
                try:
                    services.stop(spec)
                except RuntimeError as error:
                    assert "shares its console" in str(error)
                else:
                    raise AssertionError("Shared-console Stop was not refused")
                assert child.poll() is None and not (directory / "signals").exists()
            finally:
                joiner.terminate()
                joiner.wait(timeout=5)
            print("Stale identity and shared console refused without signalling", flush=True)
            services.stop(spec)
            wait_for(lambda: (directory / "signals").exists())
            time.sleep(15.1)
            status = services._stop_status(spec, {"running": True})
            assert child.poll() is None and status["force_stoppable"]
            assert status["status_label"] == "Still finishing…"
            wait_for(lambda: child.poll() is not None)
            assert child.returncode == 0 and (directory / "finished").exists()
            print("15-second threshold did not interrupt delayed cleanup", flush=True)
        finally:
            if child.poll() is None:
                services.force_stop(spec)
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
