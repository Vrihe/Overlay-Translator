"""
ui/monitoring_page.py — the "Monitoring" tab of the main window.

The saved screen regions and live monitoring on one screen: the list of regions with
their sizes and binds, the start / stop button for monitoring the selected one, adding a
region and opening the manager. What is set up once (how often to check, the sensitivity,
the popup behaviour) stays in Settings → Monitoring.

The page does nothing itself: its buttons emit signals handled in main.py, and
``refresh_regions`` / ``set_monitoring_active`` bring the state back.
"""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

import config
from i18n import tr
from ui import theme
from ui.hud_widgets import Panel, page_title


class MonitoringPage(QWidget):
    add_region_requested = pyqtSignal()
    manage_regions_requested = pyqtSignal()
    #: Start live monitoring of the selected region (x1, y1, x2, y2).
    monitor_region_requested = pyqtSignal(int, int, int, int)
    stop_monitoring_requested = pyqtSignal()
    #: Open Settings → Monitoring (interval, sensitivity, popup behaviour).
    open_settings_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._monitoring_active = False
        self._build_ui()
        self.refresh_regions()

    # ── UI ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(page_title(tr("Мониторинг")))

        regions = Panel(tr("Регионы"))
        about = QLabel(
            tr(
                "Сохранённые области экрана. Бинд переводит область сразу, без выделения. "
                "Мониторинг следит за выбранной областью и переводит её снова, когда в ней "
                "меняется текст."
            )
        )
        about.setWordWrap(True)
        about.setStyleSheet(theme.label_css("caption"))
        regions.body.addWidget(about)
        self._regions_list = QListWidget()
        self._regions_list.setSelectionMode(QListWidget.SingleSelection)
        self._regions_list.setStyleSheet(theme.list_css())
        self._regions_list.setMinimumHeight(150)
        self._regions_list.currentRowChanged.connect(lambda _row: self._update_monitor_button())
        regions.body.addWidget(self._regions_list)

        self._btn_monitor = QPushButton()
        self._btn_monitor.setCursor(Qt.PointingHandCursor)
        self._btn_monitor.setFont(theme.display_font(10, spacing=112))
        self._btn_monitor.setStyleSheet(theme.btn_primary("10px 18px", 10))
        self._btn_monitor.clicked.connect(self._on_monitor_clicked)
        self._btn_add = QPushButton(tr("Добавить регион"))
        self._btn_add.setCursor(Qt.PointingHandCursor)
        self._btn_add.setStyleSheet(theme.btn_accent("7px 14px", 9))
        self._btn_add.clicked.connect(self.add_region_requested)
        self._btn_manage = QPushButton(tr("Управление…"))
        self._btn_manage.setCursor(Qt.PointingHandCursor)
        self._btn_manage.setStyleSheet(theme.btn_secondary("7px 14px", 9))
        self._btn_manage.setToolTip(tr("Переименовать, удалить регион или назначить ему бинд."))
        self._btn_manage.clicked.connect(self.manage_regions_requested)
        buttons = QHBoxLayout()
        buttons.addWidget(self._btn_monitor)
        buttons.addWidget(self._btn_add)
        buttons.addWidget(self._btn_manage)
        buttons.addStretch()
        regions.body.addLayout(buttons)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(theme.text_css(theme.current().ok, 9))
        regions.body.addWidget(self._status)
        root.addWidget(regions)

        # What is set up once lives in the settings: show it and lead there.
        params = Panel(tr("Интервал и чувствительность"))
        self._params_label = QLabel("")
        self._params_label.setWordWrap(True)
        self._params_label.setStyleSheet(theme.label_css("caption"))
        params.body.addWidget(self._params_label)
        self._btn_settings = QPushButton(tr("Настройки"))
        self._btn_settings.setCursor(Qt.PointingHandCursor)
        self._btn_settings.setStyleSheet(theme.btn_accent("6px 12px", 8.5))
        self._btn_settings.clicked.connect(self.open_settings_requested)
        params_buttons = QHBoxLayout()
        params_buttons.addWidget(self._btn_settings)
        params_buttons.addStretch()
        params.body.addLayout(params_buttons)
        root.addWidget(params)
        root.addStretch()

    # ── State from the app ───────────────────────────────

    def refresh_regions(self) -> None:
        """List the saved regions: name, size and bind."""
        try:
            from settings.region_presets import load_presets

            presets = load_presets()
        except Exception:
            presets = []
        self._regions_list.clear()
        for preset in presets:
            w, h = preset.get("x2", 0) - preset.get("x1", 0), preset.get("y2", 0) - preset.get("y1", 0)
            hotkey = (preset.get("hotkey") or "").upper() or tr("без бинда")
            item = QListWidgetItem(f"{preset.get('name', '')}   ·   {w}×{h}   ·   {hotkey}")
            item.setData(Qt.UserRole, preset)
            self._regions_list.addItem(item)
        if presets:
            self._regions_list.setCurrentRow(0)
        else:
            placeholder = QListWidgetItem(tr("Регионов пока нет: нажмите «Добавить регион»."))
            placeholder.setFlags(Qt.NoItemFlags)
            self._regions_list.addItem(placeholder)
        self._update_monitor_button()

    def set_monitoring_active(self, active: bool) -> None:
        """Live monitoring started / stopped (also from the tray or a bind)."""
        self._monitoring_active = active
        self._update_monitor_button()

    def start_selected(self) -> bool:
        """Ask to monitor the selected region; False when there is no region to monitor."""
        preset = self._selected_preset()
        if not preset:
            return False
        self.monitor_region_requested.emit(
            preset.get("x1", 0), preset.get("y1", 0), preset.get("x2", 0), preset.get("y2", 0)
        )
        return True

    def reload(self) -> None:
        """Called when the tab is opened: regions and settings may have changed."""
        self.refresh_regions()

    # ── Internals ────────────────────────────────────────

    def _selected_preset(self):
        item = self._regions_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _update_monitor_button(self) -> None:
        active = self._monitoring_active
        self._btn_monitor.setText((tr("Остановить мониторинг") if active else tr("Запустить мониторинг")).upper())
        self._btn_monitor.setEnabled(active or self._selected_preset() is not None)
        self._status.setText(tr("Мониторинг идёт.") if active else "")
        self._status.setVisible(active)
        interval = int(getattr(config, "LIVE_INTERVAL_SEC", 10) or 10)
        self._params_label.setText(tr("Область проверяется каждые {seconds} сек.", seconds=interval))

    def _on_monitor_clicked(self) -> None:
        if self._monitoring_active:
            self.stop_monitoring_requested.emit()
            return
        self.start_selected()
