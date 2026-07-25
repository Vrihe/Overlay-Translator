"""
build.py — Script to generate application icon and build standalone application (onedir) via PyInstaller.

Usage:
    python build.py
    python build.py --clean  (to force clean build cache)
"""

import os
import sys
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

    result = subprocess.run(cmd)

    out_exe = root / "dist" / "TranslatorOverlay" / "TranslatorOverlay.exe"
    if result.returncode == 0 and out_exe.exists():
        print(f"\n[OK] Build successful! Application directory is located at: {out_exe.parent}")
        print(f"Main executable: {out_exe}")
    else:
        print(f"\n[ERROR] Build failed with exit code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
