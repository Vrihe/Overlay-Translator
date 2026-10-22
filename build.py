"""
build.py — Layered build orchestrator for Translator Overlay.

Usage:
    python build.py               — smart build (uses deps cache when possible)
    python build.py --clean       — full clean rebuild, refreshes deps cache
    python build.py --cache-info  — print current cache fingerprint and exit
    python build.py --installer   — build, then pack dist/TranslatorOverlay/ into
                                    dist/installer/TranslatorOverlay-Setup-<version>.exe
                                    with Inno Setup 6 (installer/TranslatorOverlay.iss)
    python build.py --installer-only — only pack the existing dist/TranslatorOverlay/
    python build.py --update-package — only write the app-layer update package of the
                                    existing build: dist/installer/TranslatorOverlay-app-
                                    <version>.zip + update-manifest.json (--installer and
                                    --installer-only write it too, before Inno Setup)

Release helpers (used by .github/workflows/release.yml, nothing is built):
    python build.py --fingerprint            — print the deps fingerprint (CI cache key)
    python build.py --check-tag vX.Y.Z       — fail unless the tag equals v + APP_VERSION
                                               and CHANGELOG.md has a section for it
    python build.py --release-notes OUT.md   — write the release notes for APP_VERSION
                                               (CHANGELOG section + install steps;
                                               --sha256 / --app-sha256 add the checksums
                                               of Setup.exe / the app zip)

How it works (optimization 2.1 — layered build):
  The build is split into two independent layers:

  ┌─────────────────────────────────────────────────────────────────────┐
  │  Layer 1 — DEPS  (build_deps.spec, run with --noarchive)            │
  │  Heavy packages: onnxruntime, rapidocr, numpy, cv2, PyQt5 …        │
  │  Output: dist/TranslatorOverlay_deps/_internal/  (~500 MB)          │
  │  Build time: 10–15 min  (but cached between builds!)                │
  ├─────────────────────────────────────────────────────────────────────┤
  │  Layer 2 — APP   (build_app.spec)                                    │
  │  Only app code: main.py, translate/, ocr/, ui/, … (no heavy deps)   │
  │  Output: dist/TranslatorOverlay/_internal/  (tiny, ~5 MB)           │
  │  Build time: 1–3 min  ← what you wait for on every rebuild          │
  └─────────────────────────────────────────────────────────────────────┘

  After building, the two layers are MERGED:
    dist/TranslatorOverlay_deps/_internal/*  →  dist/TranslatorOverlay/_internal/
  (app files take precedence; dep files are only added if not already present)

  The deps layer is cached in  _build_cache/<fingerprint>/
  The fingerprint is a SHA-256 hash of requirements.txt + installed package
  versions, so the cache is invalidated automatically when deps change.

Full build (first time or --clean):
    Phase 1: pyinstaller build_deps.spec --noarchive   (10–15 min)
    Phase 2: pyinstaller build_app.spec                 (1–3 min)
    Cache: saved to _build_cache/<fingerprint>/

Subsequent builds (same deps):
    Phase 1: restore cache → dist/TranslatorOverlay_deps/  (seconds)
    Phase 2: pyinstaller build_app.spec                     (1–3 min)
    Total: ~2–3 min instead of 15–20 min
"""

import filecmp
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────


def generate_icon(icon_path: Path) -> None:
    """Generate the app .ico with Pillow: the HUD tile (flat square, amber accent from
    ui/theme.py's default palette, dark "T"), matching tray/icon_gen.py."""
    try:
        from PIL import Image, ImageDraw, ImageFont

        icon_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rectangle([8, 8, 247, 247], fill=(0xFF, 0xB0, 0x20))  # accent
        try:
            font = ImageFont.truetype("bahnschrift.ttf", 170)
            font.set_variation_by_name("Bold")
        except Exception:
            font = ImageFont.load_default(size=170)
        d.text((128, 132), "T", fill=(0x1A, 0x12, 0x00), anchor="mm", font=font)  # on_accent
        img.save(
            icon_path,
            format="ICO",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
        )
        print(f"✓ Created icon at {icon_path}")
    except Exception as e:
        print(f"Warning: Could not generate icon: {e}")


def post_build_cleanup(dist_dir: Path) -> None:
    """Remove development-only files from the distribution directory to reduce size.

    Targets:
      - Python type stubs (.pyi) — only needed for IDEs, not at runtime.
      - Cython sources (.pyx) — compiled to .pyd already, originals unneeded.
      - Test directories shipped inside packages (scipy/.../tests/, skimage data).
    """
    import glob

    internal = dist_dir / "_internal"
    if not internal.exists():
        return

    removed_count = 0
    removed_bytes = 0

    patterns = [
        "**/*.pyx",  # Cython sources
        "**/test_*.py",  # test scripts shipped in packages
        "**/tests/__init__.py",  # marks test packages (prunes discovery)
        # NOTE: **/*.pyi is intentionally excluded here.
        # In noarchive=True builds, PyInstaller creates internal .pyi stubs
        # for C extensions (e.g. skimage\_init_.pyi for skimage/__init__.pyd).
        # Deleting them causes "Cannot load imports from non-existent stub" crash.
        # Type annotation stubs are already filtered out during collection
        # (see collect_data_files filtering in build_deps.spec).
    ]

    dirs_to_remove = [
        "scipy/io/matlab/tests",
        "scipy/ndimage/tests",
        "skimage/data",
        "skimage/_shared/tests",
    ]

    for pattern in patterns:
        for path_str in glob.glob(str(internal / pattern), recursive=True):
            p = Path(path_str)
            try:
                size = p.stat().st_size
                p.unlink()
                removed_count += 1
                removed_bytes += size
            except Exception as e:
                print(f"  Warning: Could not remove {p}: {e}")

    for rel_dir in dirs_to_remove:
        target = internal / rel_dir
        if target.exists():
            try:
                size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
                shutil.rmtree(target)
                removed_count += 1
                removed_bytes += size
                print(f"  Removed dir: {rel_dir} ({size // 1024:,} KB)")
            except Exception as e:
                print(f"  Warning: Could not remove {target}: {e}")

    print(f"✓ Post-build cleanup: removed {removed_count} items, freed ~{removed_bytes // 1024 // 1024} MB")


# ── Fingerprint / cache ───────────────────────────────────────────────────────

# Packages whose version changes should trigger a full deps rebuild.
_TRACKED_PACKAGES = [
    'onnxruntime',
    'onnxruntime-directml',
    'rapidocr',
    'numpy',
    'opencv-python',
    'opencv-python-headless',
    'Pillow',
    'pyclipper',
    'shapely',
    'PyYAML',
    'omegaconf',
    'langid',
    'PyQt5',
    'mss',
    'ctranslate2',
    'sentencepiece',
    'pydantic-core',
    # Not in the deps layer, but checks the exact pydantic-core version on import.
    'pydantic',
]


def runtime_tag() -> str:
    """Python ABI and PyInstaller version, e.g. ``cp312-pyinstaller6.11.1``.

    The bootloader and pythonXY.dll ship in the app layer but must match the compiled
    modules of the deps layer, so a change here invalidates the deps layer too.
    """
    try:
        pyinstaller = importlib.metadata.version('pyinstaller')
    except importlib.metadata.PackageNotFoundError:
        pyinstaller = 'MISSING'
    return f"cp{sys.version_info.major}{sys.version_info.minor}-pyinstaller{pyinstaller}"


def deps_fingerprint(root: Path) -> str:
    """Return a short hex hash identifying the current dependency state.

    The hash covers:
      - The full content of requirements.txt (if it exists)
      - The installed version of every tracked package
      - The Python ABI and PyInstaller version (runtime_tag)
    Any change in deps (pip install/upgrade) produces a different fingerprint.
    """
    parts: list[str] = [runtime_tag()]

    req_file = root / 'requirements.txt'
    if req_file.exists():
        parts.append(req_file.read_text(encoding='utf-8', errors='replace'))

    for pkg in _TRACKED_PACKAGES:
        try:
            ver = importlib.metadata.version(pkg)
            parts.append(f"{pkg}=={ver}")
        except importlib.metadata.PackageNotFoundError:
            parts.append(f"{pkg}=MISSING")

    raw = '\n'.join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def get_cache_dir(root: Path, fingerprint: str) -> Path:
    return root / '_build_cache' / fingerprint


def save_deps_cache(root: Path, fingerprint: str) -> None:
    """Copy the freshly built deps layer to the cache directory."""
    src = root / 'dist' / 'TranslatorOverlay_deps'
    dst = get_cache_dir(root, fingerprint)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Caching deps layer → _build_cache/{fingerprint[:8]}… ", end='', flush=True)
    shutil.copytree(src, dst)
    print("done.")


def restore_deps_cache(root: Path, fingerprint: str) -> None:
    """Restore the cached deps layer to dist/TranslatorOverlay_deps/."""
    src = get_cache_dir(root, fingerprint)
    dst = root / 'dist' / 'TranslatorOverlay_deps'
    if dst.exists():
        shutil.rmtree(dst)
    print(f"  Restoring deps from cache ({fingerprint[:8]}…) … ", end='', flush=True)
    shutil.copytree(src, dst)
    print("done.")


# ── PyInstaller runner ────────────────────────────────────────────────────────


def run_pyinstaller(spec: str, *, clean: bool = False) -> None:
    """Run PyInstaller for the given spec, raising RuntimeError on failure."""
    cmd = [sys.executable, '-m', 'PyInstaller', spec, '--noconfirm']
    if clean:
        cmd.append('--clean')
    print(f"  > {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError(f"PyInstaller failed for {spec} (exit code {result.returncode})")


# ── Merge ─────────────────────────────────────────────────────────────────────


def merge_deps_into_app(root: Path) -> list[str]:
    """Copy deps layer files into the app dist directory; return the deps-layer paths.

    The returned paths are relative to dist/TranslatorOverlay/ in POSIX form
    (``_internal/numpy/...``): the files an app-only update must leave alone. They
    are the copied files plus the app-layer files that are byte-identical to their
    deps-layer copy (PyInstaller also collects e.g. Qt5 DLLs for the app layer).

    The app layer files (PYZ, EXE, domain_profiles) already sit in
    dist/TranslatorOverlay/_internal/.  We add everything from the deps layer
    that is NOT already present, so the app's own files always take precedence.

    At runtime the PyInstaller bootloader adds _internal/ to sys.path.
    Python's regular import machinery then finds onnxruntime, rapidocr, numpy etc.
    as individual .pyc / .pyd files placed here by the deps layer.
    """
    deps_internal = root / 'dist' / 'TranslatorOverlay_deps' / '_internal'
    app_internal = root / 'dist' / 'TranslatorOverlay' / '_internal'

    if not deps_internal.exists():
        raise FileNotFoundError(f"Deps _internal not found at {deps_internal}")

    deps_files: list[str] = []
    added = 0
    for item in deps_internal.rglob('*'):
        if item.is_file():
            rel = item.relative_to(deps_internal)
            target = app_internal / rel
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                added += 1
            elif not filecmp.cmp(item, target, shallow=False):
                continue
            deps_files.append(f"_internal/{rel.as_posix()}")

    print(f"  ✓ Merged deps layer: {added:,} files added to app dist.")
    return deps_files


# onnxruntime imports MSVCP140.dll + MSVCP140_1.dll and needs >= 14.40, but the
# only msvcp140_1.dll PyInstaller collects is PyQt5's 14.26 copy in Qt5\bin.
# Ship one consistent, current set at the _internal root (main.py preloads it).
_MSVC_RUNTIME_DLLS = ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll', 'msvcp140_1.dll')


def bundle_msvc_runtime(dist_dir: Path) -> None:
    """Copy the system VC++ runtime (System32) over the copies in _internal/."""
    system32 = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32'
    internal = dist_dir / '_internal'
    missing = [name for name in _MSVC_RUNTIME_DLLS if not (system32 / name).exists()]
    if missing:
        raise RuntimeError(
            f"VC++ runtime not found in {system32}: {', '.join(missing)}. "
            "Install the latest Microsoft Visual C++ Redistributable (x64)."
        )
    for name in _MSVC_RUNTIME_DLLS:
        shutil.copy2(system32 / name, internal / name)
    print(f"  ✓ Bundled VC++ runtime from {system32}: {', '.join(_MSVC_RUNTIME_DLLS)}")


def precompile_sources(root: Path) -> None:
    """Precompile application Python files to bytecode (.pyc) in parallel (optimization 2.4).

    Using all available CPU cores speeds up PyInstaller's analysis and compilation
    step by 5–10%.
    """
    import compileall
    import multiprocessing

    workers = max(1, multiprocessing.cpu_count())
    print(f"  Precompiling Python sources ({workers} CPU workers)… ", end="", flush=True)
    try:
        rx = re.compile(r"(\.venv|venv|_build_cache|dist|build|\.git)")  # compileall needs a regex object
        compileall.compile_dir(
            str(root),
            maxlevels=10,
            rx=rx,
            workers=workers,
            quiet=1,
            force=False,
        )
        print("done.")
    except Exception as e:
        print(f"skipped ({e}).")


# ── Update package (app layer only) ───────────────────────────────────────────

# Written next to dist/TranslatorOverlay/ by every build: which files of the merged
# tree came from the deps layer, and the fingerprint they were built with.
_LAYERS_FILE = Path('dist') / 'TranslatorOverlay.layers.json'
UPDATE_MANIFEST = 'update-manifest.json'


def save_layer_info(root: Path, fingerprint: str, deps_files: list[str]) -> None:
    """Record the deps-layer file list of the build in dist/ (read by --update-package)."""
    info = {'deps_fingerprint': fingerprint, 'runtime': runtime_tag(), 'deps_files': sorted(deps_files)}
    (root / _LAYERS_FILE).write_text(json.dumps(info, indent=1), encoding='utf-8')


def app_layer_files(dist_dir: Path, deps_files: list[str]) -> list[str]:
    """Files of the final tree that an app-only update ships, sorted POSIX paths.

    Everything that did not come from the deps layer, plus the VC++ runtime DLLs:
    bundle_msvc_runtime overwrites them after the merge, so they follow the exe.
    """
    deps = set(deps_files) - {f"_internal/{name}" for name in _MSVC_RUNTIME_DLLS}
    files = (p.relative_to(dist_dir).as_posix() for p in dist_dir.rglob('*') if p.is_file())
    return sorted(f for f in files if f not in deps)


def _content_sha256(path: Path) -> str:
    """SHA-256 of a file, streamed; a .pyc without its 16-byte header.

    The header holds the source's mtime and size. A deps layer rebuilt from a fresh
    pip install (CI cache evicted) gets new mtimes, but the same bytecode must keep
    the same fingerprint, or app-only updates would never apply after that.
    """
    with open(path, 'rb') as f:
        if path.suffix == '.pyc':
            f.seek(16)
        return hashlib.file_digest(f, 'sha256').hexdigest()


def deps_content_fingerprint(dist_dir: Path, deps_files: list[str], runtime: str) -> str:
    """Hash of the runtime tag and the path + content hash of every deps-layer file.

    An app-only update is safe only when the installed deps files are exactly the
    new build's. Hashing the files themselves catches what the package list in
    deps_fingerprint cannot: an untracked package, or a file moving between layers.
    """
    digest = hashlib.sha256(runtime.encode())
    for rel in sorted(deps_files):
        digest.update(f"\n{rel}:{_content_sha256(dist_dir / rel)}".encode())
    return digest.hexdigest()[:16]


def build_update_package(root: Path, version: str) -> tuple[Path, Path]:
    """Write the app-layer zip and update-manifest.json to dist/installer/.

    Needs dist/TranslatorOverlay/ and the layer info of the build that produced it.
    """
    dist_dir = root / 'dist' / 'TranslatorOverlay'
    layers_file = root / _LAYERS_FILE
    if not layers_file.is_file():
        raise RuntimeError(f"{_LAYERS_FILE.as_posix()} not found — run python build.py first.")
    info = json.loads(layers_file.read_text(encoding='utf-8'))
    deps_present = [f for f in info['deps_files'] if (dist_dir / f).is_file()]
    app_files = app_layer_files(dist_dir, deps_present)
    deps_in_tree = sorted(set(deps_present) - set(app_files))  # minus the VC++ runtime
    if 'TranslatorOverlay.exe' not in app_files:
        raise RuntimeError(f"TranslatorOverlay.exe not found in {dist_dir}")

    out_dir = root / 'dist' / 'installer'
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f'TranslatorOverlay-app-{version}.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in app_files:
            zf.write(dist_dir / rel, rel)

    manifest = {
        'version': version,
        'deps_fingerprint': deps_content_fingerprint(dist_dir, deps_in_tree, info['runtime']),
        'runtime': info['runtime'],
        'app_zip': {
            'name': zip_path.name,
            'sha256': _content_sha256(zip_path),
            'size': zip_path.stat().st_size,
        },
        'app_files': app_files,
    }
    manifest_path = out_dir / UPDATE_MANIFEST
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding='utf-8')
    return zip_path, manifest_path


# ── Installer (Inno Setup) ────────────────────────────────────────────────────

_ISS_SCRIPT = Path('installer') / 'TranslatorOverlay.iss'


def find_iscc() -> Path | None:
    """Locate the Inno Setup 6 compiler: $ISCC, PATH, then the default install dirs."""
    candidates = []
    if os.environ.get('ISCC'):
        candidates.append(Path(os.environ['ISCC']))
    on_path = shutil.which('ISCC')
    if on_path:
        candidates.append(Path(on_path))
    for base in (
        os.environ.get('ProgramFiles(x86)'),
        os.environ.get('ProgramFiles'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs'),
    ):
        if base:
            candidates.append(Path(base) / 'Inno Setup 6' / 'ISCC.exe')
    return next((c for c in candidates if c.is_file()), None)


def app_version(root: Path) -> str:
    """APP_VERSION from config.py, read as text (importing config would load .env)."""
    match = re.search(
        r'^\s*APP_VERSION\s*=\s*["\']([^"\']+)["\']', (root / 'config.py').read_text(encoding='utf-8'), re.MULTILINE
    )
    if match is None:
        raise RuntimeError("APP_VERSION not found in config.py")
    return match.group(1)


def build_installer(root: Path) -> Path:
    """Compile installer/TranslatorOverlay.iss; return the Setup.exe path."""
    iscc = find_iscc()
    if iscc is None:
        raise RuntimeError(
            "Inno Setup 6 compiler (ISCC.exe) not found. Install it "
            "(winget install JRSoftware.InnoSetup) or set the ISCC environment variable."
        )
    version = app_version(root)
    cmd = [str(iscc), f'/DAppVersion={version}', str(root / _ISS_SCRIPT)]
    print(f"  > {' '.join(cmd)}")
    if subprocess.run(cmd).returncode != 0:
        raise RuntimeError("Inno Setup failed to compile the installer")
    return root / 'dist' / 'installer' / f'TranslatorOverlay-Setup-{version}.exe'


# ── Release helpers (.github/workflows/release.yml) ───────────────────────────

_SEMVER = re.compile(r'^\d+\.\d+\.\d+$')


def changelog_section(root: Path, version: str) -> str:
    """Body of the ``## [version]`` section of CHANGELOG.md; '' when there is none."""
    text = (root / 'CHANGELOG.md').read_text(encoding='utf-8')
    match = re.search(
        rf'^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)',
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ''


def check_release_tag(root: Path, tag: str) -> str:
    """Return APP_VERSION when *tag* is ``v<APP_VERSION>`` and CHANGELOG.md covers it."""
    version = app_version(root)
    if not _SEMVER.match(version):
        raise RuntimeError(f"APP_VERSION {version!r} is not X.Y.Z")
    if tag != f'v{version}':
        raise RuntimeError(f"Tag {tag!r} does not match APP_VERSION {version} (expected v{version})")
    if not changelog_section(root, version):
        raise RuntimeError(f"CHANGELOG.md has no '## [{version}]' section")
    return version


def release_notes(root: Path, version: str, sha256: str = '', app_sha256: str = '') -> str:
    """GitHub release notes: the CHANGELOG section plus download and install steps."""
    setup = f'TranslatorOverlay-Setup-{version}.exe'
    app_zip = f'TranslatorOverlay-app-{version}.zip'
    lines = [
        changelog_section(root, version),
        '',
        '## Install',
        '',
        f'1. Download **{setup}** below (Windows 10 / 11, 64-bit) and run it. It installs '
        'for your user without admin rights.',
        '2. Windows SmartScreen may say "Windows protected your PC": the installer is not '
        'code-signed. Click **More info → Run anyway**.',
        '3. Updating: run the new setup over the old version; settings, history and models '
        'in `%APPDATA%\\translator-overlay\\` are kept.',
    ]
    if app_sha256:
        lines += [
            '',
            f'`{app_zip}` and `{UPDATE_MANIFEST}` are for the in-app updater; to install, '
            f'you only need {setup}.',
        ]
    if sha256:
        lines += ['', f'SHA-256 of `{setup}`: `{sha256.upper()}`']
    if app_sha256:
        lines += ['', f'SHA-256 of `{app_zip}`: `{app_sha256.upper()}`']
    return '\n'.join(lines) + '\n'


def _arg_after(flag: str) -> str:
    """The command-line value that follows *flag*."""
    i = sys.argv.index(flag)
    if i + 1 >= len(sys.argv):
        print(f"[ERROR] {flag} needs a value")
        sys.exit(2)
    return sys.argv[i + 1]


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    root = Path(__file__).resolve().parent

    # ── Release helpers: answer and exit, nothing is built ───────────────────
    try:
        if '--fingerprint' in sys.argv:
            print(deps_fingerprint(root))
            return
        if '--check-tag' in sys.argv:
            print(f"Tag OK: version {check_release_tag(root, _arg_after('--check-tag'))}")
            return
        if '--release-notes' in sys.argv:
            out = Path(_arg_after('--release-notes'))
            sha = _arg_after('--sha256') if '--sha256' in sys.argv else ''
            app_sha = _arg_after('--app-sha256') if '--app-sha256' in sys.argv else ''
            out.write_text(release_notes(root, app_version(root), sha, app_sha), encoding='utf-8')
            print(f"Release notes written to {out}")
            return
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        sys.exit(1)

    # ── Precompile (2.4) ─────────────────────────────────────────────────────
    precompile_sources(root)

    # ── Icon ─────────────────────────────────────────────────────────────────
    icon_path = root / 'assets' / 'icon.ico'
    if not icon_path.exists():
        generate_icon(icon_path)

    # ── Flags ────────────────────────────────────────────────────────────────
    force_full = '--clean' in sys.argv or '--full' in sys.argv
    cache_info = '--cache-info' in sys.argv

    fingerprint = deps_fingerprint(root)
    cache_dir = get_cache_dir(root, fingerprint)
    cache_exists = cache_dir.exists()

    if cache_info:
        print(f"Deps fingerprint : {fingerprint}")
        print(f"Cache directory  : {cache_dir}")
        print(f"Cache exists     : {cache_exists}")
        return

    if '--installer-only' in sys.argv or '--update-package' in sys.argv:
        # Pack the existing dist/TranslatorOverlay/ without rebuilding it.
        if not (root / 'dist' / 'TranslatorOverlay' / 'TranslatorOverlay.exe').exists():
            print("[ERROR] dist/TranslatorOverlay/TranslatorOverlay.exe not found — run python build.py first.")
            sys.exit(1)
        try:
            _package(root, installer='--installer-only' in sys.argv)
        except RuntimeError as exc:
            print(f"\n[ERROR] {exc}")
            sys.exit(1)
        return

    print("=" * 60)
    print("  Translator Overlay — Layered Build (optimization 2.1)")
    print("=" * 60)
    print(f"  Deps fingerprint : {fingerprint}")
    print(f"  Cache exists     : {cache_exists}")
    print(
        f"  Mode             : {'FULL (--clean)' if force_full else 'FULL (first run)' if not cache_exists else 'FAST (cache hit)'}"
    )
    print()

    try:
        if force_full or not cache_exists:
            # ── FULL BUILD ────────────────────────────────────────────────────
            print("[Phase 1/2] Building heavy deps layer  (build_deps.spec)…")
            print("            This takes 10–15 min and only needs to run when deps change.")
            run_pyinstaller('build_deps.spec', clean=force_full)
            save_deps_cache(root, fingerprint)
            print()

            print("[Phase 2/2] Building app layer  (build_app.spec)…")
            run_pyinstaller('build_app.spec', clean=force_full)

        else:
            # ── FAST BUILD ────────────────────────────────────────────────────
            print("[Phase 1/2] Restoring heavy deps from cache…")
            restore_deps_cache(root, fingerprint)
            print()

            print("[Phase 2/2] Building app layer  (build_app.spec)…")
            run_pyinstaller('build_app.spec', clean=False)

        # ── Merge layers ──────────────────────────────────────────────────────
        print()
        print("  Merging dep layer → app dist…")
        save_layer_info(root, fingerprint, merge_deps_into_app(root))
        bundle_msvc_runtime(root / 'dist' / 'TranslatorOverlay')

    except RuntimeError as exc:
        print(f"\n[ERROR] {exc}")
        sys.exit(1)

    # ── Post-build ────────────────────────────────────────────────────────────
    dist_dir = root / 'dist' / 'TranslatorOverlay'
    out_exe = dist_dir / 'TranslatorOverlay.exe'

    if not out_exe.exists():
        print("\n[ERROR] Build failed — TranslatorOverlay.exe not found.")
        sys.exit(1)

    print("\n[OK] Build successful!")
    print(f"  Output : {dist_dir}")
    print(f"  EXE    : {out_exe}")
    print("\n  Running post-build cleanup…")
    post_build_cleanup(dist_dir)

    if '--installer' in sys.argv:
        try:
            _package(root, installer=True)
        except RuntimeError as exc:
            print(f"\n[ERROR] {exc}")
            sys.exit(1)


def _package(root: Path, *, installer: bool) -> None:
    """Write the update package; with *installer*, then Setup.exe (it embeds the manifest)."""
    print("\n  Building update package (app layer)…")
    zip_path, manifest_path = build_update_package(root, app_version(root))
    print(f"  ✓ App zip  : {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"  ✓ Manifest : {manifest_path}")
    if installer:
        print("\n  Building installer (Inno Setup)…")
        print(f"  ✓ Installer: {build_installer(root)}")


if __name__ == '__main__':
    main()
