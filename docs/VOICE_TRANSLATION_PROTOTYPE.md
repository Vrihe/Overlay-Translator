# Voice translation prototype plan

Plan for a throwaway prototype of real-time speech translation, for Claude Code. Read
`CLAUDE.md` and the pipeline / backend sections of `ARCHITECTURE.md` first. All project
rules from `CLAUDE.md` apply. The prototype lives in `scratch/voice/` (gitignored) and
does not touch the app: no new settings, no UI, no changes to `requirements*.txt`.

---

## 1. Goal

Answer one question with numbers: **can this machine turn speech into a translated
subtitle fast enough to be useful** (target: under ~3 s from the end of a phrase), and
with which Whisper model and device.

Out of scope for the prototype: the overlay, settings, the installer, TTS voice quality.

## 2. Pipeline under test

```
audio source → VAD (phrase segmentation) → speech-to-text → translate.backend → print / TTS
```

| Stage | Choice for the prototype | Notes |
|---|---|---|
| Capture | WASAPI loopback of the default output (`soundcard` or `pyaudiowpatch`); microphone as a second mode | 16 kHz mono float32 after resampling |
| VAD | Silero VAD (ONNX) | `onnxruntime` is already a dependency via RapidOCR |
| STT | `faster-whisper` | Runs on CTranslate2, already used by NLLB; models `tiny.en`, `base.en`, `small.en`, `small` |
| Translation | existing `translate.backend.translate` | Both the local NLLB and an API backend |
| Output | console line with per-stage timings; optional `tts.engine.speak` | |

## 3. Prerequisites (need the user's go-ahead)

- Install into `.venv` only for the prototype: `faster-whisper`, one capture library.
- Download Whisper models (~75 MB for tiny, ~150 MB for base, ~500 MB for small) into
  `scratch/voice/models/`. Nothing is downloaded implicitly.
- The prototype records system audio. Recordings and transcripts stay in
  `scratch/voice/` and are never committed or logged elsewhere.

## 4. Steps

1. **Test set.** Generate 20–30 English phrases (short chat lines, game callouts, long
   sentences) with SAPI into WAV files, keeping the reference text. Add 30 s of silence,
   30 s of music and 30 s of noise for the hallucination check. No real recordings of
   people.
2. **Offline benchmark** (`bench_stt.py`). Feed the WAV files straight into
   VAD → Whisper → translation, without capture. For each model × device (CPU, and CUDA
   if the cuBLAS libraries are present), record:
   - STT time per phrase and the real-time factor (processing time / audio length);
   - WER against the reference text;
   - translation time (NLLB and one API backend);
   - end-of-phrase → translated-text latency;
   - anything produced on silence / music / noise.
3. **Live capture** (`live.py`). Play the WAV files and record them through loopback at
   the same time; check the captured audio is not silent (muted output or no device is a
   known failure) and that the live numbers match the offline ones.
4. **Echo check.** With TTS on the same output device, confirm whether the spoken
   translation is captured again. Try: muting capture while TTS speaks; TTS on another
   device; per-process capture (Windows 10 2004+ process loopback) if a library exposes it.
5. **Load check.** CPU / GPU usage and RAM while the live loop runs.

## 5. Results to report

- A table: model × device → real-time factor, WER, median and p95 latency, RAM.
- Hallucinations seen on non-speech input and whether VAD filtered them.
- Echo: which mitigation works.
- A recommendation: go / no-go, default model and device, and whether stage 1 should be
  subtitles only.

## 6. Checks only the user can do

- How the TTS voice sounds and how annoying it is over the original audio.
- Real sources: Discord, games, videos, accents, several speakers, background noise.
- Readability of subtitles over a game and the FPS impact.

## 7. If it goes ahead (not part of the prototype)

- Stage 1: live subtitles. New `audio/` package (capture, VAD, STT worker on a `QThread`,
  results via signals), a subtitle strip window, settings for source, model, device and
  language (DEFAULTS + `_LiveConfig` + `SettingsWidget`), lazy imports, the Whisper model
  downloaded only by an explicit action like NLLB, off by default.
- Stage 2: optional TTS with an output-device choice and echo protection.
- Privacy: audio and transcripts are user data, never logged in full; cloud STT only by
  explicit choice. Update `ARCHITECTURE.md`, `docs/privacy.md`, `requirements*.txt`.
