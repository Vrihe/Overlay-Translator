"""
tests/test_audio_packages.py — audio/packages.py: what is missing, and the pip install.

Nothing is imported or installed: ``find_spec`` and ``subprocess.Popen`` are faked.
"""

import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from audio import packages


class _Process:
    def __init__(self, lines=(), returncode=0, hang=False):
        self.stdout = iter(lines)
        self.returncode = returncode
        self._hang = hang
        self.terminated = False

    def poll(self):
        return None if self._hang and not self.terminated else self.returncode

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return self.returncode


class TestMissing(unittest.TestCase):
    def test_names_of_packages_that_cannot_be_found(self):
        found = {"faster_whisper": object(), "av": object()}
        with mock.patch("importlib.util.find_spec", side_effect=lambda name: found.get(name)):
            self.assertEqual(packages.missing_packages(), ["tokenizers", "PyAudioWPatch"])

    def test_nothing_missing(self):
        with mock.patch("importlib.util.find_spec", return_value=object()):
            self.assertEqual(packages.missing_packages(), [])


class TestCanInstall(unittest.TestCase):
    def test_a_packaged_build_cannot(self):
        with mock.patch.object(sys, "frozen", True, create=True):
            self.assertFalse(packages.can_install())

    def test_the_requirements_file_is_in_the_project(self):
        self.assertTrue(packages.requirements_file().is_file())
        self.assertTrue(packages.can_install())

    def test_without_the_file_it_cannot(self):
        with mock.patch.object(packages, "requirements_file", return_value=Path("nowhere/requirements-voice.txt")):
            self.assertFalse(packages.can_install())


class TestInstall(unittest.TestCase):
    def run_install(self, process, missing_after=(), cancel=None):
        with (
            mock.patch("subprocess.Popen", return_value=process) as popen,
            mock.patch.object(packages, "missing_packages", return_value=list(missing_after)),
        ):
            packages.install(cancel=cancel)
        return popen

    def test_pip_runs_without_dependency_resolution(self):
        popen = self.run_install(_Process(["Successfully installed faster-whisper"]))
        command = popen.call_args.args[0]
        self.assertEqual(command[1:4], ["-m", "pip", "install"])
        self.assertIn("--no-deps", command)  # otherwise onnxruntime-directml would be overwritten
        self.assertTrue(command[-1].endswith("requirements-voice.txt"))

    def test_a_pip_failure_reports_its_last_line(self):
        process = _Process(["Collecting x", "ERROR: no matching distribution", ""], returncode=1)
        with self.assertRaises(packages.PackagesInstallError) as ctx:
            self.run_install(process)
        self.assertIn("no matching distribution", str(ctx.exception))

    def test_packages_still_missing_after_a_clean_pip_run_are_an_error(self):
        with self.assertRaises(packages.PackagesInstallError) as ctx:
            self.run_install(_Process(), missing_after=["av"])
        self.assertIn("av", str(ctx.exception))

    def test_cancel_stops_pip(self):
        cancel = threading.Event()
        cancel.set()
        process = _Process(hang=True)
        with self.assertRaises(packages.InstallCancelled):
            self.run_install(process, cancel=cancel)
        self.assertTrue(process.terminated)

    def test_a_packaged_build_refuses(self):
        with mock.patch.object(packages, "can_install", return_value=False):
            with self.assertRaises(packages.PackagesInstallError):
                packages.install()


if __name__ == "__main__":
    unittest.main()
