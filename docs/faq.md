# FAQ

## I have no GPU. Will it work?

Yes. A GPU is only a speed-up:

- **OCR** uses any DirectX 12 GPU (NVIDIA, AMD, Intel) through DirectML and falls back to the CPU
  by itself: about 0.5–1.5 s per screenshot instead of a fraction of a second.
- **Cloud backends** (Google, DeepL, Azure, LLM) do not use your GPU at all.
- **The local NLLB model** runs on the CPU by default: about 1 s for a chat line on a modern
  4-core CPU. An NVIDIA GPU with cuBLAS for CUDA 12 makes it about 3× faster; see
  [GPU acceleration](local-model.md#gpu-acceleration). On a machine without an NVIDIA GPU the
  app uses the CPU silently.

## Windows SmartScreen or my antivirus warns about the installer

The installer is not code-signed yet, so Windows SmartScreen shows "Windows protected your PC"
for a new release: choose **More info → Run anyway**. Some antivirus programs also flag the app
because it installs a global keyboard hook (that is how the hotkeys work anywhere).

To check that the file is the one published here, compare its SHA-256 with the one in the
release notes:

```powershell
Get-FileHash .\TranslatorOverlay-Setup-<version>.exe -Algorithm SHA256
```

If your antivirus quarantines the app, restore it and add an exception for the install folder,
or [run it from source](installation.md#from-source).

## The hotkey does nothing in some games or programs

Windows does not pass keystrokes from a window running **as Administrator** to programs running
with normal rights. Some games and launchers run elevated, so the hotkey is ignored while they
have focus.

- Start Translator Overlay as Administrator too, only for those programs: right-click the
  shortcut → **Run as administrator**, or `run.bat --admin` from source.
- Do not run it elevated by default: an elevated app gives Administrator rights to anything that
  can change its folder.

If the hotkey does nothing anywhere, another program has probably taken the same combination.
Pick another one in **Settings → Hotkeys**; the app refuses combinations already used by the
other hotkey or by a region preset.

## The popup says "переведено через API" (translated through the API)

The local model is selected but could not be loaded (not downloaded, an incomplete folder, or a
wrong custom path), so this request went to the API backend. Open Settings → Translation
backend: the status line says what is missing. Download a build there, or see
[Local offline model](local-model.md).

## Text is recognised badly or not at all

- Select a tight rectangle around the text; large empty areas slow OCR down and add noise.
- OCR reads Latin and Cyrillic scripts only. Chinese, Japanese, Korean, Arabic and other scripts
  are not recognised.
- Coloured text on a busy background: turn on the HSV filter (`OCR_USE_HSV_FILTER=1`), or lower
  `EASYOCR_CONFIDENCE_THRESHOLD` (default `0.25`) in `.env`.
- Turn on **Предпросмотр и правка OCR-текста перед переводом** (preview and edit the OCR text
  before translating) in Settings to see and fix the recognised text first.

## Can it work fully offline?

Yes, with the local NLLB backend. Two downloads are needed once, while online: the OCR
recognition model (on first launch, ~8 MB) and a model build (Settings, ~620 MB). After that,
translation needs no network. The update check at start simply fails without a connection.

## Where are my settings and history? How do I remove everything?

In `%APPDATA%\translator-overlay\`. Uninstalling the app keeps this folder, so a reinstall keeps
your settings and models. Delete the folder to remove everything; delete the keys under
`OverlayTranslator` in Windows Credential Manager as well. See [Privacy](privacy.md).

## Does it work on Linux or macOS?

No. Global hotkeys, the key storage, the popup's capture exclusion and the installer are
Windows-specific. The test suite runs on Linux in CI, but the app does not.
