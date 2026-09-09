"""Small, durable local store. Each operation owns its SQLite connection."""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("APPLICATION_HELPER_DATA", ROOT / "data"))


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    db = sqlite3.connect(DATA / "application.db", timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


def init():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS documents_kind ON documents(kind);
        """)
    os.chmod(DATA / "application.db", 0o600)


def put(kind, payload, ident=None):
    ident = ident or uuid.uuid4().hex
    previous = get(ident)
    item = {**payload, "id": ident, "kind": kind,
            "created_at": previous["created_at"] if previous else now(), "updated_at": now()}
    with connect() as db:
        db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                   (ident, kind, json.dumps(item, ensure_ascii=False), item["created_at"], item["updated_at"]))
    return item


def get(ident):
    with connect() as db:
        row = db.execute("SELECT payload FROM documents WHERE id=?", (ident,)).fetchone()
    return json.loads(row[0]) if row else None


def all_of(kind, limit=200):
    with connect() as db:
        rows = db.execute("SELECT payload FROM documents WHERE kind=? ORDER BY created_at DESC LIMIT ?",
                          (kind, limit)).fetchall()
    return [json.loads(row[0]) for row in rows]


def delete(ident):
    with connect() as db:
        db.execute("DELETE FROM documents WHERE id=?", (ident,))


def profile():
    return get("profile") or {}


def library(query, limit=8):
    # Text matching uses bound parameters, never SQL assembled from user input.
    words = [w for w in query.split() if w][:8] or [query]
    searchable = "(coalesce(json_extract(payload,'$.title'),'') || ' ' || coalesce(json_extract(payload,'$.content'),'') || ' ' || coalesce(json_extract(payload,'$.url'),''))"
    clauses = " OR ".join(searchable + " LIKE ? ESCAPE '\\'" for _ in words)
    escape = lambda w: w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with connect() as db:
        rows = db.execute(f"SELECT payload FROM documents WHERE kind='evidence' AND ({clauses}) ORDER BY created_at DESC LIMIT ?",
                          [f"%{escape(w)}%" for w in words] + [limit]).fetchall()
    return [json.loads(row[0]) for row in rows]
