"""
tray/icon_gen.py — generate a simple tray icon pixmap on the fly.

Creates a 64×64 icon: a flat square tile in the palette accent with an
``on_accent`` "T" (HUD theme, ui/theme.py), so the project doesn't depend on
external asset files.
"""

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QFont, QIcon, QPainter, QPen, QPixmap

from ui import theme


def create_tray_icon() -> QIcon:
    """Return a QIcon suitable for the system tray."""
    size = 64
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)

    # Flat square tile.
    p.fillRect(2, 2, size - 4, size - 4, theme.qcolor("accent"))

    # "T" letter.
    font = QFont(theme.display_family(), 34)
    font.setWeight(QFont.Bold)
    p.setPen(QPen(theme.qcolor("on_accent"), 0))
    p.setFont(font)
    p.drawText(QRect(0, -1, size, size), Qt.AlignCenter, "T")

    p.end()
    return QIcon(pix)
