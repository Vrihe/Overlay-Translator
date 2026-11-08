"""Generate the landing page images: landing/img/og-image.png and landing/img/favicon.png.

The social card is 1200x630: the app name and a one-line tagline next to a real frame
of docs/assets/demo-lf2m.gif (the last one, with the translation shown). Needs Pillow.

    python scripts/make_landing_images.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GIF = ROOT / "docs" / "assets" / "demo-lf2m.gif"
ICON = ROOT / "assets" / "icon.ico"
OUT = ROOT / "landing" / "img"

BG = (13, 17, 23)
TEXT = (230, 237, 243)
MUTED = (161, 171, 183)
ACCENT = (31, 111, 235)
BORDER = (48, 54, 61)

W, H = 1200, 630
FONT_CANDIDATES = {
    "bold": ["segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"],
    "regular": ["segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in FONT_CANDIDATES[kind]:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def last_frame(path: Path) -> Image.Image:
    with Image.open(path) as gif:
        gif.seek(gif.n_frames - 1)
        return gif.convert("RGB")


def make_og() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Accent bar on the left edge.
    draw.rectangle((0, 0, 12, H), fill=ACCENT)

    # Text block.
    draw.text((70, 150), "Translator", font=font("bold", 78), fill=TEXT)
    draw.text((70, 235), "Overlay", font=font("bold", 78), fill=TEXT)
    draw.text((70, 355), "Screen translator for Windows", font=font("regular", 28), fill=MUTED)
    draw.text((70, 405), "One hotkey. Any text on screen.", font=font("regular", 28), fill=MUTED)
    draw.text((70, 520), "Works without a key or fully offline", font=font("regular", 24), fill=MUTED)

    # Real demo frame on the right, scaled to fit.
    frame = last_frame(GIF)
    fw = 560
    fh = round(frame.height * fw / frame.width)
    frame = frame.resize((fw, fh), Image.LANCZOS)
    x, y = W - fw - 45, (H - fh) // 2
    draw.rounded_rectangle((x - 3, y - 3, x + fw + 3, y + fh + 3), radius=12, outline=BORDER, width=3)
    img.paste(frame, (x, y))

    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / "og-image.png", optimize=True)


def make_favicon() -> None:
    with Image.open(ICON) as ico:
        sizes = sorted(ico.ico.sizes(), key=lambda s: s[0])
        ico.size = next((s for s in sizes if s[0] >= 64), sizes[-1])
        icon = ico.convert("RGBA")
    icon = icon.resize((64, 64), Image.LANCZOS)
    OUT.mkdir(parents=True, exist_ok=True)
    icon.save(OUT / "favicon.png", optimize=True)


if __name__ == "__main__":
    make_og()
    make_favicon()
    print("wrote", OUT / "og-image.png", "and", OUT / "favicon.png")
