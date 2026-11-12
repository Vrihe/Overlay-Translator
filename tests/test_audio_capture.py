"""
tests/test_audio_capture.py — audio/capture.py with a fake ``pyaudiowpatch``.

Covers the 16 kHz mono conversion, the wall-clock timeline that fills idle holes with
silence, device selection and the failure modes. No sound device is opened.
"""

import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from audio import capture
from audio.capture import SAMPLE_RATE, CaptureUnavailable, LoopbackCapture, Timeline, to_16k_mono

_SPEAKERS = {"index": 3, "name": "Speakers (Fake) [Loopback]", "defaultSampleRate": 48000.0, "maxInputChannels": 2}
_CHAT = {"index": 5, "name": "Chat (Fake) [Loopback]", "defaultSampleRate": 16000.0, "maxInputChannels": 1}


class _FakeStream:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.closed = False

    def push(self, samples):
        """Deliver one block the way PortAudio's thread does."""
        return self.kwargs["stream_callback"](np.asarray(samples, dtype="float32").tobytes(), 0, None, 0)

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class _FakePyAudio:
    devices = [_SPEAKERS, _CHAT]
    has_default = True
    open_error = None
    instances = []

    def __init__(self):
        self.stream = None
        self.terminated = False
        _FakePyAudio.instances.append(self)

    def get_loopback_device_info_generator(self):
        yield from self.devices

    def get_default_wasapi_loopback(self):
        if not self.has_default:
            raise OSError("no default output")
        return _SPEAKERS

    def open(self, **kwargs):
        if self.open_error:
            raise self.open_error
        self.stream = _FakeStream(kwargs)
        return self.stream

    def terminate(self):
        self.terminated = True


def _fake_module():
    module = types.ModuleType("pyaudiowpatch")
    module.PyAudio = _FakePyAudio
    module.paFloat32 = 1
    module.paContinue = 0
    return module


class TestConversion(unittest.TestCase):
    def test_stereo_48k_becomes_mono_16k(self):
        left = np.repeat(np.array([0.3, 0.6], dtype="float32"), 3)  # 6 frames at 48 kHz
        block = np.stack([left, -left * 0 + 0.1], axis=1).reshape(-1)  # interleaved L, R
        out = to_16k_mono(block, 48000, 2)
        self.assertEqual(out.dtype, np.float32)
        np.testing.assert_allclose(out, [0.2, 0.35], atol=1e-6)

    def test_16k_mono_is_passed_through(self):
        block = np.linspace(-1, 1, 160, dtype="float32")
        np.testing.assert_array_equal(to_16k_mono(block, 16000, 1), block)

    def test_odd_rate_is_resampled_to_the_right_length(self):
        out = to_16k_mono(np.zeros(44100, dtype="float32"), 44100, 1)
        self.assertEqual(len(out), SAMPLE_RATE)

    def test_incomplete_frame_is_ignored(self):
        self.assertEqual(len(to_16k_mono(np.zeros(7, dtype="float32"), 16000, 2)), 3)

    def test_display_name_drops_the_loopback_suffix(self):
        self.assertEqual(capture.display_name("Speakers (Fake) [Loopback]"), "Speakers (Fake)")
        self.assertEqual(capture.display_name("Speakers"), "Speakers")


class TestTimeline(unittest.TestCase):
    def test_continuous_audio_is_untouched(self):
        timeline = Timeline(100.0)
        block = np.ones(800, dtype="float32")  # 50 ms
        for i in range(1, 5):
            self.assertEqual(len(timeline.align(block, 100.0 + 0.05 * i)), 800)

    def test_idle_output_is_filled_with_silence(self):
        timeline = Timeline(0.0)
        timeline.align(np.ones(800, dtype="float32"), 0.05)
        idle = timeline.align(np.zeros(0, dtype="float32"), 1.05)  # nothing arrived for 1 s
        self.assertEqual(len(idle), SAMPLE_RATE)
        self.assertFalse(idle.any())
        # Sound resumes: no second helping of silence for the hole already filled.
        resumed = timeline.align(np.ones(800, dtype="float32"), 1.10)
        self.assertEqual(len(resumed), 800)

    def test_silence_goes_before_the_block_that_ends_the_hole(self):
        timeline = Timeline(0.0)
        out = timeline.align(np.ones(800, dtype="float32"), 0.55)
        self.assertEqual(len(out), int(0.55 * SAMPLE_RATE))
        self.assertFalse(out[:-800].any())
        self.assertTrue(out[-800:].all())

    def test_jitter_is_not_a_hole(self):
        timeline = Timeline(0.0)
        self.assertEqual(len(timeline.align(np.ones(800, dtype="float32"), 0.11)), 800)

    def test_fast_device_clock_does_not_delay_hole_detection(self):
        timeline = Timeline(0.0)
        timeline.align(np.ones(SAMPLE_RATE, dtype="float32"), 0.5)  # 1 s of audio in 0.5 s
        idle = timeline.align(np.zeros(0, dtype="float32"), 1.0)
        self.assertEqual(len(idle), SAMPLE_RATE // 2)


class _CaptureCase(unittest.TestCase):
    def setUp(self):
        _FakePyAudio.devices = [_SPEAKERS, _CHAT]
        _FakePyAudio.has_default = True
        _FakePyAudio.open_error = None
        _FakePyAudio.instances = []
        patcher = patch.dict(sys.modules, {"pyaudiowpatch": _fake_module()})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.chunks = []
        self.lock = threading.Lock()

    def on_audio(self, chunk):
        with self.lock:
            self.chunks.append(chunk)

    def captured(self):
        with self.lock:
            return np.concatenate(self.chunks) if self.chunks else np.zeros(0, dtype="float32")

    def start(self, device_name=""):
        cap = LoopbackCapture(self.on_audio, device_name)
        cap.start()
        self.addCleanup(cap.stop)
        return cap

    def wait_for(self, condition, timeout=3.0):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            time.sleep(0.01)
        return condition()


class TestLoopbackCapture(_CaptureCase):
    def test_default_device_is_opened_with_its_own_format(self):
        cap = self.start()
        kwargs = _FakePyAudio.instances[-1].stream.kwargs
        self.assertEqual(cap.device_name, _SPEAKERS["name"])
        self.assertFalse(cap.fell_back)
        self.assertEqual((kwargs["rate"], kwargs["channels"], kwargs["input_device_index"]), (48000, 2, 3))
        self.assertTrue(kwargs["input"])

    def test_blocks_reach_the_consumer_as_16k_mono(self):
        self.start()
        stream = _FakePyAudio.instances[-1].stream
        stream.push(np.full(4800 * 2, 0.5))  # 100 ms of stereo at 48 kHz
        self.assertTrue(self.wait_for(lambda: np.count_nonzero(self.captured()) == 1600))
        np.testing.assert_allclose(self.captured()[self.captured() != 0], 0.5)

    def test_silence_is_delivered_while_the_output_is_idle(self):
        self.start()
        self.assertTrue(self.wait_for(lambda: len(self.captured()) >= SAMPLE_RATE // 5))
        self.assertFalse(self.captured().any())

    def test_named_device_is_used(self):
        cap = self.start(_CHAT["name"])
        self.assertEqual(cap.device_name, _CHAT["name"])
        self.assertEqual(_FakePyAudio.instances[-1].stream.kwargs["input_device_index"], 5)

    def test_missing_named_device_falls_back_to_the_default(self):
        cap = self.start("Unplugged headset [Loopback]")
        self.assertEqual(cap.device_name, _SPEAKERS["name"])
        self.assertTrue(cap.fell_back)

    def test_stop_closes_everything_and_is_repeatable(self):
        cap = self.start()
        pa = _FakePyAudio.instances[-1]
        cap.stop()
        cap.stop()
        self.assertFalse(cap.is_running)
        self.assertTrue(pa.stream.closed)
        self.assertTrue(pa.terminated)

    def test_a_failing_consumer_does_not_kill_the_capture(self):
        calls = []

        def consumer(chunk):
            calls.append(len(chunk))
            raise RuntimeError("consumer exploded")

        cap = LoopbackCapture(consumer)
        cap.start()
        self.addCleanup(cap.stop)
        self.assertTrue(self.wait_for(lambda: len(calls) >= 2))


class TestCaptureFailures(_CaptureCase):
    def test_no_output_device(self):
        _FakePyAudio.has_default = False
        cap = LoopbackCapture(self.on_audio)
        with self.assertRaises(CaptureUnavailable):
            cap.start()
        self.assertFalse(cap.is_running)
        self.assertTrue(_FakePyAudio.instances[-1].terminated)

    def test_stream_open_failure(self):
        _FakePyAudio.open_error = OSError("device busy")
        with self.assertRaises(CaptureUnavailable) as ctx:
            LoopbackCapture(self.on_audio).start()
        self.assertIn("device busy", str(ctx.exception))

    def test_missing_package(self):
        with patch.dict(sys.modules, {"pyaudiowpatch": None}):
            with self.assertRaises(CaptureUnavailable):
                LoopbackCapture(self.on_audio).start()
            self.assertEqual(capture.list_loopback_devices(), [])


class TestDeviceList(_CaptureCase):
    def test_lists_loopback_devices_and_releases_pyaudio(self):
        self.assertEqual(capture.list_loopback_devices(), [_SPEAKERS["name"], _CHAT["name"]])
        self.assertTrue(_FakePyAudio.instances[-1].terminated)


if __name__ == "__main__":
    unittest.main()
