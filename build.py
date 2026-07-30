"""
build.py — Script to generate application icon and build standalone application (onedir) via PyInstaller.

Usage:
    python build.py           — incremental build (reuses PyInstaller cache)
    python build.py --clean   — full clean rebuild (removes cache first)
"""

import os
import sys
import glob
import shutil
import subprocess
from pathlib import Path


def generate_icon(icon_path: Path):
    """Generate placeholder .ico file using Pillow if missing."""
    try:
        from PIL import Image, ImageDraw
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGBA", (256, 256), color=(0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([8, 8, 248, 248], radius=40, fill=(99, 102, 241))
        d.text((128, 120), "T", fill=(255, 255, 255), anchor="mm", font_size=150)
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
      - Test directories shipped inside packages (torch/test/, scipy/.../tests/).
      - PyTorch C++ build artifacts (torch/include/, torch/share/) — not used at runtime.
    """
    internal = dist_dir / "_internal"
    if not internal.exists():
        return

    removed_count = 0
    removed_bytes = 0

    patterns = [
        "**/*.pyi",              # type stubs
        "**/*.pyx",              # Cython sources
        "**/test_*.py",          # test scripts shipped in packages
        "**/tests/__init__.py",  # marks test packages (prunes discovery)
    ]

    dirs_to_remove = [
        "torch/test",
        "torch/include",
        "torch/share",
        "scipy/io/matlab/tests",
        "scipy/ndimage/tests",
        "skimage/data",
        "skimage/_shared/tests",
    ]

    # Remove matching files
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

    # Remove whole directories
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


def main():
    root = Path(__file__).resolve().parent
    icon_path = root / "assets" / "icon.ico"
    if not icon_path.exists():
        generate_icon(icon_path)

    spec_file = root / "build.spec"

    print("==================================================")
    print("Building TranslatorOverlay (onedir mode) with PyInstaller...")
    print("==================================================")

    cmd = [sys.executable, "-m", "PyInstaller", str(spec_file), "--noconfirm"]
    if "--clean" in sys.argv:
        cmd.append("--clean")
        print("ℹ  --clean flag detected: PyInstaller cache will be cleared.")

    result = subprocess.run(cmd)

    dist_dir = root / "dist" / "TranslatorOverlay"
    out_exe = dist_dir / "TranslatorOverlay.exe"

    if result.returncode == 0 and out_exe.exists():
        print(f"\n[OK] Build successful! Application directory: {dist_dir}")
        print(f"Main executable: {out_exe}")
        print("\nRunning post-build cleanup...")
        post_build_cleanup(dist_dir)
    else:
        print(f"\n[ERROR] Build failed with exit code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
