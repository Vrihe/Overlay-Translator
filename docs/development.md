# Development

The rules for contributions (branches, code style, UI strings, commit messages) are in
[CONTRIBUTING.md](https://github.com/Vrihe/Overlay-Translator/blob/main/CONTRIBUTING.md); the
module-by-module map is [ARCHITECTURE.md](https://github.com/Vrihe/Overlay-Translator/blob/main/ARCHITECTURE.md).

## Setup

```powershell
install.bat
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pre-commit install    # ruff lint + format and file checks on every commit
run.bat --console                   # the app with a visible log
```

## Tests and checks

```powershell
.venv\Scripts\python -m pytest tests/ -m "not slow"   # what CI runs
.venv\Scripts\python -m pytest --cov                   # coverage of translate/, cache/, settings/ (floor: 60 %)
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\pre-commit run --all-files
```

- Tests use `unittest.TestCase` and run under pytest too. They must not need a GPU, the network,
  API keys or a downloaded model: mock them, as the existing tests do. A test that really needs a
  model or a GPU gets `@pytest.mark.slow`.
- Settings for pytest, coverage, ruff and mypy are in `pyproject.toml`.

## Continuous integration

`.github/workflows/ci.yml` runs on every pull request and on pushes to `main`:

| Job | Does |
|---|---|
| `lint` | `ruff check` and `ruff format --check` |
| `test (windows-latest)`, `test (ubuntu-latest)` | The test suite with coverage. The app is Windows-only; on Linux, hotkey tests stub the key name lookup and WinAPI calls are mocked or skipped |
| `tests` | Required status check of `main`: green only when the jobs above pass |
| `coverage badge` | On `main` only: writes the coverage percentage to the `badges` branch for the README badge |

`.github/workflows/docs.yml` builds this site with `mkdocs build --strict` on pull requests that
touch the docs and publishes it to GitHub Pages from `main`.
`.github/workflows/release.yml` builds and publishes the installer for a `v*` tag.

## Documentation site

```powershell
.venv\Scripts\pip install -r requirements-docs.txt
.venv\Scripts\mkdocs serve           # http://127.0.0.1:8000, reloads on save
```

Pages live in `docs/`, the navigation in `mkdocs.yml`. Diagrams are Mermaid code blocks; GitHub
renders them in the README as well.
