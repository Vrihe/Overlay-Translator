"""
tests/test_cuda_download.py — the cuBLAS download for NLLB on an NVIDIA GPU: what the
settings offer, checksum and unpacking, cleanup on failure or cancel, the search
order, and the NLLB device setting.

No network and no GPU: the "wheel" is a small zip built here, urlopen and the
NVIDIA driver are mocked.
"""

import hashlib
import io
import os
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import config
from translate import cuda_download, cuda_support, nllb_backend
from translate.cuda_download import DownloadCancelled, download_cublas, extract_dlls, gpu_offer


def _wheel_bytes(names=("cublas64_12.dll", "cublasLt64_12.dll", "nvblas64_12.dll")) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(f"nvidia/cublas/bin/{name}", f"dll {name}")
        zf.writestr("nvidia/cublas/include/cublas.h", "header")
        zf.writestr("nvidia_cublas_cu12-12.9.2.10.dist-info/METADATA", "meta")
    return buf.getvalue()


class _Response(io.BytesIO):
    """urlopen() result: a context manager with read() and headers."""

    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}


class TestGpuOffer(unittest.TestCase):
    def test_states(self):
        self.assertEqual(gpu_offer(None, False), "none")
        self.assertEqual(gpu_offer(None, True), "none")
        self.assertEqual(gpu_offer(11080, False), "old_driver")
        self.assertEqual(gpu_offer(12080, False), "download")
        self.assertEqual(gpu_offer(12080, True), "ready")


class TestDriverVersion(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_reads_the_driver_version(self):
        def fake_get_version(ref):
            ref._obj.value = 12080
            return 0

        nvcuda = mock.Mock()
        nvcuda.cuDriverGetVersion.side_effect = fake_get_version
        with mock.patch.object(cuda_download.ctypes, "WinDLL", return_value=nvcuda):
            self.assertEqual(cuda_download.driver_cuda_version(), 12080)

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_no_nvidia_driver(self):
        with mock.patch.object(cuda_download.ctypes, "WinDLL", side_effect=OSError("not found")):
            self.assertIsNone(cuda_download.driver_cuda_version())


class TestDownload(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.dest = self.root / "cuda"

    def _run(self, wheel: bytes, sha: str | None = None, cancel=None):
        sha = sha or hashlib.sha256(wheel).hexdigest()
        progress = []
        with (
            mock.patch.object(
                cuda_download, "wheel_info", return_value=("https://example.invalid/w.whl", sha, len(wheel))
            ),
            mock.patch.object(cuda_download.urllib.request, "urlopen", return_value=_Response(wheel)),
            mock.patch.object(cuda_download, "_CHUNK", 64),
        ):
            result = download_cublas(dest=self.dest, cancel=cancel, progress=lambda d, t: progress.append((d, t)))
        return result, progress

    def _leftovers(self):
        return sorted(p.name for p in self.root.iterdir() if p.name != "cuda")

    def test_unpacks_only_the_dlls(self):
        wheel = _wheel_bytes()
        result, progress = self._run(wheel)
        self.assertEqual(result, self.dest)
        self.assertEqual(
            sorted(p.name for p in self.dest.iterdir()),
            ["cublas64_12.dll", "cublasLt64_12.dll", "nvblas64_12.dll", "version.json"],
        )
        self.assertEqual(progress[-1], (len(wheel), len(wheel)))
        self.assertEqual(self._leftovers(), [])  # no .part dir, no wheel file

    def test_checksum_mismatch_leaves_nothing(self):
        with self.assertRaisesRegex(OSError, "Checksum"):
            self._run(_wheel_bytes(), sha="0" * 64)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self._leftovers(), [])

    def test_wheel_without_cublas_is_rejected(self):
        with self.assertRaisesRegex(OSError, "cublas64_12.dll"):
            self._run(_wheel_bytes(names=("nvblas64_12.dll",)))
        self.assertFalse(self.dest.exists())
        self.assertEqual(self._leftovers(), [])

    def test_cancel_cleans_up(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(DownloadCancelled):
            self._run(_wheel_bytes(), cancel=cancel)
        self.assertFalse(self.dest.exists())
        self.assertEqual(self._leftovers(), [])

    def test_a_failed_update_keeps_the_working_copy(self):
        self.dest.mkdir()
        (self.dest / "cublas64_12.dll").write_text("old")
        with self.assertRaises(OSError):
            self._run(_wheel_bytes(), sha="0" * 64)
        self.assertEqual((self.dest / "cublas64_12.dll").read_text(), "old")

    def test_extract_flattens_paths(self):
        wheel_path = self.root / "w.whl"
        with zipfile.ZipFile(wheel_path, "w") as zf:
            zf.writestr("nvidia/cublas/bin/sub/../cublas64_12.dll", "x")
        out = self.root / "out"
        out.mkdir()
        self.assertEqual(extract_dlls(wheel_path, out), ["cublas64_12.dll"])
        self.assertTrue((out / "cublas64_12.dll").is_file())


class TestSearchOrder(unittest.TestCase):
    def test_app_download_is_searched_first(self):
        self.assertEqual(cuda_support.candidate_dirs()[0], cuda_download.cuda_dir())

    def test_cuda_dir_is_per_user(self):
        self.assertEqual(cuda_download.cuda_dir(), Path(config.USER_DATA_DIR) / "cuda")


class TestDeviceSetting(unittest.TestCase):
    def setUp(self):
        nllb_backend._backend = None
        self.addCleanup(setattr, nllb_backend, "_backend", None)
        env = {k: v for k, v in os.environ.items() if k.upper() != "NLLB_DEVICE"}
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _device_for(self, setting: str) -> str:
        nllb_backend._backend = None
        with mock.patch.object(type(config), "NLLB_DEVICE", new_callable=mock.PropertyMock, return_value=setting):
            return nllb_backend.get_backend()._device

    def test_setting_selects_the_device(self):
        self.assertEqual(self._device_for("cpu"), "cpu")
        self.assertEqual(self._device_for("auto"), "auto")

    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {"NLLB_DEVICE": "cuda"}):
            self.assertEqual(self._device_for("cpu"), "cuda")

    def test_default_is_auto(self):
        from settings.config_manager import DEFAULTS

        self.assertEqual(DEFAULTS["nllb_device"], "auto")


if __name__ == "__main__":
    unittest.main()
