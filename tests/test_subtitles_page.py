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
    missing_packages: list = []  # package names reported as not installed
    can_install = True
    missing_models: tuple = ("small",)  # models that are not on disk whatever model_dir says

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
            mock.patch("audio.packages.missing_packages", side_effect=lambda: list(self.missing_packages)),
            mock.patch("audio.packages.can_install", side_effect=lambda: self.can_install),
            mock.patch(
                "audio.stt.resolve_model_dir",
                side_effect=lambda name: None if name in self.missing_models else self.model_dir,
            ),
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

    def test_running_subtitles_restart_once_after_a_change(self):
        asked = []
        self.page.toggle_requested.connect(asked.append)
        self.page.set_active(True)
        self.page._chk_streaming.setChecked(True)
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("de"))
        self.assertTrue(self.page._restart_timer.isActive())
        self.assertEqual(asked, [])  # debounced: several quick changes, one restart
        self.page._restart_timer.timeout.emit()
        self.assertEqual(asked, [False, True])

    def test_stopped_subtitles_are_not_started_by_a_change(self):
        asked = []
        self.page.toggle_requested.connect(asked.append)
        self.page._chk_streaming.setChecked(True)
        self.assertFalse(self.page._restart_timer.isActive())
        self.assertEqual(asked, [])

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
        self.assertTrue(self.page._model_status.text().startswith("✓"))
        self.assertIn("small.en", self.page._model_status.text())
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
        self.page.reload()
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("de"))
        self.assertTrue(self.page._hint.isHidden())


class TestMultilingualOnDisk(_PageCase):
    missing_models = ()

    def test_no_hint_when_the_session_can_swap_the_model_in(self):
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("de"))
        self.assertTrue(self.page._hint.isHidden())
        # The filter alone with English speech still cannot work on an English-only model.
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("en"))
        self.page._chk_skip_foreign.setChecked(True)
        self.assertFalse(self.page._hint.isHidden())


class TestMissingModel(_PageCase):
    model_dir = None

    def test_missing_model_offers_the_download_on_the_page(self):
        self.assertFalse(self.page._btn_model.isHidden())
        self.assertIn("не скачана", self.page._model_status.text())
        self.assertIn("465", self.page._model_status.text())
        self.assertIsNone(self.page._model_worker)  # only the button starts a download

    def test_start_without_the_model_starts_nothing_and_leads_to_the_download(self):
        asked = []
        self.page.toggle_requested.connect(asked.append)
        self.page._btn_toggle.click()
        self.assertEqual(asked, [])
        self.assertIn("small.en", self.page._status.text())
        self.assertFalse(self.page._status.isHidden())

    def test_start_failure_from_elsewhere_points_at_the_model(self):
        self.page.on_start_failed("Модель распознавания речи small.en не найдена. Искали в:\n  • C:/x")
        self.assertIn("Скачайте", self.page._status.text())
        self.assertNotIn("Искали", self.page._status.text())

    def test_other_failures_are_shown_as_they_are(self):
        self.model_dir = "C:/models/whisper"
        self.page.on_start_failed("Не найдено устройство вывода звука для захвата.")
        self.assertEqual(self.page._status.text(), "Не найдено устройство вывода звука для захвата.")

    def test_language_that_needs_the_multilingual_model_selects_it(self):
        self.page._lang_combo.setCurrentIndex(self.page._lang_combo.findData("de"))
        self.page._btn_toggle.click()
        self.assertEqual(self.page._model_combo.currentData(), "small")
        self.assertEqual(self.disk["subtitles_model"], "small")
        self.assertIn("small", self.page._status.text())


class TestMissingPackages(_PageCase):
    missing_packages = ["faster-whisper", "PyAudioWPatch"]

    def test_the_install_button_is_offered(self):
        self.assertFalse(self.page._packages_panel.isHidden())
        self.assertFalse(self.page._btn_packages.isHidden())
        self.assertIn("faster-whisper", self.page._packages_status.text())
        self.assertIsNone(self.page._packages_worker)  # only the button installs

    def test_start_without_packages_starts_nothing_and_leads_to_the_button(self):
        asked = []
        self.page.toggle_requested.connect(asked.append)
        self.page._btn_toggle.click()
        self.assertEqual(asked, [])
        self.assertIn("Установить пакеты", self.page._status.text())

    def test_start_failure_from_elsewhere_points_at_the_packages(self):
        self.page.on_start_failed("Не установлен пакет faster-whisper для распознавания речи.")
        self.assertIn("Установить пакеты", self.page._status.text())

    def test_the_install_button_starts_and_cancels(self):
        with mock.patch("ui.subtitles_page.SpeechPackagesInstallWorker") as worker_cls:
            self.page._on_packages_clicked()
            worker_cls.assert_called_once_with(self.page)
            worker_cls.return_value.start.assert_called_once()
            self.page._on_packages_clicked()  # second click cancels
            worker_cls.return_value.cancel.set.assert_called_once()

    def test_a_finished_install_hides_the_panel(self):
        with mock.patch("ui.subtitles_page.SpeechPackagesInstallWorker"):
            self.page._on_packages_clicked()
        self.missing_packages = []
        self.page._on_packages_done(True, "")
        self.assertTrue(self.page._packages_panel.isHidden())
        self.assertIn("Пакеты установлены", self.page._status.text())

    def test_a_failed_install_shows_why(self):
        with mock.patch("ui.subtitles_page.SpeechPackagesInstallWorker"):
            self.page._on_packages_clicked()
        self.page._on_packages_done(False, "no network")
        self.assertIn("no network", self.page._packages_status.text())
        self.assertFalse(self.page._packages_panel.isHidden())


class TestMissingPackagesPackagedBuild(_PageCase):
    missing_packages = ["faster-whisper"]
    can_install = False

    def test_no_button_only_advice(self):
        self.assertTrue(self.page._btn_packages.isHidden())
        self.assertIn("install.bat", self.page._packages_status.text())


class TestPackagesPresent(_PageCase):
    def test_the_panel_is_hidden(self):
        self.assertTrue(self.page._packages_panel.isHidden())


class TestModelSettings(_PageCase):
    def test_choices_are_saved_at_once(self):
        self.page._model_combo.setCurrentIndex(self.page._model_combo.findData("base.en"))
        self.page._stt_device_combo.setCurrentIndex(self.page._stt_device_combo.findData("cpu"))
        self.assertEqual(self.disk["subtitles_model"], "base.en")
        self.assertEqual(self.disk["subtitles_stt_device"], "cpu")

    def test_low_vram_switch_is_off_by_default_saved_and_reaches_the_recognizer(self):
        from audio import session

        self.assertFalse(self.page._chk_low_vram.isChecked())
        self.assertEqual(session._default_recognizer()._cuda_compute_type, "float16")
        self.page._chk_low_vram.setChecked(True)
        self.assertTrue(self.disk["subtitles_low_vram"])
        self.assertEqual(session._default_recognizer()._cuda_compute_type, "int8_float16")

    def test_memory_hint_follows_the_model_and_the_switch(self):
        combo, hint = self.page._model_combo, self.page._vram_hint
        combo.setCurrentIndex(combo.findData("large-v3-turbo"))
        self.assertIn("2250", hint.text())
        self.assertIn("1200", hint.text())
        self.page._chk_low_vram.setChecked(True)
        self.assertIn("слегка упадёт", hint.text())
        combo.setCurrentIndex(combo.findData("small.en"))
        self.assertIn("450", hint.text())
        self.assertNotIn("2250", hint.text())

    def test_reload_shows_the_saved_model(self):
        self.disk["subtitles_model"] = "tiny.en"
        config_manager._cache = dict(self.disk)
        self.page.reload()
        self.assertEqual(self.page._model_combo.currentData(), "tiny.en")


class TestDownloads(_PageCase):
    """The model and GPU-library rows: what is offered, and that nothing starts by itself."""

    def _refresh(self, *, model_dir=None, driver=12080, cudnn=None, cublas=None):
        with (
            mock.patch("audio.stt.resolve_model_dir", return_value=model_dir),
            mock.patch("translate.cuda_download.driver_cuda_version", return_value=driver),
            mock.patch("audio.stt.find_cudnn_dir", return_value=cudnn),
            mock.patch("translate.cuda_support.find_cublas_dir", return_value=cublas),
        ):
            self.page._refresh_model_row()
            self.page._refresh_gpu_row()

    def test_installed_model_hides_the_button(self):
        self._refresh(model_dir="C:/models/whisper-small.en")
        self.assertTrue(self.page._btn_model.isHidden())
        self.assertTrue(self.page._model_status.text().startswith("✓"))

    def test_gpu_row_is_hidden_without_an_nvidia_driver(self):
        self._refresh(driver=None)
        self.assertTrue(self.page._gpu_widget.isHidden())

    def test_gpu_libraries_are_offered_when_cudnn_is_missing(self):
        self._refresh(cublas="C:/cuda")
        self.assertFalse(self.page._gpu_widget.isHidden())
        self.assertFalse(self.page._btn_gpu.isHidden())
        self.assertIsNone(self.page._gpu_worker)

    def test_gpu_row_reports_ready_libraries(self):
        self._refresh(cudnn="C:/cudnn", cublas="C:/cuda")
        self.assertTrue(self.page._btn_gpu.isHidden())
        self.assertTrue(self.page._gpu_status.text().startswith("✓"))

    def test_old_driver_gets_no_download(self):
        self._refresh(driver=11040)
        self.assertTrue(self.page._btn_gpu.isHidden())
        self.assertIn("Драйвер", self.page._gpu_status.text())

    def test_model_button_starts_and_cancels_the_download(self):
        self._refresh()
        with mock.patch("ui.subtitles_page.SpeechModelDownloadWorker") as worker_cls:
            self.page._on_model_clicked()
            worker_cls.assert_called_once_with("small.en", self.page)
            worker_cls.return_value.start.assert_called_once()
            self.assertFalse(self.page._model_combo.isEnabled())
            self.page._on_model_clicked()  # second click cancels
            worker_cls.return_value.cancel.set.assert_called_once()
        with mock.patch("audio.stt.resolve_model_dir", return_value=None):
            self.page._on_model_done(False, "no network")
        self.assertIsNone(self.page._model_worker)
        self.assertIn("no network", self.page._model_status.text())
        self.assertTrue(self.page._model_combo.isEnabled())

    def test_a_finished_download_says_subtitles_can_start(self):
        with mock.patch("ui.subtitles_page.SpeechModelDownloadWorker"):
            self.page._on_model_clicked()
        self.page._on_model_done(True, "C:/models/whisper-small.en")
        self.assertIn("Можно запускать", self.page._status.text())

    def test_starting_during_a_download_waits(self):
        asked = []
        self.page.toggle_requested.connect(asked.append)
        with mock.patch("ui.subtitles_page.SpeechModelDownloadWorker"):
            self.page._on_model_clicked()
        self.page._btn_toggle.click()
        self.assertEqual(asked, [])
        self.assertIn("скачивается", self.page._status.text())


if __name__ == "__main__":
    unittest.main()
