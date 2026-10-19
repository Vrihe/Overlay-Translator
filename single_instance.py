"""
Single-instance guard for Windows (pure ctypes, no Qt).

The first process creates a named mutex and a named auto-reset event.  A
second process sees the mutex already exists, signals the event so the first
instance brings its window to the front, and exits.  The OS releases both
kernel objects when the owning process dies, even after a crash, so a stale
lock can never block a fresh start.

Runs before torch/Qt are imported, so a duplicate launch exits in milliseconds.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading
from typing import Callable

logger = logging.getLogger("translator")

DEFAULT_NAME = "TranslatorOverlay.SingleInstance"

_ERROR_ALREADY_EXISTS = 183
_ERROR_ACCESS_DENIED = 5
_EVENT_MODIFY_STATE = 0x0002
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0
_ASFW_ANY = 0xFFFFFFFF


def _kernel32():
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateEventW.restype = wintypes.HANDLE
    k32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    k32.OpenEventW.restype = wintypes.HANDLE
    k32.SetEvent.argtypes = [wintypes.HANDLE]
    k32.SetEvent.restype = wintypes.BOOL
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


class SingleInstance:
    """Named mutex + activation event shared by all copies of the app in a session."""

    def __init__(self, name: str = DEFAULT_NAME):
        # "Local\" scopes the objects to the current logon session.
        self._mutex_name = f"Local\\{name}.Mutex"
        self._event_name = f"Local\\{name}.Activate"
        self._mutex = None
        self._event = None
        self._k32 = _kernel32() if sys.platform == "win32" else None

    def acquire(self) -> bool:
        """Return True if this is the first instance (and keep the lock until exit)."""
        if self._k32 is None:
            return True
        handle = self._k32.CreateMutexW(None, False, self._mutex_name)
        err = ctypes.get_last_error()
        if not handle:
            # An elevated instance owns the mutex and its DACL denies us access.
            if err == _ERROR_ACCESS_DENIED:
                return False
            logger.warning(f"Single-instance mutex unavailable (error {err}); guard disabled.")
            return True
        if err == _ERROR_ALREADY_EXISTS:
            self._k32.CloseHandle(handle)
            return False
        self._mutex = handle
        self._event = self._k32.CreateEventW(None, False, False, self._event_name)
        return True

    def notify_existing(self) -> bool:
        """Ask the running instance to show its window. Return True on success."""
        if self._k32 is None:
            return False
        handle = self._k32.OpenEventW(_EVENT_MODIFY_STATE, False, self._event_name)
        if not handle:
            return False
        try:
            # Let the running instance take the foreground; Windows blocks it otherwise.
            try:
                ctypes.windll.user32.AllowSetForegroundWindow(_ASFW_ANY)
            except Exception:
                pass
            return bool(self._k32.SetEvent(handle))
        finally:
            self._k32.CloseHandle(handle)

    def listen(self, callback: Callable[[], None]) -> None:
        """Call *callback* (on a background thread) each time another copy is launched."""
        if self._k32 is None or not self._event:
            return

        def _wait_loop() -> None:
            while self._k32.WaitForSingleObject(self._event, _INFINITE) == _WAIT_OBJECT_0:
                try:
                    callback()
                except Exception:
                    logger.exception("Single-instance activation callback failed")

        threading.Thread(target=_wait_loop, name="SingleInstanceListener", daemon=True).start()
