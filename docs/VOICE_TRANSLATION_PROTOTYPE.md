# Voice translation prototype plan

Plan for a throwaway prototype of real-time speech translation, for Claude Code. Read
`CLAUDE.md` and the pipeline / backend sections of `ARCHITECTURE.md` first. All project
rules from `CLAUDE.md` apply. The prototype lives in `scratch/voice/` (gitignored) and
does not touch the app: no new settings, no UI, no changes to `requirements*.txt`.

---

## 1. Goal

Answer one question with numbers: **can this machine turn speech into a translated
subtitle fast enough to be useful**, and with which Whisper model and device.

Latency is measured **from the true end of speech** (known from the test audio) to the
translated text. It therefore includes the pause the segmenter waits for before it decides
the phrase is over.

Go / no-go thresholds (proposed; the user confirms or changes them before the run):

| Metric | Go if |
|---|---|
| Latency, p95 | ≤ 3 s |
| Real-time factor of STT | ≤ 0.5 |
| WER, clean speech | ≤ 10 % |
| WER, speech with noise at 10 dB SNR | ≤ 20 % |
| Text produced on silence / noise / music | none |

Scope: English speech, translated into the app's configured target language. Other source
languages are added only if the user asks.

Out of scope for the prototype: the overlay, settings, the installer, TTS and echo
handling (stage 2, section 7).

## 2. Pipeline under test

```
audio source → segmenter (streaming VAD) → speech-to-text → translate.backend → print
```

| Stage | Choice for the prototype | Notes |
|---|---|---|
| Capture | WASAPI loopback of the default output (`pyaudiowpatch` preferred, `soundcard` as a fallback); microphone as a second mode | 16 kHz mono float32 after resampling. Loopback may deliver no packets while nothing is playing: fill the gaps with silence so timing and VAD stay correct. Check `soundcard` against the project's numpy 2.x before relying on it |
| Segmenter | Own streaming endpointer (`segmenter.py`) on top of the Silero VAD model bundled with `faster-whisper` (`faster_whisper.vad`) | See section 2.1. `vad_filter=True` alone is not enough: it removes silence from a finished buffer and cannot signal the end of a phrase in a live stream |
| STT | `faster-whisper` | Runs on CTranslate2, already used by NLLB; models `tiny.en`, `base.en`, `small.en`. Multilingual `small` only if a non-English source is added |
| STT, optional | Whisper exported to ONNX on `onnxruntime-directml` | Only if the machine has no NVIDIA GPU, so DirectML is the only GPU path. Decoding and tokenizer glue has to be written |
| Translation | existing `translate.backend.translate` | Both the local NLLB and an API backend; see section 2.3 |
| Output | console line with per-stage timings | |

### 2.1 Segmenter

- Audio arrives in small chunks; the VAD runs on a rolling window.
- A phrase is closed after `min_silence_ms` of silence (start with 600 ms; also try 400
  and 800). This wait is part of the latency budget.
- A phrase is cut by force at `max_phrase_s` (start with 10 s), so speech without pauses
  (a video, a stream) still produces subtitles.
- Step 0 confirms the bundled VAD can be called chunk by chunk. If it cannot, a simple
  energy-based endpointer is enough for the prototype.

### 2.2 Fixed Whisper parameters

Speed changes several times over with these, so they are fixed and written into the
results:

- `compute_type`: `int8` on CPU, `float16` on CUDA;
- `beam_size=1` for the main table; one extra run with `beam_size=5` on the chosen model
  to show the cost;
- `language="en"` (no language detection), `condition_on_previous_text=False`;
- model loading and the first call are excluded from the timings and reported separately
  as cold start.

### 2.3 Translation backend guard

`translate.backend.translate` takes the backend from the config, not from an argument,
and falls through to the cloud LLM when the local NLLB model is not ready. Before each
measured run the benchmark sets the backend explicitly, checks
`translate.backend.get_active_backend()` and that the NLLB model is loaded
(`translate.backend.preload`), and aborts otherwise. Without this the "NLLB" column could
hold cloud numbers and transcripts would go to the network.

## 3. Prerequisites (need the user's go-ahead)

- **A separate environment `.venv-voice/`** (gitignored), not the app's `.venv`.
  `faster-whisper` depends on the plain `onnxruntime` package, while the app uses
  `onnxruntime-directml`. Both install the same `onnxruntime` module, so pip would put one
  over the other and RapidOCR could lose DirectML. The prototype environment is built from
  **`requirements-cpu.txt`** (it already uses plain `onnxruntime`, so there is no
  conflict) plus `faster-whisper` and one capture library. The optional DirectML run, if
  needed, gets its own environment.
- **GPU:** Whisper in CTranslate2 needs **cuDNN 9 in addition to cuBLAS 12** (the
  convolutional encoder). `translate/cuda_download.py` only fetches cuBLAS, which is enough
  for NLLB but not for Whisper. For the prototype install `nvidia-cublas-cu12` and
  `nvidia-cudnn-cu12` into `.venv-voice` (cuDNN is several hundred MB); without them only
  the CPU column is measured. On Windows the DLLs from these wheels land in
  `site-packages/nvidia/*/bin` and are not found automatically: prepend those folders to
  `PATH` before loading the model. `os.add_dll_directory` does not help, because
  CTranslate2 loads the libraries with plain `LoadLibrary` (see `translate/cuda_support.py`).
- **App state:** `translate.backend` writes to the translation cache and history, and
  setting the backend through `config` is saved to `settings.json`. The prototype points
  `APPDATA` at `scratch/voice/appdata` before importing `config` and turns the cache off,
  so the user's settings, cache and history are never read or changed.
- Download Whisper models (~75 MB for tiny, ~150 MB for base, ~500 MB for small) into
  `scratch/voice/models/`. Nothing is downloaded implicitly: `WhisperModel("small")` alone
  fetches into the Hugging Face cache, so always pass `download_root=scratch/voice/models`
  or a local model path.
- The prototype records system audio. Recordings and transcripts stay in
  `scratch/voice/` and are never committed or logged elsewhere.

## 4. Steps

0. **Environment check.** In `.venv-voice`: `onnxruntime.get_available_providers()` lists
   what is expected, `faster-whisper` runs on one WAV file, the bundled VAD works chunk by
   chunk, and with CUDA a `device="cuda"` model loads without missing-DLL errors
   (cuBLAS / cuDNN). Write the CPU and GPU model into the results; without an NVIDIA GPU
   the CUDA column is dropped.
1. **Test set.** Generate 20–30 English phrases (short chat lines, game callouts, long
   sentences) with SAPI into WAV files, keeping the reference text. No real recordings of
   people. From them build:
   - **a stream file**: all phrases joined into one recording with pauses of different
     length (0.3–2 s) and a table of true phrase end times;
   - **a monologue**: 30–60 s of speech with no pauses longer than 0.3 s, for the forced
     cut;
   - **noisy copies** of the stream file with generated noise mixed in at 20, 10 and 5 dB
     SNR;
   - **non-speech**: 30 s of silence, 30 s of generated noise, and 30 s of instrumental
     music if the user provides a track (kept in `scratch/voice/`, skipped otherwise).

   A clean SAPI voice is much easier to recognise than live speech, so WER on the clean
   set is a best case; real speech is checked by the user (section 6).
2. **Offline benchmark** (`bench_stt.py`). Feed the stream files chunk by chunk, at
   real-time pace or faster with simulated timestamps, into
   segmenter → Whisper → translation, without capture. For each model × device (CPU, and
   CUDA if cuBLAS and cuDNN are present), record:
   - STT time per phrase and the real-time factor (processing time / audio length);
   - WER against the reference text, clean and per SNR level. Normalise both sides first
     (lowercase, strip punctuation, spell numbers the same way); a small own function is
     enough, no new dependency;
   - segmentation: phrases split or merged wrongly, and the delay between the true end of
     speech and the moment the segmenter closed the phrase;
   - translation time (NLLB and one API backend, with the guard from section 2.3);
   - true-end-of-speech → translated-text latency, median and p95;
   - behaviour on the monologue (latency of each forced cut, words lost at the cuts);
   - anything produced on silence / noise / music.
3. **Translation quality spot check.** For the same phrases, put side by side the
   translation of the reference text and the translation of the STT output. Count the
   phrases where recognition errors or missing punctuation changed the meaning. This is a
   manual read of 20–30 lines, not a metric.
4. **Live capture** (`live.py`). Play the stream file and record it through loopback at
   the same time; check the captured audio is not silent (muted output or no device is a
   known failure) and that the live numbers match the offline ones.
5. **Load check.** CPU / GPU usage, RAM and VRAM while the live loop runs. Repeat one run
   of the chosen model **under background load** (a game or a GPU benchmark running, NLLB
   and OCR loaded), because an idle machine gives optimistic numbers.

## 5. Results to report

- Hardware and the fixed parameters from section 2.2.
- A table: model × device → real-time factor, WER (clean and per SNR), median and p95
  latency, RAM / VRAM, cold start.
- The same latency for the chosen model under background load.
- Segmenter: the `min_silence_ms` and `max_phrase_s` that worked best, and the errors seen.
- Hallucinations seen on non-speech input and whether VAD filtered them.
- Translation spot check: how many phrases lost their meaning.
- A recommendation against the thresholds from section 1: go / no-go, default model and
  device, and whether stage 1 should be subtitles only.

## 6. Checks only the user can do

- Real sources: Discord, games, videos, accents, several speakers, background noise.
- Readability of subtitles over a game and the FPS impact.

## 7. If it goes ahead (not part of the prototype)

- Stage 1: live subtitles. New `audio/` package (capture, segmenter, STT worker on a
  `QThread`, results via signals), a subtitle strip window, settings for source, model,
  device and language (DEFAULTS + `_LiveConfig` + `SettingsWidget`), lazy imports, the
  Whisper model downloaded only by an explicit action like NLLB, off by default.
- Dependencies in the app: install `faster-whisper` with `pip install --no-deps` (a
  separate line in `install.bat`, CI and the build, since a requirements file cannot set
  `--no-deps` for one package) and list its other dependencies (`av`, `tokenizers`)
  explicitly; `onnxruntime-directml` then stays the only `onnxruntime` and also serves the
  VAD. `pip check` reports the "missing" `onnxruntime`; that is expected. A test or a CI
  step checks that `DmlExecutionProvider` is still available after the install.
- GPU: extend `translate/cuda_download.py` to fetch cuDNN 9 next to cuBLAS, only by an
  explicit user action; the download grows by several hundred MB.
- Watch the build size: `av` and `tokenizers` are added to the PyInstaller bundle.
- Stage 2: optional TTS with an output-device choice and echo protection. Start with an
  echo check: with TTS on the same output device, confirm whether the spoken translation
  is captured again. Try muting capture while TTS speaks, and per-process capture
  (Windows 10 2004+ process loopback) if a library exposes it. Note that
  `tts.engine.speak` (pyttsx3 / SAPI) always speaks on the default output device and keeps
  only the newest queued phrase, so "TTS on another device" needs a different output
  library. How the TTS voice sounds over the original audio is a check for the user.
- Privacy: audio and transcripts are user data, never logged in full; cloud STT only by
  explicit choice. Update `ARCHITECTURE.md`, `docs/privacy.md`, `requirements*.txt`.
