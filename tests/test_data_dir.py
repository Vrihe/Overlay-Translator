"""The storage folder (Settings → Storage): where models and other downloads go."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
from audio import stt, stt_download
from translate import cuda_download, nllb_backend, nllb_models


def _with_data_dir(value: str):
    real_get = __import__("settings.config_manager", fromlist=["get"]).get
    return patch("settings.config_manager.get", lambda key: value if key == "data_dir" else real_get(key))


class TestDataDir(unittest.TestCase):
    def test_default_is_user_data_dir(self):
        with _with_data_dir(""):
            self.assertEqual(config.DATA_DIR, Path(config.USER_DATA_DIR))

    def test_custom_folder_is_used(self):
        with tempfile.TemporaryDirectory() as tmp, _with_data_dir(tmp):
            self.assertEqual(config.DATA_DIR, Path(tmp))
            self.assertEqual(stt_download.download_dir("small"), Path(tmp) / "models" / "whisper-small")
            self.assertEqual(nllb_models.download_root(), Path(tmp) / "models")

    def test_models_are_still_found_in_the_old_folder(self):
        with tempfile.TemporaryDirectory() as tmp, _with_data_dir(tmp):
            roots = nllb_backend._models_roots()
            self.assertIn(Path(tmp) / "models", roots)
            self.assertIn(Path(config.USER_DATA_DIR) / "models", roots)
            self.assertLess(roots.index(Path(tmp) / "models"), roots.index(Path(config.USER_DATA_DIR) / "models"))
            dirs = stt.model_dirs("small")
            self.assertIn(Path(tmp) / "models" / "whisper-small", dirs)
            self.assertIn(Path(config.USER_DATA_DIR) / "models" / "whisper-small", dirs)

    def test_no_duplicate_roots_by_default(self):
        with _with_data_dir(""):
            roots = nllb_backend._models_roots()
            self.assertEqual(len(roots), len(set(roots)))

    def test_data_path_prefers_the_new_folder(self):
        with tempfile.TemporaryDirectory() as tmp, _with_data_dir(tmp):
            self.assertEqual(config.data_path("cuda"), Path(tmp) / "cuda")
            self.assertEqual(cuda_download.cuda_dir(), Path(tmp) / "cuda")

    def test_data_path_falls_back_to_existing_old_folder(self):
        with tempfile.TemporaryDirectory() as new, tempfile.TemporaryDirectory() as old:
            (Path(old) / "cuda").mkdir()
            with _with_data_dir(new), patch.object(type(config), "USER_DATA_DIR", old):
                self.assertEqual(config.data_path("cuda"), Path(old) / "cuda")
                (Path(new) / "cuda").mkdir()
                self.assertEqual(config.data_path("cuda"), Path(new) / "cuda")


if __name__ == "__main__":
    unittest.main()
