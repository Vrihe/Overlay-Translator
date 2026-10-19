"""
ui/theme.py — app-wide styling for Qt's stock dialogs.

The app's own widgets style themselves, but QMessageBox / QInputDialog come
from Qt with the system palette. On Windows in dark mode that palette gives a
dark window with dark text, so the dialogs look empty. This sheet pins them to
the app's dark theme (colours match ui/settings_dialog.py).
"""

from PyQt5.QtWidgets import QApplication

_DIALOG_CSS = (
    "QMessageBox, QInputDialog { background: #1c1c24; }"
    "QMessageBox QLabel, QInputDialog QLabel {"
    "  color: #e0e0e0; background: transparent;"
    "  font-family: 'Segoe UI'; font-size: 10pt;"
    "}"
    "QInputDialog QLineEdit {"
    "  background: #2a2a3e; color: #e0e0e0; border: 1px solid #444;"
    "  border-radius: 6px; padding: 6px 10px; font-family: 'Segoe UI'; font-size: 10pt;"
    "}"
    "QInputDialog QLineEdit:focus { border-color: #5b8def; }"
    "QMessageBox QPushButton, QInputDialog QPushButton {"
    "  background: #2a2a3e; color: #e0e0e0; border: 1px solid #5b8def;"
    "  border-radius: 6px; padding: 6px 18px; min-width: 64px;"
    "  font-family: 'Segoe UI'; font-size: 9.5pt;"
    "}"
    "QMessageBox QPushButton:hover, QInputDialog QPushButton:hover { background: #3a3a5c; }"
    "QMessageBox QPushButton:default, QInputDialog QPushButton:default {"
    "  background: #5b8def; color: #fff; border: none;"
    "}"
)


def apply_app_theme(app: QApplication) -> None:
    """Install the stock-dialog styling on the whole application."""
    app.setStyleSheet(_DIALOG_CSS)
