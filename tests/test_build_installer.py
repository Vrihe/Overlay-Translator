"""
tests/test_build_installer.py — build.py finds the Inno Setup compiler, reads the app
version for the installer name, and the .iss script stays in step with the app.

No compiler is run: ISCC lookups use temp files, subprocess is mocked.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
import zipfile
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
        self.assertNotIn("TranslatorOverlay-app-", notes)

    def test_release_notes_with_app_zip(self):
        notes = build.release_notes(self.root, "1.2.0", "ab" * 32, "cd" * 32)
        self.assertIn("SHA-256 of `TranslatorOverlay-app-1.2.0.zip`: `" + "CD" * 32 + "`", notes)
        self.assertIn("in-app updater", notes)
        self.assertIn("AB" * 32, notes)

    def test_workflow_uploads_update_package(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("TranslatorOverlay-app-$version.zip", workflow)
        self.assertIn(f"dist/installer/{build.UPDATE_MANIFEST}", workflow)
        self.assertIn("$files = @($env:SETUP, $env:APPZIP, $env:MANIFEST)", workflow)
        self.assertIn("--app-sha256", workflow)


class TestRepositoryReleaseState(unittest.TestCase):
    """The real CHANGELOG.md and release.yml stay usable for the next release."""

    def test_current_version_is_releasable(self):
        version = build.app_version(ROOT)
        self.assertEqual(build.check_release_tag(ROOT, f"v{version}"), version)

    def test_changelog_has_an_unreleased_section(self):
        self.assertRegex((ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), r"(?m)^## \[Unreleased\]$")

    def test_workflow_uses_existing_build_flags(self):
        build_py = (ROOT / "build.py").read_text(encoding="utf-8")
        for name in ("release.yml", "deps-cache.yml"):
            workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
            flags = set(re.findall(r"build\.py (--[a-z-]+)", workflow))
            self.assertTrue(flags, name)
            for flag in flags:
                self.assertIn(f"'{flag}'", build_py, f"{name}: {flag}")

    def test_release_and_cache_install_the_lock_with_the_same_key(self):
        workflows = ROOT / ".github" / "workflows"
        release = (workflows / "release.yml").read_text(encoding="utf-8")
        cache = (workflows / "deps-cache.yml").read_text(encoding="utf-8")
        for text in (release, cache):
            self.assertIn("pip install -r requirements-lock.txt", text)
            self.assertIn("key: deps-layer-${{ runner.os }}-${{ steps.deps.outputs.fingerprint }}", text)
            self.assertIn('python-version: "3.12"', text)
        self.assertIn("branches: [main]", cache)

    def test_lock_pins_every_requirement(self):
        def norm(name):
            return re.sub(r"[-_.]+", "-", name).lower()

        lock = (ROOT / build.LOCK_FILE).read_text(encoding="utf-8")
        pins = {norm(m.group(1)) for m in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)==\S+$", lock)}
        lines = [ln for ln in lock.splitlines() if ln.strip() and not ln.startswith("#")]
        self.assertEqual(len(pins), len(lines))  # every line is name==version
        required = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^([A-Za-z0-9_.-]+)", required):
            self.assertIn(norm(match.group(1)), pins, match.group(1))


class TestRequirementsLock(unittest.TestCase):
    def test_lock_from_pip_report(self):
        report = {
            "environment": {"python_version": "3.12"},
            "install": [
                {"metadata": {"name": "numpy", "version": "2.5.4"}},
                {"metadata": {"name": "PyQt5", "version": "5.15.11"}},
            ],
        }
        text = build.lock_from_report(report)
        self.assertTrue(text.startswith("# Exact versions"))
        self.assertIn("Python 3.12", text)
        self.assertTrue(text.endswith("PyQt5==5.15.11\nnumpy==2.5.4\n"))

    def test_lock_is_part_of_the_deps_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "requirements.txt").write_text("numpy>=1\n", encoding="utf-8")
            before = build.deps_fingerprint(root)
            (root / build.LOCK_FILE).write_text("numpy==2.5.4\n", encoding="utf-8")
            pinned = build.deps_fingerprint(root)
            (root / build.LOCK_FILE).write_text("numpy==2.5.5\n", encoding="utf-8")
            self.assertNotEqual(before, pinned)
            self.assertNotEqual(build.deps_fingerprint(root), pinned)


class TestUpdatePackage(unittest.TestCase):
    """build.py splits the merged tree into layers and packs the app layer."""

    DEPS = ["_internal/numpy/core.pyd", "_internal/cv2/cv2.pyd", "_internal/msvcp140.dll"]
    APP = ["TranslatorOverlay.exe", "_internal/base_library.zip", "_internal/python312.dll"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.dist = self.root / "dist" / "TranslatorOverlay"
        for rel in self.APP + self.DEPS:
            path = self.dist / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(rel.encode())

    def _save(self, deps=None, fingerprint="f" * 16):
        with mock.patch.object(build, "runtime_tag", return_value="cp312-pyinstaller6.0"):
            build.save_layer_info(self.root, fingerprint, self.DEPS if deps is None else deps)

    def test_merge_returns_copied_deps_files_only(self):
        deps_internal = self.root / "dist" / "TranslatorOverlay_deps" / "_internal"
        files = {"numpy/new.pyd": b"deps", "python312.dll": b"deps", "base_library.zip": b"_internal/base_library.zip"}
        for rel, data in files.items():
            (deps_internal / rel).parent.mkdir(parents=True, exist_ok=True)
            (deps_internal / rel).write_bytes(data)
        deps = build.merge_deps_into_app(self.root)
        # python312.dll differs: the app's copy wins and stays app-layer. base_library.zip
        # is byte-identical in both layers, so it counts as deps.
        self.assertEqual(sorted(deps), ["_internal/base_library.zip", "_internal/numpy/new.pyd"])
        self.assertEqual((self.dist / "_internal" / "python312.dll").read_bytes(), b"_internal/python312.dll")

    def test_app_layer_excludes_deps_but_keeps_msvc_runtime(self):
        files = build.app_layer_files(self.dist, self.DEPS)
        self.assertEqual(files, sorted(self.APP + ["_internal/msvcp140.dll"]))

    def test_package_zip_and_manifest(self):
        self._save()
        zip_path, manifest_path = build.build_update_package(self.root, "1.4.0")
        self.assertEqual(zip_path.name, "TranslatorOverlay-app-1.4.0.zip")
        self.assertEqual(manifest_path.name, build.UPDATE_MANIFEST)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = sorted(self.APP + ["_internal/msvcp140.dll"])
        with zipfile.ZipFile(zip_path) as zf:
            self.assertEqual(sorted(zf.namelist()), expected)
            self.assertEqual(zf.read("TranslatorOverlay.exe"), b"TranslatorOverlay.exe")
        self.assertEqual(manifest["version"], "1.4.0")
        self.assertEqual(manifest["runtime"], "cp312-pyinstaller6.0")
        self.assertEqual(manifest["app_files"], expected)
        self.assertEqual(manifest["app_zip"]["name"], zip_path.name)
        self.assertEqual(manifest["app_zip"]["size"], zip_path.stat().st_size)
        self.assertEqual(manifest["app_zip"]["sha256"], hashlib.sha256(zip_path.read_bytes()).hexdigest())

    def test_fingerprint_follows_deps_content(self):
        def fingerprint(**kwargs):
            self._save(**kwargs)
            _, manifest_path = build.build_update_package(self.root, "1.4.0")
            return json.loads(manifest_path.read_text(encoding="utf-8"))["deps_fingerprint"]

        same = fingerprint()
        self.assertEqual(fingerprint(), same)
        # The package-list fingerprint does not matter, only the files do.
        self.assertEqual(fingerprint(fingerprint="0" * 16), same)
        self.assertNotEqual(fingerprint(deps=self.DEPS[1:]), same)
        # Deps files removed by post_build_cleanup do not count, nor does the VC++ runtime.
        self.assertEqual(fingerprint(deps=self.DEPS + ["_internal/scipy/tests/x.py"]), same)
        (self.dist / "_internal" / "msvcp140.dll").write_bytes(b"newer")
        self.assertEqual(fingerprint(), same)
        # A .pyc header (source mtime) does not: a fresh deps build keeps the fingerprint.
        pyc = self.dist / "_internal" / "numpy" / "mod.pyc"
        pyc.write_bytes(b"H" * 16 + b"code")
        with_pyc = fingerprint(deps=self.DEPS + ["_internal/numpy/mod.pyc"])
        pyc.write_bytes(b"h" * 16 + b"code")
        self.assertEqual(fingerprint(deps=self.DEPS + ["_internal/numpy/mod.pyc"]), with_pyc)
        pyc.write_bytes(b"h" * 16 + b"edoc")
        self.assertNotEqual(fingerprint(deps=self.DEPS + ["_internal/numpy/mod.pyc"]), with_pyc)
        # A changed deps file does.
        (self.dist / "_internal" / "numpy" / "core.pyd").write_bytes(b"rebuilt")
        self.assertNotEqual(fingerprint(), same)

    def test_needs_layer_info(self):
        with self.assertRaisesRegex(RuntimeError, "layers.json"):
            build.build_update_package(self.root, "1.4.0")

    def test_runtime_changes_the_deps_fingerprint(self):
        with mock.patch.object(build, "runtime_tag", return_value="cp312-pyinstaller6.0"):
            before = build.deps_fingerprint(self.root)
        with mock.patch.object(build, "runtime_tag", return_value="cp313-pyinstaller6.0"):
            self.assertNotEqual(build.deps_fingerprint(self.root), before)

    def test_iss_installs_the_manifest(self):
        self.assertIn(rf'Source: "{{#RootDir}}\dist\installer\{build.UPDATE_MANIFEST}"; DestDir: "{{app}}"', ISS)


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
