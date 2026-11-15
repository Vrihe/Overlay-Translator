"""
tests/test_audio_segmenter.py — audio/segmenter.py with a fake VAD (no onnxruntime).

The fake VAD calls a frame "speech" when it is loud, so a test stream is just blocks of
ones (speech) and zeros (silence).
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from audio.segmenter import FRAME, SAMPLE_RATE, Segmenter


class _LoudnessVad:
    def prob(self, frame):
        return 1.0 if float(np.abs(frame).mean()) > 0.5 else 0.0


def _speech(seconds):
    return np.ones(int(seconds * SAMPLE_RATE), dtype="float32")


def _silence(seconds):
    return np.zeros(int(seconds * SAMPLE_RATE), dtype="float32")


def _run(segmenter, audio, chunk=1600):
    phrases = []
    for i in range(0, len(audio), chunk):
        phrases += segmenter.feed(audio[i : i + chunk])
    return phrases


class TestSegmenter(unittest.TestCase):
    def make(self, **kwargs):
        return Segmenter(_LoudnessVad(), **kwargs)

    def test_silence_gives_nothing(self):
        seg = self.make()
        self.assertEqual(_run(seg, _silence(5)), [])
        self.assertEqual(seg.flush(), [])

    def test_phrase_closes_after_the_pause(self):
        seg = self.make(min_silence_ms=400)
        phrases = _run(seg, np.concatenate([_silence(1), _speech(2), _silence(1)]))
        self.assertEqual(len(phrases), 1)
        phrase = phrases[0]
        self.assertFalse(phrase.forced)
        self.assertAlmostEqual(phrase.end, 3.0, delta=0.05)
        # Closed about min_silence after the speech ended, not at the end of the stream.
        self.assertAlmostEqual(phrase.closed_at - phrase.end, 0.4, delta=0.05)
        # Leading and trailing padding are part of the audio.
        self.assertLess(phrase.start, 1.0)
        self.assertGreater(len(phrase.audio) / SAMPLE_RATE, 2.0)

    def test_short_pause_does_not_split(self):
        seg = self.make(min_silence_ms=400)
        audio = np.concatenate([_speech(1), _silence(0.2), _speech(1), _silence(1)])
        self.assertEqual(len(_run(seg, audio)), 1)

    def test_long_pause_splits(self):
        seg = self.make(min_silence_ms=400)
        audio = np.concatenate([_speech(1), _silence(0.8), _speech(1), _silence(1)])
        phrases = _run(seg, audio)
        self.assertEqual(len(phrases), 2)
        self.assertLess(phrases[0].end, phrases[1].start + 0.25)

    def test_click_is_not_a_phrase(self):
        seg = self.make(min_speech_ms=200)
        audio = np.concatenate([_silence(1), _speech(0.05), _silence(1)])
        self.assertEqual(_run(seg, audio), [])

    def test_speech_without_pauses_is_cut_by_force(self):
        seg = self.make(max_phrase_s=3.0)
        phrases = _run(seg, np.concatenate([_speech(10), _silence(1)]))
        self.assertGreaterEqual(len(phrases), 3)
        self.assertTrue(all(p.forced for p in phrases[:-1]))
        self.assertFalse(phrases[-1].forced)
        for p in phrases:
            self.assertLessEqual(len(p.audio) / SAMPLE_RATE, 3.0 + 0.3)
        # Nothing is lost or repeated at the cuts: the pieces follow each other exactly.
        for prev, nxt in zip(phrases, phrases[1:]):
            self.assertAlmostEqual(prev.end, nxt.start, places=6)

    def test_forced_cut_prefers_the_quietest_recent_frame(self):
        class _DipVad:
            """Speech everywhere, with one weak frame 1 s before the forced cut."""

            def __init__(self):
                self.n = 0

            def prob(self, frame):
                self.n += 1
                return 0.6 if self.n == dip else 1.0

        max_frames = int(3.0 * SAMPLE_RATE / FRAME)
        dip = max_frames - int(1.0 * SAMPLE_RATE / FRAME)
        seg = Segmenter(_DipVad(), max_phrase_s=3.0)
        phrases = _run(seg, _speech(3.5))
        self.assertTrue(phrases[0].forced)
        self.assertAlmostEqual(phrases[0].end, dip * FRAME / SAMPLE_RATE, places=6)

    def test_flush_closes_the_phrase_in_progress(self):
        seg = self.make()
        self.assertEqual(_run(seg, np.concatenate([_silence(0.5), _speech(1)])), [])
        phrases = seg.flush()
        self.assertEqual(len(phrases), 1)
        self.assertAlmostEqual(phrases[0].end, 1.5, delta=0.05)
        self.assertEqual(seg.flush(), [])

    def test_chunk_size_does_not_matter(self):
        audio = np.concatenate([_silence(0.5), _speech(1.5), _silence(1), _speech(1), _silence(1)])
        small = [(p.start, p.end) for p in _run(self.make(), audio, chunk=160)]
        large = [(p.start, p.end) for p in _run(self.make(), audio, chunk=48000)]
        self.assertEqual(small, large)
        self.assertEqual(len(small), 2)

    def test_default_vad_is_not_loaded_until_audio_arrives(self):
        Segmenter()  # must not import faster_whisper / onnxruntime
        self.assertNotIn("faster_whisper.vad", sys.modules)


if __name__ == "__main__":
    unittest.main()
