# 🌐 Translator Overlay

Screen region translator for Windows. Select any text on screen with a hotkey,
and get an instant translation in a floating popup — powered by OCR and LLM.

![Demo](docs/demo.gif)
> **TODO:** Record a demo GIF and place it at `docs/demo.gif`.

---

## ✨ Features

- **Global hotkey** (`Ctrl+Shift+T` by default) — works from any application
- **System Tray support** — runs quietly in the background without a cluttering console window
- **Region selector** — fullscreen transparent overlay with mouse-drag selection
- **Multi-monitor support** — works across all connected displays, including negative-coordinate layouts
- **OCR** via Tesseract with preprocessing (2× upscale, contrast boost, sharpening)
- **Translation** via OpenRouter (free models) or Anthropic Claude
- **SQLite cache** — repeated texts are translated instantly without API calls
- **Floating popup** — shows original + translation near the selected area; draggable, auto-closes after a timeout
- **Executable support** — can be compiled into a standalone `.exe` file via PyInstaller

---

## 📁 Project Structure

```
translator-overlay/
├── main.py              # Entry point — system tray, hotkey, pipeline orchestration
├── config.py            # All settings (loaded from .env)
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
│   └── engine.py        # Tesseract OCR with image preprocessing
├── translate/
│   └── llm_client.py    # LLM translation (OpenRouter / Anthropic) + logging
├── cache/
│   └── store.py         # SQLite translation cache
├── ui/
│   └── result_popup.py  # Floating result popup (PyQt5)
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

### 2. Install Tesseract OCR (Windows)

Tesseract is a standalone program — the Python package `pytesseract` is just a wrapper.

1. Download the installer from the **[UB Mannheim builds](https://github.com/UB-Mannheim/tesseract/wiki)** page
   (e.g. `tesseract-ocr-w64-setup-5.x.x.exe`).
2. Run the installer. During setup:
   - Check **"Add to PATH"** if the option is available.
   - Under **"Additional language data"**, check **Russian** (or any other languages you need).
3. Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`
   — if different, update `TESSERACT_CMD` in your `.env`.
4. Verify:
   ```powershell
   tesseract --version
   ```

### 3. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure API keys

Copy the example and fill in your keys:

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
> `google/gemma-4-26b-a4b-it:free` by default — no credit card required.

---

## ▶️ Usage

### Running Python Script

```powershell
python main.py
```
*(or `pythonw main.py` to launch without any console window)*

> **Note:** On Windows, the `keyboard` library requires Administrator privileges for global low-level hooks. Run your terminal **as Administrator**.

---

## 📦 Building Standalone Executable (.exe)

You can compile the application into a single standalone `.exe` file using PyInstaller:

### Option 1: One-click Build Script
Simply double-click `build.bat` or run:
```powershell
.\build.bat
```

### Option 2: PyInstaller Command
```powershell
pip install pyinstaller
pyinstaller translator.spec --clean
```

The compiled binary will be saved in `dist\TranslatorOverlay.exe`.

### Running the Executable
1. Place a copy of your `.env` file in the **same directory** as `TranslatorOverlay.exe`.
2. Run `TranslatorOverlay.exe` **as Administrator** (required for global hotkeys).
3. The app will launch directly into the System Tray without opening any command prompt windows.

---

## ⚙️ Configuration

All settings can be overridden in `.env`:

| Variable | Default | Description |
|---|---|---|
| `HOTKEY` | `ctrl+shift+t` | Global hotkey combo |
| `TARGET_LANG` | `ru` | Target translation language |
| `SOURCE_LANG` | `en` | Source language hint |
| `OCR_LANG` | `eng` | Tesseract language(s) |
| `TESSERACT_CMD` | `C:\Program Files\Tesseract-OCR\tesseract.exe` | Path to Tesseract binary |
| `POPUP_TIMEOUT_SEC` | `10` | Popup auto-close timeout (seconds) |
| `OVERLAY_OPACITY` | `0.85` | Overlay background opacity |
| `OPENROUTER_API_KEY` | — | OpenRouter API key (free) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (paid) |

---

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
| OCR | Tesseract + pytesseract + Pillow |
| Translation | OpenRouter (free) / Anthropic API |
| Cache | SQLite |
| Hotkey | keyboard |
| Config | python-dotenv |
| Packaging | PyInstaller |

---

## 📝 License

MIT
