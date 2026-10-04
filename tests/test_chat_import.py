import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
import chat_import


def test_source_replay_split_and_atomic_conflict(tmp_path):
    db = tmp_path / "chats.db"
    scope = {"user_id": "TestOwner", "soul_id": "TestSoul", "label": "Replika"}
    raw = [{"id": str(i), "role": "user", "name": "TestSpeaker", "content": f"message {i}",
            "timestamp": f"2025-01-0{i + 1}"} for i in range(5)]
    messages, title, _ = chat_import.normalize_messages(raw)
    preview = chat_import.prepare_upload(db, **scope, messages=messages, history_count=2)
    assert len(preview["messages"]) == 5 and not db.exists()
    first = chat_import.store_upload(db, **scope, messages=messages, history_count=2, title=title)
    replay = chat_import.store_upload(db, **scope, messages=messages, history_count=5)
    assert replay["chat_id"] == first["chat_id"] and replay["messages"] == []
    older, _, _ = chat_import.normalize_messages([
        {"role": "assistant", "name": "TestCompanion", "content": "older history", "timestamp": "2024-01-01"}])
    added = chat_import.store_upload(db, **scope, messages=older, history_count=1)
    assert added["messages"][0]["position"] == 5 and added["history_end_index"] == 6
    conflict, _, _ = chat_import.normalize_messages([
        {"role": "user", "content": "new", "timestamp": "2026-01-01"},
        {"role": "assistant", "name": "TestCompanion", "content": "changed", "timestamp": "2024-01-01"}])
    with pytest.raises(ValueError, match="Conflicting"):
        chat_import.store_upload(db, **scope, messages=conflict, history_count=2)
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT position, historical FROM imported_messages ORDER BY position").fetchall() == [
            (0, 1), (1, 1), (2, 0), (3, 0), (4, 0), (5, 1)]
        assert con.execute("SELECT COUNT(*) FROM imported_chats").fetchone()[0] == 1
    assert chat_import.store_upload(db, **scope, messages=older, history_count=0)["duplicates"] == 1
    other = chat_import.store_upload(db, **{**scope, "soul_id": "OtherSoul"}, messages=messages, history_count=5)
    assert other["chat_id"] != first["chat_id"]


def test_conversion_date_identity_and_metadata(tmp_path):
    raw = [{"id": "a", "meta": {"nature": "Customer", "timestamp": "2025-01-01T00:30:00+02:00"},
            "name": "TestSpeaker", "content": {"type": "text", "text": "hello"}},
           {"id": "b", "meta": {"nature": "Robot", "timestamp": "2025-01-01T00:31:00+02:00"},
            "content": {"type": "text", "text": "hi"}}]
    messages, _, _ = chat_import.normalize_messages(raw)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[0]["timestamp"] == "2024-12-31T22:30:00+00:00"
    assert messages[0]["source_day"] == "2025-01-01"
    assert messages[0]["metadata"] == raw[0] and messages[1]["name"] == ""
    native_preview = chat_import.prepare_upload(tmp_path / "native.db", user_id="TestOwner", soul_id="TestSoul",
                                               label="Replika", messages=messages, history_count=0)
    assert native_preview["messages"][0]["name"] == "TestOwner"
    assert native_preview["messages"][0]["metadata"] == raw[0]
    scope = {"user_id": "TestOwner", "soul_id": "TestSoul", "label": "Nomi"}
    db = tmp_path / "chats.db"
    no_ids, _, _ = chat_import.normalize_messages([{"role": "user", "content": "hi", "timestamp": "2025-01-01T01:00:00+01:00"}])
    chat_import.store_upload(db, **scope, messages=no_ids, history_count=0)
    replay, _, _ = chat_import.normalize_messages([{"role": "user", "content": "hi", "timestamp": "2025-01-01T00:00:00Z"}])
    assert chat_import.store_upload(db, **scope, messages=replay, history_count=1)["duplicates"] == 1
    with pytest.raises(ValueError, match="Ambiguous"):
        chat_import.store_upload(db, **scope, messages=replay * 2, history_count=1)
    dated, _, _ = chat_import.normalize_messages([{"id": str(i), "role": "user", "content": "same",
                                                 "timestamp": "2025-02-01"} for i in range(2)])
    chat_import.store_upload(db, **scope, messages=dated, history_count=2)
    ambiguous, _, _ = chat_import.normalize_messages([{"role": "user", "content": "same", "timestamp": "2025-02-01"}])
    with pytest.raises(ValueError, match="ambiguous"):
        chat_import.store_upload(db, **scope, messages=ambiguous, history_count=0)
    aliases, _, _ = chat_import.normalize_messages([
        {"id": primary, "source_message_id": str(i), "role": "user", "content": f"alias {i}",
         "timestamp": "2025-03-01"} for i, primary in enumerate((None, "", "  ", 0))])
    assert [m["source_message_id"] for m in aliases] == ["0", "1", "2", "0"]
    distinct = aliases[:3]
    added = chat_import.store_upload(db, **{**scope, "label": "Kindroid", "user_id": " TestOwner ", "soul_id": " TestSoul "},
                                     messages=distinct, history_count=3)
    assert added["user_id"] == "TestOwner" and added["soul_id"] == "TestSoul"
    assert chat_import.store_upload(db, **{**scope, "label": "Kindroid"}, messages=distinct, history_count=0)["duplicates"] == 3
    with pytest.raises(ValueError, match="Conflicting messages for ID"):
        chat_import.store_upload(db, **scope, messages=[aliases[0], aliases[3]], history_count=2)


@pytest.mark.parametrize("message", [
    {"role": "user", "content": "hello"},
    {"role": "user", "content": "hello", "timestamp": "2025-01-01T12:00:00"},
    {"role": "user", "content": "hello", "timestamp": "2025-02-30"},
    {"role": "system", "content": "hello", "timestamp": "2025-01-01"},
    {"content": "hello", "meta": {"timestamp": "2025-01-01"}},
])
def test_invalid_input_is_refused(message):
    with pytest.raises(ValueError):
        chat_import.normalize_messages([message])
