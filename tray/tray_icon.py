"""
tray/tray_icon.py — QSystemTrayIcon with context menu.

Menu items:
  • Показать окно              — toggle main window visibility
  • Перевести (Ctrl+Shift+R)   — triggers the selector overlay
  • Живой мониторинг области   — toggle live region monitoring
  • Пресеты регионов           — quick-launch saved region presets
  • Настройки                  — open main window on Settings tab
  • История переводов          — open main window on History tab
  • ──────────────────
  • Выход                      — full shutdown
"""

import logging

from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QApplication
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon

from tray.icon_gen import create_tray_icon
import config

# C2: Quick language switch — same list as settings_dialog to stay in sync.
_QUICK_LANGS = [
    ("ru", "🇷🇺 Русский"),
    ("en", "🇬🇧 English"),
    ("de", "🇩🇪 Deutsch"),
    ("fr", "🇫🇷 Français"),
    ("es", "🇪🇸 Español"),
    ("ja", "🇯🇵 日本語"),
    ("zh", "🇨🇳 中文"),
    ("uk", "🇺🇦 Українська"),
    ("ko", "🇰🇷 한국어"),
    ("pl", "🇵🇱 Polski"),
]


logger = logging.getLogger("translator")


class TrayIcon(QSystemTrayIcon):
    """System-tray icon with a right-click context menu."""

    # Emitted when a preset is chosen from the quick-launch submenu.
    preset_quick_start = pyqtSignal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setIcon(create_tray_icon())
        self.setToolTip("Translator Overlay")

        self._build_menu()

        # Single-click on the tray icon → toggle main window.
        # Double-click → trigger translation.
        self.activated.connect(self._on_activated)

    # ── Menu ─────────────────────────────────────────────

    def _build_menu(self) -> None:
        menu = QMenu()
        menu.setStyleSheet(
            """
            QMenu {
                background: #1e1e2e;
                color: #e0e0e0;
                border: 1px solid #333;
                padding: 4px 0;
                font-family: 'Segoe UI';
                font-size: 10pt;
            }
            QMenu::item {
                padding: 6px 28px 6px 16px;
            }
            QMenu::item:selected {
                background: #3a3a5c;
            }
            QMenu::item:checked {
                color: #6fcf97;
            }
            QMenu::separator {
                height: 1px;
                background: #333;
                margin: 4px 8px;
            }
            """
        )

        # ── Show Window ──
        self.act_show_window = QAction("Показать окно")
        menu.addAction(self.act_show_window)

        menu.addSeparator()

        # ── Translate ──
        self.act_translate = QAction(f"Перевести  ({config.HOTKEY.upper()})")
        menu.addAction(self.act_translate)

        # ── D2: Live Monitor ──
        self.act_live_monitor = QAction("▶ Живой мониторинг области")
        self.act_live_monitor.setCheckable(True)
        menu.addAction(self.act_live_monitor)

        # ── Region Presets submenu ──
        self._presets_menu = QMenu("📋 Пресеты регионов")
        self._presets_menu.setStyleSheet(menu.styleSheet())
        self.act_presets = QAction("Управление пресетами…")
        self._presets_menu.addAction(self.act_presets)
        self._presets_menu.addSeparator()
        self._preset_quick_actions: list[QAction] = []
        menu.addMenu(self._presets_menu)
        self.rebuild_presets_menu()

        menu.addSeparator()

        # ── C2: Quick language submenu ──
        self._lang_menu = QMenu("🌐 Язык перевода")
        self._lang_menu.setStyleSheet(menu.styleSheet())
        self._lang_actions: dict[str, QAction] = {}
        for code, label in _QUICK_LANGS:
            act = QAction(label)
            act.setCheckable(True)
            act.setChecked(code == config.TARGET_LANG)
            act.triggered.connect(lambda checked, c=code: self._on_lang_selected(c))
            self._lang_menu.addAction(act)
            self._lang_actions[code] = act
        menu.addMenu(self._lang_menu)

        menu.addSeparator()

        # ── Settings ──
        self.act_settings = QAction(f"Настройки  ({config.SETTINGS_HOTKEY.upper()})")
        menu.addAction(self.act_settings)

        # ── History ──
        self.act_history = QAction("История переводов")
        menu.addAction(self.act_history)

        menu.addSeparator()

        # ── Exit ──
        self.act_exit = QAction("Выход")
        menu.addAction(self.act_exit)

        self.setContextMenu(menu)

    # ── C2: Language switch handler ────────────────────────────────

    def _on_lang_selected(self, lang_code: str) -> None:
        """C2: Switch target language instantly, persist to config, invalidate LLM cache."""
        from settings import config_manager
        from translate.llm_client import reset_client

        cfg = config_manager.load_config()
        cfg["target_language"] = lang_code
        config_manager.save_config(cfg)
        reset_client()  # flushes _prompt_cache so new lang is used on next call

        # Update checkmarks
        for code, act in self._lang_actions.items():
            act.setChecked(code == lang_code)

        # Show brief notification
        label = next((l for c, l in _QUICK_LANGS if c == lang_code), lang_code)
        self.showMessage(
            "Overlay Translator",
            f"Язык перевода: {label}",
            QSystemTrayIcon.Information,
            2000,
        )

    def rebuild_lang_menu(self) -> None:
        """Refresh checkmarks when target language is changed from settings dialog."""
        for code, act in self._lang_actions.items():
            act.setChecked(code == config.TARGET_LANG)

    def rebuild_presets_menu(self) -> None:
        """Refresh the quick-launch preset entries in the tray submenu."""
        # Remove old quick-launch actions
        for act in self._preset_quick_actions:
            self._presets_menu.removeAction(act)
        self._preset_quick_actions.clear()

        try:
            from settings.region_presets import load_presets
            presets = load_presets()
        except Exception:
            logger.debug("Failed to load presets for tray menu", exc_info=True)
            return

        # Show up to 5 most recent presets
        for p in presets[-5:]:
            name = p.get("name", "???")
            x1, y1 = p.get("x1", 0), p.get("y1", 0)
            x2, y2 = p.get("x2", 0), p.get("y2", 0)
            w, h = x2 - x1, y2 - y1
            hk = p.get("hotkey")
            hk_label = f" ({hk.upper()})" if hk else ""
            act = QAction(f"▶ {name}{hk_label}  [{w}×{h}]")
            act.triggered.connect(
                lambda checked, _x1=x1, _y1=y1, _x2=x2, _y2=y2:
                    self.preset_quick_start.emit(_x1, _y1, _x2, _y2)
            )
            self._presets_menu.addAction(act)
            self._preset_quick_actions.append(act)

    # ── Activation handler ───────────────────────────────

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            # Single-click → toggle main window
            self.act_show_window.trigger()
        elif reason == QSystemTrayIcon.DoubleClick:
            # Double-click → trigger translation
            self.act_translate.trigger()
