# Changelog

All notable changes to Translator Overlay are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
A release is tagged `vX.Y.Z`, where `X.Y.Z` equals `APP_VERSION` in `config.py`;
the section for that version becomes the GitHub release notes.

## [Unreleased]

### Fixed
- Offline translation of chat abbreviations that start with "l" (`lf2m`, `lfm`, `lol`):
  in most fonts the text recognition reads that "l" as a capital "I" (`If2m`), and the
  abbreviation was then translated word for word. Such misread abbreviations are now
  recognised.

## [1.4.0] - 2026-10-22

### Changed
- Updates download only the changed part of the app (~14 MB instead of ~124 MB) when the
  bundled libraries did not change; otherwise, or if anything goes wrong, the full
  installer is used as before. The update banner shows the download size. The first
  such update is possible from this version on.

## [1.3.0] - 2026-10-22

### Added
- Updates are checked every 30 minutes while the app runs, not only at launch; each new
  version is announced once.
- Documentation site (https://vrihe.github.io/Overlay-Translator/): installation, configuration,
  the local model, privacy, FAQ, how it works, training and reproducing the experiments.
- GPU acceleration for the offline model without a CUDA install: with an NVIDIA driver,
  Settings → local model offers "Download for the GPU", which fetches cuBLAS from PyPI
  (~530 MB, SHA-256 checked). Translation on the GPU is about 3× faster.
- Settings → local model → Device: "Auto" or "CPU only" (keeps the GPU free, e.g. for games).

### Changed
- The popup can stay up to 10 minutes before it hides itself (was 1 minute), with a hint
  next to the setting.
- The README now starts with what the app does and a 3-step install; the details moved to the docs.

### Fixed
- A popup of a region (live monitoring, a region bind) that you dragged somewhere came
  back to its default place when the next popup for that region opened; it now opens
  where you put it.
- A new popup auto-hide time applied only after a restart; it applies at once now.
- Google, DeepL and Azure translations are now served from the cache when the source
  language is auto-detected; before, the same text was sent to the service every time.

## [1.2.2] - 2026-10-21

### Added
- A stop button in the popup's header while live monitoring updates it.

### Changed
- Live monitoring is started and stopped on Settings → Regions ("Monitor" for the selected
  region, "Stop monitoring" while it runs, in step with the tray toggle) instead of the
  regions management dialog.

### Fixed
- Live monitoring updates kept scrolling the popup back to the top; it now stays where you
  scrolled to, and follows new lines when you are at the bottom.
- Live monitoring of a busy region (e.g. a stream chat): the popup no longer disappears
  and reappears on every change — it is updated in place and does not take the focus.
- With a short check interval most monitoring results were thrown away as outdated; every
  result is shown now unless you asked for another translation since.
- The popup is left out of screen captures, so monitoring and OCR never pick it up when
  it lies over the watched region. It does not show in screenshots or recordings either.
- A new translation started while another was running stopped the running one by force,
  which could leave translation broken until a restart; the newest request now waits.
- A popup closed shortly before a new translation could make the new one lose its result.
- Regions dialog: the monitoring button was cut off; region rows were cut off too.

## [1.2.1] - 2026-10-21

### Added
- Custom hotkeys: Settings → Hotkeys changes the translate and the settings hotkey and
  applies them at once. Clashes and single ordinary keys are refused; while a field is
  being edited the global hotkeys are paused.
- Settings → Regions: the saved screen regions with their size and bind, an "Add region"
  button (select an area, name it) and "Manage…" for renaming, deleting and binds.
- Live monitoring settings: how often the region is checked (1–120 s) and how big a change
  must be to translate it again.
- One-click update: the "Update" button in the new-version banner downloads the installer,
  checks its SHA-256, installs it silently and restarts the app.

### Changed
- Releases carry only `Setup.exe`; its SHA-256 is in the release notes instead of a
  separate `.sha256` file.

### Fixed
- Saving a new region with an unusable name (empty, taken, or over the limit) failed
  silently; the reason is now shown.

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

[Unreleased]: https://github.com/Vrihe/Overlay-Translator/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/Vrihe/Overlay-Translator/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/Vrihe/Overlay-Translator/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/Vrihe/Overlay-Translator/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/Vrihe/Overlay-Translator/compare/v1.1.0...v1.2.1
[1.1.0]: https://github.com/Vrihe/Overlay-Translator/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Vrihe/Overlay-Translator/releases/tag/v1.0.0
