# 🌐 Translator Overlay

Screen region translator for Windows. Select any text on screen with a hotkey,
and get an instant translation in a floating popup — powered by OCR and LLM.

![Demo](docs/demo.gif)
> **TODO:** Record a demo GIF and place it at `docs/demo.gif`.

---

## ✨ Features

- **Global hotkey** (`Ctrl+Shift+R` by default) — works from any application
- **Settings hotkey** (`Ctrl+Shift+O`) — quick access to settings without leaving your workflow
- **First-run setup** — guided API key entry with live validation on first launch
- **Secure key storage** — API keys stored in OS credential vault via `keyring` (Windows Credential Locker)
- **System Tray support** — runs quietly in the background without a cluttering console window
- **Region selector** — fullscreen transparent overlay with mouse-drag selection
- **Multi-monitor support** — works across all connected displays, including negative-coordinate layouts
- **OCR** via EasyOCR (CRAFT + CRNN neural network) with multilingual support (`ru` + `en`), GPU acceleration, and optimised preprocessing
- **Translation** via OpenRouter (free models) or Anthropic Claude
- **SQLite cache** — repeated texts are translated instantly without API calls
- **Floating popup** — shows original + translation near the selected area; draggable, auto-closes after a timeout
- **Auto language detection** — automatically detects the source language before translation (offline via `langid` or via LLM); falls back to a fixed language for very short texts
- **Executable support** — can be compiled into a standalone `.exe` file via PyInstaller

---

## 📁 Project Structure

```
translator-overlay/
├── main.py              # Entry point — system tray, hotkeys, pipeline orchestration
├── config.py            # All settings (loaded from .env)
├── settings.py          # Secure API key storage via keyring
├── .env                 # API keys and personal settings (git-ignored)
├── .env.example         # Template for .env
├── requirements.txt     # Python dependencies
├── translator.spec      # PyInstaller build specification
├── build.bat            # One-click Windows build script
│
├── overlay/
│   └── selector.py      # Fullscreen region-selection overlay (PyQt5)
├── capture/
│   └── screenshot.py    # Screen capture via mss
├── ocr/
│   ├── engine.py        # EasyOCR engine with lazy model loading & Cyrillic optimisation
│   └── hsv_filter.py    # Optional HSV-based preprocessing filter
├── translate/
│   ├── llm_client.py    # LLM translation (OpenRouter / Anthropic) + logging
│   └── lang_detect.py   # Auto source-language detection (langid / LLM)
├── cache/
│   └── store.py         # SQLite translation cache
├── ui/
│   ├── result_popup.py  # Floating result popup (PyQt5)
│   ├── first_run_dialog.py  # First-launch API key setup dialog
│   └── settings_dialog.py   # Runtime settings dialog
├── tray/
│   ├── tray_icon.py     # System tray icon and context menu
│   └── icon_gen.py      # Programmatic icon generator
└── logs/
    └── translator.log   # Request log (auto-created)
```

---

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/overlay-translator.git
cd overlay-translator
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

> **Note:** EasyOCR will automatically download pre-trained model files (~100 MB)
> to `~/.EasyOCR/model/` on first launch. No external binaries required.
>
> For GPU acceleration, install the CUDA-enabled version of PyTorch.
> With CPU-only, EasyOCR still works but is slower (~0.5–2s per screenshot).

### 3. Configure API keys

The app will ask for your API key on first launch. You can also set it
manually in `.env` (useful for development):

```bash
cp .env.example .env
```

Edit `.env`:

```ini
# Free option — get a key at https://openrouter.ai/keys
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Or paid Anthropic option
# ANTHROPIC_API_KEY=sk-ant-your-key-here
```

> **Tip:** OpenRouter offers several free models. The app uses
> `meta-llama/llama-3.3-70b-instruct:free` by default — no credit card required.

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

> **Note:** On Windows, the `keyboard` library requires Administrator privileges for global low-level hooks. Run your terminal **as Administrator**.

### Hotkeys

| Hotkey | Action |
|---|---|
| `Ctrl+Shift+T` | Start region selection → translate |
| `Ctrl+Shift+O` | Open settings dialog |

## 📦 Building Standalone Executable (.exe)

You can compile the application into a single standalone `.exe` file using PyInstaller:

### Build Script
```powershell
python build.py
```
*(or `pyinstaller build.spec --clean`)*

> **Note:** The initial build can take several minutes due to heavy PyTorch and EasyOCR dependencies. The output executable will be created at `dist\TranslatorOverlay.exe`.

### User Data & Persistence
Settings (`settings.json`), translation history/cache database (`translations.db`), and logs are automatically stored in the user's roaming AppData directory:
`%APPDATA%\translator-overlay\`

This guarantees that:
- User configuration and history are preserved when updating or replacing `TranslatorOverlay.exe`.
- The application runs cleanly even when installed in write-restricted system folders like `C:\Program Files\`.

### 🔄 Automatic Update Checking
The application automatically checks for new releases on GitHub in the background at launch (or via the **"Проверить обновления"** button in Settings). If a new version is available, a download button and notification will be displayed with a direct link to GitHub Releases.

---

## ⚙️ Configuration

All settings can be overridden in `.env`:

| Variable | Default | Description |
|---|---|---|
| `HOTKEY` | `ctrl+shift+t` | Global hotkey combo for translation |
| `SETTINGS_HOTKEY` | `ctrl+shift+o` | Global hotkey combo for settings |
| `TARGET_LANG` | `ru` | Target translation language |
| `SOURCE_LANG` | `en` | Source language (fallback when auto-detect is off or text is too short) |
| `LANG_DETECT_ENGINE` | `langid` | Source language detection engine: `langid` (offline ML), `llm` (via API), `off` (fixed) |
| `MIN_CHARS_FOR_DETECTION` | `15` | Minimum character count for auto-detection; shorter texts use fixed `SOURCE_LANG` |
| `EASYOCR_LANGS` | `ru,en` | Comma-separated list of OCR languages |
| `EASYOCR_GPU` | `auto` | GPU mode: `auto` (detect CUDA), `true`, or `false` |
| `EASYOCR_CONFIDENCE_THRESHOLD` | `0.25` | Minimum confidence for recognised text blocks (0.0–1.0) |
| `OCR_USE_HSV_FILTER` | `false` | Enable HSV preprocessing for coloured backgrounds |
| `POPUP_TIMEOUT_SEC` | `10` | Popup auto-close timeout (seconds) |
| `OVERLAY_OPACITY` | `0.85` | Overlay background opacity |
| `OPENROUTER_API_KEY` | — | OpenRouter API key (free) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (paid) |

---

## 🌍 Auto Language Detection

The app can automatically detect the source language of recognised text before sending it for translation. This is especially useful when translating game chat where players write in different languages (English, German, Polish, Russian, etc.).

### Detection Engines

| Engine | `LANG_DETECT_ENGINE` | Description |
|---|---|---|
| **langid** (default) | `langid` | Offline ML model — fast, deterministic, no API cost |
| **LLM** | `llm` | Uses the active LLM provider — more accurate on noisy/short texts, but adds latency and cost |
| **Off** | `off` | Disabled — uses the fixed `SOURCE_LANG` value |

You can switch engines in the Settings dialog (Ctrl+Shift+O) under "Перевод" → "Определение языка".

### Limitations

- **Short texts** (< 15 characters by default): Auto-detection is unreliable on very short messages (1–3 words, gamer tags, slang). The app falls back to the fixed `SOURCE_LANG` for texts below the `MIN_CHARS_FOR_DETECTION` threshold.
- **Same-language skip**: If the detected source language matches the target language, translation is skipped and the original text is shown as-is — saving an unnecessary API call.

## 📊 Logging & Statistics

Every translation request is logged to `logs/translator.log`:

```
2025-07-21 14:30:01 | INFO  | CACHE MISS | text='Hello world' | calling API…
2025-07-21 14:30:02 | INFO  | API OK | provider=openrouter model=google/gemma-... | 1.23s | src='Hello world' | result='Привет мир'
2025-07-21 14:30:15 | INFO  | CACHE HIT | text='Hello world'
```

Quick stats example (PowerShell):

```powershell
# Total requests
(Select-String "CACHE" logs\translator.log).Count

# Cache hit rate
$hits = (Select-String "CACHE HIT" logs\translator.log).Count
$total = (Select-String "CACHE" logs\translator.log).Count
"Cache hit rate: $([math]::Round($hits / $total * 100, 1))%"
```

---

## 🛠 Tech Stack

| Component | Technology |
|---|---|
| UI / Overlay | PyQt5 |
| System Tray | QSystemTrayIcon (PyQt5) |
| Screen capture | mss |
| OCR | EasyOCR (CRAFT + CRNN) + PyTorch + Pillow |
| Translation | OpenRouter (free) / Anthropic API |
| Cache | SQLite |
| Key storage | keyring (OS credential vault) |
| Language detection | langid |
| Hotkey | keyboard |
| Config | python-dotenv |
| Packaging | PyInstaller |

---

## 📝 License

MIT
