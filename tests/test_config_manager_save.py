"""
tests/test_config_manager_save.py — settings.json is written atomically: a failed
write leaves the previous file intact instead of a broken one read back as defaults.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from settings import config_manager


class TestSaveConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "settings.json"
        for patcher in (
            mock.patch.object(config_manager, "_CONFIG_FILE", self.path),
            mock.patch.object(config_manager, "_cache", None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_writes_the_file_without_leftovers(self):
        config_manager.save_config({"popup_timeout_sec": 5})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["popup_timeout_sec"], 5)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["settings.json"])

    def test_failed_write_keeps_the_previous_file(self):
        config_manager.save_config({"popup_timeout_sec": 5})
        with mock.patch.object(config_manager.json, "dump", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                config_manager.save_config({"popup_timeout_sec": 7})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["popup_timeout_sec"], 5)


if __name__ == "__main__":
    unittest.main()
