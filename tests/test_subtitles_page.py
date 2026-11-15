"""
tests/test_subtitles_page.py — the Subtitles tab: the start / stop button, the status line
and the day-to-day parameters that save themselves.

The page is built offscreen; settings.json, the list of sound devices and the model lookup
are faked — no device is opened, nothing is loaded.
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtWidgets import QApplication

from settings import config_manager

_APP = QApplication.instance() or QApplication(sys.argv[:1])
_DEVICES = ["Speakers (Fake) [Loopback]", "Chat (Fake) [Loopback]"]


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


class _PageCase(unittest.TestCase):
    saved: dict = {}
    model_dir = "C:/models/whisper"  # None = the chosen model is not on disk

    def setUp(self):
        self.disk = {**config_manager.DEFAULTS, **self.saved}
        config_manager._cache = dict(self.disk)
        self.addCleanup(setattr, config_manager, "_cache", None)

        def fake_set(key, value):
            self.disk[key] = value
            config_manager._cache = dict(self.disk)

        for patcher in (
            mock.patch.object(config_manager, "set_value", side_effect=fake_set),
            mock.patch.object(config_manager, "save_config", side_effect=lambda cfg: None),
            mock.patch("audio.capture.list_loopback_devices", return_value=list(_DEVICES)),
            mock.patch("audio.stt.resolve_model_dir", side_effect=lambda name: self.model_dir),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        from ui.subtitles_page import SubtitlesPage

        self.page = SubtitlesPage()
        self.addCleanup(self.page.deleteLater)


class TestStartStop(_PageCase):
    def test_button_asks_to_start_then_to_stop(self):
        asked = []
        self.page.toggle_requested.connect(asked.append)
        self.assertEqual(self.page._btn_toggle.text(), "ЗАПУСТИТЬ СУБТИТРЫ")
        self.page._btn_toggle.click()
        self.page.set_active(True)
        self.assertEqual(self.page._btn_toggle.text(), "ОСТАНОВИТЬ СУБТИТРЫ")
        self.page._btn_toggle.click()
        self.assertEqual(asked, [True, False])

    def test_status_line_is_hidden_until_there_is_something_to_say(self):
        self.assertTrue(self.page._status.isHidden())
        self.page.set_status("Слушаю: Speakers", "ok")
        self.assertEqual(self.page._status.text(), "Слушаю: Speakers")
        self.assertFalse(self.page._status.isHidden())
        self.page.set_status("")
        self.assertTrue(self.page._status.isHidden())

    def test_settings_link(self):
        asked = []
        self.page.open_settings_requested.connect(lambda: asked.append(True))
        self.page._btn_settings.click()
        self.assertEqual(asked, [True])


class TestParameters(_PageCase):
    def test_opening_the_page_shows_the_defaults_and_saves_nothing(self):
        combo = self.page._device_combo
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], ["", *_DEVICES])
        self.assertEqual(combo.itemText(1), "Speakers (Fake)")  # shown without the loopback suffix
        self.assertEqual(combo.currentData(), "")
        self.assertEqual(self.page._lang_combo.currentData(), "en")
        self.assertFalse(self.page._chk_streaming.isChecked())
        self.assertFalse(self.page._chk_skip_foreign.isChecked())
        config_manager.set_value.assert_not_called()

    def test_every_change_is_saved_at_once(self):
        self.page._device_combo.setCurrentIndex(2)
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("auto"))
        self.page._chk_streaming.setChecked(True)
        self.page._chk_skip_foreign.setChecked(True)
        self.assertEqual(self.disk["subtitles_device"], _DEVICES[1])
        self.assertEqual(self.disk["subtitles_language"], "auto")
        self.assertTrue(self.disk["subtitles_streaming"])
        self.assertTrue(self.disk["subtitles_skip_foreign"])

    def test_reload_picks_up_values_changed_elsewhere(self):
        self.disk["subtitles_language"] = "de"
        config_manager._cache = dict(self.disk)
        self.page.reload()
        self.assertEqual(self.page._lang_combo.currentData(), "de")
        config_manager.set_value.assert_not_called()

    def test_session_gets_what_the_page_saved(self):
        from audio import session

        self.disk["subtitles_model"] = "small"
        config_manager._cache = dict(self.disk)
        self.page._chk_skip_foreign.setChecked(True)
        self.assertTrue(session._default_recognizer().filters_language)

    def test_page_works_without_the_sound_packages(self):
        with mock.patch("audio.capture.list_loopback_devices", side_effect=RuntimeError("no PyAudio")):
            self.page.reload()
        self.assertEqual(self.page._device_combo.count(), 1)  # the default device only


class TestUnpluggedDevice(_PageCase):
    saved = {"subtitles_device": "Headset (Gone) [Loopback]"}

    def test_saved_choice_is_kept_while_the_device_is_away(self):
        self.assertEqual(self.page._device_combo.currentData(), "Headset (Gone) [Loopback]")
        config_manager.set_value.assert_not_called()


class TestModelHints(_PageCase):
    def test_installed_model_is_named(self):
        self.assertIn("small.en", self.page._model_label.text())
        self.assertTrue(self.page._hint.isHidden())

    def test_english_only_model_cannot_do_other_languages_or_the_filter(self):
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("de"))
        self.assertFalse(self.page._hint.isHidden())
        self.assertIn("small.en", self.page._hint.text())
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("en"))
        self.assertTrue(self.page._hint.isHidden())
        self.page._chk_skip_foreign.setChecked(True)
        self.assertFalse(self.page._hint.isHidden())

    def test_multilingual_model_needs_no_hint(self):
        self.disk["subtitles_model"] = "small"
        config_manager._cache = dict(self.disk)
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("de"))
        self.assertTrue(self.page._hint.isHidden())


class TestMissingModel(_PageCase):
    model_dir = None

    def test_missing_model_is_reported_on_the_page(self):
        self.assertIn("не скачана", self.page._model_label.text())


if __name__ == "__main__":
    unittest.main()
