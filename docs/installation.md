# Installation

The app runs on Windows 10 and 11 (64-bit).

## With the installer (recommended)

1. Download `TranslatorOverlay-Setup-<version>.exe` from the
   [latest release](https://github.com/Vrihe/Overlay-Translator/releases/latest).
2. Run it. It installs for the current user without administrator rights (or for all users, chosen
   on the first page) and adds a Start menu shortcut; a desktop shortcut and start with Windows are
   optional. SmartScreen may warn about an unsigned installer: see the [FAQ](faq.md#windows-smartscreen-or-my-antivirus-warns-about-the-installer).
3. On first start a wizard asks how to translate:
    - **Online without a key** — Google Translate;
    - **LLM with your API key** — OpenRouter (free models) or Anthropic;
    - **Offline** — downloads the local NLLB model (~620 MB) with progress and a SHA-256 check.

Then select text on screen with `Ctrl+Shift+R`. Settings open with `Ctrl+Shift+O` or from the tray
icon.

Updates: the app checks GitHub for a new release at start. The **Update** button in the banner
downloads the new installer, checks its SHA-256, installs it silently and restarts the app.

Uninstalling keeps `%APPDATA%\translator-overlay\` (settings, history, downloaded models); delete
that folder to remove them.

## From source

Needs Python 3.10 or newer (3.12–3.13 are used in development).

```powershell
git clone https://github.com/Vrihe/Overlay-Translator.git
cd Overlay-Translator
install.bat          # creates .venv and installs requirements.txt
run.bat              # starts the app without a console window
```

| Script | What it does |
|---|---|
| `install.bat` | Creates `.venv` and installs `requirements.txt` into it; `install.bat --gpu` also installs `requirements-gpu.txt` (cuBLAS for the local model on an NVIDIA GPU) |
| `download_model.bat` | Downloads the local NLLB model into `models/nllb-200-ct2-int8` (optional; arguments go to `scripts/download_model.py`) |
| `run.bat` | Starts the app from `.venv`; `--console` keeps a console with logs, `--admin` starts it as Administrator (see the [FAQ](faq.md#the-hotkey-does-nothing-in-some-games-or-programs)) |

The same by hand:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

### Requirements files

| File | For |
|---|---|
| `requirements.txt` | The app, with OCR on any DirectX 12 GPU through DirectML |
| `requirements-cpu.txt` | The app with CPU-only OCR (do not install both: they share a module name) |
| `requirements-gpu.txt` | Optional cuBLAS for the local NLLB model on an NVIDIA GPU |
| `requirements-dev.txt` | Tests, lint, type checks, git hooks, model conversion |
| `requirements-train.txt` | Fine-tuning, in a separate `.venv-train` (see [Training](training.md)) |
| `requirements-docs.txt` | This documentation site |

OCR needs no PyTorch: the detector ships with `rapidocr`, and the recognition model (~8 MB) is
downloaded once on first launch to `%APPDATA%\translator-overlay\ocr_models\`.

## Building the standalone app

```powershell
python build.py                    # PyInstaller onedir build → dist\TranslatorOverlay\
python build.py --installer        # build, then pack Setup.exe with Inno Setup 6
python build.py --installer-only   # only pack the existing dist\TranslatorOverlay\
```

- The build is two-layered (`build_deps.spec` for heavy dependencies, `build_app.spec` for the app
  code): the first run takes 10–15 minutes, later runs reuse the dependency layer.
- Distribute the whole `dist\TranslatorOverlay\` folder; `TranslatorOverlay.exe` needs the DLLs
  next to it.
- The installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php)
  (`winget install JRSoftware.InnoSetup`); set `ISCC` to its path if it is not found. The result is
  `dist\installer\TranslatorOverlay-Setup-<version>.exe`.
- Releases are built by `.github/workflows/release.yml` from a `v*` tag.
