"""
cache/store.py — SQLite translation cache and history storage.

Two-level cache:
  L1 — in-memory OrderedDict (LRU, max 128 entries): ~0 ms hit latency.
  L2 — SQLite on disk (WAL mode): ~1-5 ms hit latency.
Save operations populate both levels.
"""

import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path

import config

_DB_PATH = Path(config.CACHE_DIR) / "translations.db"

# ── L1: in-memory LRU cache ───────────────────────────────
# Key: (source_text, source_lang, target_lang, domain_id)
# Evicts least-recently-used entry when size exceeds _MEM_CACHE_SIZE.

_MEM_CACHE_SIZE = 128
_mem_cache: OrderedDict[tuple, str] = OrderedDict()
_mem_cache_lock = threading.Lock()

# C4: Per-thread connection pool.
# Each thread keeps its own connection open permanently.
# SQLite connections are NOT thread-safe; threading.local() ensures isolation.
_thread_local = threading.local()


def _get_connection() -> sqlite3.Connection:
    """Return a persistent per-thread SQLite connection, creating it on first access."""
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        db_path = Path(_DB_PATH)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrent read/write performance
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _init_db(conn)
        _thread_local.conn = conn
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
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_translations_lookup "
            "ON translations (source_text, source_lang, target_lang, domain_id);"
        )


def _evict_old_records(conn: sqlite3.Connection) -> None:
    """C4: Remove oldest rows when the cache exceeds CACHE_MAX_ITEMS."""
    max_items = getattr(config, "CACHE_MAX_ITEMS", 1000)
    conn.execute(
        """
        DELETE FROM translations
        WHERE id IN (
            SELECT id FROM translations
            ORDER BY timestamp ASC
            LIMIT MAX(0, (SELECT COUNT(*) FROM translations) - ?)
        )
        """,
        (max_items,),
    )


def get_cached(
    text: str,
    source_lang: str,
    target_lang: str,
    *,
    domain_id: str = "general",
) -> str | None:
    """Retrieve cached translation if present.

    Checks L1 in-memory LRU cache first (~0 ms), then falls back to L2 SQLite (~1-5 ms).
    """
    key = (text, source_lang, target_lang, domain_id)

    # L1 hit
    with _mem_cache_lock:
        if key in _mem_cache:
            _mem_cache.move_to_end(key)  # mark as recently used
            return _mem_cache[key]

    # L2 hit
    conn = _get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT translated_text FROM translations
        WHERE source_text = ? AND source_lang = ? AND target_lang = ? AND domain_id = ?
        """,
        (text, source_lang, target_lang, domain_id),
    )
    row = cursor.fetchone()
    if row:
        result = row["translated_text"]
        with _mem_cache_lock:
            _mem_cache[key] = result
            if len(_mem_cache) > _MEM_CACHE_SIZE:
                _mem_cache.popitem(last=False)  # evict LRU
        return result
    return None


def save_to_cache(
    text: str,
    source_lang: str,
    target_lang: str,
    translation: str,
    *,
    domain_id: str = "general",
) -> None:
    """Save translation entry to both L1 in-memory and L2 SQLite cache."""
    key = (text, source_lang, target_lang, domain_id)

    # Populate L1
    with _mem_cache_lock:
        _mem_cache[key] = translation
        _mem_cache.move_to_end(key)
        if len(_mem_cache) > _MEM_CACHE_SIZE:
            _mem_cache.popitem(last=False)  # evict LRU

    # Persist to L2
    now = time.time()
    conn = _get_connection()
    with conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO translations
            (source_text, source_lang, target_lang, domain_id, translated_text, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (text, source_lang, target_lang, domain_id, translation, now),
        )
        _evict_old_records(conn)  # C4: keep cache bounded


def warm_cache(limit: int = 50) -> int:
    """Pre-populate the in-memory L1 cache with recent translations from SQLite.

    Returns the number of entries loaded.
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT source_text, source_lang, target_lang, domain_id, translated_text
            FROM translations
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        loaded = 0
        with _mem_cache_lock:
            # Insert in reverse order so the newest items are marked most recently used
            for row in reversed(rows):
                key = (
                    row["source_text"],
                    row["source_lang"],
                    row["target_lang"],
                    row["domain_id"],
                )
                _mem_cache[key] = row["translated_text"]
                _mem_cache.move_to_end(key)
                if len(_mem_cache) > _MEM_CACHE_SIZE:
                    _mem_cache.popitem(last=False)
                loaded += 1
        return loaded
    except Exception as e:
        import logging
        logging.warning(f"Failed to warm cache from history: {e}")
        return 0


def get_all_history(limit: int = 200) -> list[dict]:
    """Retrieve history records sorted by timestamp descending."""
    conn = _get_connection()
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


def clear_history() -> None:
    """Clear all records from history cache."""
    conn = _get_connection()
    with conn:
        conn.execute("DELETE FROM translations")
