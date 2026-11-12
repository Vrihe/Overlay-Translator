"""
tests/test_stt_download.py — the Whisper model download for live subtitles and the cuDNN
download for the GPU: files land in the destination only when complete and verified.

No network: the Hub listing, PyPI and urlopen are faked.
"""

import hashlib
import io
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from audio import stt, stt_download
from translate import cuda_download, nllb_models

_FILES = {
    "model.bin": b"weights" * 50,
    "config.json": b"{}",
    "tokenizer.json": b"{}",
    "vocabulary.txt": b"a\nb\n",
    "README.md": b"readme",
}


class _Response(io.BytesIO):
    status = 200
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _listing(files=_FILES, bad_sha=False):
    entries = []
    for name, body in files.items():
        entry = {"type": "file", "path": name, "size": len(body)}
        if name == "model.bin":
            entry["lfs"] = {"oid": "0" * 64 if bad_sha else hashlib.sha256(body).hexdigest()}
        entries.append(entry)
    return entries


class TestModelDownload(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dest = Path(tmp.name) / "models" / "whisper-small.en"
        self.requested = []

    def _download(self, listing=None, **kwargs):
        def urlopen(req, timeout=None):
            self.requested.append(req.full_url)
            return _Response(_FILES[req.full_url.rsplit("/", 1)[1]])

        with (
            mock.patch.object(nllb_models, "resolve_revision", return_value="abc123"),
            mock.patch.object(nllb_models, "_repo_files", return_value=listing or _listing()),
            mock.patch.object(nllb_models.urllib.request, "urlopen", side_effect=urlopen),
            mock.patch.object(nllb_models, "_CHUNK", 64),
        ):
            return stt_download.download_model("small.en", dest=self.dest, **kwargs)

    def test_downloads_only_the_model_files(self):
        progress = []
        path = self._download(progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(path, self.dest)
        self.assertEqual(stt.missing_files(self.dest), [])
        self.assertFalse((self.dest / "README.md").exists())
        self.assertFalse((self.dest / nllb_models.PART_MARKER).exists())
        self.assertFalse(self.dest.with_name("whisper-small.en.part").exists())
        self.assertTrue(all("Systran/faster-whisper-small.en/resolve/abc123/" in url for url in self.requested))
        total = sum(len(body) for name, body in _FILES.items() if name != "README.md")
        self.assertEqual(progress[-1], (total, total))

    def test_checksum_mismatch_leaves_nothing(self):
        with self.assertRaises(OSError):
            self._download(listing=_listing(bad_sha=True))
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_name("whisper-small.en.part").exists())

    def test_repository_without_weights_is_rejected(self):
        files = {name: body for name, body in _FILES.items() if name != "model.bin"}
        with self.assertRaises(OSError):
            self._download(listing=_listing(files))
        self.assertFalse(self.dest.exists())

    def test_cancel_keeps_the_partial_download_for_a_resume(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(stt_download.DownloadCancelled):
            self._download(cancel=cancel)
        self.assertFalse(self.dest.exists())
        self.assertTrue((self.dest.with_name("whisper-small.en.part") / nllb_models.PART_MARKER).is_file())

    def test_an_incomplete_folder_is_replaced(self):
        self.dest.mkdir(parents=True)
        (self.dest / "config.json").write_bytes(b"old")
        self._download()
        self.assertEqual((self.dest / "config.json").read_bytes(), b"{}")

    def test_unknown_model_is_not_downloadable(self):
        self.assertFalse(stt_download.is_downloadable("large-v3"))
        with self.assertRaises(KeyError):
            stt_download.download_model("large-v3", dest=self.dest)

    def test_download_folder_is_where_the_recognizer_looks(self):
        self.assertIn(stt_download.download_dir("base.en"), stt.model_dirs("base.en"))


def _cudnn_wheel(names=("cudnn64_9.dll", "cudnn_ops64_9.dll")) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(f"nvidia/cudnn/bin/{name}", f"dll {name}")
        zf.writestr("nvidia/cudnn/include/cudnn.h", "header")
    return buf.getvalue()


class TestCudnnDownload(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dest = Path(tmp.name) / "cudnn"

    def _download(self, wheel, sha256=None):
        info = ("https://files.example/cudnn.whl", sha256 or hashlib.sha256(wheel).hexdigest(), len(wheel))
        with (
            mock.patch.object(cuda_download, "wheel_info", return_value=info) as wheel_info,
            mock.patch.object(cuda_download.urllib.request, "urlopen", return_value=_Response(wheel)),
        ):
            result = cuda_download.download_cudnn(dest=self.dest)
        wheel_info.assert_called_once_with(cuda_download.CUDNN_PACKAGE, cuda_download.CUDNN_VERSION)
        return result

    def test_unpacks_the_dlls(self):
        self.assertEqual(self._download(_cudnn_wheel()), self.dest)
        self.assertEqual(
            sorted(p.name for p in self.dest.iterdir()), ["cudnn64_9.dll", "cudnn_ops64_9.dll", "version.json"]
        )

    def test_recognizer_finds_the_downloaded_library(self):
        self.assertEqual(cuda_download.CUDNN_DLL, stt.CUDNN_DLL)
        self._download(_cudnn_wheel())
        with (
            mock.patch.object(cuda_download, "cudnn_dir", return_value=self.dest),
            mock.patch.object(cuda_download, "cuda_dir", return_value=self.dest.with_name("cuda")),
        ):
            self.assertEqual(stt.find_cudnn_dir(), self.dest)

    def test_a_copy_in_use_is_kept_instead_of_failing(self):
        self._download(_cudnn_wheel())
        # A loaded DLL cannot be deleted: rmtree fails silently and the rename hits the old folder.
        with mock.patch.object(cuda_download.shutil, "rmtree"):
            self.assertEqual(self._download(_cudnn_wheel()), self.dest)
        self.assertTrue((self.dest / cuda_download.CUDNN_DLL).is_file())

    def test_bad_checksum_or_wrong_wheel_leaves_nothing(self):
        with self.assertRaises(OSError):
            self._download(_cudnn_wheel(), sha256="0" * 64)
        with self.assertRaises(OSError):
            self._download(_cudnn_wheel(names=("other.dll",)))
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.dest.with_name("cudnn.part").exists())


if __name__ == "__main__":
    unittest.main()
