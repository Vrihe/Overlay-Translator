"""
settings/hotkeys.py — the app's own global hotkeys: translate a region and open the
settings. Turns what a QKeySequenceEdit captured into the ``keyboard`` library's
format and checks a new combination before it is saved. Preset hotkeys are checked
in ``settings/region_presets.py``.
"""

from __future__ import annotations

import re

from i18n import tr

TRANSLATE = "translate"
SETTINGS = "settings"
#: settings.json key of each hotkey.
SETTING_KEYS = {TRANSLATE: "hotkey", SETTINGS: "settings_hotkey"}

# Qt key names that the keyboard library spells differently.
_QT_TO_KEYBOARD = {
    "meta": "windows", "pgup": "page up", "pgdown": "page down", "del": "delete",
    "ins": "insert", "return": "enter", "backspace": "backspace",
}
_FUNCTION_KEY = re.compile(r"f([1-9]|1\d|2[0-4])")


def from_key_sequence(text: str) -> str:
    """``QKeySequence.toString()`` → keyboard format: ``"Ctrl+Shift+R"`` → ``"ctrl+shift+r"``.

    Only the first chord counts (a QKeySequenceEdit can record up to four,
    separated by ``", "``).
    """
    first = text.split(", ")[0].strip()
    if not first:
        return ""
    parts = [p.strip().lower() for p in first.split("+")]
    if parts[-1] == "" and len(parts) > 1:  # "Ctrl++" — the plus key itself
        parts = parts[:-2] + ["+"]
    return "+".join(_QT_TO_KEYBOARD.get(p, p) for p in parts)


def current(role: str) -> str:
    import config
    value = config.HOTKEY if role == TRANSLATE else config.SETTINGS_HOTKEY
    return str(value or "").strip().lower()


def default(role: str) -> str:
    from settings.config_manager import DEFAULTS
    return DEFAULTS[SETTING_KEYS[role]]


def validate_app_hotkey(hotkey: str, role: str) -> str:
    """Return *hotkey* normalised for the ``keyboard`` library, or raise ValueError.

    Rejects an empty value, a syntax the keyboard library cannot hook, a single
    ordinary key (it would fire while typing text; F1–F24 alone are fine), the
    other app hotkey, and any region preset hotkey.
    """
    hk = (hotkey or "").strip().lower()
    if not hk:
        raise ValueError(tr("Нажмите сочетание клавиш."))
    try:
        import keyboard
        keyboard.parse_hotkey(hk)
    except Exception as exc:
        raise ValueError(tr("Некорректная комбинация клавиш: '{hotkey}'. ({error})",
                            hotkey=hotkey, error=exc))

    if "+" not in hk and not _FUNCTION_KEY.fullmatch(hk):
        raise ValueError(tr("Добавьте Ctrl, Alt, Shift или Win: одна обычная клавиша "
                            "срабатывала бы при наборе текста."))

    other = SETTINGS if role == TRANSLATE else TRANSLATE
    if hk == current(other):
        raise ValueError(tr("Комбинация '{hotkey}' уже занята для другого действия.",
                            hotkey=hk.upper()))

    try:
        from settings.region_presets import load_presets
        presets = load_presets()
    except Exception:
        presets = []
    for preset in presets:
        if (preset.get("hotkey") or "").strip().lower() == hk:
            raise ValueError(tr("Комбинация '{hotkey}' уже назначена пресету «{name}».",
                                hotkey=hk.upper(), name=preset.get("name", "")))
    return hk
