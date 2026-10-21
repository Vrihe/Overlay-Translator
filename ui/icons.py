"""
ui/icons.py — simple stroke icons drawn with QPainterPath (no emoji, no SVG module).

Every icon lives on a 24×24 grid and is stroked at 1.8 px with square caps, then
scaled to the requested size. ``icon(name, color)`` / ``pixmap(name, color)``
render one in any colour; names are the keys of ``_SHAPES``.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap

_STROKE = 1.8


def _poly(path: QPainterPath, *points: tuple[float, float]) -> None:
    path.moveTo(*points[0])
    for pt in points[1:]:
        path.lineTo(*pt)


def _home(p: QPainterPath) -> None:
    _poly(p, (3, 11), (12, 3), (21, 11))
    _poly(p, (5, 9.5), (5, 21), (19, 21), (19, 9.5))
    _poly(p, (10, 21), (10, 15), (14, 15), (14, 21))


def _sliders(p: QPainterPath) -> None:
    for y, knob in ((6, 8), (12, 15), (18, 10)):
        _poly(p, (3, y), (knob - 2, y))
        _poly(p, (knob + 2, y), (21, y))
        p.addRect(QRectF(knob - 2, y - 2, 4, 4))


def _clock(p: QPainterPath) -> None:
    p.addEllipse(QPointF(12, 12), 9, 9)
    _poly(p, (12, 7), (12, 12), (15.5, 14))


def _upload(p: QPainterPath) -> None:
    _poly(p, (12, 15), (12, 4))
    _poly(p, (7, 9), (12, 4), (17, 9))
    _poly(p, (4, 15), (4, 20), (20, 20), (20, 15))


def _copy(p: QPainterPath) -> None:
    p.addRect(QRectF(8, 8, 12, 12))
    _poly(p, (16, 8), (16, 4), (4, 4), (4, 16), (8, 16))


def _speaker(p: QPainterPath) -> None:
    _poly(p, (4, 9), (8, 9), (13, 5), (13, 19), (8, 15), (4, 15))
    p.closeSubpath()
    for r in (3.5, 7):
        rect = QRectF(13 - r, 12 - r, 2 * r, 2 * r)
        p.arcMoveTo(rect, -45)
        p.arcTo(rect, -45, 90)


def _close(p: QPainterPath) -> None:
    _poly(p, (6, 6), (18, 18))
    _poly(p, (18, 6), (6, 18))


def _minimize(p: QPainterPath) -> None:
    _poly(p, (6, 12), (18, 12))


def _maximize(p: QPainterPath) -> None:
    p.addRect(QRectF(6, 6, 12, 12))


def _restore(p: QPainterPath) -> None:
    p.addRect(QRectF(5, 9, 10, 10))
    _poly(p, (9, 9), (9, 5), (19, 5), (19, 15), (15, 15))


def _chevron_down(p: QPainterPath) -> None:
    _poly(p, (6, 9), (12, 15), (18, 9))


def _chevron_up(p: QPainterPath) -> None:
    _poly(p, (6, 15), (12, 9), (18, 15))


def _arrow_right(p: QPainterPath) -> None:
    _poly(p, (4, 12), (20, 12))
    _poly(p, (14, 6), (20, 12), (14, 18))


def _search(p: QPainterPath) -> None:
    p.addEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
    _poly(p, (15.5, 15.5), (21, 21))


def _globe(p: QPainterPath) -> None:
    p.addEllipse(QPointF(12, 12), 9, 9)
    p.addEllipse(QPointF(12, 12), 4, 9)
    _poly(p, (3, 12), (21, 12))


def _check(p: QPainterPath) -> None:
    _poly(p, (5, 12), (10, 17), (19, 7))


def _stop(p: QPainterPath) -> None:
    p.addRect(QRectF(7, 7, 10, 10))


def _keyboard(p: QPainterPath) -> None:
    p.addRect(QRectF(2.5, 6, 19, 12))
    for x in (6, 10, 14, 18):
        _poly(p, (x, 10), (x + 0.01, 10))
    _poly(p, (7, 14), (17, 14))


_SHAPES = {
    "home": _home,
    "sliders": _sliders,
    "clock": _clock,
    "upload": _upload,
    "copy": _copy,
    "speaker": _speaker,
    "close": _close,
    "minimize": _minimize,
    "maximize": _maximize,
    "restore": _restore,
    "chevron_down": _chevron_down,
    "chevron_up": _chevron_up,
    "arrow_right": _arrow_right,
    "search": _search,
    "globe": _globe,
    "check": _check,
    "stop": _stop,
    "keyboard": _keyboard,
}

NAMES = tuple(_SHAPES)


def path(name: str) -> QPainterPath:
    """The icon's outline on the 24×24 grid."""
    p = QPainterPath()
    _SHAPES[name](p)
    return p


def paint(painter: QPainter, name: str, rect: QRectF, color: QColor | str) -> None:
    """Stroke icon ``name`` into ``rect`` with an existing painter."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width() / 24.0, rect.height() / 24.0)
    pen = QPen(QColor(color), _STROKE)
    pen.setCapStyle(Qt.SquareCap)
    pen.setJoinStyle(Qt.MiterJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path(name))
    painter.restore()


def pixmap(name: str, color: QColor | str, size: int = 18) -> QPixmap:
    """A transparent ``size``×``size`` pixmap (HiDPI aware) with the icon."""
    app = QGuiApplication.instance()
    dpr = app.devicePixelRatio() if app is not None else 1.0
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    paint(painter, name, QRectF(0, 0, size, size), color)
    painter.end()
    return pix


def icon(name: str, color: QColor | str, size: int = 18, *,
         active_color: QColor | str | None = None) -> QIcon:
    """QIcon with the icon in ``color`` (and ``active_color`` for the checked / on state)."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    if active_color is not None:
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Active, QIcon.Off)
    return ic
