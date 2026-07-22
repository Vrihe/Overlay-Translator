"""
tray/tray_icon.py — QSystemTrayIcon with context menu.

Menu items:
  • Показать окно              — toggle main window visibility
  • Перевести (Ctrl+Shift+R)   — triggers the selector overlay
  • Настройки                  — open main window on Settings tab
  • История переводов          — open main window on History tab
  • ──────────────────
  • Выход                      — full shutdown
"""

from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction, QApplication
from PyQt5.QtGui import QIcon

from tray.icon_gen import create_tray_icon
import config


class TrayIcon(QSystemTrayIcon):
    """System-tray icon with a right-click context menu."""

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

    # ── Activation handler ───────────────────────────────

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            # Single-click → toggle main window
            self.act_show_window.trigger()
        elif reason == QSystemTrayIcon.DoubleClick:
            # Double-click → trigger translation
            self.act_translate.trigger()
