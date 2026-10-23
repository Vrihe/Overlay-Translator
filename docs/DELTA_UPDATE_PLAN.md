# Plan: smaller updates (app layer / deps layer split)

Status: implemented (build, installer, release workflow, updater). Not yet tried on a
real release: the first app-only update needs an install that already has the manifest.

## Problem

Every update downloads the full `TranslatorOverlay-Setup-X.Y.Z.exe` (~115 MB), even though
between releases usually only our own code changes. Most of the weight is the dependency
layer: onnxruntime-directml, PyQt5, numpy, OpenCV. It changes rarely, and `build.py`
already builds it as a separate PyInstaller layer with a fingerprint
(`deps_fingerprint`, `_TRACKED_PACKAGES`).

## Goal

- When the deps layer did not change, an update downloads only the app layer (~14 MB
  for 1.3.0, of which the exe is ~13 MB; Setup.exe is ~124 MB).
- When it did change, or anything in the light path fails, fall back to today's flow:
  download and silently run the full `Setup.exe`.
- New installs keep using the same `Setup.exe`; nothing changes for them.

## Release assets

| Asset | Content | Always present |
|---|---|---|
| `TranslatorOverlay-Setup-X.Y.Z.exe` | full installer, as today | yes |
| `TranslatorOverlay-app-X.Y.Z.zip` | every file of `dist/TranslatorOverlay/` that is **not** a deps-layer file, paths relative to the install dir | yes |
| `update-manifest.json` | metadata used to choose the update path (below) | yes |

There is no separate deps archive: a deps change means the full installer. That keeps one
heavy path instead of two.

`update-manifest.json`:

```json
{
  "version": "1.3.0",
  "deps_fingerprint": "3f2a9c...",
  "runtime": "cp312-pyinstaller6.x",
  "app_zip": {"name": "TranslatorOverlay-app-1.3.0.zip", "sha256": "...", "size": 4123456},
  "app_files": ["TranslatorOverlay.exe", "_internal/base_library.zip", "..."]
}
```

- `deps_fingerprint`: hash of `runtime` plus the path and SHA-256 of every deps-layer file
  in the final tree. It is computed from the files, not from the package list of
  `build.py --fingerprint` (the CI cache key): that list cannot see an untracked package
  or a file moving between the layers, and a wrong match would break the install.
- `runtime`: Python ABI and PyInstaller version. The bootloader lives in the app layer but
  must match the deps layer's compiled modules, so a runtime change also forces the full
  installer. It is also part of the cache-key fingerprint.
- `app_files`: the full list of app-layer files, so the updater can remove files that a
  new version no longer ships.

The installer also writes this manifest to `{app}\update-manifest.json`, so the installed
app knows its own fingerprint and file list.

## Build changes (`build.py`) — done

1. `merge_deps_into_app` returns the deps-layer files: the ones it copies, plus app-layer
   files that are byte-identical to their deps-layer copy. PyInstaller collects binaries
   for the app spec too (Qt5 DLLs, `python312.dll`); counting only copied files put
   ~93 MB of unchanged files into the app zip. The list goes to
   `dist/TranslatorOverlay.layers.json`, so `--installer-only` can package later.
2. The app-layer set = all files of `dist/TranslatorOverlay/` minus the deps-layer list,
   computed after `post_build_cleanup` and `bundle_msvc_runtime`. The MSVC runtime DLLs
   go to the app layer (cheap, and always consistent with the exe).
3. `build.py --update-package` writes `dist/installer/TranslatorOverlay-app-X.Y.Z.zip`
   and `dist/installer/update-manifest.json`. `--installer` and `--installer-only` call
   it before Inno Setup, so the manifest goes into the installer.
4. `runtime_tag()` (Python ABI + PyInstaller version) is part of the fingerprint.
5. Large native packages the app imports were only in the app layer: `ctranslate2`
   (~58 MB), `pydantic_core`, `sentencepiece`, `sqlite3`. They moved to `build_deps.spec`
   (excluded in `build_app.spec`, tracked in `_TRACKED_PACKAGES` with `pydantic`, which
   pins the exact `pydantic-core`). The zip went from 71.6 MB to 14.3 MB. Left in the app
   layer as not worth it (< 3 MB together): `pywin32`, `protobuf`, `jiter`, `tzdata`.

What stays in the zip is mostly `TranslatorOverlay.exe` (~13 MB): its PYZ holds all
pure-Python code, the API SDKs included. A per-file delta against the previous release
would not be smaller, because the exe changes in every release.

## Installer changes (`installer/TranslatorOverlay.iss`)

- Install `update-manifest.json` into `{app}` — done.
- `[UninstallDelete]` for `{app}\_internal` and `{app}\.update-staging` — done.

## Release workflow (`.github/workflows/release.yml`) — done

- Upload the zip and `update-manifest.json` next to `Setup.exe` in the draft release.
- Put the zip's SHA-256 into the release notes as well (`build.py --release-notes
  --app-sha256`; the updater checks the asset `digest` from the GitHub API first, like
  for `Setup.exe`). The notes say the two extra files are for the in-app updater.

## Updater changes (`updater/install_update.py`) — done

As built: the swap script is written to `apply-update.ps1` (UTF-8 with BOM) and run with
`-File`, since ~650 paths do not fit `-EncodedCommand` (32K command line). On rollback it
writes `%APPDATA%\translator-overlay\update\app-update-failed-<version>.txt` (so does a
swap that cannot be started); the next try for that version takes the installer. The
`.old` files are deleted and the registry is touched only after a successful swap. The
manifest is used only when GitHub's asset `digest` checks it. `.pyc` files are hashed
without their header (source mtime), so a deps layer rebuilt after a CI cache eviction
keeps its fingerprint. A read-only install dir (all-users install) takes
the installer too. The zip's file list must equal `app_files`, and manifest paths must be
plain relative paths. Checked by hand with real PowerShell on a fake install dir
(success and rollback).

1. `Release` gets the manifest asset URL; `latest_release` keeps working without it
   (old releases → full installer).
2. `choose_update_path(installed_manifest, new_manifest) -> "app" | "full"`:
   `"app"` only when both manifests exist and `deps_fingerprint` and `runtime` match.
   Pure function, easy to unit-test.
3. `download_app_zip(...)`: same `.part` + SHA-256 + cancel logic as `download_setup`
   (reuse it, the function differs only in the asset).
4. Applying the app zip cannot happen while the app runs (the exe and `.pyd` files are
   locked). Reuse the waiter: the hidden PowerShell script waits for the app's pid, then
   - extracts the zip to `{app}\.update-staging\`,
   - renames each current app file to `*.old` and moves the new one into place,
   - deletes app files listed in the old manifest but missing from the new one,
   - writes the new `update-manifest.json`,
   - on any error, restores the `*.old` files and starts the old exe (rollback),
   - on success, deletes `*.old` and the staging folder and starts the new exe.
   An option to keep the script small: do the file swap in a tiny Python-free PowerShell
   function and test the plan (list of moves) in Python, not the shell itself.
5. If the light path fails before the app exits (download error, checksum mismatch,
   manifest unreadable), log it and fall back to `download_setup` + `launch_installer`.

## Things the light path must keep in sync

- **"Apps & features" version.** Inno Setup writes `DisplayVersion` under
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{AppId}_is1`. After an app-zip
  update the waiter script updates `DisplayVersion` (and `DisplayName` if it carries the
  version) itself. Otherwise Windows shows the old version.
- **Uninstall.** Inno's uninstaller removes files from its own log (`unins000.dat`); files
  added only by the app zip would be left behind. Fix: an `[UninstallDelete]` entry
  `Type: filesandordirs; Name: "{app}\_internal"` (and the exe), so uninstall removes the
  whole app directory regardless of how it was updated.
- **`[InstallDelete] {app}\_internal`** stays: a later full install starts clean.

## UI — done

The button works as before. The download progress shows the size ("…: 40% из 14 МБ"):
before the click the app does not know yet which path it will take.

## Tests (no network)

- `choose_update_path`: matching fingerprints → app; different fingerprint, different
  runtime, missing installed or new manifest → full.
- Manifest parsing: unknown fields ignored, broken JSON → full path.
- `build.py` (done, `tests/test_build_installer.py`): app-layer set excludes deps files,
  includes the exe and MSVC DLLs; manifest sha256/size match the zip; the fingerprint
  follows deps file content (build on a fake dist tree in a temp dir).
- Swap plan: given old and new file lists, the planned moves/deletes are correct, and the
  rollback plan restores every moved file.
- Waiter script text contains the expected paths and the rollback branch (like the
  existing `waiter_script` tests).
- Fallback: checksum mismatch on the zip → `download_setup` is called.

## Rollout

The build and the updater ship together in one release N: updating to N still takes the
installer (older installs have no manifest), and from N on, N → N+1 can be app-only when
the deps did not change. No two-step rollout is needed: the updater never takes the
light path without both manifests.

## Docs — done

- `ARCHITECTURE.md`: release pipeline section (new assets, manifest) and the updater section.
- `CHANGELOG.md`: "Updates download only the changed part of the app when possible."
- `CONTRIBUTING.md`: the release process mentions the new assets.

## Rough size of the work

All done in one branch. Left: watch the first real N → N+1 update.

## After 1.4.1: pinned deps and a shared cache

1.4.0 → 1.4.1 still took the installer: the fingerprints differed, correctly. Both tag
runs missed the deps cache (a tag cannot read another tag's cache) and rebuilt the layer
from open version ranges, and in one day pip picked newer certifi, anthropic,
huggingface_hub and jiter. Fix: `requirements-lock.txt` (exact versions, used by
release.yml, generated by `build.py --lock-requirements`, matching what 1.4.1 was built
with) and `deps-cache.yml`, which keeps the layer cached on main for every tag run. The
deps layer is not reproducible byte for byte: a dry run of release.yml with the same
locked versions as 1.4.1 gave fingerprint `9ade6c53…` against 1.4.1's `d592cefb…`. So
the cache is what makes releases match. 1.4.2, the first release built from the main
cache, takes the installer from 1.4.1; from 1.4.2 on, releases built from the same cached
layer can update app-only. If the cache is ever lost, one update falls back to the
installer again.
