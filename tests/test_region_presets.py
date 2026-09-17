"""
tests/test_region_presets.py — Unit tests for region preset storage layer and hotkeys.

Uses tmp_path / monkeypatch to redirect the presets file to a temporary
directory, avoiding writes to the real %APPDATA%.
"""

import json
import pytest
from pathlib import Path

from settings import region_presets
from settings.region_presets import (
    load_presets,
    save_preset,
    delete_preset,
    rename_preset,
    update_preset_hotkey,
    validate_hotkey,
    MAX_PRESETS,
    MAX_NAME_LENGTH,
)


@pytest.fixture(autouse=True)
def _isolated_presets_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect _PRESETS_FILE to a temporary directory for every test."""
    fake_file = tmp_path / "region_presets.json"
    monkeypatch.setattr(region_presets, "_PRESETS_FILE", fake_file)
    yield fake_file


# ── Basic CRUD ───────────────────────────────────────────


class TestSaveAndLoad:
    def test_save_and_load_preset(self):
        preset = save_preset("Чат", 100, 200, 500, 600)
        assert preset["name"] == "Чат"
        assert preset["x1"] == 100
        assert preset["y1"] == 200
        assert preset["x2"] == 500
        assert preset["y2"] == 600
        assert preset["hotkey"] is None
        assert "id" in preset
        assert "created_at" in preset

        loaded = load_presets()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "Чат"
        assert loaded[0]["id"] == preset["id"]
        assert loaded[0]["hotkey"] is None

    def test_save_with_hotkey(self):
        preset = save_preset("Чат", 100, 200, 500, 600, hotkey="Ctrl+Alt+1")
        assert preset["hotkey"] == "ctrl+alt+1"

        loaded = load_presets()
        assert loaded[0]["hotkey"] == "ctrl+alt+1"

    def test_save_multiple_presets(self):
        save_preset("Чат", 10, 20, 100, 200)
        save_preset("Квесты", 50, 60, 300, 400)
        save_preset("Торговля", 0, 0, 1920, 1080)

        loaded = load_presets()
        assert len(loaded) == 3
        names = [p["name"] for p in loaded]
        assert names == ["Чат", "Квесты", "Торговля"]

    def test_load_empty(self):
        loaded = load_presets()
        assert loaded == []


class TestDeletePreset:
    def test_delete_preset(self):
        p1 = save_preset("Первый", 10, 20, 100, 200)
        p2 = save_preset("Второй", 50, 60, 300, 400)

        delete_preset(p1["id"])

        loaded = load_presets()
        assert len(loaded) == 1
        assert loaded[0]["id"] == p2["id"]

    def test_delete_nonexistent(self):
        save_preset("Существующий", 10, 20, 100, 200)
        with pytest.raises(ValueError, match="не найден"):
            delete_preset("non-existent-id")


class TestRenamePreset:
    def test_rename_preset(self):
        preset = save_preset("Старое имя", 10, 20, 100, 200)
        rename_preset(preset["id"], "Новое имя")

        loaded = load_presets()
        assert len(loaded) == 1
        assert loaded[0]["name"] == "Новое имя"

    def test_rename_nonexistent(self):
        with pytest.raises(ValueError, match="не найден"):
            rename_preset("non-existent-id", "Новое имя")

    def test_rename_strips_whitespace(self):
        preset = save_preset("Тест", 10, 20, 100, 200)
        rename_preset(preset["id"], "   Пробелы   ")

        loaded = load_presets()
        assert loaded[0]["name"] == "Пробелы"


# ── Hotkey management & validation ───────────────────────


class TestHotkeyManagement:
    def test_validate_valid_hotkeys(self):
        assert validate_hotkey("Ctrl+Alt+1") == "ctrl+alt+1"
        assert validate_hotkey("f8") == "f8"
        assert validate_hotkey("ctrl+shift+1") == "ctrl+shift+1"
        assert validate_hotkey(None) is None
        assert validate_hotkey("") is None
        assert validate_hotkey("   ") is None

    def test_validate_invalid_syntax(self):
        with pytest.raises(ValueError, match="Некорректная комбинация"):
            validate_hotkey("not_a_key_xyz_123")

    def test_validate_collision_with_app_hotkey(self):
        import config
        app_hk = config.HOTKEY
        with pytest.raises(ValueError, match="уже занята для основного перевода"):
            validate_hotkey(app_hk.upper())

    def test_validate_collision_with_settings_hotkey(self, monkeypatch):
        import config
        monkeypatch.setattr(config, "SETTINGS_HOTKEY", "ctrl+shift+o")
        with pytest.raises(ValueError, match="уже занята для окна настроек"):
            validate_hotkey("ctrl+shift+o")

    def test_validate_collision_with_other_preset(self):
        save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+1")
        with pytest.raises(ValueError, match="уже назначена для пресета"):
            validate_hotkey("ctrl+alt+1")

    def test_validate_self_collision_allowed(self):
        p = save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+1")
        # Validating the same hotkey for the same preset should not raise
        result = validate_hotkey("ctrl+alt+1", current_preset_id=p["id"])
        assert result == "ctrl+alt+1"

    def test_update_preset_hotkey(self):
        p = save_preset("Один", 10, 20, 100, 200)
        updated = update_preset_hotkey(p["id"], "Ctrl+Alt+2")
        assert updated["hotkey"] == "ctrl+alt+2"

        loaded = load_presets()
        assert loaded[0]["hotkey"] == "ctrl+alt+2"

    def test_clear_preset_hotkey(self):
        p = save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+3")
        update_preset_hotkey(p["id"], None)

        loaded = load_presets()
        assert loaded[0]["hotkey"] is None

    def test_update_preset_hotkey_nonexistent(self):
        with pytest.raises(ValueError, match="не найден"):
            update_preset_hotkey("fake-id", "ctrl+alt+4")


# ── Validation: name ─────────────────────────────────────


class TestNameValidation:
    def test_invalid_name_empty(self):
        with pytest.raises(ValueError, match="пустым"):
            save_preset("", 10, 20, 100, 200)

    def test_invalid_name_whitespace_only(self):
        with pytest.raises(ValueError, match="пустым"):
            save_preset("   ", 10, 20, 100, 200)

    def test_invalid_name_too_long(self):
        long_name = "А" * (MAX_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="длиннее"):
            save_preset(long_name, 10, 20, 100, 200)

    def test_name_exactly_max_length(self):
        name = "Б" * MAX_NAME_LENGTH
        preset = save_preset(name, 10, 20, 100, 200)
        assert preset["name"] == name

    def test_name_strips_whitespace(self):
        preset = save_preset("  Тест  ", 10, 20, 100, 200)
        assert preset["name"] == "Тест"

    def test_rename_invalid_name_empty(self):
        preset = save_preset("Тест", 10, 20, 100, 200)
        with pytest.raises(ValueError, match="пустым"):
            rename_preset(preset["id"], "")

    def test_rename_invalid_name_too_long(self):
        preset = save_preset("Тест", 10, 20, 100, 200)
        with pytest.raises(ValueError, match="длиннее"):
            rename_preset(preset["id"], "X" * (MAX_NAME_LENGTH + 1))


# ── Validation: coordinates ──────────────────────────────


class TestCoordinateValidation:
    def test_invalid_x1_ge_x2(self):
        with pytest.raises(ValueError, match="x1"):
            save_preset("Тест", 500, 20, 500, 200)

    def test_invalid_x1_gt_x2(self):
        with pytest.raises(ValueError, match="x1"):
            save_preset("Тест", 600, 20, 500, 200)

    def test_invalid_y1_ge_y2(self):
        with pytest.raises(ValueError, match="y1"):
            save_preset("Тест", 10, 200, 100, 200)

    def test_invalid_y1_gt_y2(self):
        with pytest.raises(ValueError, match="y1"):
            save_preset("Тест", 10, 300, 100, 200)

    def test_negative_coordinates_valid(self):
        """Negative coordinates are valid (multi-monitor setups)."""
        preset = save_preset("Мульти-монитор", -1920, -500, -100, 0)
        assert preset["x1"] == -1920
        assert preset["y2"] == 0


# ── Validation: max presets limit ────────────────────────


class TestMaxPresetsLimit:
    def test_max_presets_ok(self):
        for i in range(MAX_PRESETS):
            save_preset(f"Пресет {i}", 0, 0, 100 + i, 100 + i)
        assert len(load_presets()) == MAX_PRESETS

    def test_max_presets_exceeded(self):
        for i in range(MAX_PRESETS):
            save_preset(f"Пресет {i}", 0, 0, 100 + i, 100 + i)
        with pytest.raises(ValueError, match="лимит"):
            save_preset("Лишний", 0, 0, 999, 999)


# ── Persistence & Backwards Compatibility ────────────────


class TestPersistence:
    def test_persistence_across_reload(self, _isolated_presets_file):
        """Presets survive a fresh load_presets() call (reads from disk)."""
        save_preset("Один", 10, 20, 100, 200, hotkey="ctrl+alt+1")
        save_preset("Два", 50, 60, 300, 400)

        loaded = load_presets()
        assert len(loaded) == 2
        assert loaded[0]["name"] == "Один"
        assert loaded[0]["hotkey"] == "ctrl+alt+1"
        assert loaded[1]["name"] == "Два"
        assert loaded[1]["hotkey"] is None

    def test_legacy_preset_without_hotkey_key(self, _isolated_presets_file):
        """Older JSON format without 'hotkey' key loads gracefully with hotkey=None."""
        legacy_data = [
            {"id": "old-1", "name": "Старый", "x1": 10, "y1": 20, "x2": 100, "y2": 200, "created_at": "2026-01-01T00:00:00Z"}
        ]
        _isolated_presets_file.write_text(json.dumps(legacy_data), encoding="utf-8")
        loaded = load_presets()
        assert len(loaded) == 1
        assert loaded[0]["hotkey"] is None

    def test_corrupted_file_returns_empty(self, _isolated_presets_file):
        """Corrupted JSON file doesn't crash, returns empty list."""
        _isolated_presets_file.write_text("{invalid json!!!", encoding="utf-8")
        loaded = load_presets()
        assert loaded == []

    def test_non_list_root_returns_empty(self, _isolated_presets_file):
        """JSON file with wrong root type returns empty list."""
        _isolated_presets_file.write_text('{"not": "a list"}', encoding="utf-8")
        loaded = load_presets()
        assert loaded == []
