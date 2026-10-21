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
import tempfile
import threading
import unittest
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
