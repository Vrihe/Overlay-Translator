"""
tests/test_cache_store.py — the two-level translation cache in cache/store.py.

Covers:
  • save/get round trip, keys separated by languages and domain, replace on save;
  • L1 (in-memory LRU): served without SQLite, bounded, refilled from L2 and warm_cache();
  • L2 (SQLite): bounded by CACHE_MAX_ITEMS (oldest rows go first), history order,
    clear_history(), and an old table without the required columns being rebuilt.
Every test writes to a temporary database (tests/store_isolation.py).
"""

import sqlite3
import threading
import unittest
from unittest import mock

import config
from cache import store
from tests.store_isolation import isolate_store


def _clear_l1():
    with store._mem_cache_lock:
        store._mem_cache.clear()


class TestRoundTrip(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_save_then_get(self):
        self.assertIsNone(store.get_cached("hello", "en", "ru"))
        store.save_to_cache("hello", "en", "ru", "привет")
        self.assertEqual(store.get_cached("hello", "en", "ru"), "привет")

    def test_key_includes_languages_and_domain(self):
        store.save_to_cache("hello", "en", "ru", "привет", domain_id="games")
        _clear_l1()
        self.assertEqual(store.get_cached("hello", "en", "ru", domain_id="games"), "привет")
        self.assertIsNone(store.get_cached("hello", "en", "ru"))
        self.assertIsNone(store.get_cached("hello", "en", "uk", domain_id="games"))
        self.assertIsNone(store.get_cached("hello", "_auto", "ru", domain_id="games"))

    def test_saving_again_replaces_the_translation(self):
        store.save_to_cache("hello", "en", "ru", "привет")
        store.save_to_cache("hello", "en", "ru", "здравствуйте")
        _clear_l1()
        self.assertEqual(store.get_cached("hello", "en", "ru"), "здравствуйте")
        self.assertEqual(len(store.get_all_history()), 1)


class TestMemoryCache(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_l1_hit_does_not_touch_sqlite(self):
        store.save_to_cache("hello", "en", "ru", "привет")
        with mock.patch.object(store, "_get_connection", side_effect=AssertionError("SQLite used")):
            self.assertEqual(store.get_cached("hello", "en", "ru"), "привет")

    def test_l1_is_bounded_and_evicts_the_least_recently_used(self):
        with mock.patch.object(store, "_MEM_CACHE_SIZE", 2):
            store.save_to_cache("a", "en", "ru", "A")
            store.save_to_cache("b", "en", "ru", "B")
            store.get_cached("a", "en", "ru")  # "a" is now the most recent
            store.save_to_cache("c", "en", "ru", "C")
        keys = [key[0] for key in store._mem_cache]
        self.assertEqual(keys, ["a", "c"])
        self.assertEqual(store.get_cached("b", "en", "ru"), "B", "evicted from L1, still in SQLite")

    def test_l2_hit_refills_l1(self):
        store.save_to_cache("hello", "en", "ru", "привет")
        _clear_l1()
        store.get_cached("hello", "en", "ru")
        self.assertIn(("hello", "en", "ru", "general"), store._mem_cache)

    def test_warm_cache_loads_the_newest_rows(self):
        with mock.patch("cache.store.time.time", side_effect=[1.0, 2.0, 3.0]):
            for text in ("old", "mid", "new"):
                store.save_to_cache(text, "en", "ru", text.upper())
        _clear_l1()
        self.assertEqual(store.warm_cache(limit=2), 2)
        self.assertEqual([key[0] for key in store._mem_cache], ["mid", "new"], "newest is most recently used")

    def test_warm_cache_never_raises(self):
        with mock.patch.object(store, "_get_connection", side_effect=sqlite3.OperationalError("locked")):
            self.assertEqual(store.warm_cache(), 0)


class TestDiskCache(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_sqlite_is_bounded_and_drops_the_oldest(self):
        with (
            mock.patch.object(type(config), "CACHE_MAX_ITEMS", 3),
            mock.patch("cache.store.time.time", side_effect=[float(i) for i in range(5)]),
        ):
            for i in range(5):
                store.save_to_cache(f"t{i}", "en", "ru", f"r{i}")
        self.assertEqual([row["source_text"] for row in store.get_all_history()], ["t4", "t3", "t2"])

    def test_history_is_newest_first_and_limited(self):
        with mock.patch("cache.store.time.time", side_effect=[10.0, 30.0, 20.0]):
            for text in ("a", "b", "c"):
                store.save_to_cache(text, "en", "ru", text)
        history = store.get_all_history(limit=2)
        self.assertEqual([row["source_text"] for row in history], ["b", "c"])
        self.assertEqual(
            set(history[0]),
            {"id", "source_text", "source_lang", "target_lang", "domain_id", "translated_text", "timestamp"},
        )

    def test_clear_history(self):
        store.save_to_cache("hello", "en", "ru", "привет")
        store.clear_history()
        self.assertEqual(store.get_all_history(), [])
        self.assertIsNone(store.get_cached("hello", "en", "ru"))

    def test_old_schema_is_rebuilt(self):
        conn = sqlite3.connect(store._DB_PATH)
        with conn:
            conn.execute("CREATE TABLE translations (id INTEGER PRIMARY KEY, source_text TEXT, result TEXT)")
            conn.execute("INSERT INTO translations (source_text, result) VALUES ('x', 'y')")
        conn.close()

        store.save_to_cache("hello", "en", "ru", "привет")
        self.assertEqual([row["source_text"] for row in store.get_all_history()], ["hello"])

    def test_current_schema_is_kept(self):
        store.save_to_cache("hello", "en", "ru", "привет")
        store._init_db(store._get_connection())  # e.g. the next app start
        self.assertEqual(len(store.get_all_history()), 1)


class TestCloseConnection(unittest.TestCase):
    def setUp(self):
        isolate_store(self)

    def test_worker_thread_closes_its_connection(self):
        seen = {}

        def worker():
            store.save_to_cache("hello", "en", "ru", "привет")
            conn = store._thread_local.conn
            store.close_connection()
            seen["left"] = store._thread_local.conn
            try:
                conn.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                seen["closed"] = True

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(seen, {"left": None, "closed": True})

    def test_next_call_reopens(self):
        store.save_to_cache("hello", "en", "ru", "привет")
        store.close_connection()
        _clear_l1()
        self.assertEqual(store.get_cached("hello", "en", "ru"), "привет")


if __name__ == "__main__":
    unittest.main()
