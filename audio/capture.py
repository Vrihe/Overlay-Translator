"""
audio/capture.py — what the computer is playing, as 16 kHz mono (WASAPI loopback).

    capture = LoopbackCapture(worker.feed, device_name=config.SUBTITLES_DEVICE)
    capture.start()        # raises CaptureUnavailable
    ...
    capture.stop()

``PyAudioWPatch`` (PortAudio with WASAPI loopback) is imported lazily. Each output
device has a loopback twin; ``device_name=""`` follows the default output device, a
name from ``list_loopback_devices()`` picks one (e.g. a separate "chat" output).

Loopback delivers **nothing** while the output is idle, so the stream is put back on
a wall-clock timeline here: a hole is filled with silence. Without that a phrase would
stay open until some other sound played, and the subtitle would wait for it.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

import numpy as np

from i18n import tr

_logger = logging.getLogger("translator.capture")

SAMPLE_RATE = 16000
#: Setting value for "whatever the default output device is".
DEFAULT_DEVICE = ""
_LOOPBACK_SUFFIX = " [Loopback]"
#: A hole shorter than this is timing jitter, not an idle output.
_MIN_GAP_S = 0.1
_POLL_S = 0.1


class CaptureUnavailable(Exception):
    """Audio cannot be captured: package missing, no output device, or the stream failed."""


def to_16k_mono(block: np.ndarray, rate: int, channels: int) -> np.ndarray:
    """Interleaved float32 samples → 16 kHz mono float32."""
    usable = len(block) - len(block) % channels
    mono = block[:usable].reshape(-1, channels).mean(axis=1)
    if rate == SAMPLE_RATE:
        return mono.astype("float32")
    if rate % SAMPLE_RATE == 0:  # 48 / 96 kHz: averaging whole groups is a cheap low-pass
        k = rate // SAMPLE_RATE
        n = len(mono) // k
        return mono[: n * k].reshape(n, k).mean(axis=1).astype("float32")
    n = int(len(mono) * SAMPLE_RATE / rate)
    return np.interp(np.linspace(0, len(mono), n, endpoint=False), np.arange(len(mono)), mono).astype("float32")


def display_name(device_name: str) -> str:
    """A loopback device's name the way Windows shows the output device."""
    return device_name.removesuffix(_LOOPBACK_SUFFIX)


def _pyaudio():
    try:
        import pyaudiowpatch
    except ImportError as exc:
        raise CaptureUnavailable(tr("Не установлен пакет PyAudioWPatch для захвата звука.")) from exc
    return pyaudiowpatch


def list_loopback_devices() -> list[str]:
    """Names of the output devices that can be captured; empty when capture is unavailable."""
    try:
        module = _pyaudio()
        pa = module.PyAudio()
    except Exception:
        return []
    try:
        return [str(info["name"]) for info in pa.get_loopback_device_info_generator()]
    except Exception:
        _logger.exception("Failed to list loopback devices")
        return []
    finally:
        pa.terminate()


class Timeline:
    """Puts captured blocks on a wall-clock timeline, filling idle holes with silence."""

    def __init__(self, start: float) -> None:
        self._origin = start
        self._fed = 0  # samples returned so far

    def align(self, audio: np.ndarray, now: float) -> np.ndarray:
        """*audio* ends at *now*; returns it, preceded by silence for a hole before it."""
        missing = int((now - self._origin) * SAMPLE_RATE) - self._fed - len(audio)
        if missing > _MIN_GAP_S * SAMPLE_RATE:
            audio = np.concatenate([np.zeros(missing, dtype="float32"), audio])
        elif missing < 0:
            # The device clock runs ahead of ours: move the origin, or the next hole
            # would be detected that much later.
            self._origin += missing / SAMPLE_RATE
        self._fed += len(audio)
        return audio


class LoopbackCapture:
    """Captures an output device and hands 16 kHz mono chunks to ``on_audio``.

    ``on_audio`` is called on the capture's own thread, so it must be thread-safe
    (``SttWorker.feed`` is).
    """

    def __init__(self, on_audio, device_name: str = DEFAULT_DEVICE, *, clock=time.perf_counter) -> None:
        self._on_audio = on_audio
        self._wanted = device_name or DEFAULT_DEVICE
        self._clock = clock
        self._pa = None
        self._stream = None
        self._thread: threading.Thread | None = None
        self._blocks: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        #: The device actually captured (set by start()).
        self.device_name = ""
        #: True when the wanted device was not found and the default one is used.
        self.fell_back = False

    @property
    def is_running(self) -> bool:
        return self._thread is not None

    def start(self) -> None:
        if self.is_running:
            return
        module = _pyaudio()
        try:
            self._pa = module.PyAudio()
            device = self._pick_device()
            rate, channels = int(device["defaultSampleRate"]), int(device["maxInputChannels"])
            self._stream = self._pa.open(
                format=module.paFloat32,
                channels=channels,
                rate=rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=max(1, rate // 20),
                stream_callback=lambda data, _frames, _info, _status: self._on_block(data, module.paContinue),
            )
        except CaptureUnavailable:
            self._close()
            raise
        except Exception as exc:
            self._close()
            raise CaptureUnavailable(tr("Не удалось начать захват звука: {error}", error=exc)) from exc
        self.device_name = str(device["name"])
        _logger.info("Loopback capture: %s (%d Hz, %d ch)", self.device_name, rate, channels)
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, args=(rate, channels), name="loopback-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        thread, self._thread = self._thread, None
        if thread is None:
            return
        self._stop.set()
        thread.join(2.0)
        self._close()

    def _pick_device(self) -> dict:
        if self._wanted:
            for info in self._pa.get_loopback_device_info_generator():
                if info["name"] == self._wanted:
                    return info
            self.fell_back = True
            _logger.warning("The chosen output device is gone; capturing the default one")
        try:
            return self._pa.get_default_wasapi_loopback()
        except Exception as exc:
            raise CaptureUnavailable(tr("Не найдено устройство вывода звука для захвата.")) from exc

    def _on_block(self, data, flag):
        # PortAudio's thread: only hand the bytes over.
        self._blocks.put((self._clock(), data))
        return (None, flag)

    def _pump(self, rate: int, channels: int) -> None:
        timeline = Timeline(self._clock())
        while not self._stop.is_set():
            try:
                now, data = self._blocks.get(timeout=_POLL_S)
                audio = to_16k_mono(np.frombuffer(data, dtype="float32"), rate, channels)
            except queue.Empty:
                now, audio = self._clock(), np.zeros(0, dtype="float32")
            audio = timeline.align(audio, now)
            if len(audio):
                try:
                    self._on_audio(audio)
                except Exception:
                    _logger.exception("Audio consumer failed")

    def _close(self) -> None:
        stream, self._stream = self._stream, None
        pa, self._pa = self._pa, None
        try:
            if stream is not None:
                stream.stop_stream()
                stream.close()
        except Exception:
            _logger.debug("Closing the capture stream failed", exc_info=True)
        try:
            if pa is not None:
                pa.terminate()
        except Exception:
            _logger.debug("Terminating PyAudio failed", exc_info=True)
