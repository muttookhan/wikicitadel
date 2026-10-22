"""Build-list W2 (2026-10-22) — Reader View toggle + Line Focus.

Reader View is a PRESENTATION of the compiled page (a class on
the reading wrap; lens.css hides the furniture and centres the
one column) and Line Focus shipped with item 64 — this lane
composes the two and hardens Line Focus (plain-words
explanation, scroll-following, keyboard + reduced-motion
statements). These tests pin the wiring in the source assets,
the same inspection style as test_wcag_typography: a class or
handler renamed away fails here, not silently in the browser.

Run from anywhere:
    python3 -m unittest tools.lens.tests.test_reader_view
    python3 tools/lens/tests/test_reader_view.py
"""

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
ASSETS = LENS_DIR / "assets"

JS = (ASSETS / "app.js").read_text(encoding="utf-8")
CSS = (ASSETS / "lens.css").read_text(encoding="utf-8")


def css_block(marker):
    """The CSS rules of the section whose header comment carries
    the marker, up to the next section comment, comments
    stripped. The marker sits INSIDE its header comment, so the
    block proper starts after that comment closes."""
    start = CSS.index("*/", CSS.index(marker)) + 2
    rest = CSS[start:]
    nxt = rest.find("\n/* ----------", 10)
    block = rest if nxt < 0 else rest[:nxt]
    return re.sub(r"/\*.*?\*/", "", block, flags=re.S)


class ReaderViewWiring(unittest.TestCase):
    def test_toggle_markup_in_read_render(self):
        self.assertIn('data-readview', JS)
        self.assertIn('id="reader-toggle"', JS)
        self.assertIn('aria-pressed="false">Read</button>', JS)

    def test_toggle_wired_in_render_read(self):
        self.assertIn("setupReaderView(rvBtn, lfWrap)", JS)
        self.assertIn("function setupReaderView(btn, wrap)", JS)

    def test_state_is_a_browser_preference_only(self):
        # Stored like the Line Focus preference; defaults OFF
        # (anything but the stored "1" renders the old view).
        self.assertIn('store("lens.readerview") === "1"', JS)
        self.assertIn('store("lens.readerview", readerOn ? "1" : "0")', JS)
        self.assertIn('wrap.classList.toggle("reader-on", readerOn)', JS)
        self.assertIn('btn.setAttribute("aria-pressed", String(readerOn))',
                      JS)

    def test_escape_leaves_reader_view(self):
        self.assertIn('ev.key === "Escape" && readerOn', JS)

    def test_plain_words_for_reader_view(self):
        self.assertIn("Read view shows just this page, in one clean "
                      "column, in your saved reading type", JS)


class ReaderViewCss(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.block = css_block("Build-list W2 (2026-10-22): Reader View")

    def test_furniture_hidden(self):
        for sel in (".page-breadcrumb", ".chip-row", ".page-tabs",
                    ".toc", ".page-provenance", ".verified-line",
                    ".cite-pair", ".feedback-controls",
                    "#page-history-panel", "#page-diff-panel",
                    "#page-content-panel > h2",
                    "#page-content-panel > ul"):
            self.assertIn(f".reading-wrap.reader-on {sel}", self.block,
                          f"reader view must hide {sel}")

    def test_stale_banner_not_hidden(self):
        self.assertNotIn(".stale-banner", self.block)

    def test_portal_chrome_minimised_via_has(self):
        for sel in ("#rail", "#navcol", "#inspector", "#tabbar"):
            self.assertIn(f"body:has(.reading-wrap.reader-on) {sel}",
                          self.block)

    def test_no_typography_fork(self):
        # Reader View must consume the SAME --read-* variables
        # via the existing .reading-wrap/.reading-body rules —
        # redeclaring type here would fork the profile and break
        # the WCAG gate's premise.
        for prop in ("font-size:", "line-height:", "font-family:",
                     "letter-spacing:", "word-spacing:", "max-width:"):
            self.assertNotIn(prop, self.block,
                             f"reader CSS must not redeclare {prop}")

    def test_no_transitions_declared(self):
        self.assertNotIn("transition", self.block)


class LineFocusHardening(unittest.TestCase):
    def test_plain_words_explanation(self):
        self.assertIn("Line focus dims the rest of the page so a few "
                      "lines stay bright and easy to follow", JS)
        self.assertIn("arrow keys", JS)

    def test_band_sizes_unchanged(self):
        # The chips are rendered by interpolation over the size
        # list; the list and the attribute are what to pin.
        self.assertIn('data-lf="${n}"', JS)
        self.assertIn("[0, 1, 3, 5]", JS)

    def test_keyboard_advance_still_wired(self):
        self.assertIn('ev.key === "ArrowDown" || ev.key === "ArrowUp"',
                      JS)
        self.assertIn("lfPosition(wrap, article)", JS)

    def test_scroll_following(self):
        self.assertIn("lfScrollHandler", JS)
        self.assertIn('window.addEventListener("scroll", '
                      'lfScrollHandler', JS)
        self.assertIn('window.removeEventListener("scroll", '
                      'lfScrollHandler', JS)

    def test_reduced_motion_respected(self):
        # The global block kills transitions portal-wide, and the
        # band itself declares none — it repositions instantly.
        self.assertIn("@media (prefers-reduced-motion: reduce)", CSS)
        mask = re.search(r"\.lf-mask\s*\{([^}]*)\}", CSS).group(1)
        self.assertNotIn("transition", mask)

    def test_line_focus_stays_available_in_reader_view(self):
        # The .lf-controls block is not a direct child of the
        # content panel and is named by no reader-on hide rule.
        block = css_block("Build-list W2 (2026-10-22): Reader View")
        self.assertNotIn(".lf-controls", block)
        self.assertNotIn(".lf-mask", block)


class DefaultsUnchanged(unittest.TestCase):
    def test_read_render_still_the_same_shape(self):
        self.assertIn('<article class="reading-body">', JS)
        self.assertIn('class="lf-controls"', JS)
        self.assertIn("setupLineFocus(lfWrap, lfArticle)", JS)


if __name__ == "__main__":
    unittest.main()
