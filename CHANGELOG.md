# Changelog

All notable changes to Translator Overlay are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
A release is tagged `vX.Y.Z`, where `X.Y.Z` equals `APP_VERSION` in `config.py`;
the section for that version becomes the GitHub release notes.

## [Unreleased]

### Added
- Custom hotkeys: Settings → Hotkeys changes the translate and the settings hotkey and
  applies them at once. Clashes and single ordinary keys are refused; while a field is
  being edited the global hotkeys are paused.
- One-click update: the "Update" button in the new-version banner downloads the installer,
  checks its SHA-256, installs it silently and restarts the app.

### Changed
- Releases carry only `Setup.exe`; its SHA-256 is in the release notes instead of a
  separate `.sha256` file.

## [1.1.0] - 2026-10-21

### Added
- First-run wizard: choose how to translate (online without a key, an LLM with your API key,
  or offline) and download the offline NLLB model with progress and a SHA-256 check.
  Installs that are already set up skip it; Settings → Interface can run it again.
- `release.yml` workflow: a `vX.Y.Z` tag runs the tests, builds the app and the installer
  on GitHub Actions and creates a draft release with `Setup.exe` and its SHA-256.

### Fixed
- Windows shown before the main window (the setup wizard, the API key dialog) had the
  default Windows icon instead of the app icon.
- `build.py` precompiled no sources (the exclude pattern was passed as a string).

## [1.0.0] - 2026-10-21

First public release.

### Added
- Hotkey translation: select a region (Ctrl+Shift+R), the text is recognised and shown
  translated in a popup next to it. Ctrl+Shift+O opens the settings.
- Translation backends: keyless Google Translate (default), DeepL and Microsoft Azure
  Translator with your own key, LLMs through OpenRouter or Anthropic with domain profiles
  and streaming, and the local NLLB-200 model that works fully offline.
- NLLB model version picker in the settings: lists the Hugging Face tags, matches local
  builds and downloads missing ones with a SHA-256 check.
- Offline OCR (RapidOCR on ONNX Runtime), on the GPU through DirectML when available.
- Region presets with their own hotkeys, live monitoring of a region, translation history.
- Result popup: copy, read aloud, drag and resize; the size is remembered.
- Russian and English interface, HUD-style themes.
- Inno Setup installer: per-user install without admin rights, Start menu shortcut,
  optional desktop shortcut and start with Windows; user data is kept on uninstall.
- Update check against GitHub Releases at launch.

### Security
- The text you translate is not written to the logs (only its length) unless
  `OVERLAY_LOG_TEXT` is set.

[Unreleased]: https://github.com/Vrihe/Overlay-Translator/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Vrihe/Overlay-Translator/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Vrihe/Overlay-Translator/releases/tag/v1.0.0
