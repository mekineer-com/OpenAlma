"""Client-owned JSON conversion and append-only SQLite chat sources."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4


def source_path(apps_root: Path) -> Path:
    return apps_root / "openalma" / "imports" / "chats.db"


def list_chats(db_path: Path, *, user_id: str, soul_id: str) -> list[dict]:
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(
            "SELECT chat_id, label, title FROM imported_chats WHERE user_id = ? AND soul_id = ? ORDER BY label",
            (user_id, soul_id),
        )]


def extract_text(item: dict) -> str:
    # Ported from the workspace Replika converter.
    content = item.get("content")
    if isinstance(content, dict):
        content = content.get("text")
    if not isinstance(content, str):
        raise ValueError("Imported messages must contain text")
    return content


def infer_role(item: dict) -> str:
    meta = item.get("meta", {})
    nature = meta.get("nature")
    if nature not in {"Customer", "Robot"}:
        raise ValueError(f"Unsupported Replika speaker: {nature}")
    return "user" if nature == "Customer" else "assistant"


def normalize_date(value: str) -> tuple[str, str, int]:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Every imported message needs an ISO date or timezone-bearing timestamp")
    value = value.strip()
    if len(value) == 10:
        day = date.fromisoformat(value).isoformat()
        dt = datetime.combine(date.fromisoformat(day), datetime.min.time(), UTC)
        return dt.isoformat(), day, int(dt.timestamp() * 1000)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Imported timestamps need an explicit timezone; date-only values are allowed")
    return dt.astimezone(UTC).isoformat(), dt.date().isoformat(), int(dt.timestamp() * 1000)


def normalize_messages(raw: list | dict) -> tuple[list[dict], str | None, dict]:
    title = raw.get("title") if isinstance(raw, dict) else None
    items = raw.get("messages") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("Use a JSON message array or an object containing messages")
    if title is not None and not isinstance(title, str):
        raise ValueError("Chat title must be text")
    out = []
    stats = {"total_items": len(items), "skipped_non_text": 0, "skipped_empty": 0}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Every imported message must be an object")
        meta = item.get("meta")
        native = isinstance(meta, dict) and "role" not in item
        role = infer_role(item) if native else item.get("role")
        if role not in {"user", "assistant"}:
            raise ValueError("Imported roles must be user or assistant")
        original_date = meta.get("timestamp") if native else item.get("timestamp")
        timestamp, source_day, ts_ms = normalize_date(original_date)
        content = item.get("content")
        if native and isinstance(content, dict) and content.get("type", "text") != "text":
            stats["skipped_non_text"] += 1
            continue
        text = extract_text(item).strip()
        if not text:
            stats["skipped_empty"] += 1
            continue
        name = item.get("name", item.get("speaker", ""))
        if not isinstance(name, str):
            raise ValueError("Imported speaker names must be text")
        supplied_id = item.get("id", item.get("source_message_id"))
        if supplied_id is None or isinstance(supplied_id, str) and not supplied_id.strip():
            supplied_id = item.get("source_message_id")
        if supplied_id is not None and (isinstance(supplied_id, bool) or not isinstance(supplied_id, (str, int))):
            raise ValueError("Imported message IDs must be text or integers")
        out.append({
            "role": role, "name": name.strip(), "content": text,
            "timestamp": timestamp, "source_day": source_day, "ts_ms": ts_ms,
            "source_message_id": (str(supplied_id).strip() or None) if supplied_id is not None else None,
            "metadata": item,
        })
    return out, title, stats


def connect(db_path: Path) -> sqlite3.Connection:
    # Connection/transaction pattern from Hermes's web-source store, without its migrations.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=wal")
    con.execute("PRAGMA foreign_keys=on")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS imported_chats (
            chat_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            soul_id TEXT NOT NULL,
            label TEXT NOT NULL,
            title TEXT,
            UNIQUE(user_id, soul_id)
        );
        CREATE TABLE IF NOT EXISTS imported_messages (
            chat_id TEXT NOT NULL REFERENCES imported_chats(chat_id),
            position INTEGER NOT NULL,
            supplied_id TEXT,
            timestamp TEXT NOT NULL,
            source_day TEXT NOT NULL,
            ts_ms INTEGER NOT NULL,
            speaker TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            historical INTEGER NOT NULL CHECK(historical IN (0, 1)),
            raw_json TEXT NOT NULL,
            PRIMARY KEY(chat_id, position),
            UNIQUE(chat_id, supplied_id)
        );
        CREATE INDEX IF NOT EXISTS imported_messages_match
            ON imported_messages(chat_id, timestamp, speaker, role);
        CREATE INDEX IF NOT EXISTS imported_messages_mode
            ON imported_messages(chat_id, historical, position);
        CREATE TABLE IF NOT EXISTS imported_files (
            file_id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL REFERENCES imported_chats(chat_id),
            filename TEXT NOT NULL,
            start_position INTEGER NOT NULL,
            end_position INTEGER NOT NULL
        );
    """)
    return con


def _prepare(con: sqlite3.Connection | None, user_id: str, soul_id: str, label: str,
             messages: list[dict], history_count: int, title: str | None) -> dict:
    user_id, soul_id = user_id.strip(), soul_id.strip()
    if not user_id.strip() or not soul_id.strip() or len(label.split()) != 1:
        raise ValueError("Owner, Soul and a one-word chat-app label are required")
    if type(history_count) is not int or not 0 <= history_count <= len(messages):
        raise ValueError("The history split must be within the imported messages")
    messages = [
        {**m, "name": user_id}
        if "role" not in m["metadata"] and (m["metadata"].get("meta") or {}).get("nature") == "Customer"
        else m for m in messages
    ]
    chat = con.execute(
        "SELECT * FROM imported_chats WHERE user_id = ? AND soul_id = ?",
        (user_id, soul_id),
    ).fetchone() if con is not None else None
    if chat is not None:
        if chat["label"].casefold() != label.casefold():
            raise ValueError("Each Soul can import only one chat app")
        label = chat["label"]
    else:
        label = {"replika": "Replika", "nomi": "Nomi", "kindroid": "Kindroid",
                 "whatsapp": "WhatsApp", "smartglasses": "Smartglasses"}.get(label.casefold(), label)
    chat_id = chat["chat_id"] if chat is not None else uuid4().hex
    position = con.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM imported_messages WHERE chat_id = ?", (chat_id,),
    ).fetchone()[0] if chat is not None else 0
    keys = Counter((m["timestamp"], m["name"], m["role"]) for m in messages)
    for m in messages:
        if m["source_message_id"] is None and keys[(m["timestamp"], m["name"], m["role"])] > 1:
            raise ValueError("Ambiguous messages at the same date/speaker/role; provide message IDs")
    pending, seen_ids = [], {}
    for index, m in enumerate(messages):
        supplied_id = m["source_message_id"]
        if supplied_id is not None:
            identity = (m["timestamp"], m["name"], m["role"], m["content"])
            if supplied_id in seen_ids:
                if seen_ids[supplied_id] != identity:
                    raise ValueError(f"Conflicting messages for ID {supplied_id}")
                continue
            seen_ids[supplied_id] = identity
            matches = con.execute(
                "SELECT position FROM imported_messages WHERE chat_id = ? AND supplied_id = ?",
                (chat_id, supplied_id),
            ).fetchall() if chat is not None else []
        else:
            matches = con.execute(
                "SELECT content FROM imported_messages WHERE chat_id = ? AND timestamp = ? AND speaker = ? AND role = ? LIMIT 2",
                (chat_id, m["timestamp"], m["name"], m["role"]),
            ).fetchall() if chat is not None else []
            if len(matches) > 1 or matches and matches[0]["content"] != m["content"]:
                raise ValueError("Conflicting or ambiguous messages at the same date/speaker/role; provide message IDs")
        if matches:
            continue
        pending.append({**m, "position": position, "input_index": index, "historical": index < history_count})
        position += 1
    return {"chat_id": chat_id, "conversation_id": f"import:dm:{chat_id}",
            "user_id": user_id, "soul_id": soul_id, "label": label,
            "title": chat["title"] if chat is not None else title,
            "messages": pending, "duplicates": len(messages) - len(pending)}


def prepare_upload(db_path: Path, *, user_id: str, soul_id: str, label: str,
                   messages: list[dict], history_count: int, title: str | None = None) -> dict:
    if not db_path.exists():
        return _prepare(None, user_id, soul_id, label.strip(), messages, history_count, title)
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        return _prepare(con, user_id, soul_id, label.strip(), messages, history_count, title)


def store_upload(db_path: Path, *, user_id: str, soul_id: str, label: str,
                 messages: list[dict], history_count: int, title: str | None = None,
                 filename: str = "Chat import") -> dict:
    with closing(connect(db_path)) as con, con:
        con.execute("BEGIN IMMEDIATE")
        upload = _prepare(con, user_id, soul_id, label.strip(), messages, history_count, title)
        con.execute("INSERT OR IGNORE INTO imported_chats VALUES (?, ?, ?, ?, ?)",
                    (upload["chat_id"], upload["user_id"], upload["soul_id"], upload["label"], upload["title"]))
        con.executemany("INSERT INTO imported_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (upload["chat_id"], m["position"], m["source_message_id"], m["timestamp"],
             m["source_day"], m["ts_ms"], m["name"], m["role"], m["content"],
             int(m["historical"]), json.dumps(m["metadata"], ensure_ascii=False))
            for m in upload["messages"]
        ])
        if upload["messages"]:
            con.execute("INSERT INTO imported_files VALUES (?, ?, ?, ?, ?)", (
                uuid4().hex, upload["chat_id"], filename,
                upload["messages"][0]["position"], upload["messages"][-1]["position"] + 1,
            ))
        upload["history_end_index"] = con.execute(
            "SELECT COALESCE(MAX(position) + 1, 0) FROM imported_messages WHERE chat_id = ? AND historical = 1",
            (upload["chat_id"],),
        ).fetchone()[0]
        return upload


def list_files(db_path: Path, *, user_id: str) -> list[dict]:
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        return [dict(row) for row in con.execute(
            "SELECT f.*, c.soul_id, c.label FROM imported_files f JOIN imported_chats c USING(chat_id) "
            "WHERE c.user_id = ? ORDER BY c.soul_id, f.start_position", (user_id,),
        )]


def file_progress(db_path: Path, file: dict, status: dict) -> dict:
    record = status.get("import_state") or {}
    end, cursor = record.get("history_end_index", 0), record.get("memorize_cursor", -1)
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as con:
        eligible, extracted, deferred, current = con.execute(
            "SELECT COUNT(CASE WHEN historical = 1 AND position < ? THEN 1 END), "
            "COUNT(CASE WHEN historical = 1 AND position < ? AND position <= ? THEN 1 END), "
            "COUNT(CASE WHEN historical = 1 AND position >= ? THEN 1 END), "
            "COUNT(CASE WHEN historical = 0 THEN 1 END) FROM imported_messages "
            "WHERE chat_id = ? AND position >= ? AND position < ?",
            (end, end, cursor, end, file["chat_id"], file["start_position"], file["end_position"]),
        ).fetchone()
    # ponytail: import-wide pending IDs; per-file attribution if multi-file initial imports need it.
    pending = bool(eligible and extracted and record.get("pending_segment_ids"))
    failed = bool(eligible and record.get("error"))
    complete = bool(record) and extracted == eligible and not pending and not failed
    return {**file, "eligible": eligible, "extracted": extracted, "deferred": deferred, "current": current,
            "percent": min(99 if pending or failed else 100, int(100 * extracted / eligible)) if eligible else None,
            "dismissible": complete, "running": bool(eligible and not complete and status.get("running")),
            "error": record.get("error") if eligible else None, "pending_consolidation": pending,
            "registered": bool(record)}
