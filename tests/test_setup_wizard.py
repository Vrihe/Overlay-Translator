"""
tests/test_setup_wizard.py — the first-run wizard: when it shows, what it saves, the
offline model list, and that closing it never drops a running worker.

settings.json lives in a temp dir; no network (the version list and local models are
stubbed), no model is downloaded or loaded.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QApplication

from settings import config_manager
from translate.nllb_models import LocalModel, RemoteVersion
from ui import setup_wizard
from ui.setup_wizard import (
    MODE_LLM, MODE_OFFLINE, MODE_ONLINE, SetupWizard, apply_choice, build_entries,
    preferred_index,
)

_APP = QApplication.instance() or QApplication(sys.argv[:1])


class _TempSettings(unittest.TestCase):
    """A private settings.json for each test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.file = Path(self._tmp.name) / "settings.json"
        patcher = mock.patch.object(config_manager, "_CONFIG_FILE", self.file)
        patcher.start()
        self.addCleanup(patcher.stop)
        old_cache = config_manager._cache
        config_manager._cache = None
        self.addCleanup(setattr, config_manager, "_cache", old_cache)

    def write(self, data: dict) -> None:
        self.file.write_text(json.dumps(data), encoding="utf-8")
        config_manager._cache = None

    def saved(self) -> dict:
        return json.loads(self.file.read_text(encoding="utf-8"))


class TestFirstRunPending(_TempSettings):

    def test_fresh_install_shows_the_wizard(self):
        self.assertTrue(config_manager.first_run_pending())
        self.assertFalse(self.file.exists())  # deciding writes nothing

    def test_upgrade_from_a_version_without_the_wizard_skips_it(self):
        self.write({"translation_backend": "deepl", "hotkey": "ctrl+shift+r"})
        self.assertFalse(config_manager.first_run_pending())
        self.assertTrue(self.saved()["first_run_done"])
        self.assertEqual(self.saved()["translation_backend"], "deepl")

    def test_unfinished_wizard_shows_again(self):
        self.write({**config_manager.DEFAULTS, "first_run_done": False})
        self.assertTrue(config_manager.first_run_pending())

    def test_done(self):
        self.write({**config_manager.DEFAULTS, "first_run_done": True})
        self.assertFalse(config_manager.first_run_pending())

    def test_corrupted_file_shows_the_wizard(self):
        self.file.write_text("{not json", encoding="utf-8")
        self.assertTrue(config_manager.first_run_pending())


class TestApplyChoice(_TempSettings):

    def test_each_mode_sets_its_backend(self):
        for mode, backend in ((MODE_ONLINE, "google"), (MODE_LLM, "api"), (MODE_OFFLINE, "nllb")):
            apply_choice(mode, "C:/models/nllb-v2-game" if mode == MODE_OFFLINE else "")
            saved = self.saved()
            self.assertEqual(saved["translation_backend"], backend, mode)
            self.assertTrue(saved["first_run_done"], mode)

    def test_offline_saves_the_model_path(self):
        apply_choice(MODE_OFFLINE, "C:/models/nllb-v2-game")
        self.assertEqual(self.saved()["nllb_model_path"], "C:/models/nllb-v2-game")

    def test_online_keeps_an_existing_model_path(self):
        self.write({**config_manager.DEFAULTS, "nllb_model_path": "C:/models/x"})
        apply_choice(MODE_ONLINE)
        self.assertEqual(self.saved()["nllb_model_path"], "C:/models/x")


class TestOfflineEntries(unittest.TestCase):
    V0, V2 = RemoteVersion("v0-base", "a" * 40), RemoteVersion("v2-game", "c" * 40)

    def test_local_first_and_downloaded_tags_not_offered_again(self):
        local = [LocalModel(Path("C:/m/nllb-v2-game"), "v2-game")]
        entries = build_entries(local, [self.V0, self.V2])
        self.assertEqual([data[0] for _label, data in entries], ["local", "remote"])
        self.assertEqual(entries[0][1][1], str(Path("C:/m/nllb-v2-game")))
        self.assertIs(entries[1][1][1], self.V0)

    def test_without_the_remote_list_only_local(self):
        local = [LocalModel(Path("C:/m/custom-ct2"), None)]
        entries = build_entries(local, None)
        self.assertEqual(len(entries), 1)
        self.assertIn("custom-ct2", entries[0][0])

    def test_preselects_the_pinned_build(self):
        entries = build_entries([], [self.V0, self.V2])
        self.assertEqual(preferred_index(entries, "a" * 40), 0)

    def test_otherwise_the_newest(self):
        entries = build_entries([], [self.V0, self.V2])
        self.assertEqual(preferred_index(entries, "f" * 40), 1)
        self.assertEqual(preferred_index([], "f" * 40), -1)


class _IdleVersionsWorker:
    """Stands in for NllbVersionsWorker: never touches the network."""

    def __init__(self, *_args):
        self.finished_with_versions = mock.Mock()

    def start(self):
        pass


class TestWizardFlow(_TempSettings):

    def setUp(self):
        super().setUp()
        for patcher in (
            mock.patch.object(setup_wizard, "NllbVersionsWorker", _IdleVersionsWorker),
            mock.patch("translate.nllb_models.list_local_models", return_value=[]),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.wizard = SetupWizard()
        self.addCleanup(self.wizard.deleteLater)

    def _choose(self, mode: str) -> None:
        for button in self.wizard._mode_group.buttons():
            if button.property("mode") == mode:
                button.setChecked(True)

    def test_default_is_online_and_start_saves_it(self):
        with mock.patch.object(self.wizard, "accept") as accept:
            self.wizard._on_next()   # mode → done
            self.assertEqual(self.wizard._pages.currentIndex(), 2)
            self.wizard._on_next()   # start
        accept.assert_called_once()
        self.assertEqual(self.saved()["translation_backend"], "google")
        self.assertTrue(self.saved()["first_run_done"])

    def test_llm_choice(self):
        self._choose(MODE_LLM)
        with mock.patch.object(self.wizard, "accept"):
            self.wizard._on_next()
            self.wizard._on_next()
        self.assertEqual(self.saved()["translation_backend"], "api")

    def test_offline_needs_a_model_on_disk_before_next(self):
        self._choose(MODE_OFFLINE)
        self.wizard._on_next()
        self.assertEqual(self.wizard._pages.currentIndex(), 1)
        self.wizard._remote_versions = [RemoteVersion("v2-game", "c" * 40)]
        self.wizard._load_offline_entries()
        self.assertFalse(self.wizard._btn_next.isEnabled())
        self.assertIsNone(self.wizard._download_worker)  # nothing starts on its own
        self.wizard._on_next()
        self.assertEqual(self.wizard._pages.currentIndex(), 1)
        self.assertFalse(self.file.exists())

    def test_offline_with_a_local_model(self):
        self._choose(MODE_OFFLINE)
        local = [LocalModel(Path("C:/m/nllb-v2-game"), "v2-game")]
        with mock.patch("translate.nllb_models.list_local_models", return_value=local):
            self.wizard._on_next()
            self.assertTrue(self.wizard._btn_next.isEnabled())
            with mock.patch.object(self.wizard, "accept"):
                self.wizard._on_next()   # offline → done
                self.wizard._on_next()   # start
        saved = self.saved()
        self.assertEqual(saved["translation_backend"], "nllb")
        self.assertEqual(saved["nllb_model_path"], str(Path("C:/m/nllb-v2-game")))

    def test_closing_writes_nothing(self):
        self.wizard.reject()
        self.assertFalse(self.file.exists())


class TestClosingKeepsRunningWorkers(unittest.TestCase):

    def test_running_download_is_cancelled_and_parked(self):
        worker = mock.Mock(spec=QThread)
        worker.isRunning.return_value = True
        worker.cancel = mock.Mock()
        worker.finished_with_status = mock.Mock()
        worker.finished_with_versions = None
        worker.progress_changed = mock.Mock()
        try:
            setup_wizard._keep_until_finished(worker)
            worker.cancel.set.assert_called_once()
            worker.setParent.assert_called_once_with(None)
            self.assertIn(worker, setup_wizard._finishing)
            on_finished = worker.finished.connect.call_args.args[0]
            on_finished()
            self.assertNotIn(worker, setup_wizard._finishing)
        finally:
            setup_wizard._finishing.discard(worker)


if __name__ == "__main__":
    unittest.main()
