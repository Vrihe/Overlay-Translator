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
        # No real install may leak in: each test points these at its temp dir.
        # Case-insensitive: Windows env names are, and CI runners spell them in capitals.
        hidden = {"ISCC", "PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"}
        env = {k: v for k, v in os.environ.items() if k.upper() not in hidden}
        for patcher in (
            mock.patch.dict(os.environ, env, clear=True),
            mock.patch.object(shutil, "which", return_value=None),
        ):
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
        with (
            mock.patch.object(build, "find_iscc", return_value=Path("C:/Inno/ISCC.exe")),
            mock.patch.object(build.subprocess, "run") as run,
        ):
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
        with (
            mock.patch.object(build, "find_iscc", return_value=Path("C:/Inno/ISCC.exe")),
            mock.patch.object(build.subprocess, "run") as run,
        ):
            run.return_value.returncode = 2
            with self.assertRaises(RuntimeError):
                build.build_installer(ROOT)


_CHANGELOG = """# Changelog

## [Unreleased]

### Added
- Something new.

## [1.2.0] - 2026-11-01

### Fixed
- A bug.

## [1.1.0] - 2026-10-30

### Added
- A feature.

[Unreleased]: https://example.invalid/compare/v1.2.0...HEAD
[1.2.0]: https://example.invalid/v1.2.0
"""


class TestReleaseHelpers(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "CHANGELOG.md").write_text(_CHANGELOG, encoding="utf-8")
        self._version("1.2.0")

    def _version(self, version: str) -> None:
        (self.root / "config.py").write_text(f'class C:\n    APP_VERSION = "{version}"\n', encoding="utf-8")

    def test_section_stops_at_the_next_version(self):
        self.assertEqual(build.changelog_section(self.root, "1.2.0"), "### Fixed\n- A bug.")

    def test_last_section_stops_at_the_link_list(self):
        self.assertEqual(build.changelog_section(self.root, "1.1.0"), "### Added\n- A feature.")

    def test_missing_section_is_empty(self):
        self.assertEqual(build.changelog_section(self.root, "9.9.9"), "")
        self.assertEqual(build.changelog_section(self.root, "1.2"), "")

    def test_matching_tag_passes(self):
        self.assertEqual(build.check_release_tag(self.root, "v1.2.0"), "1.2.0")

    def test_tag_must_equal_app_version(self):
        for tag in ("v1.1.0", "1.2.0", "v1.2.0-rc1"):
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                build.check_release_tag(self.root, tag)

    def test_version_needs_a_changelog_section(self):
        self._version("1.3.0")
        with self.assertRaisesRegex(RuntimeError, "CHANGELOG"):
            build.check_release_tag(self.root, "v1.3.0")

    def test_version_must_be_semver(self):
        self._version("1.2")
        with self.assertRaisesRegex(RuntimeError, "X.Y.Z"):
            build.check_release_tag(self.root, "v1.2")

    def test_release_notes(self):
        notes = build.release_notes(self.root, "1.2.0", "ab" * 32)
        self.assertTrue(notes.startswith("### Fixed\n- A bug.\n"))
        self.assertIn("TranslatorOverlay-Setup-1.2.0.exe", notes)
        self.assertIn("Run anyway", notes)
        self.assertIn("AB" * 32, notes)
        self.assertNotIn("SHA-256", build.release_notes(self.root, "1.2.0"))


class TestRepositoryReleaseState(unittest.TestCase):
    """The real CHANGELOG.md and release.yml stay usable for the next release."""

    def test_current_version_is_releasable(self):
        version = build.app_version(ROOT)
        self.assertEqual(build.check_release_tag(ROOT, f"v{version}"), version)

    def test_changelog_has_an_unreleased_section(self):
        self.assertRegex((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), r"(?m)^## \[Unreleased\]$")

    def test_workflow_uses_existing_build_flags(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        build_py = (ROOT / "build.py").read_text(encoding="utf-8")
        flags = set(re.findall(r"build\.py (--[a-z-]+)", workflow))
        self.assertTrue(flags)
        for flag in flags:
            self.assertIn(f"'{flag}'", build_py, flag)


class TestIssScript(unittest.TestCase):
    """Values the script duplicates from the app must not drift."""

    def test_mutex_matches_single_instance(self):
        self.assertIn(f"AppMutex=Local\\{single_instance.DEFAULT_NAME}.Mutex", ISS)

    def test_app_user_model_id_matches_main(self):
        aumid = re.search(
            r'SetCurrentProcessExplicitAppUserModelID\("([^"]+)"\)', (ROOT / "main.py").read_text(encoding="utf-8")
        ).group(1)
        self.assertEqual(re.findall(r'AppUserModelID: "([^"]+)"', ISS), [aumid, aumid])

    def test_output_name_matches_build_py(self):
        self.assertIn("OutputBaseFilename=TranslatorOverlay-Setup-{#AppVersion}", ISS)
        self.assertIn(r"OutputDir={#RootDir}\dist\installer", ISS)


if __name__ == "__main__":
    unittest.main()
