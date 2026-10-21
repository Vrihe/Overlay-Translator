# Contributing to Translator Overlay

Thanks for helping out! This guide covers how to set up the project, what we
expect from a change, and how to get it merged.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

- **Bugs and ideas**: open an [issue](https://github.com/Vrihe/Overlay-Translator/issues/new/choose)
  first, using the bug report or feature request template.
- **Large changes** (a new backend, a new OCR engine, a redesign of a UI page):
  describe the plan in an issue before you write code, so that nobody wastes work.
- **Small fixes** (typos, docs, an obvious bug) can go straight to a pull request.
- Read [ARCHITECTURE.md](ARCHITECTURE.md). It is the map of the project: modules,
  data flow, settings, known problems and tests.

## Development setup

The app is Windows-only (global hotkeys, the tray, DirectML, the credential vault).
You need Python 3.10+.

```powershell
git clone https://github.com/Vrihe/Overlay-Translator.git
cd Overlay-Translator
install.bat                 # creates .venv and installs requirements.txt
.venv\Scripts\pip install -r requirements-dev.txt
run.bat --console           # start the app with a visible log
```

Optional parts:

- `install.bat --gpu`: cuBLAS for GPU inference of the local NLLB model.
- `download_model.bat`: the offline NLLB model (see README → Local Offline Translation).
- `requirements-train.txt`: a separate venv for fine-tuning (`training/`), not needed for the app.

API keys go in through the first-run dialog or `.env` (see `.env.example`).
Never commit real keys, `.env`, models, caches or the `history/` and `data/` contents.

## Making a change

1. Fork the repo and create a branch from `main`, for example `feat/deepl-backend`
   or `fix/popup-multi-monitor`.
2. Keep the change focused: one feature or fix per pull request.
3. Follow the existing code style. Match the surrounding code in naming,
   structure and how many comments it has.
4. Code, comments and docs are in **English**.
5. User-facing UI strings are written in **Russian** inside `tr()` (or `N_()`),
   with the English translation added to `i18n/en.py`. `tests/test_i18n.py`
   fails if a key is missing, unused or duplicated.
6. If you change how a module works, update `ARCHITECTURE.md` (and `README.md`
   if users see the difference).
7. Add or update tests in `tests/` for logic you change. Tests use
   `unittest.TestCase` and must not need a GPU, network access, API keys or a
   downloaded model: mock them, as the existing tests do.

## Running tests

Run from the project root:

```powershell
.venv\Scripts\python -m pytest tests/ -v
# or
.venv\Scripts\python -m unittest discover -s tests -p "test_*.py" -v
```

A few tests already fail on `main` (listed in ARCHITECTURE.md → Known problems).
Your change must not add new failures. Say in the pull request if you saw any.

If your change touches packaging, also check the standalone build:

```powershell
build.bat
```

## Commit messages

Write a short summary in the imperative mood, in English, for example
`Fix popup position on negative-coordinate monitors`. Add a body when the
reason for the change is not obvious.

## Pull requests

- Fill in the pull request template: what changed, why, and how you tested it.
- Link the issue it closes (`Closes #123`).
- Add screenshots or a short GIF for UI changes.
- Keep the branch up to date with `main` and resolve conflicts yourself.
- A maintainer reviews it. Expect questions and requests for changes; that is
  part of the process, not a rejection.

## Releasing (maintainers)

Versions follow [SemVer](https://semver.org/): patch for fixes, minor for new features.

1. Move the `[Unreleased]` entries in `CHANGELOG.md` into a new `## [X.Y.Z] - YYYY-MM-DD`
   section and update the links at the bottom.
2. Set `APP_VERSION = "X.Y.Z"` in `config.py`, commit, and push to `main`.
3. Tag and push: `git tag -a vX.Y.Z -m "Translator Overlay X.Y.Z"` and
   `git push origin vX.Y.Z`.
4. The `Release` workflow checks that the tag matches `APP_VERSION` and the changelog,
   runs the tests, builds the installer and creates a **draft** release with
   `TranslatorOverlay-Setup-X.Y.Z.exe`; the notes are the changelog section, install
   steps and the installer's SHA-256.
5. Install the draft's setup on a clean Windows (Windows Sandbox is enough), check
   install → first launch → translation → uninstall, then publish the release.

`python build.py --check-tag vX.Y.Z` runs the same check locally before you tag.
The workflow can also be started by hand (Actions → Release → Run workflow): it builds
the installer as an artifact without creating a release.

## Reporting security problems

Do not open a public issue for a vulnerability (for example a way to leak the
stored API keys). Use GitHub's
[private vulnerability reporting](https://github.com/Vrihe/Overlay-Translator/security/advisories/new)
instead.
