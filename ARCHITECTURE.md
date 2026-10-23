# ARCHITECTURE.md — Overlay Translator project map

> Internal document for finding your way around the repository quickly.
> Read it instead of re-scanning every file.

---

## 1. Overview

**Overlay Translator** is a Windows desktop app (PyQt5). A global hotkey lets
you select any region of the screen; the app recognises the text in it (OCR)
and shows the translation in an always-on-top popup.

**Main flow**: `Ctrl+Shift+R` → selection frame → screenshot of the region →
RapidOCR → translation (cloud API **or** the local NLLB model) → popup with the translation.

**Stack**:

| Layer | Technology |
|---|---|
| GUI | PyQt5 5.15 (QMainWindow + sidebar, QSystemTrayIcon, frameless popups) |
| Screen capture | `mss` |
| OCR | RapidOCR 3.x: PP-OCRv6 det + PP-OCRv5 `eslav` rec on ONNX Runtime, GPU via DirectML (`onnxruntime-directml`) or CPU; no torch |
| Translation (API) | OpenRouter (OpenAI-compatible SDK) and/or Anthropic SDK |
| Translation (offline) | NLLB-200-distilled-600M, CTranslate2 int8 + sentencepiece, CPU or optional CUDA |
| Language detection | `langid` + a script heuristic, or an LLM |
| Storage | SQLite (cache + history), JSON (settings, presets, profiles) |
| Secrets | OS keyring (Windows Credential Manager) + `.env` |
| Hotkeys | `keyboard` (global, background thread) |
| Packaging | PyInstaller (`build.py`, `*.spec`) |

The UI is available in Russian and English (`i18n/`, see section 5); Russian is
the source language of UI strings. Code, comments, docstrings and documentation
are in English.

---

## 2. Directory layout

```
Overlay-Translator/
├── main.py                 # Entry point: logging, splash, TranslatorApp, hotkeys
├── single_instance.py      # Windows named-mutex guard: one running copy per session
├── config.py               # Global config facade (replaces itself in sys.modules!)
├── build.py / build.bat    # PyInstaller build scripts
├── install.bat / download_model.bat / run.bat  # Dev quick start: .venv + deps, NLLB model, launch (--admin elevates)
├── build*.spec             # Spec files (layered build: app + deps)
├── installer/TranslatorOverlay.iss  # Inno Setup script: dist/TranslatorOverlay/ → Setup.exe (build.py --installer)
├── .github/workflows/release.yml   # v* tag → tests, build, installer, draft GitHub release
├── .github/workflows/ci.yml        # tests on every PR and push to main (required check of main)
├── CHANGELOG.md            # Keep a Changelog; the X.Y.Z section becomes the release notes
├── _deps_stub.py           # Stub for the layered dependency build
├── pyi_rth_onnxruntime.py  # Runtime hook: import onnxruntime before PyInstaller's PyQt5 hook
│
├── capture/                # Screen capture
│   ├── screenshot.py       #   capture_region() via mss
│   └── live_monitor.py     #   LiveMonitor(QThread) — periodic re-scan of a region (interval,
│                           #   change threshold: threshold_for("high"|"medium"|"low") = 1.0/2.5/5.0)
│
├── ocr/                    # Text recognition
│   ├── engine.py           #   RapidOCR singleton, preprocessing, line sorting
│   └── hsv_filter.py       #   Optional HSV filter for coloured text
│
├── overlay/
│   └── selector.py         #   RegionSelector — full-screen selection frame (accent + corner brackets)
│
├── translate/              # Translation and language logic
│   ├── backend.py          #   * Dispatcher: picks the API or the local model
│   ├── llm_client.py       #   * Translation backend via the cloud API
│   ├── nllb_backend.py     #   * Offline backend: NLLB-200 (CTranslate2 int8)
│   ├── nllb_models.py      #   Published NLLB builds (HF tags): list, match local copies, download
│   ├── chat_glossary.py    #   Expands English game-chat terms before NLLB (wts, gg wp, lf2m)
│   ├── glossary/game_en.json  # Term list, exported by training/game_abbreviations.py
│   ├── cuda_support.py     #   Locates cuBLAS for optional GPU inference
│   ├── cuda_download.py    #   Downloads cuBLAS (PyPI wheel, SHA-256) into %APPDATA%\…\cuda
│   ├── domain_manager.py   #   Domain profiles (prompts + few-shot)
│   ├── lang_detect.py      #   Language detection, "same language" fast path
│   ├── error_classification.py  # Whether a provider error is retryable
│   ├── privacy.py          #   loggable(text): keeps captured screen text out of the logs
│   └── domain_profiles/    #   general.json, chat.json, game.json, documentation.json
│
├── cache/                  # SQLite cache and history (L1 LRU + L2 SQLite)
│   └── store.py            #   * translations table schema
│
├── settings/               # Settings persistence
│   ├── __init__.py         #   * API keys via keyring + provider/fallback
│   ├── config_manager.py   #   * settings.json: DEFAULTS / get / set_value
│   ├── hotkeys.py          #   App hotkeys (translate / settings): Qt → keyboard names, validation
│   └── region_presets.py   #   Screen-region presets + their hotkeys
│
├── ui/                     # PyQt5 widgets
│   ├── main_window.py      #   MainWindow with a nav rail (Home/Settings/History)
│   ├── settings_dialog.py  #   * SettingsWidget — all settings; ProfileEditorDialog
│   ├── result_popup.py     #   ResultPopup — result window (TTS, copy, resize)
│   ├── setup_wizard.py     #   First-run wizard: online (Google) / API key / offline NLLB + download
│   ├── first_run_dialog.py #   LLM API key entry (when the LLM backend has no key)
│   ├── nllb_workers.py     #   QThreads shared by settings and wizard: NLLB preload, version list, download
│   ├── theme.py            #   * HUD palettes (UI_THEME), fonts, all stylesheet builders
│   ├── icons.py            #   Stroke icons drawn with QPainterPath (no emoji / QtSvg)
│   ├── hud_widgets.py      #   NavButton, Panel, FieldLabel, Chip, Segmented, Switch(Row)
│   ├── title_bar.py        #   Main window's own title bar + native frame messages (Windows)
│   ├── wheel_guard.py      #   Wheel over a closed combo / spin box scrolls the page instead
│   ├── ocr_preview_popup.py#   Preview/edit OCR text before translating
│   └── region_presets_dialog.py # Manage presets and their hotkeys
│
├── history/
│   └── history_window.py   #   HistoryWidget — view and export history
│
├── i18n/                   # Interface language (ru / en)
│   ├── __init__.py         #   tr(), N_(), current_language(), resolve_language()
│   └── en.py               #   MESSAGES: Russian source string → English
│
├── tray/                   # System tray icon + context menu
├── tts/engine.py           # Text-to-speech for translations (SAPI, separate thread)
├── updater/check_update.py # Checks GitHub releases
├── updater/install_update.py # One-click silent update: verified Setup.exe, waiter, /VERYSILENT
├── scripts/                # Offline utilities (not part of the app build)
│   ├── download_model.py           # Fetches the pinned model build from the HF Hub
│   ├── test_nllb_translation.py    # Local model smoke test + CPU latency
│   ├── export_history_dataset.py   # SQLite history → JSONL for fine-tuning
│   └── baseline_eval_nllb.py       # NLLB chrF baseline on real pairs
├── training/               # NLLB LoRA fine-tune (own venv: .venv-train, requirements-train.txt)
│   ├── pipeline.py         #   One command per stage: data → train → merge → convert → eval
│   ├── train_config.py     #   YAML config loading + run provenance (git sha, libs, dataset hash)
│   └── …                   #   data scripts, finetune_lora.py, merge_lora.py, evaluate.py
├── configs/train/          # Pipeline configs of the published versions (v1.yaml, v2.yaml)
├── dvc.yaml, .dvc/         # DVC stages of both versions; data cached on a Google Drive remote
│                           #   (data/*.dvc pointers are the only committed files under data/)
├── Makefile, Dockerfile.train  # make <stage> wrapper and the training image (Linux / WSL)
├── tests/                  # unittest/pytest tests
├── docs/                   # Documentation site (MkDocs, mkdocs.yml; published by docs.yml)
│   ├── index.md …          #   user and developer pages: installation, configuration,
│   │                       #   local model, privacy, FAQ, how it works, training, experiments
│   └── baseline_eval.md …  #   training and evaluation reports (v0 baseline, v1, v2)
├── data/                   # Exported datasets (gitignored — user data)
└── assets/
    ├── icon.ico            # Application icon (HUD tile; regenerated by build.generate_icon)
    └── fonts/              # JetBrains Mono Regular/Medium (SIL OFL, LICENSE.txt)
```

**Not edited / not versioned** (see `.gitignore`):
`__pycache__/`, `.venv/`, `dist/`, `build/`, `_build_cache/`, `.pytest_cache/`,
`.claude/`, `.rtk/`, `*.exe`, `.env`, `settings.json`, `logs/`,
`cache/*` (except `__init__.py` and `store.py`), `screenshots/`,
`models/`, `*.ct2/`, `.hf-cache/`, `data/`.

**Artifacts outside the repository**:
- User data: `%APPDATA%\translator-overlay\`
  (`settings.json`, `region_presets.json`, `cache/translations.db`,
  `logs/translator.log`, `app.log`, `crash.log`, custom domain profiles).
- NLLB models: `<project>/models/` by default (git-ignored, never committed):
  `nllb-200-distilled-600M` — original HF checkpoint, 2.31 GiB, needed for fine-tuning;
  `nllb-200-ct2-int8` — CTranslate2 int8, 621 MiB, used by the app.
  To keep them elsewhere, set `NLLB_BASE_MODEL_DIR` (HF checkpoint, read by
  `training/finetune_lora.py`, `merge_lora.py`, `translate_phrases.py`) and
  `NLLB_MODEL_DIR` (CT2 model, read by the app and `scripts/test_nllb_translation.py`),
  or pass `--model` / `--base`.
- Published model: Hugging Face Hub repo
  [`Alhite/overlay-translator-nllb-int8`](https://huggingface.co/Alhite/overlay-translator-nllb-int8)
  (public, CC-BY-NC-4.0). Tag `v0-base` = the plain int8 conversion before fine-tuning.
  This is where other developers get the model from (see section 9).

---

## 3. Modules and responsibilities

### `main.py` — orchestrator
- `_init_logging() -> str` — DEBUG log to `%APPDATA%/translator-overlay/app.log` (rotating, 2 MB × 3), before any
  other import. The HTTP SDK loggers (`openai`, `anthropic`, `httpx`, …) are capped at WARNING: at DEBUG they
  dump whole request bodies, i.e. the captured screen text.
- `_global_excepthook` / `_thread_excepthook` — log unhandled exceptions.
- `faulthandler` → `crash.log` and `_qt_message_handler` (Qt messages, including `qFatal`, → `app.log`) —
  catch native crashes that bypass the Python hooks.
- Single-instance guard (`single_instance.SingleInstance`, only when run as `__main__`, before Qt loads):
  a named mutex `Local\TranslatorOverlay.SingleInstance.Mutex`. A second launch signals the named event
  `...Activate` and exits with code 0; the running instance's listener thread emits a `HotkeyBridge`
  → `MainWindow.show_window()`. The OS frees both objects when the process dies, so a crash leaves no stale lock.
- `import onnxruntime` at module level, **before PyQt5**: PyQt5 ships msvcp140.dll 14.26 next to
  Qt5Core.dll, and onnxruntime (needs ≥ 14.40) fails with "DLL initialization routine failed"
  if Qt's copy is loaded first. `ocr/engine._onnxruntime()` never retries a failed import.
  Frozen build: PyInstaller's own PyQt5 runtime hook imports `PyQt5.QtCore` before `main.py`,
  so `pyi_rth_onnxruntime.py` (custom runtime hooks run first) does the import instead, and
  `build.py::bundle_msvc_runtime` copies `vcruntime140(_1)` / `msvcp140(_1)` from System32 to
  `_internal/` (onnxruntime imports `MSVCP140_1.dll`; the only other copy is Qt's 14.26).
  `build_app.spec` also skips `sentencepiece` in PyInstaller's isolated DLL-path probe, which
  imports it after PyQt5 and crashes for the same reason.
- `class HotkeyBridge(QObject)` — `triggered = pyqtSignal()`; bridge from the `keyboard` thread to the Qt thread.
- `class TranslationWorker(QThread)` — the whole pipeline in the background.
  `TranslatorApp._start_translation_pipeline(..., live=False)` never kills a running worker
  (`QThread.terminate()` mid-OCR left the engine broken): a request arriving while one runs
  becomes `_pending_request` (only the newest is kept) and starts on the worker's `finished`;
  each request has a sequence number and a result that is no longer the newest is dropped.
  `_replace_worker()` parks a still-running replaced worker in `_retired_workers` until it
  ends. `live=True` (LiveMonitor `region_changed`) keeps the open popup and updates it in
  place with `activate=False` (no focus taken from the watched game or stream).
  `_set_popup()` makes a popup current; its `destroyed` clears `_popup` only while it is
  still the current one (an old popup dying late used to orphan the new one).
  `_user_popup_pos` remembers, per region (`_anchor_key(anchor)`), where the user dragged a
  popup (`ResultPopup.moved_by_user`, emitted from `moveEvent` once a drag started); a new
  popup for that region (loading one, or `show_result(position=…)`) opens there via
  `place_at()`, unless that monitor is gone. Session only, not saved.
  Signals: `translation_done(str src, str translated, str error)`,
  `partial_result(str)` (streaming), `ocr_done(str, QRect)`.
  Constructor: `(x1, y1, x2, y2, text_override: str|None = None, ocr_only: bool = False)`.
- `class OcrWarmupWorker(QThread)` — builds the RapidOCR engine 3 s after start, then
  preloads langid only when `translate.backend.uses_langid()` (LLM / NLLB): its model
  unpickle holds the GIL ~1 s and would freeze the UI for nothing on Google / DeepL / Azure.
- `class TranslatorApp` — owns `QApplication`, `MainWindow`, `TrayIcon`, hotkeys,
  the selector, popups, live monitoring and preset hotkeys. `_register_app_hotkeys()`
  (re)registers `config.HOTKEY` / `config.SETTINGS_HOTKEY` (kept handles are removed
  first) and refreshes the tray labels; it runs at start and on `MainWindow.hotkeys_changed`.
  `MainWindow.hotkey_capture(True)` (a hotkey field in the settings got focus) →
  `_pause_hotkeys` unhooks every global hotkey, `False` registers app + preset ones again.
  Key methods: `_show_selector`, `_on_region_selected`,
  `_start_translation_pipeline(x1, y1, x2, y2, anchor, text_override=None)`,
  `_on_ocr_preview_requested`, `_toggle_live_monitoring`, `_register_preset_hotkeys`,
  `_on_partial_translation`, `_on_translation_finished`, `_show_result`, `_show_error`,
  `_quit`, `run`.
- Restart: `TranslatorApp._restart()` (settings → "Сохранить" for restart-only options)
  starts a detached copy with `--wait-pid <pid>` and quits; `_wait_for_previous_instance()`
  in the new copy waits for that process before the single-instance check.
- `main()` sets an explicit AppUserModelID (`Vrihe.TranslatorOverlay`) before Qt starts, so a
  source run gets its own taskbar button with the window icon instead of Python's.
- `main()` — splash → setup wizard (`config_manager.first_run_pending()`: no `settings.json`
  yet, or the wizard was never finished; a file from a version without the wizard counts
  as done) → LLM key dialog (only `backend.needs_llm_key()`) → `TranslatorApp(app).run()` →
  `logging.shutdown()` → `os._exit(code)`. Python finalization is skipped on purpose: the
  `keyboard` low-level hook thread and Qt window procedures could fire during module teardown
  and crashed ~1 exit in 3 (`0xC000041D` / access violation, also with EasyOCR). Nothing is
  saved at exit (no `atexit`), so new exit-time persistence must run before `os._exit`.
  Because destructors are skipped too, `_quit` → `_remove_tray_icon()` closes the tray menu,
  hides the icon and `sip.delete`s it while the event loop still runs, so the icon leaves
  the notification area at once instead of lingering until hovered.

### `config.py` — config facade
Unusual trick: at the end of the module, `sys.modules[__name__] = _LiveConfig()`,
so `import config; config.TARGET_LANG` reads a **property** that calls
`settings.config_manager.get(...)` every time. Assigning
`config.TARGET_LANG = "en"` writes to `settings.json` immediately.

- Dynamic (settings.json): `HOTKEY`, `TARGET_LANG`, `SOURCE_LANG`,
  `TRANSLATION_ENGINE`, `TRANSLATION_BACKEND`, `NLLB_MODEL_PATH`, `LLM_MODEL`,
  `POPUP_TIMEOUT_SEC`, `NOTIFICATION_TYPE`,
  `OCR_LANGUAGES`, `ACTIVE_DOMAIN`,
  `ENABLE_STREAMING`, `ENABLE_OCR_PREVIEW`, `COMPACT_PROMPT`, `LLM_MAX_TOKENS`,
  `HOTKEY`, `SETTINGS_HOTKEY` (the `SETTINGS_HOTKEY` env var overrides the latter).
- Static (env/constants): `MAX_RETRIES_PER_PROVIDER`, `RETRY_BACKOFF_BASE_SEC`,
  `OPENROUTER_MODEL`, `ANTHROPIC_DETECT_MODEL`, `APP_VERSION`, `GITHUB_REPO`,
  `NLLB_HF_REPO_ID`, `NLLB_HF_REVISION` (the pinned model build, see section 9),
  `EASYOCR_*`, `OVERLAY_*`, `USER_DATA_DIR`, `CACHE_DIR`,
  `CACHE_MAX_ITEMS`, `LOG_DIR`, `LOG_FILE`.

### `translate/backend.py` — backend dispatcher ★
The single entry point for translating user text. It mirrors the `llm_client`
signatures, so callers only change the import:

```python
translate(text, target_lang=None, source_lang=None, domain_id=None, on_chunk=None) -> str
detect_and_translate(text, target_lang=None, domain_id=None, on_chunk=None) -> tuple[str, str]

get_active_backend() -> str          # "api" | "nllb", read from config on every call
take_notice() -> str                 # one-shot message for the UI (thread-local)
preload(backend=None) -> (bool, str) # warms up the model for the settings indicator
reset() -> None                      # resets both backends
```

**Local backend error policy** (agreed with the user):
- Model not found / failed to load → quietly switch to the API, and leave a note via
  `take_notice()`, which the popup shows as a "⚠ …" line.
- Model loaded but the translation failed → the exception propagates and the popup
  shows an explicit error. No hidden fallback.

The notice lives in `threading.local()` because translations run in QThread workers,
and two workers must never see each other's messages.

### `translate/llm_client.py` — translation backend via the API
Public interface (the dispatcher and the local backend mirror it):

```python
translate(text: str, target_lang: str|None = None, source_lang: str|None = None,
          domain_id: str|None = None, on_chunk: Callable[[str], None]|None = None) -> str

detect_and_translate(text: str, target_lang: str|None = None,
                     domain_id: str|None = None,
                     on_chunk: Callable[[str], None]|None = None) -> tuple[str, str]
                     # -> (detected_lang, translation)

reset_client() -> None          # resets clients and the system-prompt cache
validate_api_key(provider, key) # raises RuntimeError if the provider rejects the key; no tokens spent
get_provider_chain() -> list[str]
```

Internals: `_get_client_for(provider)` (lazy import of `openai`/`anthropic`),
`_call_provider(...)` (streaming and non-streaming paths),
`_call_with_resilience(...)` (retry with exponential backoff + fallback along the
provider chain), `_build_system_prompt(domain_id, target_lang, source_lang)` with a cache,
request coalescing via `_in_flight` (two identical concurrent requests → one API call).
Reasoning models: only `content` is ever a translation. OpenRouter calls send
`include_reasoning: false`; streamed `reasoning` deltas and a reply's `message.reasoning`
are ignored, and `_strip_reasoning()` removes inline `<think>…</think>` blocks (an unclosed
one hides the rest while streaming). A reply with no answer left (the model spent its token
budget thinking) raises the "empty response" error instead of showing the thinking.

### `translate/nllb_backend.py` — offline backend ★
`class NllbBackend` with the same public interface as `llm_client`, plus
module-level wrappers `translate()` / `detect_and_translate()` / `reset_client()`
over the process-wide singleton `get_backend()`.

```python
NllbBackend(model_dir=None, *, device=None, compute_type="int8",
            gpu_compute_type="int8_float16", intra_threads=None, beam_size=4)
    .ensure_loaded()   # lazy load; raises NllbModelUnavailable
    .unload()          # reset after the model path changes in settings
    .is_loaded / .model_dir / .load_seconds
    .active_device / .cuda_fallback_reason / .take_notice()
    .translate(...) / .detect_and_translate(...)

resolve_model_dir() -> Path | None    # which directory will be used
explicit_model_dir() -> Path | None   # path from settings / NLLB_MODEL_DIR
describe_model_location() -> str      # text for the settings status line
is_available() -> bool                # whether a model exists (without loading it)
NLLB_LANG_CODES: dict[str, str]       # ISO 639-1 → FLORES-200
```

Exceptions: `NllbModelUnavailable` (infrastructure → fallback to the API) and
`NllbTranslationError` (a specific translation failed → explicit error for the user).

How it differs from the API path:
- **Lazy loading**: the ~620 MB model is read on the first real translation,
  not at import and not at app start. Loading takes ~1.2 s and is guarded by a `Lock`.
- **Domain profiles do not apply**: a seq2seq model does not take prompts;
  `domain_id` only affects the cache key.
- **Cache entries get a `"|nllb"` suffix** on `domain_id`, so the local model's
  output never ends up in the fine-tuning dataset alongside API translations.
  With the glossary on, the suffix is `"|glossary<version>|nllb"`, so a new glossary
  never serves translations cached before it.
- **Game-chat glossary** (`translate/chat_glossary.py`, English sources only,
  `NLLB_GLOSSARY=0` turns it off): before inference each known term is replaced with
  its English meaning (`wts` → "I want to sell", `lf2m` → "we need 2 more players",
  `500g` → "500 gold"); terms without a translatable meaning (game titles, emotes,
  ambiguous spellings) are masked as `[1]`, copied by NLLB and restored verbatim. If the
  model drops a placeholder, the line is retranslated unmasked. NLLB alone drops or
  invents slang (`gg ez` → «Доброе утро»); the term list (~1300 entries) comes from the
  curated v2 fine-tune lexicon, see `docs/finetune_v2_process.md`.
  OCR reads a leading `l` as `I` in most sans-serif fonts (`If2m`, `Ifm`, `Iol`), less
  often as `1` or `|`: a token unknown as read but known with `l` (3+ characters, so
  `If`/`Is`/`Id` stay words; `Ian`, `iOS` excepted) is treated as that term.
- **No streaming** (CTranslate2 beam search does not provide it): `on_chunk`
  is called once with the final text, so the UI behaves the same way.
- With `source_language=auto` the source language is detected offline via `langid`.
- Runtime dependencies are only `ctranslate2` + `sentencepiece`, no torch or transformers.
- **GPU is optional**. `get_backend()` passes `NLLB_DEVICE` env, else `config.NLLB_DEVICE`
  (`settings.json` → `nllb_device`: `"auto"` | `"cpu"`, Settings → Device), to `NllbBackend`;
  `device=None` there means `"auto"`. In auto/cuda mode
  `translate/cuda_support.py` locates `cublas64_12.dll` (the app's own download in
  `%APPDATA%\translator-overlay\cuda`, pip wheel `nvidia-cublas-cu12`,
  then `CUDA_PATH*`, then the default toolkit dir) and prepends it to `PATH`, because
  CTranslate2 loads cuBLAS via plain `LoadLibrary` and ignores `os.add_dll_directory`.
  cuBLAS loads lazily, so a tiny warm-up translation verifies the GPU. Any failure → CPU
  plus a one-shot notice via `take_notice()` → `translate.backend.take_notice()` → result popup.

Model search order: explicit path from settings → `NLLB_MODEL_DIR` →
`<project>/models/nllb-200-ct2-int8` → `%APPDATA%/translator-overlay/models/…`.
An explicitly set path is authoritative:
if it is wrong, the backend reports that instead of picking up another copy.

### `translate/cuda_support.py` — cuBLAS discovery for the GPU path
```python
candidate_dirs() -> list[Path]      # search order, deduplicated
find_cublas_dir() -> Path | None    # first dir containing cublas64_12.dll
prepare_cuda_libraries() -> Path | None  # prepend that dir to PATH once (Windows only)
cublas_missing_hint() -> str        # user-facing "not found, install …, searched: …"
```
Search order: `cuda_download.cuda_dir()` (`%APPDATA%\translator-overlay\cuda`) →
`<sys.path entry or _MEIPASS>/nvidia/cublas/bin` (pip wheel
`nvidia-cublas-cu12`, see `requirements-gpu.txt`) → `%CUDA_PATH%\bin`,
`%CUDA_PATH_V12_*%\bin` → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*\bin`.
Only cuBLAS is needed for NLLB; cuDNN/cudart are not. Called only from
`NllbBackend._create_cuda_translator`. The CPU fallback policy lives in
`NllbBackend._create_translator`: a missing GPU in `auto` mode is logged at INFO
with no user notice; every other CUDA failure logs a WARNING and leaves a notice.

### `translate/cuda_download.py` — cuBLAS for the installed app
```python
driver_cuda_version() -> int | None   # nvcuda.dll cuDriverGetVersion (12080 = 12.8); no GPU work
gpu_offer(driver_version, cublas_found) -> "none" | "old_driver" | "download" | "ready"
download_cublas(*, dest=None, progress=None, cancel=None) -> Path
```
The installer ships no CUDA. The settings page (NLLB section, `_refresh_cuda_row`) shows
the offer only with an NVIDIA driver; "Скачать для видеокарты" runs `CudaDownloadWorker`
(`ui/nllb_workers.py`): the pinned `nvidia-cublas-cu12` (`WHEEL_VERSION`) Windows wheel
from PyPI (~530 MB), checked against PyPI's SHA-256, its `nvidia/cublas/bin/*.dll` unpacked
flat into `<dest>.part`, which replaces `cuda_dir()` only when complete (a failed or
cancelled download leaves the old copy). Afterwards the NLLB backend is reset and warmed
up again, now on the GPU. Standard library only (no pip in the frozen app).

### `translate/domain_manager.py`
`load_domain_profile(domain_id) -> dict`, `list_available_domains() -> list[dict]`,
`save_custom_profile(...)`, `delete_custom_profile(domain_id) -> bool`,
`generate_slug(display_name) -> str`.
Built-in profiles live in `translate/domain_profiles/*.json`, custom ones in
`%APPDATA%\translator-overlay\`.
Format: `{display_name, system_prompt, few_shot_examples: [{source, translation}]}`.
Profile ids become file names, so `_safe_id()` accepts only `\w+` (anything else → `general`).
Built-in ids (`general`, `game`, `documentation`, `chat`) are never looked up in the custom
directories, so a dropped-in `custom/game.json` cannot replace a built-in prompt.

### `translate/lang_detect.py`
`detect_script(text) -> str`,
`is_same_language(text, target_lang, source_lang=...) -> (bool, str)`
(fast path: if the source language equals the target, the API is not called),
`LangDetector` (ABC) → `LangidDetector`, `LLMDetector`; `get_detector(engine)`.

### `cache/store.py` — SQLite cache and history
Two levels: L1 `OrderedDict` LRU (128 entries) + L2 SQLite (WAL),
one connection per thread.

```sql
CREATE TABLE translations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_text     TEXT NOT NULL,
    source_lang     TEXT NOT NULL,      -- ISO code or "_auto"
    target_lang     TEXT NOT NULL,
    domain_id       TEXT NOT NULL DEFAULT 'general',
    translated_text TEXT NOT NULL,
    timestamp       REAL NOT NULL,
    UNIQUE(source_text, source_lang, target_lang, domain_id)
);
```

API: `get_cached(text, src, tgt, *, domain_id='general') -> str|None`,
`save_to_cache(text, src, tgt, translation, *, domain_id='general')`,
`warm_cache(limit=50) -> int`, `get_all_history(limit=200) -> list[dict]`,
`clear_history()`.
Size is capped by `config.CACHE_MAX_ITEMS` (the oldest entries by `timestamp` are evicted).
DB file: `%APPDATA%\translator-overlay\cache\translations.db`.

### `settings/` — persistence
- `config_manager`: `DEFAULTS` (the canonical list of keys — **unknown keys are
  dropped on save**), `load_config()`, `save_config(cfg)`,
  `get(key)`, `set_value(key, value)`. File: `%APPDATA%\translator-overlay\settings.json`.
- `settings/__init__.py`: `get_api_key(provider)`, `set_api_key`,
  `get_primary_provider()`, `save_primary_provider()`,
  `is_fallback_enabled()`, `set_fallback_enabled()`.
- `region_presets.py`: `load_presets()`, `save_preset(...)`, `delete_preset(id)`,
  `rename_preset(id, name)`, `update_preset_hotkey(id, hotkey)`, `validate_hotkey(...)`.
  File: `%APPDATA%\translator-overlay\region_presets.json`.

### `ocr/engine.py`
`get_reader()` — lazy RapidOCR singleton, `preprocess(img, scale=1) -> np.ndarray`,
`extract_text(image) -> str`, `recognise(img, lang=None) -> str` (public entry point),
`_extract_strips` — splits tall regions into strips for accuracy.
- Models: PP-OCRv6 small detector + PP-OCRv5 mobile recognizer (`eslav` = ru/uk/be + Latin
  when `OCR_LANGUAGES` has a Cyrillic code, else `en`); the angle classifier is off.
  `_model_dir()` = `%APPDATA%\translator-overlay\ocr_models`, seeded from `rapidocr/models/`
  (`_MODEL_FILES`); a rec model missing there is downloaded once by rapidocr.
- Device: `OCR_GPU_MODE` `auto` (legacy `gpu` behaves the same) → DirectML when
  `DmlExecutionProvider` is available, `cpu` → CPU; `EASYOCR_GPU` env still overrides.
  A failing DirectML run rebuilds the engine on the CPU and re-runs the frame (`_safe_readtext`).
- `_infer_lock` serialises inference; `_reader_lock` guards the lazy init.
  Confidence threshold: `EASYOCR_CONFIDENCE_THRESHOLD` (the env names kept their old prefix).

### `ui/`
- **Look ("HUD" theme)** — near-black surfaces, square corners, 1 px borders, monospace
  body text, caps letter-spaced captions, one accent colour. `ui/theme.py` is the single
  source of truth: `Palette` tokens (`accent`, `on_accent`, `dim`, `tint`, `bg`, `panel`,
  `rail`, `line`, `active`, `outer` + shared `text`, `text_soft`, `muted`, `nav_idle`,
  `ok`, `error`, `warn`), `PALETTES` = amber / cyan / crimson, `current()` (reads
  `config.UI_THEME` once per run, unknown value → amber), style builders (`btn_primary`,
  `btn_secondary`, `btn_accent`, `btn_danger`, `btn_icon`, `input_css`, `combo_css`,
  `check_css`, `group_css`, `panel_css(object_name)`, `chip_css`, `table_css`, `list_css`,
  `menu_css`, `label_css(kind)`, `text_css`, …) and `apply_app_theme(app)` (fonts, default
  font, QPalette, app-wide sheet for stock dialogs, menus incl. the tray menu, tooltips,
  scrollbars). No UI module hard-codes a colour. Qt sheets have no letter-spacing /
  text-transform: caps are applied to the translated string for display only
  (`tr("…").upper()`), spacing through `theme.display_font()` / `theme.body_font()`.
  Combo / spin arrows are `icons` chevrons rendered once per run to
  `%APPDATA%\translator-overlay\cache\ui_icons\*.png` (`theme.icon_url`), because
  sheets only take images from files.
- **Fonts** — display: Bahnschrift SemiBold (ships with Windows 10 1709+, has Cyrillic;
  fallback Segoe UI Semibold); body: JetBrains Mono, bundled in `assets/fonts/` and loaded
  with `QFontDatabase.addApplicationFont` (fallback Consolas). Frozen builds find the folder
  under `sys._MEIPASS` (`build_app.spec` datas).
- `ui/icons.py` — 24×24 stroke icons (home, sliders, clock, upload, copy, speaker, close,
  chevrons, arrow, search, globe, check, keyboard) drawn with `QPainterPath`;
  `icon(name, color)`, `pixmap(...)`, `paint(painter, ...)`.
- `ui/hud_widgets.py` — presentation-only widgets: `NavButton` (rail item, accent bar when
  active), `Panel(title)` (`panel.body` / `panel.header`), `FieldLabel`, `Chip(kind)`,
  `Segmented(options)` (`changed(data)`), `Switch` (real checkable button, painted) and
  `SwitchRow` (switch + label with the QCheckBox API used by the settings), `page_title()`.
- **Title bars** — `ui/title_bar.py`: the main window is `FramelessWindowHint` but gets its
  native `WS_CAPTION | WS_THICKFRAME | …` styles back (`install_native_frame`);
  `MainWindow.nativeEvent` → `title_bar.native_event` answers `WM_NCCALCSIZE` (whole window
  is client area; a maximised window is inset by the frame thickness) and `WM_NCHITTEST`
  (resize edges, `HTCAPTION` for the `TitleBar` strip outside its buttons). `WM_MOUSEACTIVATE`
  on that caption activates the window itself (`SetForegroundWindow` + `MA_ACTIVATE`): while
  the result popup was active the click left the window inactive and no drag started. So Aero Snap,
  drag, double-click maximise, the system menu and the min/max animations stay native while
  the strip uses the palette (`rail`, accent `//`). Window sizes add `title_bar.HEIGHT`.
  Other framed windows (dialogs, stock dialogs) keep the native bar, switched to dark mode by
  `theme.apply_title_bar` (an app event filter on first Show); on Windows 11 DWM also takes
  the palette caption/text/border colours.
- `MainWindow` (72 px nav rail: `PAGE_HOME` / `PAGE_SETTINGS` / `PAGE_HISTORY`),
  `show_and_switch(page)`, `set_tray_icon(tray)`; workers `_TextTranslateWorker`,
  `_ImageTranslateWorker`, `_UpdateCheckWorker` (at launch and every 30 min by
  `_update_timer`; skipped while a check runs or an update downloads; each new version is
  announced in the tray once). Home: status chips (online, language
  pair, hotkey), "Перевод текста" panel, "Из скриншота" panel with a drop zone (file
  dialog or drag-and-drop of an image file; one image at a time), "Последние" panel (the
  3 newest `cache.store.get_all_history` records, refreshed on page switch and after a
  translation; never logged). Columns stack below 760 px width.
- `SettingsWidget` — all settings; methods `_build_ui()`, `_load_current()`,
  `_on_save()`, `reload()`, `_css(extra)`; constants `_SOURCE_LANGUAGES`,
  `_TARGET_LANGUAGES`, `_ENGINES`, `_UI_THEMES`, `_OPENROUTER_MODELS`, `_MODEL_HINTS`.
  Section list (`_section_list`) + `_section_stack` with one scroll page per section
  (`_SECTIONS`): "Перевод" (API key and providers, backend, fast-translator keys,
  translation, custom profiles), "Хоткеи" (`QKeySequenceEdit` per app hotkey + "По умолчанию";
  `_apply_hotkey` → `settings/hotkeys.validate_app_hotkey` → `set_value` →
  `hotkeys_changed`; a rejected one is shown and the saved one restored; focus in/out emits
  `hotkey_capture`), "Регионы" (`refresh_regions()` lists `region_presets.load_presets()` as
  name · size · bind; "Добавить регион" / "Управление…" emit `add_region_requested` /
  `manage_regions_requested`, forwarded by `MainWindow` to `TranslatorApp._add_region`
  (selector → name prompt → `save_preset`) / `_show_presets_dialog`;
  `TranslatorApp._on_presets_updated` → `MainWindow.refresh_regions()` keeps the list current;
  "Мониторинг" emits `monitor_region_requested(x1, y1, x2, y2)` for the selected region, or
  `stop_monitoring_requested` while monitoring runs (`set_monitoring_active()`, fed by
  `TranslatorApp._start/_stop_live_monitoring` through `MainWindow.set_monitoring_active`,
  which also keeps the tray toggle in step; the presets dialog has no monitoring button);
  live monitoring `live_interval_sec` spin 1–120 s and `live_sensitivity` combo, autosaved,
  read by `_start_live_monitoring` at the next start), "Распознавание" (OCR
  acceleration, OCR preview), "Попап" (notifications, popup timeout), "Интерфейс"
  (language, colour scheme, about/updates).
  **Saving**: every no-restart setting saves itself — a change starts a 400 ms debounce
  (`_schedule_autosave` → `_autosave` → `_save_instant_settings`, which writes only when a
  value differs and returns the changed keys); line edits save on `editingFinished`; a
  pending change is flushed on `reload()` / `hideEvent`. LLM clients are reset on any change,
  the NLLB model only when `translation_backend` / `nllb_model_path` change; switching to
  NLLB starts the warm-up (never twice). Restart-only settings (`ui_language`, `ui_theme`)
  are not autosaved: changing them enables "Сохранить" (left column, under the section list)
  with an "applies after a restart" hint; `_on_save` writes them and offers a restart
  (`restart_requested` → `MainWindow.restart_requested` → `TranslatorApp._restart`).
  API keys stay explicit: "Проверить" validates, "Сохранить" validates and stores in keyring.
  The "Облако / Локально" segmented control drives `_backend_combo` (it remembers the last
  cloud backend); the auto-detect switch drives `_src_lang_combo` (the combo is what is
  saved).
- **Stylesheets on page ancestors must be selector-scoped** (`#pageStack { … }`, not a bare
  `background: …;`). A bare rule cascades into every descendant, including a `QMessageBox`
  opened from the page, and ancestor rules beat the app-wide sheet in `ui/theme.py`: the
  dialog then renders with no visible text or buttons. `main.py` installs `ui/theme.py` and
  `i18n.install_qt_translator()` (Russian Yes/No/Cancel on stock buttons).
- `ui/wheel_guard.py` (app-wide event filter, installed in `main.py`): a wheel event over a
  `QComboBox` / `QAbstractSpinBox` never changes its value; it goes to the nearest scroll
  area's viewport, so long pages scroll past controls. An open combo list still scrolls.
- `ResultPopup(...)` — frameless window, streaming updates via `update_content()`,
  auto-close after `config.POPUP_TIMEOUT_SEC` (3–600 s, read by `auto_close_ms()` at every
  timer start, so a settings change applies at once), resize by the left / right / bottom edges
  (the top edge is a drag handle), TTS, copy. A drag past 5 px is handed to the OS move
  loop (`QWindow.startSystemMove()`, manual `move()` only if that fails). The card fills the
  window (no transparent border that would swallow clicks next to it). The window is opaque
  (no `WA_TranslucentBackground`) because `show()` calls `_exclude_from_capture()` —
  `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, which fails on UpdateLayeredWindow
  windows: mss/OCR and live monitoring never see the popup (it covered tall regions such
  as a stream chat and re-triggered monitoring in a loop); screenshots and recordings do
  not show it either. `update_content` rebuilds the widgets; a result replacing a result
  keeps the scroll position (`_scroll_state` / `_restore_scroll`, at the bottom it follows
  new lines), the first result after "Переводим…" starts at the top. Placement
  (`_place`, pure geometry): under the selection (above if no room), but when that spot
  covers a visible app window (main window, dialogs) the nearest spot covering neither it
  nor the selection is used; no such spot → the usual place. When the popup grows from
  "Переводим…" to the result it steps aside again only if it now covers a window and the
  user has not dragged it (`_step_aside_if_covering`). Streaming
  chunks go to `show_partial()` (a wrapped body label; the header keeps "Переводим…").
  A size dragged by hand is saved to `settings.json` → `popup_size` (`config.POPUP_SIZE`,
  written once when the drag ends) and used by later updates, popups and launches (text wraps
  to it; `ResultPopup.saved_size()` clamps it); otherwise the popup fits the wrapped text.
  "Настройки → Попап" shows it and can reset it. Square
  card with a 1 px accent frame (`dim` while loading, `error` on error), icon buttons.
- `overlay/selector.py` — selection fill / border use the palette accent (alpha 30 / 220,
  read at construction, not at import) plus 8 px corner brackets.
- `tray/icon_gen.py` — flat accent tile with an `on_accent` "T" (also the window icon).

---

## 4. Data flow

```
[keyboard hotkey, background thread]
        │ HotkeyBridge.triggered (to the Qt thread)
        ▼
TranslatorApp._show_selector()
        ▼
overlay.selector.RegionSelector  ──region_selected(x1,y1,x2,y2)──►
        ▼
TranslatorApp._on_region_selected → _start_translation_pipeline(...)
        ▼
TranslationWorker(QThread).run():
   1. capture.screenshot.capture_region()       → PIL.Image
   2. ocr.engine.recognise()                    → str
      └─ if config.ENABLE_OCR_PREVIEW → ocr_done → OcrPreviewPopup →
         pipeline restarts with text_override
   3. translate.backend:
      SOURCE_LANG == "auto" ? detect_and_translate() : translate()
         │
         ├─ config.TRANSLATION_BACKEND == "api"  → translate.llm_client
         │     ├─ fast path: lang_detect.is_same_language → return without the API
         │     ├─ cache.store.get_cached()            → return on a hit
         │     ├─ coalescing by (text, src, tgt, domain)
         │     ├─ _call_with_resilience → provider #1 (retry) → provider #2
         │     └─ cache.store.save_to_cache()
         │
         └─ config.TRANSLATION_BACKEND == "nllb" → translate.nllb_backend
               ├─ ensure_loaded() — lazy model load (~1.2 s)
               │     ├─ device auto/cuda: GPU + cuBLAS found + warm-up OK → CUDA
               │     │     └─ any CUDA failure → CPU + one-shot notice via take_notice()
               │     └─ NllbModelUnavailable → fall back to llm_client + take_notice()
               ├─ fast path / cache (domain_id + "|nllb")
               ├─ langid when source=auto → FLORES code
               └─ CTranslate2 translate_batch (beam=4; GPU int8_float16 or CPU int8)
        ▼ signals
partial_result   → ResultPopup.update_content()   (live streaming, API only)
translation_done → _on_translation_finished → _show_result(notice=…) / _show_error
                   notice = TranslationWorker.backend_notice (from backend.take_notice())
                   → ResultPopup shows a "⚠ …" line under the translation
```

**Where state lives**

| State | Where |
|---|---|
| User settings | `%APPDATA%\translator-overlay\settings.json` (+ `config_manager._cache` in memory) |
| API keys | OS keyring, service `OverlayTranslator`; fallback — `.env` |
| Translation cache and history | `%APPDATA%\translator-overlay\cache\translations.db` + in-process L1 LRU |
| Region presets | `%APPDATA%\translator-overlay\region_presets.json` |
| Custom domain profiles | `%APPDATA%\translator-overlay\` (JSON) |
| Logs | `%APPDATA%\translator-overlay\app.log`, `crash.log`, `logs/translator.log` |
| Backend choice and model path | `settings.json`: `translation_backend`, `nllb_model_path` |
| LLM clients, system-prompt cache | module globals in `translate/llm_client.py` (reset — `reset_client()`) |
| Loaded NLLB model | singleton `translate/nllb_backend._backend` (reset — `reset_client()`; both at once — `translate.backend.reset()`) |
| One-shot fallback notice | `threading.local()` in `translate/backend.py` |
| RapidOCR singleton | module global in `ocr/engine.py` |

---

## 5. Configuration points

1. **`settings/config_manager.DEFAULTS`** — the canonical list of keys.
   A new setting = an entry in `DEFAULTS` (otherwise `save_config()` drops it)
   + a property in `config._LiveConfig` + a control in `ui/settings_dialog.SettingsWidget`
   (`_build_ui` → `_load_current` → `_on_save`).
2. **Translation backend choice** — `settings.json`:
   - `translation_backend`: `"google"` (default: keyless `client=gtx` endpoint, or the official
     Cloud API when a Google key is saved) | `"api"` (LLM) | `"deepl"` | `"azure"` | `"nllb"`;
     unknown values fall back to Google (`backend.DEFAULT_BACKEND`). The first-run key dialog
     only appears when the LLM backend is selected without a key (`backend.needs_llm_key()`);
   - `first_run_done`: set once the setup wizard (`ui/setup_wizard.py`) is finished or closed.
     The wizard writes `translation_backend` (online → `google`, API key → `api`, offline →
     `nllb`) and, offline, `nllb_model_path` of the build it found or downloaded
     (`nllb_models.download_version`, SHA-256 checked). Closing it keeps the defaults; a
     running worker of a closed wizard is parked until it ends. "Настройки → Интерфейс →
     Пройти мастер настройки заново" runs it again;
   - `nllb_model_path`: explicit path to the CTranslate2 directory (`""` = auto-discovery).
   Changed in "Настройки → Бэкенд перевода" (Settings → Translation backend), which
   also has the "Загрузить модель" (Load model) button with a progress indicator and
   a model-availability status. The `NLLB_MODEL_DIR` environment variable overrides
   the path without editing settings.
   `nllb_device` (`"auto"` by default | `"cpu"`, Settings → Device; `config.NLLB_DEVICE`)
   picks the inference device; the `NLLB_DEVICE` env var (`auto` | `cuda` | `cpu`) overrides it.
   **Model build version**: `config.NLLB_HF_REPO_ID` + `config.NLLB_HF_REVISION`
   (default `Alhite/overlay-translator-nllb-int8` @ the commit SHA of tag `v0-base`, env-overridable) — the only
   place that pins which weights `scripts/download_model.py` fetches.
3. **`.env`** (see `.env.example`) — API keys and static overrides
   (`EASYOCR_*`, `OVERLAY_*`, `CACHE_DIR`, `LOG_DIR`, `SETTINGS_HOTKEY`, `GITHUB_REPO`).
   **App hotkeys** — `settings.json` → `hotkey` (translate, `ctrl+shift+r`) and
   `settings_hotkey` (`ctrl+shift+o`), set in "Настройки → Хоткеи" and applied at once.
   `settings/hotkeys.py`: `from_key_sequence()` (Qt names → `keyboard` names, first chord
   only), `validate_app_hotkey()` (syntax via `keyboard.parse_hotkey`; a single ordinary
   key is refused, F1–F24 alone are fine; no clash with the other app hotkey or a preset).
4. **Keyring** — the working store for API keys (`settings.set_api_key`).
5. **`translate/domain_profiles/*.json`** — system prompts and few-shot examples per domain.
6. **`region_presets.json`** — saved regions and their individual hotkeys.
7. **`build*.spec` / `build.py`** — PyInstaller build parameters. `build.py --installer`
   (or `--installer-only` for an existing `dist/TranslatorOverlay/`) then runs Inno Setup 6
   (`ISCC.exe`: `$ISCC`, PATH or the default install dirs) on `installer/TranslatorOverlay.iss`
   with `/DAppVersion=` from `config.APP_VERSION` → `dist/installer/TranslatorOverlay-Setup-<version>.exe`.
   Per-user install by default (no admin, `%LOCALAPPDATA%\Programs`), all-users optional;
   `AppMutex` = the `single_instance` mutex, shortcuts carry main.py's AppUserModelID,
   optional desktop icon and autostart (`HKA\…\Run`). User data in `%APPDATA%` is left on
   uninstall. `tests/test_build_installer.py` keeps these values in step with the app.
   **Update package** (groundwork for app-only updates, `docs/DELTA_UPDATE_PLAN.md`; the
   updater does not use it yet). The deps fingerprint also covers `runtime_tag()` (Python
   ABI + PyInstaller version). Every build writes `dist/TranslatorOverlay.layers.json`: the
   deps-layer files (copied by `merge_deps_into_app`, or already collected by the app spec
   byte-identically, e.g. Qt5) and the fingerprint. Large native packages the app imports
   (`ctranslate2`, `sentencepiece`, `pydantic_core`, `sqlite3`) live in `build_deps.spec`
   and are excluded from `build_app.spec`, so the app layer is mostly the exe.
   `build.py --update-package` (also run by `--installer` / `--installer-only` before ISCC)
   writes `dist/installer/TranslatorOverlay-app-<version>.zip` (every file of the final
   tree not from the deps layer; the VC++ runtime DLLs count as app layer) and
   `update-manifest.json` (`version`, `deps_fingerprint` = hash of the runtime tag and the
   path + SHA-256 of every deps-layer file in the final tree, `.pyc` without the 16-byte
   header with the source mtime, so a deps layer rebuilt after a CI cache eviction keeps it,
   `runtime`, `app_zip` name/sha256/size, `app_files`). The `.iss` installs the manifest
   into `{app}`.
   **Release pipeline** — `.github/workflows/release.yml` on a `v*` tag (windows-latest):
   `build.py --check-tag` (tag == `v` + `APP_VERSION`, `CHANGELOG.md` has that section) →
   packages from `requirements-lock.txt` → `pytest` (offscreen Qt) → Inno Setup via choco if missing → deps layer restored from
   `actions/cache` keyed by `build.py --fingerprint` → `build.py --installer` → SHA-256 of
   Setup.exe and the app zip into `build.py --release-notes --sha256 --app-sha256`
   (changelog section + install steps + checksums; no separate `.sha256` files) → draft
   release with Setup.exe, `TranslatorOverlay-app-<version>.zip` and `update-manifest.json`
   (re-runs `--clobber` the files). Manual runs only upload an artifact. Process: CONTRIBUTING.md.
   **Pinned deps and the shared cache** — an app-only update applies only when the deps
   layer is byte-identical between releases. `requirements-lock.txt` pins every package
   (`build.py --lock-requirements` resolves `requirements.txt` with `pip --dry-run
   --report`; it is part of the deps fingerprint). A tag run can restore only caches of
   that tag or of main, so `.github/workflows/deps-cache.yml` (push to main touching the
   deps, weekly, manual) installs the lock and runs `build.py --deps-only`: it builds the
   layer into `_build_cache/<fingerprint>` once per fingerprint, and the weekly restore
   keeps the cache from being evicted. Without it every release rebuilt the layer and
   resolved the open ranges anew (1.4.0 → 1.4.1 got newer certifi/anthropic/jiter), so
   the fingerprints never matched.
   **One-click update** (`updater/install_update.py`, update banner in `MainWindow`): only when
   `can_self_update()` (frozen + `unins000.exe` next to the exe; otherwise the release page).
   `_UpdateInstallWorker`: `latest_release()` → `download_setup()` into
   `%TEMP%\translator-overlay-update` (`.part`, renamed only after the SHA-256 matches) →
   `launch_installer()`: a hidden PowerShell (`CREATE_NO_WINDOW`; with `DETACHED_PROCESS` it
   never runs) does `Wait-Process` on the app's pid, then starts the setup `/VERYSILENT
   /SUPPRESSMSGBOXES /NORESTART /RELAUNCH=1` → `MainWindow.update_install_started` → app
   `_quit`. The setup must not start while the app's mutex exists: a silent setup answers
   the AppMutex prompt with Cancel. The `.iss` `[Run]` entry `Check: RelaunchRequested`
   (`{param:RELAUNCH|0}`) starts the new version `runasoriginaluser`.
   **App-only update**: the worker calls `prepare_update()`, which tries the light path
   first. `choose_update_path()` returns `"app"` only when the installed
   `{app}\update-manifest.json` (this `APP_VERSION`) and the release's manifest have the
   same `deps_fingerprint` and `runtime`, and the release's zip asset is the one the
   manifest names (same SHA-256). It also needs a manifest checked by its asset
   `digest`, a writable install dir (an all-users install takes the setup) and no
   `%APPDATA%\translator-overlay\update\app-update-failed-<version>.txt` (written when
   the swap rolled back or could not start; not in `%TEMP%`, so a cleanup does not
   retry it). `download_app_zip()` checks the SHA-256 and that the zip holds exactly
   `app_files` (safe relative paths only). Any failure before the app quits falls back
   to `download_setup()`. `launch_update()` → `launch_app_update()` writes
   `apply-update.ps1` (UTF-8 with BOM; `-File`, ~650 paths do not fit
   `-EncodedCommand`) and runs it hidden. After `Wait-Process` it extracts the zip to
   `{app}\.update-staging`, renames each replaced file and each file of the old
   `app_files` the new version drops to `*.old`, moves the new files in, writes the new
   manifest. On any error it deletes the new files, moves the `.old` ones back and
   writes the failure marker. Only after a successful swap it deletes the `.old` files
   and sets `DisplayVersion` of the Inno uninstall key. Either way it then starts
   `TranslatorOverlay.exe`. The plan compares paths case-insensitively (a file renamed
   only in case is not removed). The `.iss` `[UninstallDelete]` removes
   `{app}\_internal`, `{app}\.update-staging` and `{app}\*.old`, so files added by app
   updates go on uninstall too. The banner shows
   the download size ("…: 40% из 14 МБ").
8. **Interface language** — `settings.json` → `ui_language`: `"auto"` (default) | `"ru"` | `"en"`,
   set in "Настройки → Интерфейс" (Settings → Interface). It is resolved once per process
   (`i18n.current_language()`), so a change applies after a restart. `"auto"` picks Russian
   for a Russian/Ukrainian/Belarusian Windows UI language, otherwise English.
   **Colour scheme** — `settings.json` → `ui_theme`: `"amber"` (default) | `"cyan"` |
   `"crimson"` (`config.UI_THEME`), set next to the language; also applied after a restart.
   UI strings stay Russian in the code, wrapped in `tr("…")` (`N_("…")` marks module-level
   constants that are translated where shown); placeholders go through keyword arguments,
   `tr("Ошибка: {error}", error=e)`, never f-strings. The English text lives in `i18n/en.py`;
   a missing entry falls back to Russian. Built-in domain profile names are translated via
   `domain_manager.display_name_of()`; custom profile names, LLM prompts and few-shot
   examples are not translated.

Settings autosave (see `ui/` → `SettingsWidget`): any change resets the LLM clients
(`llm_client.reset_client`); `translate.backend.reset()`, which also drops the loaded NLLB
model, runs only when the backend or the model path changes.

---

## 6. External dependencies and where they are called

| Service / library | Where it is called |
|---|---|
| **OpenRouter API** (`openai` SDK, `base_url=https://openrouter.ai/api/v1`) | `translate/llm_client.py::_get_client_for`, `_call_provider` |
| **Anthropic API** (`anthropic` SDK) | `translate/llm_client.py::_get_client_for`, `_call_provider` |
| **GitHub Releases API** | `updater/check_update.py::check_for_update` (repository from `config.GITHUB_REPO`); `updater/install_update.py::latest_release` (installer asset + its `digest` SHA-256, else the checksum line of the notes) |
| **RapidOCR / ONNX Runtime (DirectML)** (local; a rec model missing from `rapidocr/models/` is downloaded from ModelScope on first launch) | `ocr/engine.py::get_reader` / `_build_engine` |
| **CTranslate2 + sentencepiece** (local, offline) | `translate/nllb_backend.py::NllbBackend.ensure_loaded` / `_raw_translate` |
| **cuBLAS 12** (optional; `nvidia-cublas-cu12` wheel or CUDA Toolkit 12.x) | `translate/cuda_support.py::prepare_cuda_libraries`, loaded lazily by CTranslate2 on the first GPU matmul |
| **Hugging Face Hub** (`huggingface_hub`, public repo, no login) | `translate/nllb_models.py` (Settings and the first-run wizard: list the model tags, download a build, check each file's SHA-256) and `scripts/download_model.py`. Never called during a translation |
| **langid** (local) | `translate/lang_detect.py::LangidDetector`, `nllb_backend._detect_source` |
| **keyring** (Windows Credential Manager) | `settings/__init__.py::_get_keyring` |
| **mss** (screen capture) | `capture/screenshot.py` |
| **TTS (SAPI)** | `tts/engine.py::speak` |

All network SDKs and `ctranslate2` are imported **lazily** so they do not slow down
app start. The local backend never touches the network.

Only for the offline utilities (in `requirements-dev.txt`, not part of the app):
`transformers` + `torch` — converting the HF checkpoint to CTranslate2;
`sacrebleu` — the chrF metric in `scripts/baseline_eval_nllb.py`.

---

## 7. Known limitations and TODO

- **Effectively Windows-only**: `keyboard` hotkeys, keyring, console hiding,
  `%APPDATA%` paths, `.ico` icon.
- `config.py` replaces itself in `sys.modules`, which is unusual: static analysers
  and IDEs cannot see its attributes, and `from config import X` does not behave as expected.
- The `llm_vision` and `api` engines are listed in `_ENGINES` (UI), but the
  `TranslationWorker` pipeline always takes the OCR → LLM text path.
- The local NLLB backend **does not use domain profiles** (prompts and few-shot):
  a seq2seq model cannot take them, so the translation context has no effect on it.
  That is exactly what the upcoming fine-tuning is for.
- The local backend has no streaming: the popup shows the result all at once.
- `langid` makes mistakes on short and noisy OCR lines (for example, Polish
  `idziemy na raid` is detected as `en`), and NLLB translation quality with
  `source_language=auto` depends directly on it.
- NLLB quality on gaming slang is poor without fine-tuning (`healer` → «врач» (doctor),
  `boss is enraged` → «начальник злится» (the manager is angry)) — see `docs/baseline_eval.md`.
- Cache and history are the same table; there is no separate "history" with metadata
  (provider, model, duration). The backend is told apart only by the `"|nllb"` suffix
  on `domain_id`, which `scripts/export_history_dataset.py` uses to drop the model's
  own output from the training set.
- Very little history has been collected and it is almost all test strings, so the
  baseline in `docs/baseline_eval.md` was computed on 6 pairs and is not statistically
  significant. It has to be recomputed after real use of the app.
- Not covered by tests: most of the UI layer, `main.py`, `capture/screenshot.py`, `tts/`.
- **Open: the app crashed once after the second NLLB translation** (2026-09-23 21:32,
  WER: `Qt5Core.dll`, `0xc0000409` subcode 7 = `qFatal` → `abort()`), after
  `NLLB OK` had been logged. Not reproduced headless. Main suspect:
  `_HomePage._on_text_translated` drops the last reference to a `QThread` that is
  still running. Diagnostics added for the next occurrence: Qt messages go to
  `app.log` (`qInstallMessageHandler` in `main.py`); `faulthandler` writes all
  thread stacks to `%APPDATA%\translator-overlay\crash.log`; worker/inference
  DEBUG logs in `ui/main_window.py` and `nllb_backend._raw_translate`.
- The hard-coded `HTTP-Referer` in the OpenRouter headers points to a placeholder repository.

---

## 8. Tests

Location: `tests/`. Style: `unittest.TestCase`; they also run under pytest.

| File | Coverage |
|---|---|
| `tests/test_ocr.py` | preprocessing, box sorting, GPU mode → DirectML, rec language, model dir seeding, confidence filter, strip offsets, GPU → CPU fallback (mocked engine) |
| `tests/test_lang_detect.py` | script/language detection, "same language" fast path |
| `tests/test_llm_resilience.py` | error classification, retry/backoff, moving along the provider chain |
| `tests/test_domain_profiles.py` | loading/merging domain profiles |
| `tests/test_region_presets.py` | preset CRUD, validation of names/coordinates/hotkeys |
| `tests/test_update_banner.py` | update check at launch and every 30 min, no check while one runs or an update downloads, each version announced once |
| `tests/test_popup_live.py` | popup excluded from screen capture and kept opaque, live update without taking focus, regions dialog rows and monitoring button |
| `tests/test_settings_regions.py` | Settings → Regions list (size, bind, empty state), add / manage signals, live monitoring settings autosave, sensitivity thresholds and interval clamping |
| `tests/settings_widget_case.py` | helper: SettingsWidget built offscreen with settings.json, keyring, presets and backends mocked |
| `tests/test_install_update.py` | one-click update: installer + SHA-256 from a release (digest / notes, none → no update), version check, verified download with cleanup, waiter script and its process flags, self-update only for an installed app, the setup's relaunch hook; app-only update: zip + manifest assets, manifest parsing (unsafe paths refused), `choose_update_path`, swap plan, fallback to the installer (bad zip, deps changed, read-only dir, earlier rollback), swap script with rollback, `-File` launch with a BOM |
| `tests/test_app_hotkeys.py` | app hotkeys: Qt sequence → keyboard name, validation (single key, clashes with the other hotkey / presets), `SETTINGS_HOTKEY` env override, the settings page saving / rejecting an edit and pausing the hooks on focus |
| `tests/test_cuda_download.py` | GPU offer states, cuBLAS wheel checksum / DLL-only unpacking / cleanup on failure and cancel, search order, NLLB device setting vs env |
| `tests/test_cuda_support.py` | cuBLAS search order, PATH preparation, NLLB CPU fallback for every CUDA failure mode (fake `ctranslate2`, no GPU needed) |
| `tests/test_theme.py` | every palette defines every token, unknown `UI_THEME` → amber, builders return resolved sheets, WCAG contrast ≥ 4.5 for text/muted/text_soft/accent on bg/panel and on_accent on accent, icons render |
| `tests/test_settings_autosave.py` | settings save themselves once after the debounce, opening/reload write nothing, restart-only settings light "Сохранить" and are saved + restart offered only from it |
| `tests/test_popup_size.py` | saved popup size parsing/clamping, written once when a resize drag ends |
| `tests/test_title_bar.py` | a click on the drawn caption activates the main window (drag works while the popup is active) |
| `tests/test_setup_wizard.py` | when the first-run wizard shows (fresh / upgraded / unfinished), what each mode saves, offline build list and preselection, closing never drops a running worker |
| `tests/test_popup_placement.py` | popup placed under/above the selection, steps off the main window to the nearest free spot, keeps the usual place when none |
| `tests/test_popup_drag.py` | popup top edge drags instead of resizing; a drag goes to the OS move loop, manual move as fallback |
| `tests/test_backend_dispatch.py` | `translate.backend` routing: NMT clients with a per-backend cache, NLLB used when it loads, missing model → API with a one-shot notice, a loaded model's error is not hidden, `preload()` never raises |
| `tests/test_nllb_backend.py` | NLLB with a stubbed model (fake `ctranslate2` / `sentencepiece`): model discovery, load errors, FLORES codes and token layout, cache namespace, fast path, unsupported language, inference errors, singleton reset |
| `tests/test_cache_store.py` | L1 LRU and L2 SQLite cache: round trip, key parts, eviction on both levels, `warm_cache()`, history order, `clear_history()`, rebuild of an old schema |
| `tests/test_training_data.py` | `training/` splits without leakage (stratified abbreviation split, phrase split, disjoint FLORES pools) and the metrics in `training/evaluate.py` (keep-rate, chrF groups, paired bootstrap) |
| `tests/test_training_pipeline.py` | `configs/train/*.yaml` validation and `{name}` expansion, the shipped v1/v2 hyperparameters, dataset hash and git provenance, `training/pipeline.py` stage commands and overwrite guards, config → `finetune_lora.py` defaults (no torch) |
| `tests/test_i18n.py` | `tr()` lookup and placeholders, `"auto"` language resolution, and that `i18n/en.py` covers every `tr()`/`N_()` literal in the app (no missing, unused or duplicate keys) |

Running:

```bash
py -m unittest discover -s tests -p "test_*.py" -v
# or
pytest tests/ -v
```

Run from the project root (modules are imported as top-level packages). pytest,
coverage and ruff settings live in `pyproject.toml`:

- `pytest -m "not slow"` is what CI runs; a test that needs a real model or a GPU
  is marked `@pytest.mark.slow`.
- `pytest --cov` measures `translate/`, `cache/` and `settings/` and fails below 60 %.
- CI (`.github/workflows/ci.yml`): ruff, then the tests on Windows and Linux (both
  required); pushes to `main` publish the coverage badge data to the `badges` branch.
- Off Windows, tests that validate hotkey strings stub the key name lookup
  (`tests/keyboard_stub.py`: the `keyboard` library needs root on Linux), and tests of
  WinAPI calls mock `ctypes.windll` with `create=True` or are skipped.

---

## 9. Local model: utilities and workflow

Everything is in `scripts/` and is not part of the app build. Run from the project
root with the venv interpreter.

### Where the model comes from and how its version is pinned
The app never downloads the model; it only looks for it on disk (search order in
section 3, `nllb_backend.py`). There are two ways to get it:

1. **Download the published build** (normal path for anyone but the model maintainer):
   `python scripts/download_model.py` → `huggingface_hub.snapshot_download(repo_id, revision,
   local_dir=models/nllb-200-ct2-int8)`. `models/nllb-200-ct2-int8` is the first auto-discovery
   location, so no settings change is needed. The script verifies the required files
   (`nllb_backend.missing_files`) and re-runs only fetch changed files.
2. **Convert it yourself** (below) — needed only to produce a new build.

**Versioning.** Builds are identified by **tags** in the HF repo, never by `main`:
- `v0-base` → commit `0e37166` — the plain int8 conversion of `facebook/nllb-200-distilled-600M`.
- A new build (e.g. after fine-tuning) = upload it, create a new tag (`v1-…`), then set
  `NLLB_HF_REVISION` in `config.py` to **that tag's full commit SHA** in the same commit that needs it
  (`https://huggingface.co/api/models/<repo>/revision/<tag>` → `sha`). The default is a SHA, not a tag
  name, because a tag can be moved: whoever controls the HF account could otherwise ship other files.
  Still never move or reuse a tag.
- `NLLB_HF_REVISION` can also be overridden via env or `--revision` to try another build.

The HF repo is self-contained (`model.bin`, `config.json`, `shared_vocabulary.json`,
`sentencepiece.bpe.model` + tokenizer JSONs + model card). Its model card lists speed numbers,
limitations and the CC-BY-NC-4.0 license inherited from NLLB-200.

### Converting the HF checkpoint to CTranslate2 int8
A one-off step; needs `transformers` + `torch` from `requirements-dev.txt`.

```bash
ct2-transformers-converter   --model  models/nllb-200-distilled-600M   --output_dir models/nllb-200-ct2-int8   --quantization int8   --copy_files tokenizer.json tokenizer_config.json special_tokens_map.json                sentencepiece.bpe.model generation_config.json
```

Result: 2.31 GiB (fp32) → 621 MiB (int8), −73.8%.
**Do not delete** the original checkpoint: it is needed for fine-tuning.

### `scripts/test_nllb_translation.py`
Model smoke test: loads the model, translates gaming phrases across pairs from
en/de/fr/es/ru/uk/be/pl/cs/hu, prints the CPU inference time.
Depends only on `ctranslate2` + `sentencepiece`.

```bash
python scripts/test_nllb_translation.py [--model DIR] [--threads N] [--beam N]
```

### `scripts/export_history_dataset.py`
SQLite history → JSONL for fine-tuning: `{"source", "target", "src_lang", "tgt_lang"}`.
Drops rows produced by the local model (`domain_id` with the `|nllb` suffix), pairs
where source == translation, empty rows and duplicates; a `source_lang` of `_auto` / `auto`
is resolved via `langid`.

```bash
python scripts/export_history_dataset.py   [--db PATH] [--out data/history_pairs.jsonl] [--domain game]   [--lang-format iso|flores] [--with-metadata] [--val-ratio 0.1] [--include-nllb]
```

### `scripts/baseline_eval_nllb.py`
Runs the non-fine-tuned NLLB on the exported pairs, computes chrF (sacrebleu) and
writes side-by-side examples. Writes the report to `docs/baseline_eval.md`.

```bash
python scripts/baseline_eval_nllb.py [--dataset ...] [--sample 30] [--seed 13]
```

The reference in the dataset is the API backend's translation, not a human one, so chrF
measures **agreement with the API**, not absolute quality. Only the difference between
runs before and after fine-tuning with the same `--seed` is meaningful.

### Switching the backend in the app
"Настройки → Бэкенд перевода" (Settings → Translation backend): radio buttons
"API (Anthropic / OpenRouter)" and "Локальная модель (NLLB)" (Local model), the
"Версия модели" (Model version) combo, the model path field (only for "Свой путь…"), and the "Загрузить модель" (Load model) button with a progress indicator.
The version combo lists every tag of `NLLB_HF_REPO_ID` (`translate/nllb_models.py`, stdlib
HTTP only, so it works in the frozen app): a tag already on disk (matched by the
`.hf-version.json` marker or by directory name, e.g. `nllb-v1-abbr-ct2-int8`) selects that
path; a missing one turns the button into "Скачать" (Download), which fetches the tag's commit
into `models/nllb-<tag>` (per-user `models` in the frozen app) with SHA-256 checks on LFS
files. "Автовыбор" (Auto) keeps the path empty → auto-discovery.
The choice is stored in `settings.json` (`translation_backend`, `nllb_model_path`)
and survives a restart.
The choice is saved as soon as it is made (settings autosave).
The status line shows the device the model actually runs on (`Device: CUDA/CPU`)
and, after a CPU fallback, the reason.

---

_Created: 2026-09-23. Updated: 2026-09-24 (local NLLB backend, backend switching,
export and baseline scripts; optional CUDA with CPU fallback, crash diagnostics;
translated to English; model published on the HF Hub, pinned download)._
_Update it after significant structural changes._
