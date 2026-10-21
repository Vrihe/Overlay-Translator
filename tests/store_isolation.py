"""
tests/store_isolation.py — point cache/store at a throw-away SQLite file for one test.

store keeps one SQLite connection per thread and an in-memory L1 cache, so patching
``_DB_PATH`` alone is not enough: a connection opened earlier would still write the
test rows into the user's real history. This drops both for the test and restores
them afterwards.
"""

import os
import tempfile
import unittest
from unittest import mock

from cache import store


def isolate_store(test: unittest.TestCase) -> None:
    """Call from setUp: the test's cache reads/writes go to a temporary DB."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)  # runs last: after the connection below is closed

    saved_conn = getattr(store._thread_local, "conn", None)
    with store._mem_cache_lock:
        saved_mem = store._mem_cache.copy()
        store._mem_cache.clear()
    store._thread_local.conn = None

    def restore():
        conn = getattr(store._thread_local, "conn", None)
        if conn is not None:
            conn.close()  # Windows cannot delete an open DB file
        store._thread_local.conn = saved_conn
        with store._mem_cache_lock:
            store._mem_cache.clear()
            store._mem_cache.update(saved_mem)

    test.addCleanup(restore)
    patcher = mock.patch.object(store, "_DB_PATH", os.path.join(tmp.name, "translations.db"))
    patcher.start()
    test.addCleanup(patcher.stop)
