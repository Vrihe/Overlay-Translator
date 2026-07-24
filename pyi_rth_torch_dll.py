"""
pyi_rth_torch_dll.py — PyInstaller runtime hook for PyTorch DLL resolution on Windows.

Executes before any app code or module imports to ensure Win32 SetDllDirectoryW
registers torch/lib path so LoadLibraryExW resolves c10.dll, torch_cpu.dll,
libiomp5md.dll without WinError 1114.
"""

import ctypes
import os
import sys

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["OMP_NUM_THREADS"] = "1"

if getattr(sys, "frozen", False):
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    torch_lib = os.path.join(base_dir, "torch", "lib")
    if os.path.exists(torch_lib):
        try:
            ctypes.windll.kernel32.SetDllDirectoryW(torch_lib)
        except Exception:
            pass
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(torch_lib)
            except Exception:
                pass
        os.environ["PATH"] = torch_lib + os.pathsep + os.environ.get("PATH", "")

    # Preload critical C++ runtimes and PyTorch DLLs in order
    if os.path.exists(torch_lib):
        for dll_name in [
            "vcruntime140.dll",
            "vcruntime140_1.dll",
            "msvcp140.dll",
            "vcomp140.dll",
            "libiomp5md.dll",
            "torch_cpu.dll",
            "c10.dll",
            "torch.dll",
        ]:
            dll_path = os.path.join(torch_lib, dll_name)
            if os.path.exists(dll_path):
                try:
                    ctypes.CDLL(dll_path)
                except Exception:
                    pass
