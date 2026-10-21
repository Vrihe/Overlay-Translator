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

import hashlib
import importlib.metadata
import os
import shutil
import subprocess
import sys
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
        d.rectangle([8, 8, 247, 247], fill=(0xff, 0xb0, 0x20))         # accent
        try:
            font = ImageFont.truetype("bahnschrift.ttf", 170)
            font.set_variation_by_name("Bold")
        except Exception:
            font = ImageFont.load_default(size=170)
        d.text((128, 132), "T", fill=(0x1a, 0x12, 0x00), anchor="mm", font=font)  # on_accent
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
        "**/*.pyx",              # Cython sources
        "**/test_*.py",          # test scripts shipped in packages
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

    print(f"✓ Post-build cleanup: removed {removed_count} items, "
          f"freed ~{removed_bytes // 1024 // 1024} MB")


# ── Fingerprint / cache ───────────────────────────────────────────────────────

# Packages whose version changes should trigger a full deps rebuild.
_TRACKED_PACKAGES = [
    'onnxruntime', 'onnxruntime-directml', 'rapidocr',
    'numpy', 'opencv-python', 'opencv-python-headless',
    'Pillow', 'pyclipper', 'shapely', 'PyYAML', 'omegaconf', 'langid',
    'PyQt5', 'mss',
]


def deps_fingerprint(root: Path) -> str:
    """Return a short hex hash identifying the current dependency state.

    The hash covers:
      - The full content of requirements.txt (if it exists)
      - The installed version of every tracked package
    Any change in deps (pip install/upgrade) produces a different fingerprint.
    """
    parts: list[str] = []

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

def merge_deps_into_app(root: Path) -> None:
    """Copy deps layer files into the app dist directory.

    The app layer files (PYZ, EXE, domain_profiles) already sit in
    dist/TranslatorOverlay/_internal/.  We add everything from the deps layer
    that is NOT already present, so the app's own files always take precedence.

    At runtime the PyInstaller bootloader adds _internal/ to sys.path.
    Python's regular import machinery then finds onnxruntime, rapidocr, numpy etc.
    as individual .pyc / .pyd files placed here by the deps layer.
    """
    deps_internal = root / 'dist' / 'TranslatorOverlay_deps' / '_internal'
    app_internal  = root / 'dist' / 'TranslatorOverlay' / '_internal'

    if not deps_internal.exists():
        raise FileNotFoundError(f"Deps _internal not found at {deps_internal}")

    added = 0
    for item in deps_internal.rglob('*'):
        if item.is_file():
            rel    = item.relative_to(deps_internal)
            target = app_internal / rel
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                added += 1

    print(f"  ✓ Merged deps layer: {added:,} files added to app dist.")


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
        rx = r"(\.venv|venv|_build_cache|dist|build|\.git)"
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
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'),
                 os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs')):
        if base:
            candidates.append(Path(base) / 'Inno Setup 6' / 'ISCC.exe')
    return next((c for c in candidates if c.is_file()), None)


def app_version(root: Path) -> str:
    """APP_VERSION from config.py, read as text (importing config would load .env)."""
    import re
    match = re.search(r'^\s*APP_VERSION\s*=\s*["\']([^"\']+)["\']',
                      (root / 'config.py').read_text(encoding='utf-8'), re.MULTILINE)
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    root = Path(__file__).resolve().parent

    # ── Precompile (2.4) ─────────────────────────────────────────────────────
    precompile_sources(root)

    # ── Icon ─────────────────────────────────────────────────────────────────
    icon_path = root / 'assets' / 'icon.ico'
    if not icon_path.exists():
        generate_icon(icon_path)

    # ── Flags ────────────────────────────────────────────────────────────────
    force_full   = '--clean' in sys.argv or '--full' in sys.argv
    cache_info   = '--cache-info' in sys.argv

    fingerprint  = deps_fingerprint(root)
    cache_dir    = get_cache_dir(root, fingerprint)
    cache_exists = cache_dir.exists()

    if cache_info:
        print(f"Deps fingerprint : {fingerprint}")
        print(f"Cache directory  : {cache_dir}")
        print(f"Cache exists     : {cache_exists}")
        return

    if '--installer-only' in sys.argv:
        # Pack the existing dist/TranslatorOverlay/ without rebuilding it.
        if not (root / 'dist' / 'TranslatorOverlay' / 'TranslatorOverlay.exe').exists():
            print("[ERROR] dist/TranslatorOverlay/TranslatorOverlay.exe not found — run python build.py first.")
            sys.exit(1)
        try:
            print(f"  ✓ Installer: {build_installer(root)}")
        except RuntimeError as exc:
            print(f"\n[ERROR] {exc}")
            sys.exit(1)
        return

    print("=" * 60)
    print("  Translator Overlay — Layered Build (optimization 2.1)")
    print("=" * 60)
    print(f"  Deps fingerprint : {fingerprint}")
    print(f"  Cache exists     : {cache_exists}")
    print(f"  Mode             : {'FULL (--clean)' if force_full else 'FULL (first run)' if not cache_exists else 'FAST (cache hit)'}")
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
        merge_deps_into_app(root)
        bundle_msvc_runtime(root / 'dist' / 'TranslatorOverlay')

    except RuntimeError as exc:
        print(f"\n[ERROR] {exc}")
        sys.exit(1)

    # ── Post-build ────────────────────────────────────────────────────────────
    dist_dir = root / 'dist' / 'TranslatorOverlay'
    out_exe  = dist_dir / 'TranslatorOverlay.exe'

    if not out_exe.exists():
        print("\n[ERROR] Build failed — TranslatorOverlay.exe not found.")
        sys.exit(1)

    print(f"\n[OK] Build successful!")
    print(f"  Output : {dist_dir}")
    print(f"  EXE    : {out_exe}")
    print("\n  Running post-build cleanup…")
    post_build_cleanup(dist_dir)

    if '--installer' in sys.argv:
        print("\n  Building installer (Inno Setup)…")
        try:
            setup_exe = build_installer(root)
        except RuntimeError as exc:
            print(f"\n[ERROR] {exc}")
            sys.exit(1)
        print(f"  ✓ Installer: {setup_exe}")


if __name__ == '__main__':
    main()
