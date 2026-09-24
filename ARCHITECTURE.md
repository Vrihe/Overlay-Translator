# ARCHITECTURE.md — Overlay Translator project map

> Internal document for finding your way around the repository quickly.
> Read it instead of re-scanning every file.

---

## 1. Overview

**Overlay Translator** is a Windows desktop app (PyQt5). A global hotkey lets
you select any region of the screen; the app recognises the text in it (OCR)
and shows the translation in an always-on-top popup.

**Main flow**: `Ctrl+Shift+R` → selection frame → screenshot of the region →
EasyOCR → translation (cloud API **or** the local NLLB model) → popup with the translation.

**Stack**:

| Layer | Technology |
|---|---|
| GUI | PyQt5 5.15 (QMainWindow + sidebar, QSystemTrayIcon, frameless popups) |
| Screen capture | `mss` |
| OCR | EasyOCR (CRAFT + CRNN) on top of torch/torchvision, CPU or CUDA |
| Translation (API) | OpenRouter (OpenAI-compatible SDK) and/or Anthropic SDK |
| Translation (offline) | NLLB-200-distilled-600M, CTranslate2 int8 + sentencepiece, CPU or optional CUDA |
| Language detection | `langid` + a script heuristic, or an LLM |
| Storage | SQLite (cache + history), JSON (settings, presets, profiles) |
| Secrets | OS keyring (Windows Credential Manager) + `.env` |
| Hotkeys | `keyboard` (global, background thread) |
| Packaging | PyInstaller (`build.py`, `*.spec`) |

The UI and user-facing messages are in Russian; code, comments, docstrings and
documentation are in English.

---

## 2. Directory layout

```
Overlay-Translator/
├── main.py                 # Entry point: logging, splash, TranslatorApp, hotkeys
├── config.py               # Global config facade (replaces itself in sys.modules!)
├── build.py / build.bat    # PyInstaller build scripts
├── build*.spec             # Spec files (layered build: app + deps)
├── hooks/hook-optree.py    # PyInstaller hook
├── pyi_rth_torch_dll.py    # Runtime hook: torch DLL paths in the frozen build
├── _deps_stub.py           # Stub for the layered dependency build
│
├── capture/                # Screen capture
│   ├── screenshot.py       #   capture_region() via mss
│   └── live_monitor.py     #   LiveMonitor(QThread) — periodic re-scan of a region
│
├── ocr/                    # Text recognition
│   ├── engine.py           #   EasyOCR singleton, preprocessing, line sorting
│   └── hsv_filter.py       #   Optional HSV filter for coloured text
│
├── overlay/
│   └── selector.py         #   RegionSelector — full-screen selection frame
│
├── translate/              # Translation and language logic
│   ├── backend.py          #   * Dispatcher: picks the API or the local model
│   ├── llm_client.py       #   * Translation backend via the cloud API
│   ├── nllb_backend.py     #   * Offline backend: NLLB-200 (CTranslate2 int8)
│   ├── cuda_support.py     #   Locates cuBLAS for optional GPU inference
│   ├── domain_manager.py   #   Domain profiles (prompts + few-shot)
│   ├── lang_detect.py      #   Language detection, "same language" fast path
│   ├── error_classification.py  # Whether a provider error is retryable
│   └── domain_profiles/    #   general.json, chat.json, game.json, documentation.json
│
├── cache/                  # SQLite cache and history (L1 LRU + L2 SQLite)
│   └── store.py            #   * translations table schema
│
├── settings/               # Settings persistence
│   ├── __init__.py         #   * API keys via keyring + provider/fallback
│   ├── config_manager.py   #   * settings.json: DEFAULTS / get / set_value
│   └── region_presets.py   #   Screen-region presets + their hotkeys
│
├── ui/                     # PyQt5 widgets
│   ├── main_window.py      #   MainWindow with sidebar (Home/History/Settings)
│   ├── settings_dialog.py  #   * SettingsWidget — all settings; ProfileEditorDialog
│   ├── result_popup.py     #   ResultPopup — result window (TTS, copy, resize)
│   ├── first_run_dialog.py #   First-run wizard (API key entry)
│   ├── ocr_preview_popup.py#   Preview/edit OCR text before translating
│   └── region_presets_dialog.py # Manage presets and their hotkeys
│
├── history/
│   └── history_window.py   #   HistoryWidget/HistoryWindow — view and export history
│
├── tray/                   # System tray icon + context menu
├── tts/engine.py           # Text-to-speech for translations (SAPI, separate thread)
├── updater/check_update.py # Checks GitHub releases
├── scripts/                # Offline utilities (not part of the app build)
│   ├── test_nllb_translation.py    # Local model smoke test + CPU latency
│   ├── export_history_dataset.py   # SQLite history → JSONL for fine-tuning
│   └── baseline_eval_nllb.py       # NLLB chrF baseline on real pairs
├── tests/                  # unittest/pytest tests
├── docs/
│   └── baseline_eval.md    #   NLLB quality reference point before fine-tuning
├── data/                   # Exported datasets (gitignored — user data)
└── assets/icon.ico         # Application icon
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
- NLLB models: `D:\projects\overlay-translator\models\` on the developer machine
  (`nllb-200-distilled-600M` — original HF checkpoint, 2.31 GiB, needed for fine-tuning;
  `nllb-200-ct2-int8` — CTranslate2 int8, 621 MiB, used by the app).
  Outside the repository, never committed.

---

## 3. Modules and responsibilities

### `main.py` — orchestrator
- `_init_logging() -> str` — DEBUG log to `%APPDATA%/translator-overlay/app.log`, before any other import.
- `_global_excepthook` / `_thread_excepthook` — log unhandled exceptions.
- `faulthandler` → `crash.log` and `_qt_message_handler` (Qt messages, including `qFatal`, → `app.log`) —
  catch native crashes that bypass the Python hooks.
- `_preload_torch_dlls()` — preloads torch DLLs (needed for the frozen build).
- `class HotkeyBridge(QObject)` — `triggered = pyqtSignal()`; bridge from the `keyboard` thread to the Qt thread.
- `class TranslationWorker(QThread)` — the whole pipeline in the background.
  Signals: `translation_done(str src, str translated, str error)`,
  `partial_result(str)` (streaming), `ocr_done(str, QRect)`.
  Constructor: `(x1, y1, x2, y2, text_override: str|None = None, ocr_only: bool = False)`.
- `class OcrWarmupWorker(QThread)` — warms up EasyOCR 3 s after start.
- `class TranslatorApp` — owns `QApplication`, `MainWindow`, `TrayIcon`, hotkeys,
  the selector, popups, live monitoring and preset hotkeys.
  Key methods: `_show_selector`, `_on_region_selected`,
  `_start_translation_pipeline(x1, y1, x2, y2, anchor, text_override=None)`,
  `_on_ocr_preview_requested`, `_toggle_live_monitoring`, `_register_preset_hotkeys`,
  `_on_partial_translation`, `_on_translation_finished`, `_show_result`, `_show_error`,
  `_quit`, `run`.
- `main()` — splash → first-run wizard (if there are no keys) → `TranslatorApp(app).run()`.

### `config.py` — config facade
Unusual trick: at the end of the module, `sys.modules[__name__] = _LiveConfig()`,
so `import config; config.TARGET_LANG` reads a **property** that calls
`settings.config_manager.get(...)` every time. Assigning
`config.TARGET_LANG = "en"` writes to `settings.json` immediately.

- Dynamic (settings.json): `HOTKEY`, `TARGET_LANG`, `SOURCE_LANG`,
  `TRANSLATION_ENGINE`, `TRANSLATION_BACKEND`, `NLLB_MODEL_PATH`, `LLM_MODEL`,
  `POPUP_TIMEOUT_SEC`, `NOTIFICATION_TYPE`,
  `OCR_LANGUAGES`, `ACTIVE_DOMAIN`, `PRIMARY_PROVIDER`, `ENABLE_FALLBACK`,
  `ENABLE_STREAMING`, `ENABLE_OCR_PREVIEW`, `COMPACT_PROMPT`, `LLM_MAX_TOKENS`.
- Static (env/constants): `MAX_RETRIES_PER_PROVIDER`, `RETRY_BACKOFF_BASE_SEC`,
  `OPENROUTER_MODEL`, `ANTHROPIC_DETECT_MODEL`, `APP_VERSION`, `GITHUB_REPO`,
  `SETTINGS_HOTKEY`, `EASYOCR_*`, `OVERLAY_*`, `USER_DATA_DIR`, `CACHE_DIR`,
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
BACKENDS: list[tuple[str, str]]      # (id, label) for the settings UI
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
get_provider_chain() -> list[str]
```

Internals: `_get_client_for(provider)` (lazy import of `openai`/`anthropic`),
`_call_provider(...)` (streaming and non-streaming paths),
`_call_with_resilience(...)` (retry with exponential backoff + fallback along the
provider chain), `_build_system_prompt(domain_id, target_lang, source_lang)` with a cache,
request coalescing via `_in_flight` (two identical concurrent requests → one API call).

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
- **No streaming** (CTranslate2 beam search does not provide it): `on_chunk`
  is called once with the final text, so the UI behaves the same way.
- With `source_language=auto` the source language is detected offline via `langid`.
- Runtime dependencies are only `ctranslate2` + `sentencepiece`, no torch or transformers.
- **GPU is optional** (`device=None` → `NLLB_DEVICE` env → `"auto"`). In auto/cuda mode
  `translate/cuda_support.py` locates `cublas64_12.dll` (pip wheel `nvidia-cublas-cu12`,
  then `CUDA_PATH*`, then the default toolkit dir) and prepends it to `PATH`, because
  CTranslate2 loads cuBLAS via plain `LoadLibrary` and ignores `os.add_dll_directory`.
  cuBLAS loads lazily, so a tiny warm-up translation verifies the GPU. Any failure → CPU
  plus a one-shot notice via `take_notice()` → `translate.backend.take_notice()` → result popup.

Model search order: explicit path from settings → `NLLB_MODEL_DIR` →
`<project>/models/nllb-200-ct2-int8` → `%APPDATA%/translator-overlay/models/…` →
`D:\projects\overlay-translator\models\…`. An explicitly set path is authoritative:
if it is wrong, the backend reports that instead of picking up another copy.

### `translate/cuda_support.py` — cuBLAS discovery for the GPU path
```python
candidate_dirs() -> list[Path]      # search order, deduplicated
find_cublas_dir() -> Path | None    # first dir containing cublas64_12.dll
prepare_cuda_libraries() -> Path | None  # prepend that dir to PATH once (Windows only)
cublas_missing_hint() -> str        # user-facing "not found, install …, searched: …"
```
Search order: `<sys.path entry or _MEIPASS>/nvidia/cublas/bin` (pip wheel
`nvidia-cublas-cu12`, see `requirements-gpu.txt`) → `%CUDA_PATH%\bin`,
`%CUDA_PATH_V12_*%\bin` → `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*\bin`.
Only cuBLAS is needed for NLLB; cuDNN/cudart are not. Called only from
`NllbBackend._create_cuda_translator`. The CPU fallback policy lives in
`NllbBackend._create_translator`: a missing GPU in `auto` mode is logged at INFO
with no user notice; every other CUDA failure logs a WARNING and leaves a notice.

### `translate/domain_manager.py`
`load_domain_profile(domain_id) -> dict`, `list_available_domains() -> list[dict]`,
`save_custom_profile(...)`, `delete_custom_profile(domain_id) -> bool`,
`generate_slug(display_name) -> str`.
Built-in profiles live in `translate/domain_profiles/*.json`, custom ones in
`%APPDATA%\translator-overlay\`.
Format: `{display_name, system_prompt, few_shot_examples: [{source, translation}]}`.

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
- `settings/__init__.py`: `get_api_key(provider)`, `set_api_key`, `delete_api_key`,
  `has_any_key()`, `get_primary_provider()`, `save_primary_provider()`,
  `is_fallback_enabled()`, `set_fallback_enabled()`.
- `region_presets.py`: `load_presets()`, `save_preset(...)`, `delete_preset(id)`,
  `rename_preset(id, name)`, `update_preset_hotkey(id, hotkey)`, `validate_hotkey(...)`.
  File: `%APPDATA%\translator-overlay\region_presets.json`.

### `ocr/engine.py`
`get_reader()` — lazy EasyOCR singleton, `preprocess(img, scale=1) -> np.ndarray`,
`extract_text(image) -> str`, `recognise(img, lang=None) -> str` (public entry point),
`_extract_strips` — splits tall regions into strips for accuracy.

### `ui/`
- `MainWindow` (sidebar: `PAGE_HOME` / `PAGE_HISTORY` / `PAGE_SETTINGS`),
  `show_and_switch(page)`, `set_tray_icon(tray)`; workers `_TextTranslateWorker`,
  `_ImageTranslateWorker`, `_UpdateCheckWorker`.
- `SettingsWidget` — all settings; methods `_build_ui()`, `_load_current()`,
  `_on_save()`, `reload()`, `_css(extra)`; constants `_SOURCE_LANGUAGES`,
  `_TARGET_LANGUAGES`, `_ENGINES`, `_OPENROUTER_MODELS`, `_MODEL_HINTS`.
  Sections: "API-ключ и провайдеры" (API key and providers), "Бэкенд перевода"
  (translation backend), "Перевод" (translation), then OCR / interface / updates.
  Styling: dark theme, `QGroupBox` + `self._INPUT_CSS` / `self._GROUP_CSS`.
- `ResultPopup(...)` — frameless window, streaming updates via `update_content()`,
  auto-close after `config.POPUP_TIMEOUT_SEC`, resize by the edges, TTS, copy.

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
| EasyOCR singleton | module global in `ocr/engine.py` |

---

## 5. Configuration points

1. **`settings/config_manager.DEFAULTS`** — the canonical list of keys.
   A new setting = an entry in `DEFAULTS` (otherwise `save_config()` drops it)
   + a property in `config._LiveConfig` + a control in `ui/settings_dialog.SettingsWidget`
   (`_build_ui` → `_load_current` → `_on_save`).
2. **Translation backend choice** — `settings.json`:
   - `translation_backend`: `"api"` (default) | `"nllb"`;
   - `nllb_model_path`: explicit path to the CTranslate2 directory (`""` = auto-discovery).
   Changed in "Настройки → Бэкенд перевода" (Settings → Translation backend), which
   also has the "Загрузить модель" (Load model) button with a progress indicator and
   a model-availability status. The `NLLB_MODEL_DIR` environment variable overrides
   the path without editing settings.
   `NLLB_DEVICE` (`auto` by default | `cuda` | `cpu`) picks the inference device; it is
   env-only and has no UI control.
3. **`.env`** (see `.env.example`) — API keys and static overrides
   (`EASYOCR_*`, `OVERLAY_*`, `CACHE_DIR`, `LOG_DIR`, `SETTINGS_HOTKEY`, `GITHUB_REPO`).
4. **Keyring** — the working store for API keys (`settings.set_api_key`).
5. **`translate/domain_profiles/*.json`** — system prompts and few-shot examples per domain.
6. **`region_presets.json`** — saved regions and their individual hotkeys.
7. **`build*.spec` / `build.py`** — PyInstaller build parameters.

After settings are saved, `SettingsWidget._on_save` calls
`translate.backend.reset()`. It resets both the LLM clients and the loaded NLLB
model, so a new provider/model/path is picked up on the next request.

---

## 6. External dependencies and where they are called

| Service / library | Where it is called |
|---|---|
| **OpenRouter API** (`openai` SDK, `base_url=https://openrouter.ai/api/v1`) | `translate/llm_client.py::_get_client_for`, `_call_provider` |
| **Anthropic API** (`anthropic` SDK) | `translate/llm_client.py::_get_client_for`, `_call_provider` |
| **GitHub Releases API** | `updater/check_update.py::check_for_update` (repository from `config.GITHUB_REPO`) |
| **EasyOCR / torch** (local; weights are downloaded on first launch) | `ocr/engine.py::get_reader` |
| **CTranslate2 + sentencepiece** (local, offline) | `translate/nllb_backend.py::NllbBackend.ensure_loaded` / `_raw_translate` |
| **cuBLAS 12** (optional; `nvidia-cublas-cu12` wheel or CUDA Toolkit 12.x) | `translate/cuda_support.py::prepare_cuda_libraries`, loaded lazily by CTranslate2 on the first GPU matmul |
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
- Not covered by tests: the UI layer, `cache/store.py`, `main.py`, `capture/`, `tts/`,
  `updater/`, `translate/backend.py`, `translate/nllb_backend.py` (only its device
  selection / CPU fallback is covered, by `tests/test_cuda_support.py`).
- **The backend choice is saved only by "Сохранить" (Save).** "Загрузить модель" (Load model)
  persists just `nllb_model_path` (and rewrites the file with the old `translation_backend`),
  while its status line suggests the local model is active. Leaving the page then
  makes `reload()` show "API" again. This is a UX bug and has not been fixed yet.
- **Open: the app crashed once after the second NLLB translation** (2026-09-23 21:32,
  WER: `Qt5Core.dll`, `0xc0000409` subcode 7 = `qFatal` → `abort()`), after
  `NLLB OK` had been logged. Not reproduced headless. Main suspect:
  `_HomePage._on_text_translated` drops the last reference to a `QThread` that is
  still running. Diagnostics added for the next occurrence: Qt messages go to
  `app.log` (`qInstallMessageHandler` in `main.py`); `faulthandler` writes all
  thread stacks to `%APPDATA%\translator-overlay\crash.log`; worker/inference
  DEBUG logs in `ui/main_window.py` and `nllb_backend._raw_translate`.
- `nllb_backend._auto_model_dirs()` still contains a developer-machine path
  (`D:\projects\overlay-translator\models`), harmless elsewhere but should go.
- Two tests in `tests/test_domain_profiles.py` were already failing before the NLLB work
  (they check old texts of the `game` profile), and three more test files do not import
  without `pytest`/`easyocr` in the environment.
- The hard-coded `HTTP-Referer` in the OpenRouter headers points to a placeholder repository.

---

## 8. Tests

Location: `tests/`. Style: `unittest.TestCase`; they also run under pytest.

| File | Coverage |
|---|---|
| `tests/test_ocr.py` | preprocessing, box sorting, `_resolve_gpu`, confidence filter (mocked Reader) |
| `tests/test_lang_detect.py` | script/language detection, "same language" fast path |
| `tests/test_llm_resilience.py` | error classification, retry/backoff, moving along the provider chain |
| `tests/test_domain_profiles.py` | loading/merging domain profiles |
| `tests/test_region_presets.py` | preset CRUD, validation of names/coordinates/hotkeys |
| `tests/test_cuda_support.py` | cuBLAS search order, PATH preparation, NLLB CPU fallback for every CUDA failure mode (fake `ctranslate2`, no GPU needed) |

Running:

```bash
py -m unittest discover -s tests -p "test_*.py" -v
# or
pytest tests/ -v
```

There is no `pytest.ini` / `pyproject.toml`; run from the project root
(modules are imported as top-level packages).

---

## 9. Local model: utilities and workflow

Everything is in `scripts/` and is not part of the app build. Run from the project
root with the venv interpreter.

### Converting the HF checkpoint to CTranslate2 int8
A one-off step; needs `transformers` + `torch` from `requirements-dev.txt`.

```bash
ct2-transformers-converter   --model  D:/projects/overlay-translator/models/nllb-200-distilled-600M   --output_dir D:/projects/overlay-translator/models/nllb-200-ct2-int8   --quantization int8   --copy_files tokenizer.json tokenizer_config.json special_tokens_map.json                sentencepiece.bpe.model generation_config.json
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
"API (Anthropic / OpenRouter)" and "Локальная модель (NLLB)" (Local model), the model
path field, and the "Загрузить модель" (Load model) button with a progress indicator.
The choice is stored in `settings.json` (`translation_backend`, `nllb_model_path`)
and survives a restart.
Only the "Сохранить" (Save) button writes `translation_backend`; see the known issue in section 7.
The status line shows the device the model actually runs on (`Device: CUDA/CPU`)
and, after a CPU fallback, the reason.

---

_Created: 2026-09-23. Updated: 2026-09-24 (local NLLB backend, backend switching,
export and baseline scripts; optional CUDA with CPU fallback, crash diagnostics;
translated to English)._
_Update it after significant structural changes._
