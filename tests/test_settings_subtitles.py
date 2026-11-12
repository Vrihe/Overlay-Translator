"""
tests/test_settings_subtitles.py — Settings → Subtitles: the audio source, model and
device choices save themselves, and the start / stop button follows the session.

The settings page is built offscreen with everything mocked (settings_widget_case);
the list of sound devices is faked, no device is opened.
"""

import unittest
from unittest import mock

from settings import config_manager
from tests.settings_widget_case import SettingsWidgetCase

_DEVICES = ["Speakers (Fake) [Loopback]", "Chat (Fake) [Loopback]"]


def setUpModule():
    import i18n

    i18n.set_language("ru")


def tearDownModule():
    import i18n

    i18n.set_language(None)


class _SubtitlesCase(SettingsWidgetCase):
    saved = {}

    def setUp(self):
        patcher = mock.patch("audio.capture.list_loopback_devices", return_value=list(_DEVICES))
        patcher.start()
        self.addCleanup(patcher.stop)
        defaults = dict(config_manager.DEFAULTS)
        with mock.patch.dict(config_manager.DEFAULTS, {**defaults, **self.saved}):
            super().setUp()

    def flush(self):
        self.widget._flush_autosave()


class TestSubtitleSettings(_SubtitlesCase):
    def test_defaults(self):
        self.assertEqual(config_manager.DEFAULTS["subtitles_device"], "")
        self.assertEqual(config_manager.DEFAULTS["subtitles_model"], "small.en")
        self.assertEqual(config_manager.DEFAULTS["subtitles_stt_device"], "auto")
        self.assertIsNone(config_manager.DEFAULTS["subtitles_pos"])

    def test_form_shows_the_defaults_and_the_devices(self):
        combo = self.widget._subs_device_combo
        self.assertEqual([combo.itemData(i) for i in range(combo.count())], ["", *_DEVICES])
        self.assertEqual(combo.itemText(1), "Speakers (Fake)")  # shown without the loopback suffix
        self.assertEqual(combo.currentData(), "")
        self.assertEqual(self.widget._subs_model_combo.currentData(), "small.en")
        self.assertEqual(self.widget._subs_stt_device_combo.currentData(), "auto")

    def test_choices_are_autosaved(self):
        self.widget._subs_device_combo.setCurrentIndex(2)
        self.widget._subs_model_combo.setCurrentIndex(self.widget._subs_model_combo.findData("base.en"))
        self.widget._subs_stt_device_combo.setCurrentIndex(self.widget._subs_stt_device_combo.findData("cpu"))
        self.flush()
        self.assertEqual(self.disk["subtitles_device"], _DEVICES[1])
        self.assertEqual(self.disk["subtitles_model"], "base.en")
        self.assertEqual(self.disk["subtitles_stt_device"], "cpu")

    def test_saving_does_not_reset_the_translation_backends(self):
        import translate.backend

        self.widget._subs_model_combo.setCurrentIndex(1)
        self.flush()
        translate.backend.reset.assert_not_called()

    def test_button_asks_to_start_then_to_stop(self):
        asked = []
        self.widget.subtitles_toggle_requested.connect(asked.append)
        self.assertEqual(self.widget._btn_subtitles.text(), "Запустить субтитры")
        self.widget._btn_subtitles.click()
        self.widget.set_subtitles_active(True)
        self.assertEqual(self.widget._btn_subtitles.text(), "Остановить субтитры")
        self.widget._btn_subtitles.click()
        self.assertEqual(asked, [True, False])

    def test_status_line(self):
        self.widget.set_subtitles_status("Слушаю: Speakers", "ok")
        self.assertEqual(self.widget._subtitles_status.text(), "Слушаю: Speakers")
        self.widget.set_subtitles_status("Модель не найдена", "error")
        self.assertEqual(self.widget._subtitles_status.text(), "Модель не найдена")


class TestUnpluggedDevice(_SubtitlesCase):
    saved = {"subtitles_device": "Headset (Gone) [Loopback]", "subtitles_model": "tiny.en"}

    def test_saved_choice_is_kept_while_the_device_is_away(self):
        combo = self.widget._subs_device_combo
        self.assertEqual(combo.currentData(), "Headset (Gone) [Loopback]")
        self.assertEqual(self.widget._subs_model_combo.currentData(), "tiny.en")
        self.flush()
        self.assertEqual(self.writes, [])  # opening the page changes nothing


class TestLanguageFilterSetting(_SubtitlesCase):
    def test_off_by_default_and_autosaved(self):
        self.assertFalse(config_manager.DEFAULTS["subtitles_skip_foreign"])
        self.assertFalse(self.widget._chk_subs_skip_foreign.isChecked())
        self.widget._chk_subs_skip_foreign.setChecked(True)
        self.flush()
        self.assertTrue(self.disk["subtitles_skip_foreign"])

    def test_speech_language_is_english_by_default_and_autosaved(self):
        combo = self.widget._subs_lang_combo
        self.assertEqual(config_manager.DEFAULTS["subtitles_language"], "en")
        self.assertEqual(combo.currentData(), "en")
        combo.setCurrentIndex(combo.findData("auto"))
        self.flush()
        self.assertEqual(self.disk["subtitles_language"], "auto")

    def test_another_language_with_an_english_only_model_shows_the_hint(self):
        models = self.widget._subs_model_combo
        models.setCurrentIndex(models.findData("small.en"))
        langs = self.widget._subs_lang_combo
        langs.setCurrentIndex(langs.findData("de"))
        self.assertFalse(self.widget._subs_filter_hint.isHidden())
        models.setCurrentIndex(models.findData("small"))
        self.assertTrue(self.widget._subs_filter_hint.isHidden())

    def test_streaming_is_off_by_default_and_autosaved(self):
        self.assertFalse(config_manager.DEFAULTS["subtitles_streaming"])
        self.assertFalse(self.widget._chk_subs_streaming.isChecked())
        self.widget._chk_subs_streaming.setChecked(True)
        self.flush()
        self.assertTrue(self.disk["subtitles_streaming"])

    def test_hint_appears_only_for_an_english_only_model(self):
        combo = self.widget._subs_model_combo
        combo.setCurrentIndex(combo.findData("small.en"))
        self.assertTrue(self.widget._subs_filter_hint.isHidden())
        self.widget._chk_subs_skip_foreign.setChecked(True)
        self.assertFalse(self.widget._subs_filter_hint.isHidden())
        self.assertIn("small.en", self.widget._subs_filter_hint.text())
        combo.setCurrentIndex(combo.findData("small"))
        self.assertTrue(self.widget._subs_filter_hint.isHidden())

    def test_session_passes_the_setting_to_the_recognizer(self):
        from audio import session

        self.widget._chk_subs_skip_foreign.setChecked(True)
        combo = self.widget._subs_model_combo
        combo.setCurrentIndex(combo.findData("small"))
        self.flush()
        self.assertTrue(session._default_recognizer().filters_language)


class TestSubtitleDownloads(_SubtitlesCase):
    """The model and GPU-library rows: what is offered, and that nothing starts by itself."""

    def _refresh(self, *, model_dir=None, driver=12080, cudnn=None, cublas=None):
        with (
            mock.patch("audio.stt.resolve_model_dir", return_value=model_dir),
            mock.patch("translate.cuda_download.driver_cuda_version", return_value=driver),
            mock.patch("audio.stt.find_cudnn_dir", return_value=cudnn),
            mock.patch("translate.cuda_support.find_cublas_dir", return_value=cublas),
        ):
            self.widget._refresh_subs_model_row()
            self.widget._refresh_subs_gpu_row()

    def test_missing_model_offers_the_download(self):
        self._refresh()
        self.assertFalse(self.widget._btn_subs_model.isHidden())
        self.assertIn("small.en", self.widget._subs_model_status.text())
        self.assertIn("465", self.widget._subs_model_status.text())
        self.assertIsNone(self.widget._subs_model_worker)  # only the button starts a download

    def test_installed_model_hides_the_button(self):
        self._refresh(model_dir="C:/models/whisper-small.en")
        self.assertTrue(self.widget._btn_subs_model.isHidden())
        self.assertTrue(self.widget._subs_model_status.text().startswith("✓"))

    def test_gpu_row_is_hidden_without_an_nvidia_driver(self):
        self._refresh(driver=None)
        self.assertTrue(self.widget._subs_gpu_widget.isHidden())

    def test_gpu_libraries_are_offered_when_cudnn_is_missing(self):
        self._refresh(cublas="C:/cuda")
        self.assertFalse(self.widget._subs_gpu_widget.isHidden())
        self.assertFalse(self.widget._btn_subs_gpu.isHidden())
        self.assertIsNone(self.widget._subs_gpu_worker)

    def test_gpu_row_reports_ready_libraries(self):
        self._refresh(cudnn="C:/cudnn", cublas="C:/cuda")
        self.assertTrue(self.widget._btn_subs_gpu.isHidden())
        self.assertTrue(self.widget._subs_gpu_status.text().startswith("✓"))

    def test_old_driver_gets_no_download(self):
        self._refresh(driver=11040)
        self.assertTrue(self.widget._btn_subs_gpu.isHidden())
        self.assertIn("Драйвер", self.widget._subs_gpu_status.text())

    def test_model_button_starts_and_cancels_the_download(self):
        self._refresh()
        with mock.patch("ui.settings_dialog.SpeechModelDownloadWorker") as worker_cls:
            self.widget._on_subs_model_clicked()
            worker_cls.assert_called_once_with("small.en", self.widget)
            worker_cls.return_value.start.assert_called_once()
            self.widget._on_subs_model_clicked()  # second click cancels
            worker_cls.return_value.cancel.set.assert_called_once()
        with mock.patch("audio.stt.resolve_model_dir", return_value=None):
            self.widget._on_subs_model_done(False, "no network")
        self.assertIsNone(self.widget._subs_model_worker)
        self.assertIn("no network", self.widget._subs_model_status.text())
        self.assertTrue(self.widget._subs_model_combo.isEnabled())


if __name__ == "__main__":
    unittest.main()
