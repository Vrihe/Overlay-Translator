"""
settings/region_presets.py — named region presets for on-demand translation and monitoring.

Stores user-defined screen region presets in ``region_presets.json``
inside the application's user data directory (%APPDATA%/translator-overlay/).
Each preset holds a name, bounding-box coordinates, and an optional global hotkey
so the user can quickly translate a saved region on-demand or optionally monitor it.

Preset model:
    {id, name, x1, y1, x2, y2, hotkey, created_at}
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("translator")

# ── Limits ───────────────────────────────────────────────
MAX_PRESETS = 20
MAX_NAME_LENGTH = 40

# ── User data directory (same logic as translate/domain_manager.py) ──


def _get_user_data_dir() -> Path:
    """Return user AppData directory for persistent app data."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            p = Path(appdata) / "translator-overlay"
            p.mkdir(parents=True, exist_ok=True)
            return p
    p = Path.home() / ".config" / "translator-overlay"
    p.mkdir(parents=True, exist_ok=True)
    return p


_PRESETS_FILE: Path = _get_user_data_dir() / "region_presets.json"

# ── Validation helpers ───────────────────────────────────


def _validate_name(name: str) -> str:
    """Strip and validate preset name. Returns stripped name or raises ValueError."""
    name = name.strip()
    if not name:
        raise ValueError("Имя пресета не может быть пустым.")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(
            f"Имя пресета не может быть длиннее {MAX_NAME_LENGTH} символов "
            f"(сейчас {len(name)})."
        )
    return name


def _validate_coordinates(x1: int, y1: int, x2: int, y2: int) -> None:
    """Ensure coordinates form a valid rectangle (x1 < x2, y1 < y2)."""
    if not isinstance(x1, int) or not isinstance(y1, int) \
       or not isinstance(x2, int) or not isinstance(y2, int):
        raise ValueError("Координаты должны быть целыми числами.")
    if x1 >= x2:
        raise ValueError(f"Некорректные координаты: x1 ({x1}) должен быть меньше x2 ({x2}).")
    if y1 >= y2:
        raise ValueError(f"Некорректные координаты: y1 ({y1}) должен быть меньше y2 ({y2}).")


def validate_hotkey(hotkey: str | None, current_preset_id: str | None = None) -> str | None:
    """Validate and normalize a hotkey string.

    Args:
        hotkey: Hotkey string (e.g. 'ctrl+alt+1', 'f8') or None / empty string to clear.
        current_preset_id: Optional ID of the preset being edited to avoid self-conflict.

    Returns:
        Normalized lowercase hotkey string, or None if hotkey is empty/cleared.

    Raises:
        ValueError: If hotkey syntax is invalid or conflicts with application / other presets.
    """
    if hotkey is None:
        return None
    hk = hotkey.strip().lower()
    if not hk:
        return None

    # Verify syntax with keyboard module
    try:
        import keyboard
        keyboard.parse_hotkey(hk)
    except Exception as exc:
        raise ValueError(f"Некорректная комбинация клавиш: '{hotkey}'. ({exc})")

    # Check collision with main application hotkeys
    try:
        import config
        app_hotkey = getattr(config, "HOTKEY", "") or ""
        app_settings = getattr(config, "SETTINGS_HOTKEY", "") or ""
        if hk == app_hotkey.strip().lower():
            raise ValueError(
                f"Комбинация '{hotkey}' уже занята для основного перевода ({app_hotkey})."
            )
        if hk == app_settings.strip().lower():
            raise ValueError(
                f"Комбинация '{hotkey}' уже занята для окна настроек ({app_settings})."
            )
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise

    # Check collision with other saved presets
    presets = _read_file()
    for p in presets:
        if current_preset_id and p.get("id") == current_preset_id:
            continue
        p_hk = (p.get("hotkey") or "").strip().lower()
        if p_hk and p_hk == hk:
            raise ValueError(
                f"Комбинация '{hotkey}' уже назначена для пресета «{p.get('name', '???')}»."
            )

    return hk


# ── Persistence helpers ──────────────────────────────────


def _read_file() -> list[dict[str, Any]]:
    """Read presets list from disk. Returns [] on missing/corrupt file."""
    if not _PRESETS_FILE.exists():
        return []
    try:
        with open(_PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # Ensure "hotkey" key exists in all loaded dicts
            for p in data:
                if isinstance(p, dict) and "hotkey" not in p:
                    p["hotkey"] = None
            return data
        logger.warning("region_presets.json has unexpected root type %s, resetting.", type(data).__name__)
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read region_presets.json: %s", exc)
        return []


def _write_file(presets: list[dict[str, Any]]) -> None:
    """Write presets list to disk."""
    _PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2, ensure_ascii=False)


# ── Public API ───────────────────────────────────────────


def load_presets() -> list[dict[str, Any]]:
    """Load all saved region presets from disk.

    Returns:
        List of preset dicts sorted by creation date (oldest first).
        Each dict contains: id, name, x1, y1, x2, y2, hotkey, created_at.
    """
    presets = _read_file()
    logger.debug("Loaded %d region preset(s).", len(presets))
    return presets


def save_preset(
    name: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    hotkey: str | None = None,
) -> dict[str, Any]:
    """Create and persist a new region preset.

    Args:
        name: Display name for the preset (1–40 characters).
        x1, y1: Top-left corner of the region (global screen coords).
        x2, y2: Bottom-right corner of the region (global screen coords).
        hotkey: Optional keyboard hotkey string (e.g. 'ctrl+alt+1').

    Returns:
        The newly created preset dict.

    Raises:
        ValueError: If validation fails (name, coordinates, hotkey, or max count).
    """
    name = _validate_name(name)
    _validate_coordinates(x1, y1, x2, y2)
    valid_hotkey = validate_hotkey(hotkey)

    presets = _read_file()
    if len(presets) >= MAX_PRESETS:
        raise ValueError(
            f"Достигнут лимит пресетов ({MAX_PRESETS}). "
            "Удалите ненужные пресеты перед добавлением новых."
        )

    preset: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "name": name,
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "hotkey": valid_hotkey,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    presets.append(preset)
    _write_file(presets)
    logger.info(
        "Saved region preset '%s' (%d,%d)→(%d,%d), hotkey=%s, id=%s",
        name, x1, y1, x2, y2, valid_hotkey, preset["id"],
    )
    return preset


def delete_preset(preset_id: str) -> None:
    """Delete a region preset by its id.

    Raises:
        ValueError: If no preset with the given id exists.
    """
    presets = _read_file()
    new_presets = [p for p in presets if p.get("id") != preset_id]
    if len(new_presets) == len(presets):
        raise ValueError(f"Пресет с id '{preset_id}' не найден.")
    _write_file(new_presets)
    logger.info("Deleted region preset id=%s", preset_id)


def rename_preset(preset_id: str, new_name: str) -> None:
    """Rename an existing region preset.

    Raises:
        ValueError: If no preset with the given id exists or name is invalid.
    """
    new_name = _validate_name(new_name)
    presets = _read_file()
    found = False
    for p in presets:
        if p.get("id") == preset_id:
            p["name"] = new_name
            found = True
            break
    if not found:
        raise ValueError(f"Пресет с id '{preset_id}' не найден.")
    _write_file(presets)
    logger.info("Renamed region preset id=%s to '%s'", preset_id, new_name)


def update_preset_hotkey(preset_id: str, hotkey: str | None) -> dict[str, Any]:
    """Update or clear the hotkey of an existing region preset.

    Args:
        preset_id: ID of the preset to modify.
        hotkey: New hotkey string or None / empty string to clear.

    Returns:
        The updated preset dict.

    Raises:
        ValueError: If preset not found or hotkey validation fails.
    """
    valid_hotkey = validate_hotkey(hotkey, current_preset_id=preset_id)
    presets = _read_file()
    target_preset = None
    for p in presets:
        if p.get("id") == preset_id:
            p["hotkey"] = valid_hotkey
            target_preset = p
            break
    if target_preset is None:
        raise ValueError(f"Пресет с id '{preset_id}' не найден.")
    _write_file(presets)
    logger.info("Updated hotkey for preset id=%s to %s", preset_id, valid_hotkey)
    return target_preset
