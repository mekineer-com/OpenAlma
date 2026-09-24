import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))

import windows_stop  # noqa: E402


def test_windows_stop_leaves_unrelated_port_occupant_alone(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self):
            return b'{"application":"something-else"}'

    monkeypatch.setattr(windows_stop, "_port_open", lambda: True)
    monkeypatch.setattr(windows_stop.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())

    assert windows_stop.stop() == 12


def test_windows_stop_refuses_update_while_services_are_active(monkeypatch):
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

    assert windows_stop.stop(require_update_ready=True) == 11
