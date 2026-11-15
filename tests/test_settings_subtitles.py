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

    def test_form_shows_the_defaults(self):
        self.assertEqual(self.widget._subs_model_combo.currentData(), "small.en")
        self.assertEqual(self.widget._subs_stt_device_combo.currentData(), "auto")

    def test_choices_are_autosaved(self):
        self.widget._subs_model_combo.setCurrentIndex(self.widget._subs_model_combo.findData("base.en"))
        self.widget._subs_stt_device_combo.setCurrentIndex(self.widget._subs_stt_device_combo.findData("cpu"))
        self.flush()
        self.assertEqual(self.disk["subtitles_model"], "base.en")
        self.assertEqual(self.disk["subtitles_stt_device"], "cpu")

    def test_low_vram_switch_is_off_by_default_autosaved_and_reaches_the_recognizer(self):
        from audio import session

        self.assertFalse(config_manager.DEFAULTS["subtitles_low_vram"])
        self.assertFalse(self.widget._chk_subs_low_vram.isChecked())
        self.assertEqual(session._default_recognizer()._cuda_compute_type, "float16")
        self.widget._chk_subs_low_vram.setChecked(True)
        self.flush()
        self.assertTrue(self.disk["subtitles_low_vram"])
        self.assertEqual(session._default_recognizer()._cuda_compute_type, "int8_float16")

    def test_memory_hint_follows_the_model_and_the_switch(self):
        combo = self.widget._subs_model_combo
        combo.setCurrentIndex(combo.findData("large-v3-turbo"))
        hint = self.widget._subs_vram_hint
        self.assertIn("2250", hint.text())
        self.assertIn("1200", hint.text())
        self.widget._chk_subs_low_vram.setChecked(True)
        self.assertIn("слегка упадёт", hint.text())
        combo.setCurrentIndex(combo.findData("small.en"))
        self.assertIn("450", hint.text())
        self.assertNotIn("2250", hint.text())

    def test_saving_does_not_reset_the_translation_backends(self):
        import translate.backend

        self.widget._subs_model_combo.setCurrentIndex(1)
        self.flush()
        translate.backend.reset.assert_not_called()


class TestUnpluggedDevice(_SubtitlesCase):
    saved = {"subtitles_device": "Headset (Gone) [Loopback]", "subtitles_model": "tiny.en"}

    def test_saving_the_page_keeps_what_the_subtitles_tab_owns(self):
        self.assertEqual(self.widget._subs_model_combo.currentData(), "tiny.en")
        self.flush()
        self.assertEqual(self.writes, [])  # opening the page changes nothing
        self.widget._subs_stt_device_combo.setCurrentIndex(self.widget._subs_stt_device_combo.findData("cpu"))
        self.flush()
        self.assertEqual(self.disk["subtitles_device"], "Headset (Gone) [Loopback]")

    def test_a_section_can_be_opened_by_its_key(self):
        self.widget.show_section("subtitles")
        keys = [key for _title, key in self.widget._SECTIONS]
        self.assertEqual(self.widget._section_list.currentRow(), keys.index("subtitles"))
        self.widget.show_section("no such section")
        self.assertEqual(self.widget._section_list.currentRow(), keys.index("subtitles"))


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
