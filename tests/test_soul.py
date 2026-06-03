import sys
from types import SimpleNamespace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
sys.modules.setdefault("yaml", SimpleNamespace(safe_load=lambda _raw: {}, safe_dump=lambda *_a, **_k: ""))

import soul  # noqa: E402


def test_stamp_soul_active_since_insert_or_ignore(tmp_path, monkeypatch):
    state_db = tmp_path / "state.db"
    monkeypatch.setattr(soul, "HERMES_STATE_DB_PATH", state_db)

    soul._stamp_soul_active_since("Siri", now=100.0)
    soul._stamp_soul_active_since("Siri", now=200.0)

    import sqlite3

    con = sqlite3.connect(state_db)
    try:
        rows = con.execute(
            "SELECT soul_id, active_since FROM souls ORDER BY soul_id"
        ).fetchall()
    finally:
        con.close()

    assert rows == [("Siri", 100.0)]
