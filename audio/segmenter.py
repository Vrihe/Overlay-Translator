"""
audio/segmenter.py — cuts a live audio stream into phrases.

Feed 16 kHz mono float32 audio in chunks of any size; get back finished phrases:

    segmenter = Segmenter()
    for phrase in segmenter.feed(chunk): ...

A phrase closes after ``min_silence_ms`` of silence. Speech without pauses (a video,
a stream) is cut by force at ``max_phrase_s``, at the least speech-like frame of the
last two seconds, so words are split less often.

Speech is detected by the Silero VAD model bundled with ``faster-whisper``
(``faster_whisper.vad``), run frame by frame with its LSTM state carried over.
``vad_filter=True`` of faster-whisper is not enough here: it removes silence from a
finished buffer and cannot tell when a phrase ends in a live stream.

``faster-whisper`` and ``onnxruntime`` are imported lazily, on the first frame.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
#: The only frame size Silero VAD v5 accepts at 16 kHz (32 ms).
FRAME = 512
_CONTEXT = 64


@dataclass
class Phrase:
    """One finished phrase. Times are seconds from the start of the stream."""

    audio: np.ndarray
    start: float  # speech start, including the leading padding
    end: float  # end of the last speech frame
    closed_at: float  # when the segmenter emitted the phrase
    forced: bool  # True when cut by max_phrase_s


class SileroVad:
    """Frame-by-frame Silero VAD; ``prob(frame)`` returns the speech probability."""

    def __init__(self) -> None:
        self._session = None
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype="float32")
        self._c = np.zeros((1, 1, 128), dtype="float32")
        self._context = np.zeros(_CONTEXT, dtype="float32")

    def prob(self, frame: np.ndarray) -> float:
        if self._session is None:
            from faster_whisper.vad import get_vad_model

            self._session = get_vad_model().session
        x = np.concatenate([self._context, frame])[None, :]
        out, self._h, self._c = self._session.run(None, {"input": x, "h": self._h, "c": self._c})
        self._context = frame[-_CONTEXT:]
        return float(out.reshape(-1)[0])


class Segmenter:
    """Streaming endpointer. Not thread-safe: use it from one thread."""

    def __init__(
        self,
        vad=None,
        *,
        min_silence_ms: int = 400,
        max_phrase_s: float = 10.0,
        threshold: float = 0.5,
        min_speech_ms: int = 200,
        pad_ms: int = 200,
    ) -> None:
        self._vad = vad if vad is not None else SileroVad()
        self._threshold = threshold
        # Hysteresis: a phrase that started keeps going down to a lower probability.
        self._neg_threshold = max(threshold - 0.15, 0.01)
        self._min_silence = max(1, int(min_silence_ms * SAMPLE_RATE / 1000 / FRAME))
        self._max_frames = max(2, int(max_phrase_s * SAMPLE_RATE / FRAME))
        self._min_speech = max(1, int(min_speech_ms * SAMPLE_RATE / 1000 / FRAME))
        self._pad = int(pad_ms * SAMPLE_RATE / 1000 / FRAME)
        self._cut_window = max(1, min(int(2.0 * SAMPLE_RATE / FRAME), self._max_frames - 1))

        self._pending = np.zeros(0, dtype="float32")
        self._frames: list[np.ndarray] = []  # current phrase, including leading padding
        self._probs: list[float] = []
        self._history: list[np.ndarray] = []  # recent non-speech frames, for padding
        self._in_speech = False
        self._silence = 0
        self._speech_frames = 0
        self._consumed = 0  # frames taken from the stream
        self._first = 0  # stream index of the first frame in self._frames

    def feed(self, chunk: np.ndarray) -> list[Phrase]:
        """Add audio; return the phrases that finished inside it (usually none)."""
        phrases: list[Phrase] = []
        self._pending = np.concatenate([self._pending, np.asarray(chunk, dtype="float32")])
        while len(self._pending) >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            phrase = self._step(frame)
            if phrase is not None:
                phrases.append(phrase)
        return phrases

    def flush(self) -> list[Phrase]:
        """Close the phrase in progress, e.g. when the stream stops."""
        if self._in_speech and self._speech_frames >= self._min_speech:
            return [self._emit(len(self._frames) - self._silence, forced=False)]
        self._reset_phrase()
        return []

    def partial(self) -> np.ndarray | None:
        """Audio of the phrase in progress (for interim subtitles); None outside speech."""
        if not self._in_speech or self._speech_frames < self._min_speech:
            return None
        return np.concatenate(self._frames)

    # ── Internals ────────────────────────────────────────

    def _step(self, frame: np.ndarray) -> Phrase | None:
        prob = self._vad.prob(frame)
        self._consumed += 1

        if not self._in_speech:
            if prob >= self._threshold:
                self._in_speech = True
                self._frames = [*self._history, frame]
                self._probs = [0.0] * len(self._history) + [prob]
                self._first = self._consumed - len(self._frames)
                self._silence = 0
                self._speech_frames = 1
                self._history = []
            elif self._pad:
                self._history.append(frame)
                del self._history[: -self._pad]
            return None

        self._frames.append(frame)
        self._probs.append(prob)
        if prob >= self._neg_threshold:
            if prob >= self._threshold:
                self._speech_frames += 1
            self._silence = 0
        else:
            self._silence += 1

        if self._silence >= self._min_silence:
            if self._speech_frames < self._min_speech:
                self._reset_phrase()  # a click or a cough, not a phrase
                return None
            return self._emit(len(self._frames) - self._silence, forced=False)
        if len(self._frames) >= self._max_frames:
            tail = self._probs[-self._cut_window :]
            # Among equally quiet frames take the latest one: the piece stays long.
            quietest = len(tail) - 1 - int(np.argmin(tail[::-1]))
            cut = len(self._frames) - len(tail) + quietest + 1
            return self._emit(cut, forced=True)
        return None

    def _emit(self, speech_end: int, forced: bool) -> Phrase:
        """Emit ``frames[:speech_end]``; after a forced cut the rest starts the next phrase."""
        keep = speech_end if forced else min(len(self._frames), speech_end + self._pad)
        phrase = Phrase(
            audio=np.concatenate(self._frames[:keep]),
            start=self._first * FRAME / SAMPLE_RATE,
            end=(self._first + speech_end) * FRAME / SAMPLE_RATE,
            closed_at=self._consumed * FRAME / SAMPLE_RATE,
            forced=forced,
        )
        if forced:
            self._frames = self._frames[speech_end:]
            self._probs = self._probs[speech_end:]
            self._first += speech_end
            self._speech_frames = sum(p >= self._threshold for p in self._probs)
            self._silence = 0
        else:
            self._reset_phrase()
        return phrase

    def _reset_phrase(self) -> None:
        self._in_speech = False
        self._frames, self._probs = [], []
        self._silence = 0
        self._speech_frames = 0
