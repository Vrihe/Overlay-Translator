"""
tests/keyboard_stub.py — let hotkey validation run where the keyboard library cannot.

On Linux ``keyboard.parse_hotkey`` needs root: mapping a key name to scan codes reads
the input devices. Tests that validate hotkey strings call ``stub_key_names(self)``
from setUp; off Windows it replaces the name → scan code lookup with a table of
the key names the app uses, so the validation logic still runs. On Windows the
real library is used.
"""

import sys
import unittest
from unittest import mock

_MODIFIERS = {"ctrl", "alt", "shift", "windows", "left windows", "right windows", "alt gr"}
_NAMED = {"space", "enter", "tab", "esc", "backspace", "delete", "insert", "home", "end", "page up", "page down"}
_NAMED |= {"up", "down", "left", "right", "print screen", "pause", "caps lock", "num lock", "scroll lock"}
_NAMED |= {f"f{i}" for i in range(1, 25)}


def _key_to_scan_codes(key, error_if_missing=True):
    name = str(key).strip().lower()
    if not name:
        raise ValueError(f"Can only normalize non-empty string names. Unexpected {key!r}")
    if len(name) == 1 or name in _MODIFIERS or name in _NAMED:
        return (abs(hash(name)) % 1000,)
    raise ValueError(f"Key {key!r} is not mapped to any known key.")


def stub_key_names(test: unittest.TestCase) -> None:
    """Call from setUp: off Windows, key names resolve without touching input devices."""
    if sys.platform == "win32":
        return
    import keyboard

    patcher = mock.patch.object(keyboard, "key_to_scan_codes", _key_to_scan_codes)
    patcher.start()
    test.addCleanup(patcher.stop)
