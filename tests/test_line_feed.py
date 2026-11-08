"""
tests/test_line_feed.py — a region translated again shows only its new lines: the line
diff, the per-region feed of blocks, the popup listing them newest first without
growing, and TranslatorApp keeping one feed per region.

Strings are synthetic; widgets are built offscreen; no OCR, no backend.
"""

import sys
import unittest
from unittest import mock

from PyQt5.QtCore import QRect
from PyQt5.QtWidgets import QApplication, QLabel

from translate.line_feed import MAX_BLOCKS, RegionFeed, new_lines
from ui.result_popup import ResultPopup

_APP = QApplication.instance() or QApplication(sys.argv[:1])


class TestNewLines(unittest.TestCase):
    def test_only_lines_not_seen_before(self):
        self.assertEqual(new_lines("alpha one\nbeta two", "alpha one\nbeta two\ngamma three"), "gamma three")

    def test_nothing_new(self):
        self.assertEqual(new_lines("alpha one\nbeta two", "beta two\nalpha one"), "")

    def test_case_and_spacing_do_not_matter(self):
        self.assertEqual(new_lines("Alpha  One", "alpha one"), "")

    def test_ocr_noise_counts_as_the_same_line(self):
        self.assertEqual(new_lines("player42: who is ready for the raid", "player42: who is ready for the rald"), "")

    def test_a_repeated_line_is_new_once_per_extra_copy(self):
        self.assertEqual(new_lines("gg", "gg\ngg"), "gg")

    def test_lines_scrolled_away_are_ignored_and_order_is_kept(self):
        self.assertEqual(new_lines("one\ntwo\nthree", "two\nthree\nfour\nfive"), "four\nfive")


class TestRegionFeed(unittest.TestCase):
    def test_newest_first_and_capped(self):
        feed = RegionFeed()
        for i in range(MAX_BLOCKS + 2):
            feed.add(f"00:00:0{i}", f"text {i}")
        self.assertEqual(len(feed.blocks), MAX_BLOCKS)
        self.assertEqual(feed.blocks[0], (f"00:00:0{MAX_BLOCKS + 1}", f"text {MAX_BLOCKS + 1}"))


class TestPopupBlocks(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(ResultPopup, "saved_size", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _texts(self, popup):
        """Label texts in layout order (a separator row gives its time label)."""
        layout = popup._scroll_area.widget().layout()
        widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
        return [(w if isinstance(w, QLabel) else w.findChild(QLabel)).text() for w in widgets]

    def test_single_result_has_no_separator(self):
        popup = ResultPopup("s", "перевод", blocks=[("12:00:00", "перевод")])
        self.addCleanup(popup.deleteLater)
        self.assertEqual(self._texts(popup), ["перевод"])

    def test_blocks_newest_first_with_time_separators(self):
        blocks = [("12:00:10", "новое"), ("12:00:00", "старое")]
        popup = ResultPopup("s", "новое", blocks=blocks)
        self.addCleanup(popup.deleteLater)
        self.assertEqual(self._texts(popup), ["12:00:10", "новое", "12:00:00", "старое"])
        self.assertEqual(popup._translated, "новое")  # copy / TTS take the newest only

    def test_history_does_not_grow_the_popup(self):
        newest = ("12:00:10", "короткая строка")
        one = ResultPopup("s", newest[1], blocks=[newest, ("12:00:00", "x")])
        self.addCleanup(one.deleteLater)
        long_history = [newest] + [("12:00:00", "длинная старая строка\n" * 6)] * 4
        many = ResultPopup("s", newest[1], blocks=long_history)
        self.addCleanup(many.deleteLater)
        self.assertEqual(many.height(), one.height())

    def test_notice_sits_under_the_newest_block(self):
        blocks = [("12:00:10", "новое"), ("12:00:00", "старое")]
        popup = ResultPopup("s", "новое", blocks=blocks, notice="Новых строк нет")
        self.addCleanup(popup.deleteLater)
        self.assertEqual(self._texts(popup)[2], "⚠ Новых строк нет")

    def test_error_update_drops_the_blocks(self):
        popup = ResultPopup("s", "новое", blocks=[("1", "новое"), ("0", "старое")])
        self.addCleanup(popup.deleteLater)
        popup.update_content("", "boom", is_error=True, blocks=[("1", "новое")])
        self.assertEqual(self._texts(popup), ["boom"])
        self.assertEqual(popup._fit_widgets, [])


class TestAppFeeds(unittest.TestCase):
    """TranslatorApp._on_translation_finished on a stub self."""

    ANCHOR = QRect(10, 20, 300, 200)

    def setUp(self):
        from tests.main_import import import_main

        main = import_main()

        self.main = main
        self.app = mock.Mock()
        self.app._feeds = {}
        self.app._MAX_FEEDS = 20
        self.app._feed_for = lambda anchor: main.TranslatorApp._feed_for(self.app, anchor)
        self.app._popup = None

    def _finish(self, **kwargs):
        args = {"source": "src", "translated": "перевод", "error_msg": ""}
        args.update(kwargs)
        self.main.TranslatorApp._on_translation_finished(
            self.app,
            args.pop("source"),
            args.pop("translated"),
            args.pop("error_msg"),
            self.ANCHOR,
            **args,
        )

    def test_result_is_added_to_the_region_feed(self):
        self._finish(ocr_text="line a\nline b")
        feed = self.app._feeds[self.main._anchor_key(self.ANCHOR)]
        self.assertEqual(feed.previous_source, "line a\nline b")
        self.assertEqual(feed.blocks[0][1], "перевод")
        self.assertEqual(self.app._show_result.call_args.kwargs["blocks"], feed.blocks)

    def test_live_check_with_nothing_new_keeps_the_popup(self):
        self._finish(ocr_text="line a")
        self.app._show_result.reset_mock()
        self._finish(translated="", ocr_text="line a", nothing_new=True, live=True)
        self.app._show_result.assert_not_called()

    def test_hotkey_with_nothing_new_shows_the_previous_blocks(self):
        self._finish(ocr_text="line a")
        self.app._show_result.reset_mock()
        self._finish(translated="", ocr_text="line a", nothing_new=True)
        kwargs = self.app._show_result.call_args.kwargs
        self.assertEqual(kwargs["blocks"][0][1], "перевод")
        self.assertTrue(kwargs["notice"])

    def test_error_leaves_the_feed_alone(self):
        self._finish(ocr_text="line a")
        self._finish(translated="", error_msg="Ошибка перевода", ocr_text="line a\nline b")
        feed = self.app._feeds[self.main._anchor_key(self.ANCHOR)]
        self.assertEqual(feed.previous_source, "line a")
        self.assertEqual(len(feed.blocks), 1)

    def test_oldest_region_is_forgotten_past_the_limit(self):
        self.app._MAX_FEEDS = 2
        for x in range(3):
            self.main.TranslatorApp._feed_for(self.app, QRect(x, 0, 10, 10))
        self.assertEqual(list(self.app._feeds), [(1, 0, 10, 10), (2, 0, 10, 10)])


if __name__ == "__main__":
    unittest.main()
