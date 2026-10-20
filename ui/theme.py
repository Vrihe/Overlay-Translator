"""
ui/theme.py — the single source of truth for the "HUD" look.

Holds the colour palettes (amber / cyan / crimson, picked by ``config.UI_THEME``),
the font families and the stylesheet builders every window uses. UI modules never
hard-code colours: they call the builders here or read tokens from ``current()``.

Qt stylesheets have no text-transform / letter-spacing / gap / box-shadow:
uppercase is done in Python on the translated string (display only) and letter
spacing through ``QFont`` (see ``display_font`` / ``body_font``).

``apply_app_theme(app)`` (called from main.py) loads the bundled fonts, sets the
default font and palette and installs the app-wide sheet that styles Qt's stock
dialogs, menus, tooltips and scrollbars. The palette is read once per run, so a
theme change applies after a restart, like the interface language.
"""

import sys
from dataclasses import dataclass, fields
from pathlib import Path

from PyQt5.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt5.QtWidgets import QApplication

DEFAULT_THEME = "amber"


@dataclass(frozen=True)
class Palette:
    """Colour tokens. The first block differs per theme, the second is shared."""

    accent: str
    on_accent: str
    dim: str
    tint: str
    bg: str
    panel: str
    rail: str
    line: str
    active: str
    outer: str

    text: str = "#e8e6df"
    text_soft: str = "#b9bcc5"
    muted: str = "#8f939e"
    nav_idle: str = "#9a9ea9"
    ok: str = "#5fd68a"
    ok_border: str = "#2f5a3c"
    error: str = "#ff6b6b"
    warn: str = "#ffb347"


def rgba(hex_color: str, alpha: int) -> str:
    """``#rrggbb`` + alpha 0-255 → a ``rgba()`` string Qt stylesheets accept."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


# Tints are 7 % of the accent (alpha 18 of 255).
PALETTES: dict[str, Palette] = {
    "amber": Palette(
        accent="#ffb020", on_accent="#1a1200", dim="#6b4d0f", tint=rgba("#ffb020", 18),
        bg="#0c0d10", panel="#12141a", rail="#0a0b0e", line="#262a33",
        active="#161820", outer="#050607",
    ),
    "cyan": Palette(
        accent="#35e0ff", on_accent="#00181d", dim="#1b6a7c", tint=rgba("#35e0ff", 18),
        bg="#080c10", panel="#0e151b", rail="#070a0d", line="#1f2e38",
        active="#0f1b22", outer="#04070a",
    ),
    "crimson": Palette(
        accent="#ff4d6d", on_accent="#2a030c", dim="#7f2438", tint=rgba("#ff4d6d", 18),
        bg="#0f0b0d", panel="#171114", rail="#0b0809", line="#33232a",
        active="#1d1418", outer="#070405",
    ),
}

TOKENS = tuple(f.name for f in fields(Palette))

_active: Palette | None = None


def palette_for(name: str | None) -> Palette:
    """Palette by name; an unknown or empty name falls back to amber."""
    return PALETTES.get(str(name or "").strip().lower(), PALETTES[DEFAULT_THEME])


def current() -> Palette:
    """The palette of this run (read from ``config.UI_THEME`` on first use)."""
    global _active
    if _active is None:
        try:
            import config
            name = config.UI_THEME
        except Exception:
            name = DEFAULT_THEME
        _active = palette_for(name)
    return _active


def reset() -> None:
    """Forget the cached palette (tests)."""
    global _active
    _active = None


def qcolor(token: str, alpha: int | None = None) -> QColor:
    """QColor of a palette token name (``"accent"``) with an optional alpha."""
    c = QColor(getattr(current(), token))
    if alpha is not None:
        c.setAlpha(alpha)
    return c


# ── Fonts ────────────────────────────────────────────────

# Bahnschrift ships with Windows 10 1709+ and has Cyrillic; JetBrains Mono is bundled.
_DISPLAY_CANDIDATES = ("Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Semibold", "Segoe UI")
_BODY_CANDIDATES = ("JetBrains Mono", "Consolas")
_BODY_MEDIUM_CANDIDATES = ("JetBrains Mono Medium", "JetBrains Mono", "Consolas")
_FONT_FILES = ("JetBrainsMono-Regular.ttf", "JetBrainsMono-Medium.ttf")

_display_family = "Segoe UI Semibold"
_body_family = "Consolas"
_body_medium_family = "Consolas"


def _fonts_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "assets" / "fonts"
    return Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _first_available(candidates: tuple[str, ...]) -> str:
    families = set(QFontDatabase().families())
    for name in candidates:
        if name in families:
            return name
    return candidates[-1]


def load_fonts() -> None:
    """Register the bundled fonts and pick the families (fallbacks on any failure)."""
    global _display_family, _body_family, _body_medium_family
    folder = _fonts_dir()
    for name in _FONT_FILES:
        try:
            QFontDatabase.addApplicationFont(str(folder / name))
        except Exception:
            pass
    _display_family = _first_available(_DISPLAY_CANDIDATES)
    _body_family = _first_available(_BODY_CANDIDATES)
    _body_medium_family = _first_available(_BODY_MEDIUM_CANDIDATES)


def display_family() -> str:
    return _display_family


def body_family() -> str:
    return _body_family


def display_font(pt: float, spacing: float = 110.0) -> QFont:
    """Display face (titles, primary buttons); ``spacing`` is a percentage."""
    f = QFont(_display_family)
    f.setPointSizeF(pt)
    if spacing != 100.0:
        f.setLetterSpacing(QFont.PercentageSpacing, spacing)
    return f


def body_font(pt: float = 10, *, medium: bool = False, spacing: float = 100.0) -> QFont:
    """Monospace body face; ``spacing`` is a percentage (114 ≈ 0.14 em caps labels)."""
    f = QFont(_body_medium_family if medium else _body_family)
    f.setPointSizeF(pt)
    if spacing != 100.0:
        f.setLetterSpacing(QFont.PercentageSpacing, spacing)
    return f


# ── Icons for stylesheets ────────────────────────────────

_icon_urls: dict[tuple[str, str, int], str] = {}


def _icon_cache_dir() -> Path:
    try:
        import config
        base = Path(config.USER_DATA_DIR)
    except Exception:
        import tempfile
        base = Path(tempfile.gettempdir()) / "translator-overlay"
    return base / "cache" / "ui_icons"


def icon_url(name: str, color: str, size: int) -> str:
    """Path of a PNG with icon ``name`` for ``image: url(...)`` in a stylesheet.

    Qt stylesheets only take images from files / resources, so the icon is rendered
    once per run into the app cache folder. Returns "" (no image) if that fails.
    """
    key = (name, color, size)
    if key not in _icon_urls:
        url = ""
        try:
            from ui import icons
            folder = _icon_cache_dir()
            folder.mkdir(parents=True, exist_ok=True)
            # 2x so the arrow stays sharp at 150-200 % display scaling.
            pix = icons.pixmap(name, color, size * 2)
            pix.setDevicePixelRatio(1.0)
            target = folder / f"{name}_{color.lstrip('#')}_{size}.png"
            if pix.save(str(target), "PNG"):
                url = target.as_posix()
        except Exception:
            url = ""
        _icon_urls[key] = url
    return _icon_urls[key]


# ── Stylesheet builders ──────────────────────────────────

def text_css(color: str, pt: float = 10, *, display: bool = False, bold: bool = False,
             italic: bool = False) -> str:
    """Property-only sheet for a QLabel / QCheckBox (no selector, no cascade)."""
    family = _display_family if display else _body_family
    weight = " font-weight: 600;" if bold else ""
    style = " font-style: italic;" if italic else ""
    return (f"font-family: '{family}'; font-size: {pt}pt; color: {color};"
            f" background: transparent;{weight}{style}")


def label_css(kind: str = "body") -> str:
    """Text style by role: title, panel_title, body, soft, muted, caption, accent, ok, error, warn."""
    p = current()
    if kind == "title":
        return text_css(p.text, 17, display=True)
    if kind == "panel_title":
        return text_css(p.text, 10.5, display=True)
    sizes = {"caption": 8, "muted": 9}
    colors = {
        "body": p.text, "soft": p.text_soft, "muted": p.muted, "caption": p.muted,
        "accent": p.accent, "ok": p.ok, "error": p.error, "warn": p.warn,
    }
    return text_css(colors.get(kind, p.text), sizes.get(kind, 9.5))


def btn_primary(padding: str = "9px 22px", pt: float = 10) -> str:
    p = current()
    hover = QColor(p.accent).lighter(112).name()
    return (
        "QPushButton {"
        f"  background: {p.accent}; color: {p.on_accent}; border: 1px solid {p.accent};"
        f"  border-radius: 0; padding: {padding};"
        f"  font-family: '{_display_family}'; font-size: {pt}pt;"
        "}"
        f"QPushButton:hover {{ background: {hover}; border-color: {hover}; }}"
        f"QPushButton:focus {{ border-color: {p.text}; }}"
        f"QPushButton:disabled {{ background: {p.line}; border-color: {p.line}; color: {p.muted}; }}"
    )


def btn_secondary(padding: str = "8px 16px", pt: float = 9.5) -> str:
    """Outline button in neutral colours."""
    p = current()
    return (
        "QPushButton {"
        f"  background: transparent; color: {p.text_soft}; border: 1px solid {p.line};"
        f"  border-radius: 0; padding: {padding};"
        f"  font-family: '{_body_family}'; font-size: {pt}pt;"
        "}"
        f"QPushButton:hover {{ color: {p.text}; border-color: {p.accent}; background: {p.tint}; }}"
        f"QPushButton:focus {{ border-color: {p.accent}; }}"
        f"QPushButton:disabled {{ color: {p.line}; border-color: {p.line}; background: transparent; }}"
    )


def btn_accent(padding: str = "6px 14px", pt: float = 9) -> str:
    """Outline button in the accent colour (secondary actions)."""
    p = current()
    return (
        "QPushButton {"
        f"  background: transparent; color: {p.accent}; border: 1px solid {p.dim};"
        f"  border-radius: 0; padding: {padding};"
        f"  font-family: '{_body_family}'; font-size: {pt}pt;"
        "}"
        f"QPushButton:hover {{ background: {p.tint}; border-color: {p.accent}; }}"
        f"QPushButton:focus {{ border-color: {p.accent}; }}"
        f"QPushButton:disabled {{ color: {p.muted}; border-color: {p.line}; background: transparent; }}"
    )


def btn_danger(padding: str = "8px 16px", pt: float = 9.5) -> str:
    p = current()
    return (
        "QPushButton {"
        f"  background: transparent; color: {p.error}; border: 1px solid {rgba(p.error, 90)};"
        f"  border-radius: 0; padding: {padding};"
        f"  font-family: '{_body_family}'; font-size: {pt}pt;"
        "}"
        f"QPushButton:hover {{ background: {rgba(p.error, 30)}; border-color: {p.error}; }}"
        f"QPushButton:focus {{ border-color: {p.error}; }}"
        f"QPushButton:disabled {{ color: {p.line}; border-color: {p.line}; background: transparent; }}"
    )


def btn_icon(*, danger: bool = False) -> str:
    """Flat square icon button (the icon itself is a QIcon from ui/icons.py)."""
    p = current()
    hover_border = p.error if danger else p.dim
    return (
        "QPushButton {"
        "  background: transparent; border: 1px solid transparent; border-radius: 0; padding: 0;"
        "}"
        f"QPushButton:hover {{ background: {p.tint}; border-color: {hover_border}; }}"
        f"QPushButton:focus {{ border-color: {p.dim}; }}"
    )


def input_css(pt: float = 10, padding: str = "6px 10px") -> str:
    """Line edits, text edits, spin boxes and key-sequence edits."""
    p = current()
    sel = (f"selection-background-color: {p.accent}; selection-color: {p.on_accent};")
    return (
        "QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QKeySequenceEdit {"
        f"  background: {p.bg}; color: {p.text}; border: 1px solid {p.line};"
        f"  border-radius: 0; padding: {padding};"
        f"  font-family: '{_body_family}'; font-size: {pt}pt; {sel}"
        "}"
        "QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,"
        f" QKeySequenceEdit:focus {{ border-color: {p.accent}; }}"
        "QLineEdit:disabled, QTextEdit:disabled, QSpinBox:disabled {"
        f"  color: {p.muted}; border-color: {p.line};"
        "}"
        "QLineEdit[readOnly=\"true\"], QTextEdit[readOnly=\"true\"] {"
        f"  background: {p.rail};"
        "}"
        "QSpinBox::up-button, QSpinBox::down-button {"
        f"  width: 16px; border: none; border-left: 1px solid {p.line}; background: {p.panel};"
        "}"
        f"QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: {p.active}; }}"
        f"QSpinBox::up-arrow {{ image: url(\"{icon_url('chevron_up', p.muted, 10)}\"); width: 10px; height: 10px; }}"
        f"QSpinBox::down-arrow {{ image: url(\"{icon_url('chevron_down', p.muted, 10)}\"); width: 10px; height: 10px; }}"
    )


def result_css(pt: float = 10.5) -> str:
    """Read-only result box: accent-tinted fill with a dim accent border."""
    p = current()
    return (
        "QTextEdit {"
        f"  background: {p.tint}; color: {p.text}; border: 1px solid {p.dim};"
        "  border-radius: 0; padding: 10px;"
        f"  font-family: '{_body_family}'; font-size: {pt}pt;"
        f"  selection-background-color: {p.accent}; selection-color: {p.on_accent};"
        "}"
    )


def combo_css(pt: float = 10) -> str:
    p = current()
    return (
        "QComboBox {"
        f"  background: {p.bg}; color: {p.text}; border: 1px solid {p.line};"
        "  border-radius: 0; padding: 6px 28px 6px 10px;"
        f"  font-family: '{_body_family}'; font-size: {pt}pt;"
        "}"
        f"QComboBox:focus, QComboBox:on {{ border-color: {p.accent}; }}"
        f"QComboBox:disabled {{ color: {p.muted}; }}"
        "QComboBox::drop-down {"
        "  subcontrol-origin: padding; subcontrol-position: top right;"
        f"  width: 24px; border: none; border-left: 1px solid {p.line};"
        "}"
        f"QComboBox::down-arrow {{ image: url(\"{icon_url('chevron_down', p.muted, 12)}\");"
        " width: 12px; height: 12px; }"
        "QComboBox::down-arrow:hover, QComboBox::down-arrow:on {"
        f"  image: url(\"{icon_url('chevron_down', p.accent, 12)}\");"
        "}"
        "QComboBox QAbstractItemView {"
        f"  background: {p.panel}; color: {p.text}; border: 1px solid {p.accent};"
        f"  selection-background-color: {p.active}; selection-color: {p.accent};"
        "  outline: none; padding: 0;"
        "}"
    )


def check_css(pt: float = 9.5) -> str:
    """Square check boxes and radio buttons."""
    p = current()
    return (
        "QCheckBox, QRadioButton {"
        f"  color: {p.text_soft}; background: transparent; spacing: 8px;"
        f"  font-family: '{_body_family}'; font-size: {pt}pt;"
        "}"
        f"QCheckBox:hover, QRadioButton:hover {{ color: {p.text}; }}"
        "QCheckBox::indicator, QRadioButton::indicator {"
        f"  width: 12px; height: 12px; border: 1px solid {p.muted}; background: {p.bg};"
        "  border-radius: 0;"
        "}"
        "QCheckBox::indicator:hover, QRadioButton::indicator:hover,"
        f" QCheckBox::indicator:focus, QRadioButton::indicator:focus {{ border-color: {p.accent}; }}"
        "QCheckBox::indicator:checked, QRadioButton::indicator:checked {"
        f"  background: {p.accent}; border-color: {p.accent};"
        "}"
        f"QCheckBox:checked, QRadioButton:checked {{ color: {p.text}; }}"
    )


def panel_css(object_name: str, *, background: str | None = None, border: str | None = None) -> str:
    """Flat panel scoped to ``#object_name`` so the rule never cascades into children."""
    p = current()
    return (f"#{object_name} {{ background: {background or p.panel};"
            f" border: 1px solid {border or p.line}; border-radius: 0; }}")


def group_css() -> str:
    """QGroupBox as a flat panel with a display-font title."""
    p = current()
    return (
        "QGroupBox {"
        f"  background: {p.panel}; color: {p.text}; border: 1px solid {p.line};"
        "  border-radius: 0; margin-top: 22px; padding: 16px 14px 12px;"
        f"  font-family: '{_display_family}'; font-size: 10.5pt;"
        "}"
        "QGroupBox::title {"
        "  subcontrol-origin: margin; subcontrol-position: top left;"
        f"  left: 0; padding: 0 0 4px 0; color: {p.text};"
        "}"
    )


def chip_css(kind: str = "neutral") -> str:
    """Small bordered tag; ``kind`` is ok | neutral | accent."""
    p = current()
    color, border, bg = {
        "ok": (p.ok, p.ok_border, "transparent"),
        "accent": (p.accent, p.dim, p.tint),
    }.get(kind, (p.text_soft, p.line, "transparent"))
    return (f"QLabel {{ color: {color}; border: 1px solid {border}; background: {bg};"
            " border-radius: 0; padding: 0 10px; }")


def scrollbar_css() -> str:
    p = current()
    return (
        "QScrollBar:vertical { background: transparent; width: 8px; margin: 0; border: none; }"
        "QScrollBar:horizontal { background: transparent; height: 8px; margin: 0; border: none; }"
        "QScrollBar::handle:vertical, QScrollBar::handle:horizontal {"
        f"  background: {p.line}; border-radius: 0; min-height: 24px; min-width: 24px;"
        "}"
        "QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {"
        f"  background: {p.dim};"
        "}"
        "QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {"
        "  background: none; width: 0; height: 0; border: none;"
        "}"
    )


def table_css() -> str:
    """History table: rail header, 1 px row separators, no zebra, tinted hover/selection."""
    p = current()
    return (
        "QTableWidget {"
        f"  background: {p.panel}; color: {p.text}; gridline-color: {p.line};"
        f"  border: 1px solid {p.line}; border-radius: 0; outline: none;"
        f"  font-family: '{_body_family}'; font-size: 9pt;"
        "}"
        "QTableWidget::item {"
        f"  background: {p.panel}; color: {p.text}; padding: 6px 8px;"
        f"  border: none; border-bottom: 1px solid {p.line};"
        "}"
        f"QTableWidget::item:alternate {{ background: {p.panel}; }}"
        f"QTableWidget::item:hover {{ background: {p.tint}; }}"
        f"QTableWidget::item:selected {{ background: {p.tint}; color: {p.accent}; }}"
        "QHeaderView { background: transparent; border: none; }"
        "QHeaderView::section {"
        f"  background: {p.rail}; color: {p.muted}; padding: 8px 10px;"
        f"  border: none; border-bottom: 1px solid {p.line};"
        f"  font-family: '{_body_family}'; font-size: 8pt;"
        "}"
        f"QTableWidget QTableCornerButton::section {{ background: {p.rail}; border: none; }}"
    )


def list_css() -> str:
    p = current()
    return (
        "QListWidget {"
        f"  background: {p.panel}; color: {p.text}; border: 1px solid {p.line};"
        "  border-radius: 0; padding: 0; outline: none;"
        f"  font-family: '{_body_family}'; font-size: 9.5pt;"
        "}"
        f"QListWidget::item {{ padding: 8px 10px; border-bottom: 1px solid {p.line}; }}"
        f"QListWidget::item:hover {{ background: {p.tint}; }}"
        "QListWidget::item:selected {"
        f"  background: {p.active}; color: {p.accent}; border-left: 2px solid {p.accent};"
        "}"
    )


def menu_css() -> str:
    p = current()
    return (
        "QMenu {"
        f"  background: {p.panel}; color: {p.text}; border: 1px solid {p.line};"
        "  padding: 4px 0;"
        f"  font-family: '{_body_family}'; font-size: 9.5pt;"
        "}"
        "QMenu::item { padding: 6px 28px 6px 16px; background: transparent; }"
        f"QMenu::item:selected {{ background: {p.active}; color: {p.accent}; }}"
        f"QMenu::item:disabled {{ color: {p.muted}; }}"
        f"QMenu::item:checked {{ color: {p.accent}; }}"
        f"QMenu::separator {{ height: 1px; background: {p.line}; margin: 4px 0; }}"
        "QMenu::indicator { width: 10px; height: 10px; left: 4px; }"
        f"QMenu::indicator:checked {{ background: {p.accent}; border: 1px solid {p.accent}; }}"
    )


def tooltip_css() -> str:
    p = current()
    return (f"QToolTip {{ background: {p.panel}; color: {p.text}; border: 1px solid {p.dim};"
            f" padding: 4px 6px; font-family: '{_body_family}'; font-size: 9pt; }}")


def stock_dialog_css() -> str:
    """QMessageBox / QInputDialog / QFileDialog pinned to the dark theme.

    With the Windows dark-mode system palette these dialogs otherwise render dark
    text on a dark window and look empty.
    """
    p = current()
    return (
        f"QMessageBox, QInputDialog {{ background: {p.panel}; }}"
        "QMessageBox QLabel, QInputDialog QLabel {"
        f"  color: {p.text}; background: transparent;"
        f"  font-family: '{_body_family}'; font-size: 10pt;"
        "}"
        "QInputDialog QLineEdit {"
        f"  background: {p.bg}; color: {p.text}; border: 1px solid {p.line};"
        f"  border-radius: 0; padding: 6px 10px; font-family: '{_body_family}'; font-size: 10pt;"
        "}"
        f"QInputDialog QLineEdit:focus {{ border-color: {p.accent}; }}"
        "QMessageBox QPushButton, QInputDialog QPushButton {"
        f"  background: transparent; color: {p.text_soft}; border: 1px solid {p.line};"
        "  border-radius: 0; padding: 6px 18px; min-width: 64px;"
        f"  font-family: '{_body_family}'; font-size: 9.5pt;"
        "}"
        "QMessageBox QPushButton:hover, QInputDialog QPushButton:hover {"
        f"  color: {p.text}; border-color: {p.accent}; background: {p.tint};"
        "}"
        "QMessageBox QPushButton:default, QInputDialog QPushButton:default {"
        f"  background: {p.accent}; color: {p.on_accent}; border-color: {p.accent};"
        "}"
    )


def app_css() -> str:
    """The app-wide sheet: stock dialogs, menus (incl. the tray menu), tooltips, scrollbars."""
    return stock_dialog_css() + menu_css() + tooltip_css() + scrollbar_css()


def apply_app_theme(app: QApplication) -> None:
    """Load fonts, set the default font / palette and install the app-wide sheet."""
    load_fonts()
    p = current()
    app.setFont(body_font(9.5))

    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(p.bg))
    pal.setColor(QPalette.WindowText, QColor(p.text))
    pal.setColor(QPalette.Base, QColor(p.bg))
    pal.setColor(QPalette.AlternateBase, QColor(p.panel))
    pal.setColor(QPalette.Text, QColor(p.text))
    pal.setColor(QPalette.Button, QColor(p.panel))
    pal.setColor(QPalette.ButtonText, QColor(p.text))
    pal.setColor(QPalette.Highlight, QColor(p.accent))
    pal.setColor(QPalette.HighlightedText, QColor(p.on_accent))
    pal.setColor(QPalette.ToolTipBase, QColor(p.panel))
    pal.setColor(QPalette.ToolTipText, QColor(p.text))
    pal.setColor(QPalette.PlaceholderText, QColor(p.muted))
    pal.setColor(QPalette.Link, QColor(p.accent))
    app.setPalette(pal)

    app.setStyleSheet(app_css())
