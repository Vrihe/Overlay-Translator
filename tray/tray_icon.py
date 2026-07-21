"""
tray/tray_icon.py — QSystemTrayIcon with context menu.

Menu items:
  • Перевести (Ctrl+Shift+R)  — triggers the selector overlay
  • Настройки                 — placeholder
  • История переводов         — placeholder
  • ──────────────────
  • Выход                     — full shutdown
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

        # Double-click on the tray icon → trigger translation.
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

        # ── Translate ──
        self.act_translate = QAction(f"Перевести  ({config.HOTKEY.upper()})")
        menu.addAction(self.act_translate)

        menu.addSeparator()

        # ── Settings ──
        self.act_settings = QAction(f"Настройки  ({config.SETTINGS_HOTKEY.upper()})")
        menu.addAction(self.act_settings)

        # ── History ──
        self.act_history = QAction("История переводов")
        self.act_history.triggered.connect(
            lambda: print("open history")
        )
        menu.addAction(self.act_history)

        menu.addSeparator()

        # ── Exit ──
        self.act_exit = QAction("Выход")
        menu.addAction(self.act_exit)

        self.setContextMenu(menu)

    # ── Double-click handler ─────────────────────────────

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.act_translate.trigger()
