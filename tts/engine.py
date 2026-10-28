"""
tts/engine.py — Text-to-speech synthesis using pyttsx3.
"""

import logging
import queue
import threading

try:
    import pyttsx3

    _HAS_PYTTSX3 = True
except ImportError:
    _HAS_PYTTSX3 = False

# pyttsx3 drives SAPI over COM: the engine must be created and used on one thread.
# A new thread per call reused an engine from another apartment, and the second
# utterance hung or stayed silent. One worker thread owns the engine instead.
_requests: queue.Queue = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _worker_loop() -> None:
    engine = None
    while True:
        text = _requests.get()
        while not _requests.empty():  # only the newest request is worth speaking
            text = _requests.get_nowait()
        try:
            if engine is None:
                engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            logging.warning("TTS speech synthesis error: %s", e)
            engine = None  # rebuilt on the next request


def speak(text: str) -> None:
    """Synthesize speech for *text* asynchronously on the TTS worker thread."""
    global _worker
    if not text or not text.strip() or not _HAS_PYTTSX3:
        return

    _requests.put(text)
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="tts", daemon=True)
            _worker.start()
