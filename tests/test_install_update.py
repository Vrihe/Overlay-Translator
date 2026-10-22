"""
tests/test_install_update.py — one-click update: picking the installer and its
SHA-256 from a GitHub release, the version check, the verified download, the hidden
waiter that runs the setup after the app has exited, and the setup's relaunch hook.

No network and no process is started: urlopen and Popen are mocked.
"""

import base64
import hashlib
import io
import json
import re
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import config
from updater import install_update
from updater.install_update import (
    INSTALLER_ARGS,
    DownloadCancelled,
    Release,
    download_setup,
    release_from_json,
    waiter_script,
)

ROOT = Path(__file__).resolve().parents[1]
SHA = "ab" * 32


def _release_json(tag="v9.9.9", digest=f"sha256:{SHA}", body="", name="TranslatorOverlay-Setup-9.9.9.exe"):
    return {
        "tag_name": tag,
        "html_url": f"https://example.invalid/{tag}",
        "body": body,
        "assets": [
            {"name": "notes.txt", "browser_download_url": "x", "size": 1},
            {"name": name, "browser_download_url": "https://example.invalid/setup.exe", "size": 123, "digest": digest},
        ],
    }


class _Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class TestReleaseFromJson(unittest.TestCase):
    def test_uses_githubs_asset_digest(self):
        rel = release_from_json(_release_json())
        self.assertEqual(
            (rel.tag, rel.setup_name, rel.sha256, rel.size), ("v9.9.9", "TranslatorOverlay-Setup-9.9.9.exe", SHA, 123)
        )

    def test_falls_back_to_the_checksum_in_the_notes(self):
        body = f"Notes\n\nSHA-256 of `TranslatorOverlay-Setup-9.9.9.exe`: `{SHA.upper()}`\n"
        rel = release_from_json(_release_json(digest=None, body=body))
        self.assertEqual(rel.sha256, SHA)

    def test_no_checksum_means_no_update(self):
        self.assertIsNone(release_from_json(_release_json(digest=None, body="no checksum")))

    def test_no_installer_asset(self):
        self.assertIsNone(release_from_json(_release_json(name="something-else.exe")))


class TestLatestRelease(unittest.TestCase):
    def _latest(self, tag, app_version):
        data = json.dumps(_release_json(tag=tag)).encode()
        with (
            mock.patch.object(install_update.urllib.request, "urlopen", return_value=_Response(data)),
            mock.patch.object(type(config), "APP_VERSION", app_version, create=False),
        ):
            return install_update.latest_release()

    def test_newer_release(self):
        self.assertEqual(self._latest("v1.2.0", "1.1.0").tag, "v1.2.0")

    def test_same_or_older_release(self):
        self.assertIsNone(self._latest("v1.1.0", "1.1.0"))
        self.assertIsNone(self._latest("v1.0.0", "1.1.0"))


class TestDownload(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def _download(self, data: bytes, sha: str, cancel=None):
        rel = Release(
            "v9.9.9", "u", "https://example.invalid/s.exe", "TranslatorOverlay-Setup-9.9.9.exe", sha, len(data)
        )
        with (
            mock.patch.object(install_update.urllib.request, "urlopen", return_value=_Response(data)),
            mock.patch.object(install_update, "_CHUNK", 16),
        ):
            return download_setup(rel, dest_dir=self.dir, cancel=cancel)

    def test_verified_download(self):
        data = b"installer bytes" * 10
        path = self._download(data, hashlib.sha256(data).hexdigest())
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["TranslatorOverlay-Setup-9.9.9.exe"])

    def test_checksum_mismatch_keeps_nothing(self):
        with self.assertRaisesRegex(OSError, "Checksum"):
            self._download(b"tampered", SHA)
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_cancel_keeps_nothing(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(DownloadCancelled):
            self._download(b"x" * 100, SHA, cancel=cancel)
        self.assertEqual(list(self.dir.iterdir()), [])


class TestLaunch(unittest.TestCase):
    def test_waiter_waits_for_the_app_then_runs_the_setup_silently(self):
        script = waiter_script(Path(r"C:\Temp\it's here\Setup.exe"), 4242)
        self.assertTrue(script.startswith("Wait-Process -Id 4242"))
        self.assertIn(r"'C:\Temp\it''s here\Setup.exe'", script)  # PowerShell quote escaping
        for arg in INSTALLER_ARGS:
            self.assertIn(f"'{arg}'", script)
        self.assertLess(script.index("Wait-Process"), script.index("Start-Process"))

    @unittest.skipUnless(sys.platform == "win32", "Windows process creation flags")
    def test_launch_starts_a_hidden_encoded_powershell(self):
        with mock.patch.object(install_update.subprocess, "Popen") as popen:
            install_update.launch_installer(Path(r"C:\Temp\Setup.exe"), pid=7)
        cmd = popen.call_args.args[0]
        self.assertEqual(cmd[0], "powershell.exe")
        self.assertIn("Hidden", cmd)
        flags = popen.call_args.kwargs["creationflags"]
        self.assertTrue(flags & install_update.subprocess.CREATE_NO_WINDOW)
        # PowerShell started detached (no console at all) silently never runs the script.
        self.assertFalse(flags & install_update.subprocess.DETACHED_PROCESS)
        decoded = base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertEqual(decoded, waiter_script(Path(r"C:\Temp\Setup.exe"), 7))

    def test_only_an_installed_app_updates_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "TranslatorOverlay.exe"
            exe.write_bytes(b"")
            with (
                mock.patch.object(install_update.sys, "frozen", True, create=True),
                mock.patch.object(install_update.sys, "executable", str(exe)),
            ):
                self.assertFalse(install_update.can_self_update())  # copied dist folder
                (Path(tmp) / "unins000.exe").write_bytes(b"")
                self.assertEqual(install_update.can_self_update(), install_update.os.name == "nt")
        self.assertFalse(install_update.can_self_update())  # source run: not frozen


APP_SHA = "cd" * 32
FP = "f" * 16
RUNTIME = "cp312-pyinstaller6.21.0"


def _manifest(version="9.9.9", fingerprint=FP, runtime=RUNTIME, files=None, zip_sha=APP_SHA, **extra):
    data = {
        "version": version,
        "deps_fingerprint": fingerprint,
        "runtime": runtime,
        "app_zip": {"name": f"TranslatorOverlay-app-{version}.zip", "sha256": zip_sha, "size": 10},
        "app_files": files if files is not None else ["TranslatorOverlay.exe", "_internal/base_library.zip"],
    }
    data.update(extra)
    return data


def _full_release_json(body=""):
    data = _release_json(body=body)
    data["assets"] += [
        {"name": "update-manifest.json", "browser_download_url": "https://example.invalid/m.json", "size": 5},
        {
            "name": "TranslatorOverlay-app-9.9.9.zip",
            "browser_download_url": "https://example.invalid/app.zip",
            "size": 10,
            "digest": f"sha256:{APP_SHA}",
        },
    ]
    return data


class TestReleaseAppAssets(unittest.TestCase):
    def test_app_zip_and_manifest_are_picked_up(self):
        rel = release_from_json(_full_release_json())
        self.assertEqual(rel.manifest_url, "https://example.invalid/m.json")
        self.assertEqual((rel.app_name, rel.app_sha256, rel.app_size), ("TranslatorOverlay-app-9.9.9.zip", APP_SHA, 10))

    def test_notes_checksums_are_matched_by_file_name(self):
        data = _full_release_json(
            body=(
                f"SHA-256 of `TranslatorOverlay-Setup-9.9.9.exe`: `{SHA.upper()}`\n\n"
                f"SHA-256 of `TranslatorOverlay-app-9.9.9.zip`: `{APP_SHA.upper()}`\n"
            )
        )
        for asset in data["assets"]:
            asset.pop("digest", None)
        rel = release_from_json(data)
        self.assertEqual((rel.sha256, rel.app_sha256), (SHA, APP_SHA))

    def test_old_release_without_app_assets(self):
        rel = release_from_json(_release_json())
        self.assertEqual((rel.manifest_url, rel.app_url, rel.app_sha256), ("", "", ""))


class TestManifest(unittest.TestCase):
    def test_valid_and_unknown_fields_ignored(self):
        data = install_update.parse_manifest(json.dumps(_manifest(extra_field=1)))
        self.assertEqual(data["deps_fingerprint"], FP)

    def test_broken_or_incomplete(self):
        for text in ("{", "[]", json.dumps(_manifest(fingerprint="")), json.dumps(_manifest(files=["a.dll"]))):
            self.assertIsNone(install_update.parse_manifest(text), text)

    def test_paths_outside_the_install_dir_are_refused(self):
        for bad in ("../evil.dll", "/abs.dll", "C:/x.dll", "_internal\\x.dll", "./x", ""):
            files = ["TranslatorOverlay.exe", bad]
            self.assertIsNone(install_update.parse_manifest(json.dumps(_manifest(files=files))), bad)

    def test_installed_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(install_update.installed_manifest(Path(tmp)))
            (Path(tmp) / "update-manifest.json").write_text(json.dumps(_manifest()), encoding="utf-8")
            self.assertEqual(install_update.installed_manifest(Path(tmp))["version"], "9.9.9")


class TestChooseUpdatePath(unittest.TestCase):
    def setUp(self):
        self.release = release_from_json(_full_release_json())
        self.installed = _manifest(version="1.0.0")

    def _choose(self, installed="default", new="default", release=None):
        installed = self.installed if installed == "default" else installed
        new = _manifest() if new == "default" else new
        return install_update.choose_update_path(installed, new, release or self.release, "1.0.0")

    def test_same_deps_layer_takes_the_app_zip(self):
        self.assertEqual(self._choose(), "app")

    def test_everything_else_takes_the_installer(self):
        self.assertEqual(self._choose(new=_manifest(fingerprint="0" * 16)), "full")
        self.assertEqual(self._choose(new=_manifest(runtime="cp313-pyinstaller6.21.0")), "full")
        self.assertEqual(self._choose(installed=None), "full")
        self.assertEqual(self._choose(new=None), "full")
        # The installed manifest belongs to another version (e.g. a copied folder).
        self.assertEqual(self._choose(installed=_manifest(version="0.9.0")), "full")
        # The manifest describes another zip or another version than the release.
        self.assertEqual(self._choose(new=_manifest(zip_sha="ef" * 32)), "full")
        self.assertEqual(self._choose(new=_manifest(version="9.9.8")), "full")
        self.assertEqual(self._choose(release=release_from_json(_release_json())), "full")

    def test_plan_removes_files_the_new_version_no_longer_ships(self):
        installed = _manifest(files=["TranslatorOverlay.exe", "_internal/old.pyd", "_internal/kept.pyd"])
        new = _manifest(files=["TranslatorOverlay.exe", "_internal/kept.pyd", "_internal/new.pyd"])
        files, remove = install_update.app_update_plan(installed, new)
        self.assertEqual(files, ["TranslatorOverlay.exe", "_internal/kept.pyd", "_internal/new.pyd"])
        self.assertEqual(remove, ["_internal/old.pyd"])


def _zip_bytes(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(name, name)
    return buf.getvalue()


class TestPrepareUpdate(unittest.TestCase):
    """prepare_update picks the app zip when it can and falls back to the installer."""

    FILES = ["TranslatorOverlay.exe", "_internal/base_library.zip"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.app_dir = Path(self._tmp.name) / "app"
        self.dest = Path(self._tmp.name) / "dl"
        self.app_dir.mkdir()
        (self.app_dir / "update-manifest.json").write_text(json.dumps(_manifest(version="1.0.0")), encoding="utf-8")
        self.zip_data = _zip_bytes(self.FILES)
        self.zip_sha = hashlib.sha256(self.zip_data).hexdigest()
        self.setup_data = b"setup"

    def _urlopen(self, manifest, zip_data):
        setup_data = self.setup_data

        def fake(req, timeout=None):
            url = req.full_url
            if url.endswith("m.json"):
                return _Response(json.dumps(manifest).encode())
            if url.endswith("app.zip"):
                return _Response(zip_data)
            if url.endswith("setup.exe"):
                return _Response(setup_data)
            raise AssertionError(url)

        return fake

    def _prepare(self, manifest=None, zip_data=None, cancel=None):
        release = release_from_json(_full_release_json())
        release = install_update.Release(
            **{**release.__dict__, "app_sha256": self.zip_sha, "sha256": hashlib.sha256(self.setup_data).hexdigest()}
        )
        manifest = manifest or _manifest(zip_sha=self.zip_sha, files=self.FILES)
        with (
            mock.patch.object(install_update, "latest_release", return_value=release),
            mock.patch.object(
                install_update.urllib.request,
                "urlopen",
                side_effect=self._urlopen(manifest, self.zip_data if zip_data is None else zip_data),
            ),
            mock.patch.object(type(config), "APP_VERSION", "1.0.0", create=False),
        ):
            return install_update.prepare_update(app_dir=self.app_dir, dest_dir=self.dest, cancel=cancel)

    def test_app_zip_when_the_deps_match(self):
        prepared = self._prepare()
        self.assertTrue(prepared.app_only)
        self.assertEqual(prepared.path.name, "TranslatorOverlay-app-9.9.9.zip")
        self.assertEqual(prepared.manifest["app_files"], self.FILES)

    def test_installer_when_the_deps_changed(self):
        prepared = self._prepare(manifest=_manifest(fingerprint="0" * 16, zip_sha=self.zip_sha, files=self.FILES))
        self.assertFalse(prepared.app_only)
        self.assertEqual(prepared.path.name, "TranslatorOverlay-Setup-9.9.9.exe")

    def test_installer_when_the_zip_is_bad(self):
        with self.assertLogs("translator", "WARNING"):
            prepared = self._prepare(zip_data=b"tampered")
        self.assertFalse(prepared.app_only)
        self.assertFalse((self.dest / "TranslatorOverlay-app-9.9.9.zip").exists())

    def test_installer_when_the_zip_does_not_match_the_manifest(self):
        self.zip_data = _zip_bytes(self.FILES + ["_internal/extra.dll"])
        self.zip_sha = hashlib.sha256(self.zip_data).hexdigest()
        with self.assertLogs("translator", "WARNING"):
            prepared = self._prepare()
        self.assertFalse(prepared.app_only)
        self.assertFalse((self.dest / "TranslatorOverlay-app-9.9.9.zip").exists())

    def test_installer_after_a_rolled_back_app_update(self):
        self.dest.mkdir()
        (self.dest / "app-update-failed-9.9.9.txt").write_text("error", encoding="utf-8")
        self.assertFalse(self._prepare().app_only)

    def test_installer_when_the_install_dir_is_read_only(self):
        with mock.patch.object(install_update, "_dir_writable", return_value=False):
            self.assertFalse(self._prepare().app_only)

    def test_cancel_is_not_a_fallback(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(DownloadCancelled):
            self._prepare(cancel=cancel)


class TestAppWaiter(unittest.TestCase):
    def _script(self, **kwargs):
        args = dict(
            app_dir=Path(r"C:\Apps\it's here"),
            zip_path=Path(r"C:\Temp\app.zip"),
            manifest_path=Path(r"C:\Temp\update-manifest.json"),
            files=["TranslatorOverlay.exe", "_internal/new.pyd"],
            remove=["_internal/old.pyd"],
            version="9.9.9",
            pid=4242,
            failed_marker=Path(r"C:\Temp\app-update-failed-9.9.9.txt"),
        )
        args.update(kwargs)
        return install_update.app_waiter_script(**args)

    def test_waits_for_the_app_then_swaps_with_rollback(self):
        script = self._script()
        self.assertTrue(script.startswith("Wait-Process -Id 4242"))
        self.assertIn(r"$app = 'C:\Apps\it''s here'", script)
        self.assertIn(r"$files = @('TranslatorOverlay.exe', '_internal\new.pyd')", script)
        self.assertIn(r"$remove = @('_internal\old.pyd')", script)
        # Old files are kept as .old until the end; the catch block moves them back.
        self.assertIn('-Destination "$p.old"', script)
        self.assertLess(script.index("try {"), script.index("Expand-Archive"))
        rollback = script[script.index("} catch {") :]
        self.assertIn('Move-Item -LiteralPath "$p.old" -Destination $p', rollback)
        self.assertIn(r"'C:\Temp\app-update-failed-9.9.9.txt'", rollback)
        # Apps & features shows the new version; the app starts again either way.
        self.assertIn("DisplayVersion -Value '9.9.9'", script)
        self.assertIn("{0DF3004C-2D3C-431A-8BCA-DC181526B77D}_is1", script)
        self.assertGreater(script.index("Start-Process"), script.index("} catch {"))

    def test_uninstall_key_matches_the_iss_app_id(self):
        iss = (ROOT / "installer" / "TranslatorOverlay.iss").read_text(encoding="utf-8")
        app_id = re.search(r"^AppId=\{(\{[0-9A-F-]+\})$", iss, re.MULTILINE).group(1)
        self.assertIn(app_id + "_is1", install_update._UNINSTALL_KEY)

    def test_iss_removes_files_added_by_app_updates(self):
        iss = (ROOT / "installer" / "TranslatorOverlay.iss").read_text(encoding="utf-8")
        section = iss[iss.index("[UninstallDelete]") :]
        self.assertIn(r'Type: filesandordirs; Name: "{app}\_internal"', section)

    @unittest.skipUnless(sys.platform == "win32", "Windows process creation flags")
    def test_launch_writes_the_script_and_runs_it_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir, work = Path(tmp) / "app", Path(tmp) / "dl"
            app_dir.mkdir()
            work.mkdir()
            (app_dir / "update-manifest.json").write_text(
                json.dumps(_manifest(version="1.0.0", files=["TranslatorOverlay.exe", "_internal/old.pyd"])),
                encoding="utf-8",
            )
            release = release_from_json(_full_release_json())
            prepared = install_update.PreparedUpdate(release, work / "app.zip", _manifest())
            with mock.patch.object(install_update.subprocess, "Popen") as popen:
                install_update.launch_update(prepared, app_dir=app_dir, pid=7)
            cmd = popen.call_args.args[0]
            script_path = Path(cmd[cmd.index("-File") + 1])
            raw = script_path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))  # BOM: PowerShell 5.1 reads UTF-8
            script = raw.decode("utf-8-sig")
            self.assertTrue(script.startswith("Wait-Process -Id 7"))
            self.assertIn(r"$remove = @('_internal\old.pyd')", script)
            self.assertEqual(json.loads((work / "update-manifest.json").read_text(encoding="utf-8")), _manifest())
            self.assertTrue(popen.call_args.kwargs["creationflags"] & install_update.subprocess.CREATE_NO_WINDOW)

    def test_full_update_still_runs_the_installer(self):
        release = release_from_json(_release_json())
        prepared = install_update.PreparedUpdate(release, Path(r"C:\Temp\Setup.exe"))
        with mock.patch.object(install_update, "launch_installer") as launch:
            install_update.launch_update(prepared, pid=7)
        launch.assert_called_once_with(Path(r"C:\Temp\Setup.exe"), pid=7)


class TestSetupRelaunchHook(unittest.TestCase):
    """The .iss starts the app again only for the app's own silent update."""

    def test_iss_relaunches_on_the_apps_flag(self):
        iss = (ROOT / "installer" / "TranslatorOverlay.iss").read_text(encoding="utf-8")
        self.assertIn("Check: RelaunchRequested", iss)
        self.assertIn("{param:RELAUNCH|0}", iss)
        self.assertIn("runasoriginaluser", iss)
        self.assertIn("/RELAUNCH=1", INSTALLER_ARGS)


if __name__ == "__main__":
    unittest.main()
