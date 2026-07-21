"""
tray/icon_gen.py — generate a simple tray icon pixmap on the fly.

Creates a 64×64 icon with a stylised "T" on a rounded gradient square
so the project doesn't depend on external asset files.
"""

from PyQt5.QtCore import Qt, QRect
from PyQt5.QtGui import (
    QPixmap, QPainter, QLinearGradient, QColor,
    QFont, QIcon, QPainterPath, QPen,
)


def create_tray_icon() -> QIcon:
    """Return a QIcon suitable for the system tray."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    # Rounded-rect background with a gradient.
    path = QPainterPath()
    path.addRoundedRect(2, 2, size - 4, size - 4, 14, 14)

    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#6366f1"))   # indigo
    grad.setColorAt(1.0, QColor("#06b6d4"))   # cyan
    p.fillPath(path, grad)

    # "T" letter.
    p.setPen(QPen(QColor(255, 255, 255, 230), 0))
    p.setFont(QFont("Segoe UI", 34, QFont.Bold))
    p.drawText(QRect(0, -2, size, size), Qt.AlignCenter, "T")

    p.end()
    return QIcon(pix)
