import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import windows_stop  # noqa: E402
import pytest


@pytest.mark.parametrize("registered,uninstall_log", [(False, False), (True, False), (False, True)])
def test_first_install_retry_preserves_damaged_install_checks(tmp_path, monkeypatch, registered, uninstall_log):
    venv = tmp_path / "launcher/.venv/Scripts/pythonw.exe"
    venv.parent.mkdir(parents=True)
    venv.touch()
    if uninstall_log:
        (tmp_path / "unins007.dat").touch()
    monkeypatch.setattr(windows_stop, "_port_open", lambda: False)
    expected = 14 if registered or uninstall_log else 0
    assert windows_stop.stop(True, install_dir=tmp_path, registered_install=registered) == expected
    (tmp_path / "launcher/windows_start.pyw").touch()
    assert windows_stop.stop(True, install_dir=tmp_path, registered_install=registered) == 0


def test_windows_stop_leaves_unrelated_port_occupant_alone(tmp_path, monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"application":"something-else"}'

    monkeypatch.setattr(windows_stop, "_port_open", lambda: True)
    monkeypatch.setattr(windows_stop.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    assert windows_stop.stop(install_dir=tmp_path) == 12


def test_windows_stop_refuses_update_while_services_are_active(tmp_path, monkeypatch):
    responses = iter((
        b'{"application":"openalma-launcher","protocol":1}',
        b'{"application":"openalma-launcher","active_services":["memU Server"]}',
    ))

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return next(responses)

    monkeypatch.setattr(windows_stop, "_port_open", lambda: True)
    monkeypatch.setattr(windows_stop.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    assert windows_stop.stop(require_update_ready=True, install_dir=tmp_path) == 11
