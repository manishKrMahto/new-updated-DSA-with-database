"""
SQLite persistence for chat sessions and messages.
History survives server restarts and page refreshes.
"""
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from settings import CHAT_DB_PATH


def _ensure_data_dir():
    CHAT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _get_connection():
    _ensure_data_dir()
    return sqlite3.connect(str(CHAT_DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES)


def init_db():
    """Create tables if they don't exist."""
    conn = _get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                last_message TEXT NOT NULL DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions (id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id)")
        conn.commit()
    finally:
        conn.close()


def get_or_create_session(session_id=None):
    """Return existing session id or create a new one. Always returns a valid session id."""
    conn = _get_connection()
    try:
        if session_id:
            row = conn.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row:
                return row[0]
        new_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat() + "Z"
        conn.execute(
            "INSERT INTO sessions (id, created_at, last_message) VALUES (?, ?, ?)",
            (new_id, now, ""),
        )
        conn.commit()
        return new_id
    finally:
        conn.close()


def add_message(session_id, role, content):
    """Append a message to a session."""
    conn = _get_connection()
    try:
        now = datetime.utcnow().isoformat() + "Z"
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, now),
        )
        conn.commit()
    finally:
        conn.close()


def update_session_last_message(session_id, last_message):
    """Update the last_message preview for a session."""
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE sessions SET last_message = ? WHERE id = ?",
            (last_message[:500], session_id),  # limit length
        )
        conn.commit()
    finally:
        conn.close()


def get_sessions():
    """Return list of sessions, newest first: [{ id, last_message, created_at }, ...]."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT id, last_message, created_at FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [
            {"id": r[0], "last_message": r[1] or "New conversation", "created_at": r[2]}
            for r in rows
        ]
    finally:
        conn.close()


def session_exists(session_id):
    """Return True if the session exists."""
    conn = _get_connection()
    try:
        row = conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def get_messages(session_id):
    """Return list of messages for a session: [{ role, content }, ...]."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]
    finally:
        conn.close()
