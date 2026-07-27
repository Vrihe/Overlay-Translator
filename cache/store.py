"""
cache/store.py — SQLite translation cache and history storage.
"""

import sqlite3
import time
from pathlib import Path

import config

_DB_PATH = Path(config.CACHE_DIR) / "translations.db"


def _get_connection() -> sqlite3.Connection:
    db_path = Path(_DB_PATH)
    if db_path.parent:
        db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='translations'")
        if cursor.fetchone():
            cursor.execute("PRAGMA table_info(translations)")
            cols = {row[1] for row in cursor.fetchall()}
            required = {"source_text", "source_lang", "target_lang", "domain_id", "translated_text", "timestamp"}
            if not required.issubset(cols):
                cursor.execute("DROP TABLE translations")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS translations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_text TEXT NOT NULL,
                source_lang TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                domain_id TEXT NOT NULL DEFAULT 'general',
                translated_text TEXT NOT NULL,
                timestamp REAL NOT NULL,
                UNIQUE(source_text, source_lang, target_lang, domain_id)
            );
            """
        )


def get_cached(
    text: str,
    source_lang: str,
    target_lang: str,
    *,
    domain_id: str = "general",
) -> str | None:
    """Retrieve cached translation if present."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT translated_text FROM translations
            WHERE source_text = ? AND source_lang = ? AND target_lang = ? AND domain_id = ?
            """,
            (text, source_lang, target_lang, domain_id),
        )
        row = cursor.fetchone()
        return row["translated_text"] if row else None
    finally:
        conn.close()


def save_to_cache(
    text: str,
    source_lang: str,
    target_lang: str,
    translation: str,
    *,
    domain_id: str = "general",
) -> None:
    """Save translation entry to SQLite cache."""
    now = time.time()
    conn = _get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO translations
                (source_text, source_lang, target_lang, domain_id, translated_text, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (text, source_lang, target_lang, domain_id, translation, now),
            )
    finally:
        conn.close()


def get_all_history(limit: int = 200) -> list[dict]:
    """Retrieve history records sorted by timestamp descending."""
    conn = _get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, source_text, source_lang, target_lang, domain_id, translated_text, timestamp
            FROM translations
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def clear_history() -> None:
    """Clear all records from history cache."""
    conn = _get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM translations")
    finally:
        conn.close()
