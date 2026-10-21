"""
tests/test_build_installer.py — build.py finds the Inno Setup compiler, reads the app
version for the installer name, and the .iss script stays in step with the app.

No compiler is run: ISCC lookups use temp files, subprocess is mocked.
"""

import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build
import single_instance

ROOT = Path(__file__).resolve().parents[1]
ISS = (ROOT / "installer" / "TranslatorOverlay.iss").read_text(encoding="utf-8")


class TestFindIscc(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        env = {k: v for k, v in os.environ.items() if k != "ISCC"}
        for patcher in (mock.patch.dict(os.environ, env, clear=True),
                        mock.patch.object(shutil, "which", return_value=None)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _fake_iscc(self, *parts) -> Path:
        path = self.tmp.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return path

    def test_env_variable_wins(self):
        exe = self._fake_iscc("custom", "ISCC.exe")
        with mock.patch.dict(os.environ, {"ISCC": str(exe)}):
            self.assertEqual(build.find_iscc(), exe)

    def test_default_install_dir(self):
        exe = self._fake_iscc("pf86", "Inno Setup 6", "ISCC.exe")
        with mock.patch.dict(os.environ, {"ProgramFiles(x86)": str(self.tmp / "pf86")}):
            self.assertEqual(build.find_iscc(), exe)

    def test_per_user_install_dir(self):
        exe = self._fake_iscc("local", "Programs", "Inno Setup 6", "ISCC.exe")
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp / "local")}):
            self.assertEqual(build.find_iscc(), exe)

    def test_not_installed(self):
        self.assertIsNone(build.find_iscc())


class TestBuildInstaller(unittest.TestCase):

    def test_app_version_matches_config(self):
        import config
        self.assertEqual(build.app_version(ROOT), config.APP_VERSION)

    def test_passes_version_and_script(self):
        with mock.patch.object(build, "find_iscc", return_value=Path("C:/Inno/ISCC.exe")), \
                mock.patch.object(build.subprocess, "run") as run:
            run.return_value.returncode = 0
            setup = build.build_installer(ROOT)
        cmd = run.call_args.args[0]
        version = build.app_version(ROOT)
        self.assertIn(f"/DAppVersion={version}", cmd)
        self.assertEqual(Path(cmd[-1]), ROOT / "installer" / "TranslatorOverlay.iss")
        self.assertEqual(setup.name, f"TranslatorOverlay-Setup-{version}.exe")

    def test_missing_compiler_is_a_clear_error(self):
        with mock.patch.object(build, "find_iscc", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Inno Setup"):
                build.build_installer(ROOT)

    def test_compiler_failure_is_an_error(self):
        with mock.patch.object(build, "find_iscc", return_value=Path("C:/Inno/ISCC.exe")), \
                mock.patch.object(build.subprocess, "run") as run:
            run.return_value.returncode = 2
            with self.assertRaises(RuntimeError):
                build.build_installer(ROOT)


class TestIssScript(unittest.TestCase):
    """Values the script duplicates from the app must not drift."""

    def test_mutex_matches_single_instance(self):
        self.assertIn(f"AppMutex=Local\\{single_instance.DEFAULT_NAME}.Mutex", ISS)

    def test_app_user_model_id_matches_main(self):
        aumid = re.search(r'SetCurrentProcessExplicitAppUserModelID\("([^"]+)"\)',
                          (ROOT / "main.py").read_text(encoding="utf-8")).group(1)
        self.assertEqual(re.findall(r'AppUserModelID: "([^"]+)"', ISS), [aumid, aumid])

    def test_output_name_matches_build_py(self):
        self.assertIn("OutputBaseFilename=TranslatorOverlay-Setup-{#AppVersion}", ISS)
        self.assertIn(r"OutputDir={#RootDir}\dist\installer", ISS)


if __name__ == "__main__":
    unittest.main()
