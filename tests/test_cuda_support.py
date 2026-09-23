"""
tests/test_cuda_support.py — cuBLAS discovery and the NLLB CPU fallback.

Covers:
  • find_cublas_dir() checks the pip wheel, then CUDA_PATH*, then the default toolkit dir.
  • prepare_cuda_libraries() prepends the directory to PATH exactly once.
  • NllbBackend falls back to the CPU on every CUDA failure mode, and notifies the
    user only when the fallback is unexpected (a GPU is present).
No GPU, CUDA, or real model is needed: ctranslate2 is replaced by a fake.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from translate import cuda_support
from translate.nllb_backend import NllbBackend


def _make_dll_dir(root: Path, *parts: str) -> Path:
    path = root.joinpath(*parts)
    path.mkdir(parents=True)
    (path / cuda_support.CUBLAS_DLL).write_bytes(b"")
    return path


class TestFindCublasDir(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Start from a clean slate: no CUDA env vars, no real site-packages, no default toolkit.
        clean_env = {k: v for k, v in os.environ.items() if not k.upper().startswith("CUDA_PATH")}
        self._patches = [
            patch.dict(os.environ, clean_env, clear=True),
            patch.object(sys, "path", [str(self.root / "site-packages")]),
            patch.object(cuda_support, "_DEFAULT_TOOLKIT_ROOT", self.root / "toolkit"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        self._tmp.cleanup()

    def test_nothing_installed(self):
        self.assertIsNone(cuda_support.find_cublas_dir())
        self.assertIn(cuda_support.CUBLAS_DLL, cuda_support.cublas_missing_hint())

    def test_pip_wheel(self):
        found = _make_dll_dir(self.root, "site-packages", "nvidia", "cublas", "bin")
        self.assertEqual(cuda_support.find_cublas_dir(), found)

    def test_cuda_path_env(self):
        found = _make_dll_dir(self.root, "cuda12", "bin")
        os.environ["CUDA_PATH"] = str(self.root / "cuda12")
        self.assertEqual(cuda_support.find_cublas_dir(), found)

    def test_versioned_env_used_when_cuda_path_points_elsewhere(self):
        # CUDA_PATH names a CUDA 13 install (no cublas64_12.dll); the V12 variable wins.
        (self.root / "cuda13" / "bin").mkdir(parents=True)
        found = _make_dll_dir(self.root, "cuda12.6", "bin")
        os.environ["CUDA_PATH"] = str(self.root / "cuda13")
        os.environ["CUDA_PATH_V12_6"] = str(self.root / "cuda12.6")
        self.assertEqual(cuda_support.find_cublas_dir(), found)

    def test_default_toolkit_newest_first(self):
        _make_dll_dir(self.root, "toolkit", "v12.1", "bin")
        newest = _make_dll_dir(self.root, "toolkit", "v12.8", "bin")
        self.assertEqual(cuda_support.find_cublas_dir(), newest)

    def test_pip_wheel_preferred_over_toolkit(self):
        wheel = _make_dll_dir(self.root, "site-packages", "nvidia", "cublas", "bin")
        _make_dll_dir(self.root, "toolkit", "v12.8", "bin")
        self.assertEqual(cuda_support.find_cublas_dir(), wheel)

    @unittest.skipUnless(os.name == "nt", "PATH preparation is Windows-only")
    def test_prepare_prepends_path_once(self):
        found = _make_dll_dir(self.root, "site-packages", "nvidia", "cublas", "bin")
        with patch.object(cuda_support, "_registered", set()), \
                patch.object(os, "add_dll_directory", lambda _p: None, create=True):
            self.assertEqual(cuda_support.prepare_cuda_libraries(), found)
            cuda_support.prepare_cuda_libraries()
        self.assertEqual(os.environ["PATH"].split(os.pathsep).count(str(found)), 1)


class _FakeTranslator:
    """Stands in for ctranslate2.Translator; fails on CUDA as configured."""

    def __init__(self, fake, model_dir, device, compute_type, **_kwargs):
        self.device = device
        self._fake = fake
        if device == "cuda" and fake.fail_on == "construct":
            raise RuntimeError("CUDA driver version is insufficient")

    def translate_batch(self, *_args, **_kwargs):
        if self.device == "cuda" and self._fake.fail_on == "translate":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return []


class _FakeCTranslate2:
    def __init__(self, gpus=1, fail_on=None):
        self.gpus = gpus
        self.fail_on = fail_on

    def get_cuda_device_count(self):
        return self.gpus

    def Translator(self, model_dir, device, compute_type, **kwargs):  # noqa: N802 — mirrors the real API
        return _FakeTranslator(self, model_dir, device, compute_type, **kwargs)


class TestNllbDeviceFallback(unittest.TestCase):

    def _create(self, fake, device="auto", cublas_dir=Path("C:/cublas")):
        backend = NllbBackend(device=device)
        with patch("translate.cuda_support.prepare_cuda_libraries", return_value=cublas_dir):
            translator, active, compute = backend._create_translator(fake, Path("model"))
        return backend, translator, active, compute

    def test_gpu_used_when_it_works(self):
        backend, translator, active, compute = self._create(_FakeCTranslate2())
        self.assertEqual((active, compute), ("cuda", "int8_float16"))
        self.assertEqual(backend.cuda_fallback_reason, "")
        self.assertEqual(backend.take_notice(), "")

    def test_no_gpu_in_auto_mode_is_silent(self):
        backend, _, active, _ = self._create(_FakeCTranslate2(gpus=0))
        self.assertEqual(active, "cpu")
        self.assertIn("no CUDA-capable GPU", backend.cuda_fallback_reason)
        self.assertEqual(backend.take_notice(), "")

    def test_no_gpu_when_cuda_requested_notifies(self):
        backend, _, active, _ = self._create(_FakeCTranslate2(gpus=0), device="cuda")
        self.assertEqual(active, "cpu")
        self.assertIn("CUDA unavailable, using CPU inference", backend.take_notice())

    @unittest.skipUnless(os.name == "nt", "cuBLAS lookup is Windows-only")
    def test_cublas_missing_notifies(self):
        backend, _, active, _ = self._create(_FakeCTranslate2(), cublas_dir=None)
        self.assertEqual(active, "cpu")
        notice = backend.take_notice()
        self.assertIn("cublas64_12.dll not found", notice)
        self.assertEqual(backend.take_notice(), "", "notice must be one-shot")

    def test_lazy_cublas_failure_caught_by_warmup(self):
        # The constructor succeeds; cuBLAS only fails on the first GPU translation.
        backend, translator, active, _ = self._create(_FakeCTranslate2(fail_on="translate"))
        self.assertEqual((active, translator.device), ("cpu", "cpu"))
        self.assertIn("CUDA initialisation failed", backend.take_notice())

    def test_constructor_failure(self):
        backend, _, active, _ = self._create(_FakeCTranslate2(fail_on="construct"))
        self.assertEqual(active, "cpu")
        self.assertIn("driver version", backend.cuda_fallback_reason)

    def test_cpu_mode_never_touches_cuda(self):
        fake = _FakeCTranslate2()
        fake.get_cuda_device_count = lambda: self.fail("CUDA must not be queried in cpu mode")
        _, _, active, compute = self._create(fake, device="cpu")
        self.assertEqual((active, compute), ("cpu", "int8"))

    def test_device_from_env_and_invalid_value(self):
        with patch.dict(os.environ, {"NLLB_DEVICE": "CPU"}):
            self.assertEqual(NllbBackend()._device, "cpu")
        self.assertEqual(NllbBackend(device="tpu")._device, "auto")


if __name__ == "__main__":
    unittest.main()
