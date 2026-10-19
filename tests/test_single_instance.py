"""Tests for the Windows single-instance guard (single_instance.py)."""

import os
import sys
import threading
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from single_instance import SingleInstance


@unittest.skipUnless(sys.platform == "win32", "Windows kernel objects only")
class TestSingleInstance(unittest.TestCase):
    def setUp(self):
        # Unique name per test so a running app (or another test) never interferes.
        self.name = f"TranslatorOverlay.Test.{uuid.uuid4().hex}"

    def test_first_instance_acquires(self):
        self.assertTrue(SingleInstance(self.name).acquire())

    def test_second_instance_is_rejected(self):
        first = SingleInstance(self.name)
        self.assertTrue(first.acquire())
        self.assertFalse(SingleInstance(self.name).acquire())

    def test_notify_without_running_instance_fails(self):
        self.assertFalse(SingleInstance(self.name).notify_existing())

    def test_notify_triggers_listener(self):
        first = SingleInstance(self.name)
        self.assertTrue(first.acquire())
        activated = threading.Event()
        first.listen(activated.set)

        second = SingleInstance(self.name)
        self.assertFalse(second.acquire())
        self.assertTrue(second.notify_existing())
        self.assertTrue(activated.wait(timeout=5))

    def test_listener_fires_on_every_launch(self):
        first = SingleInstance(self.name)
        first.acquire()
        calls = []
        fired = threading.Event()

        def on_activate():
            calls.append(1)
            fired.set()

        first.listen(on_activate)
        for _ in range(2):
            fired.clear()
            self.assertTrue(SingleInstance(self.name).notify_existing())
            self.assertTrue(fired.wait(timeout=5))
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
