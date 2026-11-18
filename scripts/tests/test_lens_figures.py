#!/usr/bin/env python3
"""Tests for Lens figure rendering (lenslib.render_markdown):
an image on its own line renders as a <figure>, and the caption
convention — an immediately following single italic line, or a
line starting 'Caption:' — becomes its <figcaption>."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "lens"))

import lenslib as L  # noqa: E402


def render(body):
    return L.render_markdown(body)[0]


class TestFigures(unittest.TestCase):
    def test_image_wrapped_in_figure_with_lazy_loading(self):
        html = render("![A diagram](img/diagram.svg)\n")
        self.assertIn('<figure class="page-figure">', html)
        self.assertIn('<img alt="A diagram" src="img/diagram.svg" '
                      'loading="lazy">', html)
        self.assertIn("</figure>", html)
        self.assertNotIn("<figcaption>", html)

    def test_italic_caption_line_becomes_figcaption(self):
        html = render("![A diagram](img/diagram.svg)\n"
                      "*Figure 1: the chain.*\n\nNext paragraph.\n")
        self.assertIn("<figcaption>Figure 1: the chain.</figcaption>",
                      html)
        # The caption line is consumed, not rendered twice.
        self.assertEqual(html.count("Figure 1: the chain."), 1)
        self.assertIn("<p>Next paragraph.</p>", html)

    def test_caption_prefix_line_becomes_figcaption(self):
        html = render("![A diagram](img/diagram.svg)\n"
                      "Caption: the chain, labelled.\n")
        self.assertIn("<figcaption>the chain, labelled.</figcaption>",
                      html)

    def test_non_adjacent_italic_line_is_not_a_caption(self):
        html = render("![A diagram](img/diagram.svg)\n\n"
                      "*Not a caption.*\n")
        self.assertNotIn("<figcaption>", html)
        self.assertIn("<em>Not a caption.</em>", html)

    def test_alt_is_escaped_in_figure(self):
        html = render('![A "quoted" alt](img/x.svg)\n')
        self.assertIn('alt="A &quot;quoted&quot; alt"', html)


if __name__ == "__main__":
    unittest.main()
