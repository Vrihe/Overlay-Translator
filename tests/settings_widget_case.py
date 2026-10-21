"""
tests/settings_widget_case.py — a SettingsWidget built offscreen with settings.json,
keyring, presets and the backends mocked. ``self.disk`` is the fake settings.json,
``self.writes`` every save; nothing touches the real files or the network.
"""

import os
import sys
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication

_APP = QApplication.instance() or QApplication(sys.argv[:1])


class SettingsWidgetCase(unittest.TestCase):
    #: Region presets returned by the mocked load_presets().
    presets: list = []

    def setUp(self):
        from settings import config_manager
        self.disk = dict(config_manager.DEFAULTS)
        self.disk.update(hotkey="ctrl+shift+r", settings_hotkey="ctrl+shift+o",
                         ui_language="ru", translation_backend="google")
        self.writes = []

        def fake_save(cfg):
            self.writes.append(dict(cfg))
            self.disk = {**self.disk, **cfg}
            config_manager._cache = dict(self.disk)

        config_manager._cache = dict(self.disk)
        self.addCleanup(setattr, config_manager, "_cache", None)
        env = {k: v for k, v in os.environ.items() if k.upper() != "SETTINGS_HOTKEY"}
        for patcher in (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(config_manager, "save_config", side_effect=fake_save),
            mock.patch.object(config_manager, "load_config", side_effect=lambda: dict(self.disk)),
            mock.patch.object(config_manager, "set_value",
                              side_effect=lambda k, v: fake_save({**self.disk, k: v})),
            mock.patch("settings.get_api_key", return_value=None),
            mock.patch("settings.get_primary_provider", return_value="openrouter"),
            mock.patch("settings.is_fallback_enabled", return_value=True),
            mock.patch("settings.region_presets.load_presets", side_effect=lambda: list(self.presets)),
            mock.patch("translate.backend.reset"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

        from ui import settings_dialog
        for patcher in (
            mock.patch.object(settings_dialog, "reset_client"),
            mock.patch.object(settings_dialog.SettingsWidget, "_detect_gpu_info",
                              staticmethod(lambda: "")),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.widget = settings_dialog.SettingsWidget()
        self.addCleanup(self.widget.deleteLater)
