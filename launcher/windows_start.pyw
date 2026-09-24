"""Console-free Windows entry point for the OpenAlma launcher."""
from __future__ import annotations

import os
import sys
import traceback
import winreg

import settings


def _refresh_path() -> None:
    paths = []
    for hive, key in (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
        (winreg.HKEY_CURRENT_USER, r"Environment"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                paths.append(winreg.QueryValueEx(handle, "Path")[0])
        except OSError:
            pass
    if paths:
        os.environ["PATH"] = os.path.expandvars(os.pathsep.join(paths))


def main() -> None:
    settings.LAUNCHER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with settings.LAUNCHER_LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        sys.stdout = sys.stderr = log
        try:
            _refresh_path()
            os.chdir(settings.LAUNCHER_DIR)
            import run

            if "--prepare-update" in sys.argv:
                run.prepare_update()
            elif "--stop-existing" in sys.argv:
                run.stop_existing()
            else:
                run.main()
        except (Exception, SystemExit) as exc:
            traceback.print_exc()
            import ctypes

            message = str(exc) if not isinstance(exc, SystemExit) else (
                "OpenAlma could not start. See the launcher log in Settings for details."
            )
            ctypes.windll.user32.MessageBoxW(None, message, "OpenAlma", 0x10)
            raise


if __name__ == "__main__":
    main()
