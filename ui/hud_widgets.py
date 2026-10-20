"""
ui/hud_widgets.py — small presentation-only widgets of the HUD theme.

NavButton (sidebar rail item), Panel (titled flat card), FieldLabel (caps caption),
Chip (bordered tag), Segmented (flat multi-button switch), Switch / SwitchRow
(square toggle that stays a real checkable, keyboard-accessible button) and
page_title (the ``// TITLE`` page heading).
Colours and fonts come from ui/theme.py.
"""

import html

from PyQt5.QtCore import QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ui import icons, theme


def page_title(text: str) -> QLabel:
    """Page heading ``// TEXT`` with the slashes in the accent colour."""
    p = theme.current()
    lbl = QLabel(f"<span style='color:{p.accent};'>//</span> {html.escape(text.upper())}")
    lbl.setTextFormat(Qt.RichText)
    lbl.setFont(theme.display_font(17, spacing=106))
    lbl.setStyleSheet(f"color: {p.text}; background: transparent;")
    return lbl


class NavButton(QPushButton):
    """Rail navigation item: icon above a 7 pt caps label, accent bar when active."""

    def __init__(self, icon_name: str, label: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._label = label.upper()
        self.setCheckable(True)
        self.setFixedSize(56, 52)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(label)
        self.setAccessibleName(label)
        self._hover = False

    def set_active(self, active: bool) -> None:
        self.setChecked(active)
        self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        p = theme.current()
        painter = QPainter(self)
        r = self.rect()
        active = self.isChecked()
        if active:
            painter.fillRect(r, QColor(p.active))
            painter.fillRect(0, 0, 2, r.height(), QColor(p.accent))
        elif self._hover:
            painter.fillRect(r, theme.qcolor("active", 160))
        if self.hasFocus():
            painter.setPen(QPen(QColor(p.dim), 1))
            painter.drawRect(r.adjusted(0, 0, -1, -1))

        color = p.accent if active else (p.text_soft if self._hover else p.nav_idle)
        icons.paint(painter, self._icon_name, QRectF((r.width() - 20) / 2, 8, 20, 20), color)

        painter.setPen(QColor(color))
        painter.setFont(theme.body_font(7, medium=True, spacing=108))
        painter.drawText(r.adjusted(0, 32, 0, -4), Qt.AlignHCenter | Qt.AlignTop, self._label)
        painter.end()


class Panel(QFrame):
    """Flat card: ``panel`` background, 1 px ``line`` border, optional display-font title.

    Add content to ``panel.body``; widgets for the right side of the title row go
    into ``panel.header`` (after its stretch).
    """

    def __init__(self, title: str = "", parent=None, *, object_name: str = "hudPanel"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setStyleSheet(theme.panel_css(object_name))
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(16, 14, 16, 16)
        self.body.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        self.title_label: QLabel | None = None
        if title:
            self.title_label = QLabel(title.upper())
            self.title_label.setFont(theme.display_font(10.5))
            self.title_label.setStyleSheet(
                f"color: {theme.current().text}; background: transparent;")
            self.header.addWidget(self.title_label)
            self.header.addStretch()
            self.body.addLayout(self.header)


class FieldLabel(QLabel):
    """Caps caption in ``muted`` (or accent), optionally prefixed with ``> ``."""

    def __init__(self, text: str, parent=None, *, prompt: bool = False, accent: bool = False):
        super().__init__(parent)
        self._prompt = prompt
        p = theme.current()
        self.setFont(theme.body_font(8, medium=True, spacing=114))
        self.setStyleSheet(f"color: {p.accent if accent else p.muted}; background: transparent;")
        self.set_caption(text)

    def set_caption(self, text: str) -> None:
        self.setText(("> " if self._prompt else "") + text.upper())


class Chip(QLabel):
    """28 px bordered caps tag; ``kind`` is ok | neutral | accent."""

    def __init__(self, text: str = "", kind: str = "neutral", parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.PlainText)
        self.setFixedHeight(28)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(theme.body_font(8, medium=True, spacing=114))
        self.setStyleSheet(theme.chip_css(kind))
        self.set_chip_text(text)

    def set_chip_text(self, text: str) -> None:
        self.setText(text.upper())


class Segmented(QFrame):
    """Flat row of exclusive buttons; the active one is filled with the accent."""

    changed = pyqtSignal(object)  # data of the newly selected option

    def __init__(self, options: list[tuple[str, object]], parent=None):
        super().__init__(parent)
        p = theme.current()
        self.setObjectName("hudSegmented")
        self.setStyleSheet(
            f"#hudSegmented {{ border: 1px solid {p.line}; background: {p.bg}; }}"
            "#hudSegmented QPushButton {"
            f"  background: transparent; color: {p.text_soft}; border: none; border-radius: 0;"
            f"  padding: 7px 14px; font-family: '{theme.body_family()}'; font-size: 9pt;"
            "}"
            f"#hudSegmented QPushButton:hover {{ color: {p.text}; background: {p.tint}; }}"
            f"#hudSegmented QPushButton:focus {{ color: {p.accent}; }}"
            "#hudSegmented QPushButton:checked {"
            f"  background: {p.accent}; color: {p.on_accent};"
            "}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(1, 1, 1, 1)
        row.setSpacing(0)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._data: list[object] = []
        for i, (label, data) in enumerate(options):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._group.addButton(btn, i)
            self._data.append(data)
            row.addWidget(btn)
        self._group.buttonClicked.connect(self._on_clicked)

    def _on_clicked(self, btn) -> None:
        self.changed.emit(self._data[self._group.id(btn)])

    def set_current(self, data: object) -> None:
        """Select the option with ``data`` without emitting ``changed``."""
        for i, d in enumerate(self._data):
            if d == data:
                self._group.button(i).setChecked(True)
                return
        checked = self._group.checkedButton()
        if checked is not None:  # no matching option: show none as active
            self._group.setExclusive(False)
            checked.setChecked(False)
            self._group.setExclusive(True)

    def current_data(self) -> object:
        btn = self._group.checkedButton()
        return None if btn is None else self._data[self._group.id(btn)]


class Switch(QAbstractButton):
    """Square 44×22 toggle. A real checkable button: Space toggles it, Tab focuses it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(44, 22)

    def sizeHint(self) -> QSize:
        return QSize(44, 22)

    def paintEvent(self, _event):
        p = theme.current()
        painter = QPainter(self)
        r = self.rect().adjusted(0, 0, -1, -1)
        on = self.isChecked()
        enabled = self.isEnabled()
        if self.hasFocus():
            border = p.text if on else p.accent
        else:
            border = p.accent if on and enabled else p.line
        painter.fillRect(r, theme.qcolor("accent", 18) if on else QColor(p.bg))
        painter.setPen(QPen(QColor(border), 1))
        painter.drawRect(r)
        knob = 14
        x = r.right() - knob - 3 if on else r.left() + 4
        knob_color = p.accent if on and enabled else p.muted
        painter.fillRect(x, (self.height() - knob) // 2, knob, knob, QColor(knob_color))
        painter.end()


class SwitchRow(QWidget):
    """Switch + word-wrapped label; mirrors the QCheckBox API the settings code uses."""

    toggled = pyqtSignal(bool)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        row.setSpacing(10)
        self.switch = Switch(self)
        self.switch.setAccessibleName(text)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(theme.text_css(theme.current().text_soft, 9.5))
        self.label.setCursor(Qt.PointingHandCursor)
        self.label.mousePressEvent = lambda _e: self.switch.toggle() if self.isEnabled() else None
        row.addWidget(self.switch, 0, Qt.AlignTop)
        row.addWidget(self.label, 1)
        self.switch.toggled.connect(self.toggled)

    def isChecked(self) -> bool:
        return self.switch.isChecked()

    def setChecked(self, checked: bool) -> None:
        self.switch.setChecked(checked)

    def setToolTip(self, text: str) -> None:
        super().setToolTip(text)
        self.switch.setToolTip(text)
        self.label.setToolTip(text)
