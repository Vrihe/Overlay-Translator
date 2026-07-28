"""
tts/engine.py — Text-to-speech synthesis using pyttsx3.
"""

import logging
import threading

try:
    import pyttsx3
    _HAS_PYTTSX3 = True
except ImportError:
    _HAS_PYTTSX3 = False

_engine = None
_lock = threading.Lock()


def speak(text: str) -> None:
    """Synthesize speech for *text* asynchronously in a background daemon thread."""
    if not text or not text.strip() or not _HAS_PYTTSX3:
        return

    def _run():
        global _engine
        with _lock:
            try:
                if _engine is None:
                    _engine = pyttsx3.init()
                _engine.stop()
                _engine.say(text)
                _engine.runAndWait()
            except Exception as e:
                logging.warning("TTS speech synthesis error: %s", e)

    threading.Thread(target=_run, daemon=True).start()
