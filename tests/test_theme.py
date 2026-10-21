"""
tests/test_theme.py — HUD palettes: completeness, fallback, stylesheet builders, contrast.

Needs PyQt5 (QtGui only, no window is shown). A QGuiApplication is created once
because the icon-backed builders render small pixmaps.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PyQt5.QtGui import QGuiApplication

from ui import theme

_APP = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


_BUILDERS = (
    lambda: theme.label_css("title"), lambda: theme.label_css("muted"),
    lambda: theme.label_css("error"), theme.btn_primary, theme.btn_secondary,
    theme.btn_accent, theme.btn_danger, theme.btn_icon, theme.input_css, theme.result_css,
    theme.combo_css, theme.check_css, lambda: theme.panel_css("x"), theme.group_css,
    lambda: theme.chip_css("ok"), lambda: theme.chip_css("accent"), theme.scrollbar_css,
    theme.table_css, theme.list_css, theme.menu_css, theme.tooltip_css,
    theme.stock_dialog_css, theme.app_css,
)

# A {name} left over from a forgotten f-string prefix.
_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


class TestPalettes(unittest.TestCase):

    def test_three_palettes(self):
        self.assertEqual(set(theme.PALETTES), {"amber", "cyan", "crimson"})

    def test_every_palette_defines_every_token(self):
        for name, pal in theme.PALETTES.items():
            for token in theme.TOKENS:
                value = getattr(pal, token)
                self.assertTrue(value, f"{name}.{token}")
                if not value.startswith("rgba("):
                    self.assertRegex(value, r"^#[0-9a-f]{6}$", f"{name}.{token}")

    def test_unknown_theme_falls_back_to_amber(self):
        for value in ("", None, "neon", "AMBER "):
            self.assertIs(theme.palette_for(value), theme.PALETTES["amber"], value)
        self.assertIs(theme.palette_for("Cyan"), theme.PALETTES["cyan"])

    def test_current_reads_config_once(self):
        import config
        theme.reset()
        try:
            with mock.patch.object(type(config), "UI_THEME", new_callable=mock.PropertyMock,
                                   return_value="crimson"):
                self.assertIs(theme.current(), theme.PALETTES["crimson"])
            # Cached for the run: a later settings change applies after a restart.
            self.assertIs(theme.current(), theme.PALETTES["crimson"])
        finally:
            theme.reset()

    def test_current_unknown_config_value_is_amber(self):
        import config
        theme.reset()
        try:
            with mock.patch.object(type(config), "UI_THEME", new_callable=mock.PropertyMock,
                                   return_value="purple"):
                self.assertIs(theme.current(), theme.PALETTES["amber"])
        finally:
            theme.reset()

    def test_wcag_contrast(self):
        for name, p in theme.PALETTES.items():
            for fg in ("text", "muted", "text_soft", "accent"):
                for bg in ("bg", "panel"):
                    ratio = _contrast(getattr(p, fg), getattr(p, bg))
                    self.assertGreaterEqual(ratio, 4.5, f"{name}: {fg} on {bg} = {ratio:.2f}")
            ratio = _contrast(p.on_accent, p.accent)
            self.assertGreaterEqual(ratio, 4.5, f"{name}: on_accent on accent = {ratio:.2f}")


class TestBuilders(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(theme, "_icon_cache_dir", return_value=Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)
        theme._icon_urls.clear()
        self.addCleanup(theme._icon_urls.clear)

    def test_builders_return_resolved_strings_for_every_palette(self):
        for name in theme.PALETTES:
            with mock.patch.object(theme, "_active", theme.PALETTES[name]):
                for build in _BUILDERS:
                    css = build()
                    self.assertIsInstance(css, str)
                    self.assertTrue(css)
                    self.assertIsNone(_PLACEHOLDER.search(css), f"{name}: {css[:80]}")
                    self.assertEqual(css.count("{"), css.count("}"), f"{name}: {css[:80]}")

    def test_builders_use_the_palette(self):
        with mock.patch.object(theme, "_active", theme.PALETTES["cyan"]):
            self.assertIn(theme.PALETTES["cyan"].accent, theme.btn_primary())
            self.assertIn(theme.PALETTES["cyan"].line, theme.input_css())

    def test_combo_arrow_icon_is_rendered_to_cache(self):
        with mock.patch.object(theme, "_active", theme.PALETTES["amber"]):
            css = theme.combo_css()
        pngs = list(Path(self._tmp.name).glob("chevron_down_*.png"))
        self.assertTrue(pngs)
        self.assertIn(pngs[0].as_posix(), css)

    def test_rgba(self):
        self.assertEqual(theme.rgba("#ffb020", 18), "rgba(255, 176, 32, 18)")


class TestIcons(unittest.TestCase):

    def test_every_icon_renders(self):
        from ui import icons
        for name in icons.NAMES:
            pix = icons.pixmap(name, "#ffb020", 18)
            self.assertFalse(pix.isNull(), name)
            self.assertFalse(icons.path(name).isEmpty(), name)


if __name__ == "__main__":
    unittest.main()
