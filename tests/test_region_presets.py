"""
tests/test_region_presets.py — Unit tests for region preset storage layer and hotkeys.

Every test redirects the presets file to a temporary directory, avoiding writes
to the real %APPDATA%.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from i18n import set_language
from settings import region_presets
from settings.region_presets import (
    MAX_NAME_LENGTH,
    MAX_PRESETS,
    delete_preset,
    load_presets,
    rename_preset,
    save_preset,
    update_preset_hotkey,
    validate_hotkey,
)
from tests.keyboard_stub import stub_key_names


class _PresetsTestCase(unittest.TestCase):
    """Redirect _PRESETS_FILE to a temporary directory for every test."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.presets_file = Path(tmp.name) / "region_presets.json"
        patcher = mock.patch.object(region_presets, "_PRESETS_FILE", self.presets_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        set_language("ru")  # the assertions match the Russian messages
        self.addCleanup(set_language, None)
        stub_key_names(self)


# ── Basic CRUD ───────────────────────────────────────────


class TestSaveAndLoad(_PresetsTestCase):
    def test_save_and_load_preset(self):
        preset = save_preset("Чат", 100, 200, 500, 600)
        self.assertEqual(preset["name"], "Чат")
        self.assertEqual(preset["x1"], 100)
        self.assertEqual(preset["y1"], 200)
        self.assertEqual(preset["x2"], 500)
        self.assertEqual(preset["y2"], 600)
        self.assertIsNone(preset["hotkey"])
        self.assertIn("id", preset)
        self.assertIn("created_at", preset)

        loaded = load_presets()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["name"], "Чат")
        self.assertEqual(loaded[0]["id"], preset["id"])
        self.assertIsNone(loaded[0]["hotkey"])

    def test_save_with_hotkey(self):
        preset = save_preset("Чат", 100, 200, 500, 600, hotkey="Ctrl+Alt+1")
        self.assertEqual(preset["hotkey"], "ctrl+alt+1")

        loaded = load_presets()
        self.assertEqual(loaded[0]["hotkey"], "ctrl+alt+1")

    def test_save_multiple_presets(self):
        save_preset("Чат", 10, 20, 100, 200)
        save_preset("Квесты", 50, 60, 300, 400)
        save_preset("Торговля", 0, 0, 1920, 1080)

        loaded = load_presets()
        self.assertEqual(len(loaded), 3)
        names = [p["name"] for p in loaded]
        self.assertEqual(names, ["Чат", "Квесты", "Торговля"])

    def test_load_empty(self):
        loaded = load_presets()
        self.assertEqual(loaded, [])


class TestDeletePreset(_PresetsTestCase):
    def test_delete_preset(self):
        p1 = save_preset("Первый", 10, 20, 100, 200)
        p2 = save_preset("Второй", 50, 60, 300, 400)

        delete_preset(p1["id"])

        loaded = load_presets()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], p2["id"])

    def test_delete_nonexistent(self):
        save_preset("Существующий", 10, 20, 100, 200)
        with self.assertRaisesRegex(ValueError, "не найден"):
            delete_preset("non-existent-id")


class TestRenamePreset(_PresetsTestCase):
    def test_rename_preset(self):
        preset = save_preset("Старое имя", 10, 20, 100, 200)
        rename_preset(preset["id"], "Новое имя")

        loaded = load_presets()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["name"], "Новое имя")

    def test_rename_nonexistent(self):
        with self.assertRaisesRegex(ValueError, "не найден"):
            rename_preset("non-existent-id", "Новое имя")

    def test_rename_strips_whitespace(self):
        preset = save_preset("Тест", 10, 20, 100, 200)
        rename_preset(preset["id"], "   Пробелы   ")

        loaded = load_presets()
        self.assertEqual(loaded[0]["name"], "Пробелы")


# ── Hotkey management & validation ───────────────────────


class TestHotkeyManagement(_PresetsTestCase):
    def test_validate_valid_hotkeys(self):
        self.assertEqual(validate_hotkey("Ctrl+Alt+1"), "ctrl+alt+1")
        self.assertEqual(validate_hotkey("f8"), "f8")
        self.assertEqual(validate_hotkey("ctrl+shift+1"), "ctrl+shift+1")
        self.assertIsNone(validate_hotkey(None))
        self.assertIsNone(validate_hotkey(""))
        self.assertIsNone(validate_hotkey("   "))

    def test_validate_invalid_syntax(self):
        with self.assertRaisesRegex(ValueError, "Некорректная комбинация"):
            validate_hotkey("not_a_key_xyz_123")

    def test_validate_collision_with_app_hotkey(self):
        import config

        app_hk = config.HOTKEY
        with self.assertRaisesRegex(ValueError, "уже занята для основного перевода"):
            validate_hotkey(app_hk.upper())

    def test_validate_collision_with_settings_hotkey(self):
        import config

        with mock.patch.object(
            type(config), "SETTINGS_HOTKEY", new_callable=mock.PropertyMock, return_value="ctrl+shift+o"
        ):
            with self.assertRaisesRegex(ValueError, "уже занята для окна настроек"):
                validate_hotkey("ctrl+shift+o")

    def test_validate_collision_with_other_preset(self):
        save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+1")
        with self.assertRaisesRegex(ValueError, "уже назначена для пресета"):
            validate_hotkey("ctrl+alt+1")

    def test_validate_self_collision_allowed(self):
        p = save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+1")
        # Validating the same hotkey for the same preset should not raise
        result = validate_hotkey("ctrl+alt+1", current_preset_id=p["id"])
        self.assertEqual(result, "ctrl+alt+1")

    def test_update_preset_hotkey(self):
        p = save_preset("Один", 10, 20, 100, 200)
        updated = update_preset_hotkey(p["id"], "Ctrl+Alt+2")
        self.assertEqual(updated["hotkey"], "ctrl+alt+2")

        loaded = load_presets()
        self.assertEqual(loaded[0]["hotkey"], "ctrl+alt+2")

    def test_clear_preset_hotkey(self):
        p = save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+3")
        update_preset_hotkey(p["id"], None)

        loaded = load_presets()
        self.assertIsNone(loaded[0]["hotkey"])

    def test_update_preset_hotkey_nonexistent(self):
        with self.assertRaisesRegex(ValueError, "не найден"):
            update_preset_hotkey("fake-id", "ctrl+alt+4")


# ── Validation: name ─────────────────────────────────────


class TestNameValidation(_PresetsTestCase):
    def test_invalid_name_empty(self):
        with self.assertRaisesRegex(ValueError, "пустым"):
            save_preset("", 10, 20, 100, 200)

    def test_invalid_name_whitespace_only(self):
        with self.assertRaisesRegex(ValueError, "пустым"):
            save_preset("   ", 10, 20, 100, 200)

    def test_invalid_name_too_long(self):
        long_name = "А" * (MAX_NAME_LENGTH + 1)
        with self.assertRaisesRegex(ValueError, "длиннее"):
            save_preset(long_name, 10, 20, 100, 200)

    def test_name_exactly_max_length(self):
        name = "Б" * MAX_NAME_LENGTH
        preset = save_preset(name, 10, 20, 100, 200)
        self.assertEqual(preset["name"], name)

    def test_name_strips_whitespace(self):
        preset = save_preset("  Тест  ", 10, 20, 100, 200)
        self.assertEqual(preset["name"], "Тест")

    def test_rename_invalid_name_empty(self):
        preset = save_preset("Тест", 10, 20, 100, 200)
        with self.assertRaisesRegex(ValueError, "пустым"):
            rename_preset(preset["id"], "")

    def test_rename_invalid_name_too_long(self):
        preset = save_preset("Тест", 10, 20, 100, 200)
        with self.assertRaisesRegex(ValueError, "длиннее"):
            rename_preset(preset["id"], "X" * (MAX_NAME_LENGTH + 1))


# ── Validation: coordinates ──────────────────────────────


class TestCoordinateValidation(_PresetsTestCase):
    def test_invalid_x1_ge_x2(self):
        with self.assertRaisesRegex(ValueError, "x1"):
            save_preset("Тест", 500, 20, 500, 200)

    def test_invalid_x1_gt_x2(self):
        with self.assertRaisesRegex(ValueError, "x1"):
            save_preset("Тест", 600, 20, 500, 200)

    def test_invalid_y1_ge_y2(self):
        with self.assertRaisesRegex(ValueError, "y1"):
            save_preset("Тест", 10, 200, 100, 200)

    def test_invalid_y1_gt_y2(self):
        with self.assertRaisesRegex(ValueError, "y1"):
            save_preset("Тест", 10, 300, 100, 200)

    def test_negative_coordinates_valid(self):
        """Negative coordinates are valid (multi-monitor setups)."""
        preset = save_preset("Мульти-монитор", -1920, -500, -100, 0)
        self.assertEqual(preset["x1"], -1920)
        self.assertEqual(preset["y2"], 0)


# ── Validation: max presets limit ────────────────────────


class TestMaxPresetsLimit(_PresetsTestCase):
    def test_max_presets_ok(self):
        for i in range(MAX_PRESETS):
            save_preset(f"Пресет {i}", 0, 0, 100 + i, 100 + i)
        self.assertEqual(len(load_presets()), MAX_PRESETS)

    def test_max_presets_exceeded(self):
        for i in range(MAX_PRESETS):
            save_preset(f"Пресет {i}", 0, 0, 100 + i, 100 + i)
        with self.assertRaisesRegex(ValueError, "лимит"):
            save_preset("Лишний", 0, 0, 999, 999)


# ── Persistence & Backwards Compatibility ────────────────


class TestPersistence(_PresetsTestCase):
    def test_persistence_across_reload(self):
        """Presets survive a fresh load_presets() call (reads from disk)."""
        save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+1")
        save_preset("Два", 50, 60, 300, 400)

        loaded = load_presets()
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0]["name"], "Один")
        self.assertEqual(loaded[0]["hotkey"], "ctrl+alt+1")
        self.assertEqual(loaded[1]["name"], "Два")
        self.assertIsNone(loaded[1]["hotkey"])

    def test_legacy_preset_without_hotkey_key(self):
        """Older JSON format without 'hotkey' key loads gracefully with hotkey=None."""
        legacy_data = [
            {
                "id": "old-1",
                "name": "Старый",
                "x1": 10,
                "y1": 20,
                "x2": 100,
                "y2": 200,
                "created_at": "2026-01-01T00:00:00Z",
            }
        ]
        self.presets_file.write_text(json.dumps(legacy_data), encoding="utf-8")
        loaded = load_presets()
        self.assertEqual(len(loaded), 1)
        self.assertIsNone(loaded[0]["hotkey"])

    def test_corrupted_file_returns_empty(self):
        """Corrupted JSON file doesn't crash, returns empty list."""
        self.presets_file.write_text("{invalid json!!!", encoding="utf-8")
        loaded = load_presets()
        self.assertEqual(loaded, [])

    def test_non_list_root_returns_empty(self):
        """JSON file with wrong root type returns empty list."""
        self.presets_file.write_text('{"not": "a list"}', encoding="utf-8")
        loaded = load_presets()
        self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main()
