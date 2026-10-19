"""
ui/wheel_guard.py — the mouse wheel scrolls the page, not the control under the cursor.

By default a QComboBox / QSpinBox changes its value when the wheel turns over
it, so scrolling a long page (Settings) silently changes whatever the cursor
passes over. The filter swallows those wheel events and hands them to the
nearest enclosing scroll area instead. An open combo list still scrolls: its
popup view is not a QComboBox, so the filter leaves it alone.
"""

from PyQt5.QtCore import QCoreApplication, QEvent, QObject
from PyQt5.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox


class _WheelGuard(QObject):
    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Wheel or not isinstance(obj, (QComboBox, QAbstractSpinBox)):
            return False
        area = obj.parentWidget()
        while area is not None and not isinstance(area, QAbstractScrollArea):
            area = area.parentWidget()
        if area is not None:
            # A sent (non-spontaneous) event does not propagate up the parents,
            # so deliver it to the scroll area's viewport directly.
            QCoreApplication.sendEvent(area.viewport(), event)
        return True


def install_wheel_guard(app: QApplication) -> None:
    """Install the filter on the whole application (parented to it, so it stays alive)."""
    app.installEventFilter(_WheelGuard(app))
