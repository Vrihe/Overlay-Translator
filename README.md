# 🌐 Translator Overlay

[![CI](https://github.com/Vrihe/Overlay-Translator/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Vrihe/Overlay-Translator/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Vrihe/Overlay-Translator/badges/coverage.json)](https://github.com/Vrihe/Overlay-Translator/actions/workflows/ci.yml?query=branch%3Amain)

Screen region translator for Windows. Select any text on screen with a hotkey,
and get an instant translation in a floating popup — powered by offline OCR and
Google Translate, DeepL, Azure, an LLM or a fully offline NLLB model.

**Just want to use it?** Download `TranslatorOverlay-Setup-<version>.exe` from
[Releases](https://github.com/Vrihe/Overlay-Translator/releases/latest), run it and press `Ctrl+Shift+R`.
The steps below are for running from source.

![Demo](docs/demo.gif)
> **TODO:** Record a demo GIF and place it at `docs/demo.gif`.

---

## ✨ Features

- **Global hotkey** (`Ctrl+Shift+R` by default) — works from any application
- **Settings hotkey** (`Ctrl+Shift+O`) — quick access to settings without leaving your workflow
- **First-run setup** — a wizard picks the mode (online without a key, an LLM with your API key, or offline) and downloads the offline model with progress
- **Secure key storage** — API keys stored in OS credential vault via `keyring` (Windows Credential Locker)
- **System Tray support** — runs quietly in the background without a cluttering console window
- **Region selector** — fullscreen transparent overlay with mouse-drag selection
- **Multi-monitor support** — works across all connected displays, including negative-coordinate layouts
- **OCR** via RapidOCR (PP-OCR models on ONNX Runtime) with Cyrillic + Latin recognition (`ru` + `en`), GPU acceleration through DirectML, and optimised preprocessing
- **Translation backends** — Google Translate (the default, works without a key), DeepL and Microsoft Azure Translator with your own key, or an LLM through OpenRouter (free models) or Anthropic Claude with domain profiles and streaming
- **Offline translation** (optional) with a local, quantized NLLB-200 model (CTranslate2 int8), with no API key or internet needed. Pick and download a model build in Settings. It runs on the CPU and can use an NVIDIA GPU for extra speed
- **SQLite cache** — repeated texts are translated instantly without API calls
- **Floating popup** — shows the translation next to the selected area; copy, read aloud, drag and resize (the size is remembered), auto-closes after a timeout
- **Region presets and live mode** — saved regions with their own hotkeys, periodic re-translation of a region, translation history
- **Auto language detection** — Google, DeepL and Azure detect the source language themselves; for the LLM and NLLB backends the app detects it offline (script heuristic + `langid`). A fixed source language can be set in Settings
- **Interface in English and Russian** — picked automatically from the Windows language or set in Settings → Interface (applies after a restart)
- **Executable support** — can be compiled into a standalone application folder (`onedir` mode) via PyInstaller

---

## 📁 Project Structure

```
Overlay-Translator/
├── main.py              # Entry point — tray, hotkeys, pipeline orchestration
├── config.py            # Config facade: settings.json values + .env overrides
├── single_instance.py   # One running copy per session
├── .env.example         # Template for .env (optional keys and overrides)
├── requirements*.txt    # App (DirectML / CPU / GPU), dev and training dependencies
├── build.py / build.bat # PyInstaller build (+ --installer)
├── build_*.spec         # PyInstaller specs (layered build: heavy deps + app code)
├── installer/           # Inno Setup script for Setup.exe
├── install.bat          # Creates .venv and installs dependencies
├── download_model.bat   # Downloads the local NLLB model
├── run.bat              # Starts the app from .venv (normal user rights; --admin to elevate)
│
├── capture/             # Screen capture (mss) and live region monitoring
├── ocr/                 # RapidOCR engine, optional HSV filter
├── overlay/             # Fullscreen region-selection overlay
├── translate/           # Backend dispatcher; Google, DeepL, Azure, LLM and NLLB clients;
│                        # language detection, game-chat glossary, domain profiles
├── cache/               # SQLite translation cache and history
├── settings/            # API keys (keyring), settings.json, region presets
├── ui/                  # Main window, settings, result popup, first-run wizard, theme
├── history/             # History page
├── i18n/                # Russian / English interface strings
├── tray/ tts/ updater/  # Tray icon, text-to-speech, GitHub release check
├── scripts/             # Model download, NLLB smoke test, evaluation helpers
├── training/            # NLLB LoRA fine-tuning pipeline (separate venv)
├── docs/                # Fine-tuning process and evaluation reports
└── tests/
```

A file-by-file map is in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/Vrihe/Overlay-Translator.git
cd Overlay-Translator
```

### Quick start on Windows (double-click)

| Script | What it does |
|---|---|
| `install.bat` | Creates `.venv` and installs `requirements.txt` into it (`install.bat --gpu` also installs `requirements-gpu.txt`) |
| `download_model.bat` | Downloads the local NLLB model into `models/nllb-200-ct2-int8` (optional, for offline translation; arguments go to `scripts/download_model.py`) |
| `run.bat` | Starts the app from `.venv` with no console window (`--console` keeps the console open for logs, `--admin` re-launches it as Administrator, see the note under Usage) |

The manual steps are below.

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

> **Note:** OCR needs no PyTorch. The detector ships with `rapidocr`; the Cyrillic
> recognition model (~8 MB) is downloaded once on first launch to
> `%APPDATA%\translator-overlay\ocr_models\`.
>
> GPU acceleration uses DirectML (`onnxruntime-directml`), which works with any
> DirectX 12 GPU (NVIDIA, AMD, Intel) without CUDA. Without a usable GPU, OCR runs on the
> CPU (~0.5–1.5 s per screenshot). For a CPU-only install use `requirements-cpu.txt`.

### 3. Configure API keys

Optional. The default backend, Google Translate, works without a key, and so does the local
NLLB model. A key is needed only for DeepL, Azure or the LLM backend: enter it in Settings
(the app also asks for one on start if the LLM backend is selected without a key).
You can also set keys in `.env` (useful for development):

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# LLM backend: free option — get a key at https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-v1-your-key-here
# Or paid Anthropic option
# ANTHROPIC_API_KEY=sk-ant-your-key-here

# DEEPL_API_KEY=...
# AZURE_API_KEY=...
```

> **Tip:** OpenRouter offers several free models. The app uses
> `poolside/laguna-s-2.1:free` by default (change it in Settings) — no credit card required.

---

## 🔑 Getting an API Key

### OpenRouter (free)

1. Go to **[openrouter.ai/keys](https://openrouter.ai/keys)** and sign in (Google / GitHub / email).
2. Click **"Create Key"** — no credit card required.
3. Copy the key (`sk-or-v1-...`) and paste it into the app's setup dialog.

### Anthropic (paid)

1. Go to **[console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)**.
2. Create an API key and add billing.
3. Paste the key (`sk-ant-...`) into the app.

> **Note:** Keys entered through the app are stored securely in your OS
> credential vault (Windows Credential Locker) — not in plain text files.

---

## ▶️ Usage

### Running Python Script

```powershell
python main.py
```
*(or `pythonw main.py` to launch without any console window)*

> **Note:** Global hotkeys work without Administrator rights. Windows does not deliver them while a window
> running as Administrator (some games) has focus; only in that case start the app elevated (`run.bat --admin`).
> Avoid it otherwise: an elevated app runs the project's code as Administrator, so anything that can edit
> the project folder would get those rights too.

### Hotkeys

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+R` | Start region selection → translate (changeable in Settings) |
| `Ctrl+Shift+O` | Open settings |

---

## 🧪 Running Tests

To run the unit tests suite:

```powershell
py -m unittest discover -s tests -p "test_*.py" -v
```

Or using `pytest`:

```powershell
pip install -r requirements-dev.txt
pytest tests/ -v
```

---

## 📦 Building Standalone Application (onedir mode)

You can compile the application into a standalone folder via PyInstaller (`onedir` mode):

### Build Command
```powershell
python build.py
```
*(or run `build.bat` on Windows)*

> **Important for Distribution:**
> - The output is generated inside the `dist/TranslatorOverlay/` directory.
> - To launch or distribute the application, **extract / copy the entire `TranslatorOverlay` folder** and run `dist/TranslatorOverlay/TranslatorOverlay.exe`.
> - Do not copy `TranslatorOverlay.exe` alone out of the folder, as it relies on adjacent DLLs and bundled dependencies.

### Installer (single Setup.exe)
With [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed (`winget install JRSoftware.InnoSetup`):
```powershell
python build.py --installer       # build, then pack into an installer
python build.py --installer-only  # only pack the existing dist/TranslatorOverlay/
```
The result is `dist/installer/TranslatorOverlay-Setup-<version>.exe`. It installs for the current
user without admin rights (or for all users, chosen on the first page), adds a Start menu shortcut,
and optionally a desktop shortcut and start with Windows. Uninstalling keeps
`%APPDATA%\translator-overlay\` (settings, history, downloaded models).
If `ISCC.exe` is not found automatically, set the `ISCC` environment variable to its path.

### User Data & Persistence
Settings (`settings.json`), translation history/cache database (`translations.db`), and logs are automatically stored in the user's roaming AppData directory:
`%APPDATA%\translator-overlay\`

This guarantees that:
- User configuration and history are preserved when updating or replacing the application folder.
- The application runs cleanly even when extracted into write-restricted folders.

### 🔒 Privacy
- With a cloud backend, the text recognised in the selected region is sent to that provider
  (Google, DeepL, Azure, OpenRouter or Anthropic). Free OpenRouter models may log prompts. Do not translate passwords or
  personal data that way, or use the local NLLB backend, which never touches the network.
- The text you translate is not written to the logs: they record only its length. Set
  `OVERLAY_LOG_TEXT=1` for a debugging session to log the first 80 characters. Logs rotate at 2 MB.
- The history/cache database (`cache\translations.db`) does keep source texts and translations
  (up to `CACHE_MAX_ITEMS`); clear it in the History page.

### 🔄 Automatic Update Checking
The application automatically checks for new releases on GitHub in the background at launch (or via the **"Проверить обновления"** ("Check for updates") button in Settings). If a new version is available, a banner and a notification appear.

In an app installed with the setup, the banner's **Update** button downloads the new installer, checks it against the SHA-256 GitHub publishes for it, closes the app, installs the update without any windows and starts the new version. If the app was installed for all users, Windows asks for administrator rights. A copied `dist` folder or a source run gets a link to the release page instead.

---

## ⚙️ Configuration

Everyday options (hotkey, languages, backend, OCR languages, popup timeout, theme) are set in
the Settings window and stored in `%APPDATA%\translator-overlay\settings.json`.
`.env` holds API keys and a few advanced overrides:

| Variable | Default | Description |
|---|---|---|
| `SETTINGS_HOTKEY` | — | Overrides the settings hotkey. Both app hotkeys (translate: `ctrl+shift+r`, settings: `ctrl+shift+o`) are set in **Settings → Hotkeys** and apply at once |
| `OPENROUTER_API_KEY` | — | OpenRouter API key (free) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (paid) |
| `GOOGLE_API_KEY` | — | Google Cloud Translation key (optional; without it the keyless endpoint is used) |
| `DEEPL_API_KEY` | — | DeepL API key |
| `AZURE_API_KEY` | — | Microsoft Azure Translator key |
| `EASYOCR_GPU` | `auto` | Legacy OCR GPU override: `auto` (DirectML if available), `true`, or `false` |
| `EASYOCR_CONFIDENCE_THRESHOLD` | `0.25` | Minimum confidence for recognised text blocks (0.0–1.0) |
| `OCR_USE_HSV_FILTER` | `false` | Enable HSV preprocessing for coloured backgrounds |
| `NLLB_MODEL_DIR` | — | Path to the CTranslate2 NLLB model directory (overridden by the path set in Settings) |
| `NLLB_DEVICE` | `auto` | Local NLLB device: `auto` (GPU if usable, else CPU), `cuda`, or `cpu` |
| `NLLB_GLOSSARY` | `1` | `0` turns off the game-chat glossary that expands terms before NLLB |
| `NLLB_HF_REPO_ID` | `Alhite/overlay-translator-nllb-int8` | Hugging Face repo the model builds are downloaded from |
| `NLLB_HF_REVISION` | commit of tag `v0-base` | Model build that `scripts/download_model.py` downloads |
| `CACHE_MAX_ITEMS` | `500` | Size of the translation cache / history |
| `LOG_DIR` | `%APPDATA%\translator-overlay\logs` | Log directory |
| `OVERLAY_LOG_TEXT` | `0` | `1` writes the first 80 characters of translated text to the logs (debugging only) |

---

## 🧠 Local Offline Translation (NLLB)

Instead of a cloud LLM, the app can translate with
[NLLB-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M),
converted to an int8 [CTranslate2](https://github.com/OpenNMT/CTranslate2) model (~600 MB).
It works offline, needs no API key, and covers the 29 languages mapped in `translate/nllb_backend.py`.
Domain profiles (prompts, few-shot examples) do not apply to it, because it is a plain seq2seq translation model.

The runtime needs only `ctranslate2` and `sentencepiece`, both already in `requirements.txt`.
The model weights are **not** part of the repository (`models/` is git-ignored).
The easiest way to get them is in the app: **Settings → Бэкенд перевода (Translation backend) →
Локально (NLLB) (Local) → Версия модели (Model version)** lists every build published on Hugging Face
(`v0-base`, `v1-abbr`, `v2-game`, …); pick one and press **Скачать (Download)**. Files are checked
against their SHA-256 and saved to `models/nllb-<tag>` (in the installed app, under
`%APPDATA%\translator-overlay\models\`). From source you can also use one of the two ways below.

### 1a. Quick path: download the ready-made model (recommended)

The converted model is published on the Hugging Face Hub as
[Alhite/overlay-translator-nllb-int8](https://huggingface.co/Alhite/overlay-translator-nllb-int8)
(public, no login needed, ~621 MB):

```bash
python scripts/download_model.py
```

This puts it into `models/nllb-200-ct2-int8`, where the app finds it automatically.
The build is pinned to the commit behind the `v0-base` tag (plain int8 conversion, no fine-tuning) by
`NLLB_HF_REPO_ID` / `NLLB_HF_REVISION` in `config.py`, so everyone gets identical weights. It is a
commit SHA rather than the tag name because a tag can later be moved to other files.
Re-running the script only fetches files that changed. Options: `--revision <tag>` to try
another build, `--dest <dir>` to download elsewhere (then set that path in Settings).

> **License:** the model inherits NLLB-200's **CC-BY-NC-4.0** license, so it may be used for non-commercial purposes only. See [MODEL_LICENSE.md](MODEL_LICENSE.md).

### 1b. Manual path: convert the original model yourself

The conversion needs `transformers` and `torch`, but only for this one step (they are in `requirements-dev.txt`):

```bash
pip install -r requirements-dev.txt

ct2-transformers-converter --model facebook/nllb-200-distilled-600M     --output_dir models/nllb-200-ct2-int8 --quantization int8     --copy_files sentencepiece.bpe.model tokenizer.json tokenizer_config.json                  special_tokens_map.json generation_config.json
```

The first run downloads the original checkpoint (~2.5 GB) from Hugging Face. To keep that
download inside the project, set `HF_HOME=.hf-cache`; that folder is git-ignored.
The output directory must contain `model.bin`, `config.json`, `shared_vocabulary.json` and `sentencepiece.bpe.model`.

### Check that the model works

```bash
python scripts/test_nllb_translation.py --model models/nllb-200-ct2-int8
```

### 2. Where the app looks for the model

1. The build chosen in **Версия модели (Model version)**, or the path entered under
   **Свой путь… (Custom path)** (if set, it is the only place checked).
2. The `NLLB_MODEL_DIR` environment variable.
3. Auto-discovery (**Автовыбор / Auto**): in `<project>/models/`, then `%APPDATA%\translator-overlay\models\`,
   first `nllb-200-ct2-int8`, then any other complete build, newest first.

### 3. Switch the backend in the UI

1. Open Settings (`Ctrl+Shift+O`).
2. Under **Бэкенд перевода** (Translation backend), select **Локально (NLLB)** (Local). The status line shows whether the model was found.
3. Optional: press **Загрузить модель** (Load model) to load it into memory right away (1–3 s).
   This button only loads the model; it does **not** switch the backend.
4. The choice is saved immediately (`translation_backend` in `settings.json`); there is nothing else to press.

If the local model is selected but cannot be loaded (missing files, broken install), the request
goes through the API backend instead, and the result popup says why. An error during a translation
itself is shown as an error and does not silently fall back to the API.

### ⚡ Optional GPU acceleration

The local NLLB backend runs on the CPU out of the box. GPU inference is an
**optional speed-up**: nothing breaks without it.

Measured on a Ryzen (Zen 3) + RTX 3060 Ti, one 18-token English sentence → Russian, beam size 4:

| Device | Time per sentence |
|---|---|
| CPU, int8, 4 threads | ~1050 ms |
| GPU, `int8_float16` | ~310 ms |

**GPU requirements**

- An NVIDIA GPU with a recent driver (any driver that supports CUDA 12).
- cuBLAS for **CUDA 12.x** (`cublas64_12.dll`). CTranslate2 4.x is built against
  CUDA 12, so CUDA 11 or 13 libraries will not work. Pick one of the following:
  - **Recommended:** the pip wheel. No toolkit install and no `PATH` editing:
    ```bash
    pip install -r requirements-gpu.txt   # installs nvidia-cublas-cu12 (~740 MB)
    ```
  - Or [CUDA Toolkit 12.x](https://developer.nvidia.com/cuda-12-9-0-download-archive)
    from NVIDIA. It is found through `CUDA_PATH` / `CUDA_PATH_V12_*`, or in the default
    `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*` location.

**How it is picked up**

With `NLLB_DEVICE=auto` (the default), the app checks for an NVIDIA GPU when the
model is loaded, looks for cuBLAS in the places above, and runs a short test
translation on the GPU. If any step fails, the model loads on the CPU instead.
The reason is written to the log. It is also shown once in the result popup and
in the Settings status (for example
`CUDA unavailable, using CPU inference (cublas64_12.dll not found …)`).
On a machine with no NVIDIA GPU, the app switches to the CPU silently.

Standalone builds do not bundle cuBLAS. They use the GPU only when CUDA Toolkit 12.x is installed.

---

## 🌍 Auto Language Detection

The app can automatically detect the source language of recognised text before sending it for translation. This is especially useful when translating game chat where players write in different languages (English, German, Polish, Russian, etc.).

### How it works

| Backend | Who detects the source language |
|---|---|
| Google, DeepL, Azure | The provider itself, server-side |
| LLM, local NLLB | The app, offline: a script heuristic (Cyrillic → `ru`), then the `langid` model |

The source language is **Auto** by default. To turn detection off, pick a fixed source language in
Settings (`Ctrl+Shift+O`) → "Перевод" (Translation).

### Limitations

- **Short texts**: Auto-detection is unreliable on very short messages (1–3 words, gamer tags, slang). Cyrillic text is always treated as `ru`; for other short texts set a fixed source language if detection guesses wrong.
- **Same-language skip** (LLM backend): if the detected source language matches the target language, translation is skipped and the original text is shown as-is — saving an unnecessary API call.

## 📊 Logging & Statistics

Every LLM translation request is logged to `%APPDATA%\translator-overlay\logs\translator.log`.
The text itself is replaced by its length (see Privacy):

```
2026-10-21 14:30:01 | INFO  | CACHE MISS | domain=general | text=<11 chars> | calling API…
2026-10-21 14:30:02 | INFO  | API OK | provider=openrouter domain=general model=poolside/laguna-s-2.1:free | 1.23s | src=<11 chars> | result=<10 chars>
2026-10-21 14:30:15 | INFO  | CACHE HIT | domain=general | text=<11 chars>
```

Quick stats example (PowerShell):

```powershell
$log = "$env:APPDATA\translator-overlay\logs\translator.log"
# Total requests
(Select-String "CACHE" $log).Count

# Cache hit rate
$hits = (Select-String "CACHE HIT" $log).Count
$total = (Select-String "CACHE" $log).Count
"Cache hit rate: $([math]::Round($hits / $total * 100, 1))%"
```

---

## 🛠 Tech Stack

| Component | Technology |
|---|---|
| UI / Overlay | PyQt5 |
| System Tray | QSystemTrayIcon (PyQt5) |
| Screen capture | mss |
| OCR | RapidOCR (PP-OCRv6 det + PP-OCRv5 rec) + ONNX Runtime DirectML + Pillow |
| Translation | Google Translate, DeepL, Azure Translator, OpenRouter (free) / Anthropic API |
| Offline translation | NLLB-200-distilled-600M, int8, via CTranslate2 + SentencePiece (optional CUDA via `nvidia-cublas-cu12`) |
| Cache | SQLite |
| Key storage | keyring (OS credential vault) |
| Language detection | langid + script heuristic |
| Hotkey | keyboard |
| Config | python-dotenv |
| Packaging | PyInstaller |

---

## 🤝 Contributing

Bug reports, ideas and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for the setup and the rules, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## 📝 License

The source code is released under the [MIT License](LICENSE).

The optional offline NLLB-200 model and every build made from it are licensed
separately under **CC-BY-NC-4.0** (non-commercial use only). See [MODEL_LICENSE.md](MODEL_LICENSE.md).
