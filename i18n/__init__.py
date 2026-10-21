"""
i18n — interface language (Russian / English).

Russian is the source language: user-facing strings stay in Russian in the code
and are wrapped in ``tr()``, which looks them up in the English catalog
(``i18n/en.py``) when the interface language is English. A string missing from
the catalog falls back to the Russian original, so a forgotten entry never
breaks the UI (``tests/test_i18n.py`` checks the catalog is complete).

    from i18n import tr, N_
    QLabel(tr("Перевести"))
    tr("Ошибка OCR:\\n{error}", error=e)     # placeholders use str.format

    _LABELS = [("auto", N_("Автоопределение"))]  # marks a module-level constant;
    combo.addItem(tr(label))                     # translate it where it is shown

The language is resolved once per process from ``settings.json``
(``ui_language``: ``"auto"`` | ``"ru"`` | ``"en"``); changing it takes effect
after a restart. ``"auto"`` picks Russian for a Russian, Ukrainian or Belarusian
Windows UI language, otherwise English.
"""

from __future__ import annotations

import locale
import logging
import os

log = logging.getLogger(__name__)

LANG_RU = "ru"
LANG_EN = "en"
LANG_AUTO = "auto"

# (code, native name) for the settings combo; names are not translated.
UI_LANGUAGES: list[tuple[str, str]] = [
    (LANG_AUTO, "Auto / Авто"),
    (LANG_RU, "Русский"),
    (LANG_EN, "English"),
]

# System languages for which "auto" picks the Russian interface.
_RUSSIAN_UI_SYSTEM_LANGS = {"ru", "uk", "be"}

# Windows primary language ids (LANGID & 0x3FF) of the same languages.
_RUSSIAN_UI_WIN_LANGIDS = {0x19: "ru", 0x22: "uk", 0x23: "be"}

_current: str | None = None


def _system_language() -> str:
    """Two-letter code of the OS interface language ("" if unknown)."""
    if os.name == "nt":
        try:
            import ctypes

            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return _RUSSIAN_UI_WIN_LANGIDS.get(langid & 0x3FF, "other")
        except Exception:
            pass
    try:
        code = locale.getlocale()[0] or ""
    except Exception:
        code = ""
    return code.split("_")[0].lower()


def resolve_language(setting: str | None) -> str:
    """Map a ``ui_language`` setting value to ``"ru"`` or ``"en"``."""
    if setting in (LANG_RU, LANG_EN):
        return setting
    return LANG_RU if _system_language() in _RUSSIAN_UI_SYSTEM_LANGS else LANG_EN


def current_language() -> str:
    """The interface language of this process (resolved on first use)."""
    global _current
    if _current is None:
        try:
            from settings import config_manager

            setting = config_manager.get("ui_language")
        except Exception:
            setting = LANG_AUTO
        _current = resolve_language(setting)
        log.info("Interface language: %s (setting: %s)", _current, setting)
    return _current


def set_language(lang: str | None) -> None:
    """Override the interface language (tests); ``None`` re-reads the setting."""
    global _current
    _current = None if lang is None else resolve_language(lang)


def install_qt_translator(app) -> None:
    """Translate Qt's own strings (Yes / No / Cancel buttons) into the interface language.

    English needs nothing. A missing ``qtbase_<lang>.qm`` (e.g. a stripped
    build) leaves those buttons in English instead of failing.
    """
    lang = current_language()
    if lang == LANG_EN:
        return
    from PyQt5.QtCore import QLibraryInfo, QTranslator

    translator = QTranslator(app)  # parented to the app, so it stays alive
    path = QLibraryInfo.location(QLibraryInfo.TranslationsPath)
    if translator.load(f"qtbase_{lang}", path):
        app.installTranslator(translator)
    else:
        log.info("Qt translations for %s not found in %s", lang, path)


def tr(text: str, **kwargs) -> str:
    """Translate a Russian UI string into the interface language.

    Keyword arguments fill ``{name}`` placeholders after the lookup, so the
    catalog key stays the same whatever the values are.
    """
    if current_language() == LANG_EN:
        from i18n.en import MESSAGES

        text = MESSAGES.get(text, text)
    return text.format(**kwargs) if kwargs else text


def N_(text: str) -> str:
    """Mark a string for translation without translating it yet."""
    return text
