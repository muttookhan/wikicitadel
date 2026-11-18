#!/usr/bin/env python3
"""Tests for scripts/wiki_bookbuilder.py (Wave 6 build item:
Bookbuilder editions + presentation and print-CSS exports).

Pins, on a FIXTURE corpus in a temp dir (the tool itself is
imported from the real scripts/ tree; only --root points at
the fixture):

  - edition assembly: chapters in SPEC order under the
    cover + contents; the table of contents links to the
    chapter anchors and to namespaced heading anchors;
  - link honesty in both formats: an in-edition wikilink
    becomes an internal reference (chapter anchor in the
    book, the target chapter's divider frame in the deck);
    a wikilink to a corpus page outside the edition becomes
    a boundary mark and a manifest boundary_references
    entry; an unresolvable wikilink becomes a missing mark
    and an unresolved_targets entry;
  - assets: a small local image is inlined as a data URI;
    an external image and a missing local image are omitted
    in place with named reasons, listed in the manifest;
  - content fidelity: each chapter's body TEXT equals the
    source page's rendered text word for word, modulo the
    omitted-image notes (the only added body text) and the
    link rewriting (labels preserved);
  - the print layer: the @media print block passes the
    house WCAG print rows in the wcag_gate's own shape
    (light page/dark text, chrome hidden, canvas unclipped,
    reading text not shrunk), and the paged-media rules put
    page breaks on chapter boundaries (@page with a page
    counter, the cover as a named page, .chapter
    break-before: page);
  - the deck: frame count and order (cover, divider +
    section frames per chapter at the page's top heading
    level, manifest last), every internal href landing on
    an existing frame, print CSS paginating frames;
  - determinism: two builds of each format are
    byte-identical;
  - the corpus is untouched: fixture bytes identical
    before and after both builds;
  - CLI/spec discipline: an unknown declared page exits 1,
    a duplicate page and a malformed spec exit 2, and
    nothing is written on those paths.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import base64
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = SCRIPTS / "wiki_bookbuilder.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BB = _load("wiki_bookbuilder", TOOL)

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

ALPHA = """---
title: Alpha
type: concept
---

# Alpha

Alpha opens the edition and links to [[beta]], onwards to
[[gamma]] outside the edition, and to [[missing-page]].
It also deep-links [[beta#Details]] and cites an external
[reference](https://example.org/paper).

![dot](dot.png)

![ext](https://example.com/x.png)

![gone](nope.png)
"""

BETA = """---
title: Beta
type: concept
---

Beta lead paragraph before any section heading.

## Details

The details section carries the load-bearing sentence for
the fidelity check.

## More

A closing section, so the deck gains a second section
frame for this chapter.
"""

GAMMA = """---
title: Gamma
type: concept
---

Gamma exists in the corpus but is not in the edition.
"""

SPEC = {
    "title": "Fixture Edition",
    "subtitle": "Two chapters, assembled by the bookbuilder",
    "author": "The Fixture Press",
    "pages": ["alpha", "beta"],
}


def _mkdtemp():
    ws = Path(__file__).resolve().parents[3]
    try:
        return Path(tempfile.mkdtemp(prefix="bookbuilder-",
                                     dir=ws))
    except OSError:
        return Path(tempfile.mkdtemp(prefix="bookbuilder-"))


def _tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def _text_of(fragment_html):
    text = re.sub(r"<[^>]+>", " ", fragment_html)
    text = " ".join(text.split())
    # tag removal leaves a space where an inline element sat
    # directly against punctuation; the plain render has none
    return re.sub(r" ([,.;:!?])", r"\1", text)


class BookbuilderCase(unittest.TestCase):
    def setUp(self):
        self.base = _mkdtemp()
        self.addCleanup(shutil.rmtree, self.base,
                        ignore_errors=True)
        self.root = self.base / "corpus"
        wiki = self.root / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        (wiki / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (wiki / "beta.md").write_text(BETA, encoding="utf-8")
        (wiki / "gamma.md").write_text(GAMMA, encoding="utf-8")
        (wiki / "dot.png").write_bytes(PNG_1PX)
        self.spec_path = self.base / "spec.json"
        self.spec_path.write_text(json.dumps(SPEC),
                                  encoding="utf-8")
        self.spec = BB.load_spec(self.spec_path)
        records, keys, pages_all = BB.resolve_edition(
            self.root, self.spec)
        self.records, self.keys = records, keys
        self.pages_all = pages_all
        self.book, self.book_manifest = BB.build_book(
            self.root, self.spec, records, keys, pages_all)
        # rebuild fresh records for the deck (rendering
        # annotates them)
        records2, keys2, pages_all2 = BB.resolve_edition(
            self.root, self.spec)
        self.deck, self.deck_manifest = BB.build_deck(
            self.root, self.spec, records2, keys2, pages_all2)

    # ------------------------------------------------ book

    def test_chapters_in_spec_order(self):
        first = self.book.index('id="ch-01-alpha"')
        second = self.book.index('id="ch-02-beta"')
        self.assertLess(first, second)
        self.assertIn("Chapter 1", self.book)
        self.assertIn("Chapter 2", self.book)
        self.assertEqual(
            [p["page"] for p in self.book_manifest["pages"]],
            ["wiki/concepts/alpha.md", "wiki/concepts/beta.md"])

    def test_toc_links(self):
        self.assertIn('<a href="#ch-01-alpha">', self.book)
        self.assertIn('<a href="#ch-02-beta">', self.book)
        # namespaced heading anchor for Beta's Details section
        self.assertIn('<a href="#ch-02-beta--details">',
                      self.book)

    def test_internal_and_fragment_links(self):
        self.assertIn('<a class="wl" href="#ch-02-beta">',
                      self.book)
        self.assertIn(
            '<a class="wl" href="#ch-02-beta--details">',
            self.book)

    def test_boundary_and_missing_marks(self):
        self.assertIn('class="wl-boundary"', self.book)
        self.assertIn('class="wl-missing"', self.book)
        boundary = self.book_manifest["boundary_references"]
        self.assertEqual(len(boundary), 1)
        self.assertEqual(boundary[0]["target"],
                         "wiki/concepts/gamma.md")
        self.assertEqual(boundary[0]["linked_from"],
                         ["wiki/concepts/alpha.md"])
        unresolved = self.book_manifest["unresolved_targets"]
        self.assertEqual([u["target"] for u in unresolved],
                         ["missing-page"])

    def test_assets(self):
        self.assertIn('src="data:image/png;base64,', self.book)
        omitted = {(a["src"], a["page"])
                   for a in self.book_manifest["assets_omitted"]}
        self.assertIn(("https://example.com/x.png",
                       "wiki/concepts/alpha.md"), omitted)
        self.assertIn(("nope.png", "wiki/concepts/alpha.md"),
                      omitted)
        reasons = " ".join(
            a["reason"]
            for a in self.book_manifest["assets_omitted"])
        self.assertIn("external image", reasons)
        self.assertIn("not found", reasons)
        self.assertEqual(
            len(self.book_manifest["assets_inlined"]), 1)

    def _chapter_body_html(self, doc, anchor, next_marker):
        start = doc.index(f'<section class="chapter" '
                          f'id="{anchor}"')
        end = doc.index(next_marker, start)
        region = doc[start:end]
        body = region[region.index(
            '<div class="reading-body">'):]
        body = body[:body.rindex("</div>")]
        return re.sub(r'<span class="img-omitted">.*?</span>',
                      "", body, flags=re.S)

    def test_content_fidelity(self):
        chunks = {
            "ch-01-alpha": self._chapter_body_html(
                self.book, "ch-01-alpha", 'id="ch-02-beta"'),
            "ch-02-beta": self._chapter_body_html(
                self.book, "ch-02-beta",
                '<section class="manifest"'),
        }
        for rec in self.records:
            plain_html, wikilinks = \
                BB.LENSLIB.render_markdown(rec["body"])
            for i, (_t, _a, label) in enumerate(wikilinks):
                plain_html = plain_html.replace(
                    f"\x00WL{i}\x00", label)
            plain_html = re.sub(r"<img\b[^>]*>", "", plain_html)
            self.assertEqual(
                _text_of(chunks[rec["anchor"]]),
                _text_of(plain_html),
                f"chapter {rec['anchor']} body text differs "
                f"from its source page")

    def test_print_rows(self):
        css = re.search(r"<style>(.*?)</style>", self.book,
                        re.S).group(1)
        pm = re.search(r"@media print\s*{(.*)\n}", css, re.S)
        self.assertIsNotNone(pm, "no @media print block")
        print_css = pm.group(1)
        body_rule = re.search(r"body\s*{([^}]*)}",
                              print_css).group(1)
        # the wcag_gate print rows, in the gate's own shape
        self.assertIn("background: #fff", body_rule)
        self.assertIn("color: #111", body_rule)
        self.assertIn(".screen-chrome", print_css)
        self.assertIn("display: none", print_css)
        canvas = re.search(r"#canvas\s*{([^}]*)}",
                           print_css).group(1)
        self.assertIn("max-height: none", canvas)
        self.assertIn("overflow: visible", canvas)
        shrunk = re.findall(
            r"(?:body|\.reading-body)[^{]*{[^}]*font-size"
            r"\s*:\s*([\d.]+)px", print_css)
        self.assertTrue(
            all(float(v) >= 16 for v in shrunk),
            f"print shrinks reading text: {shrunk}")

    def test_page_break_structure(self):
        css = re.search(r"<style>(.*?)</style>", self.book,
                        re.S).group(1)
        self.assertRegex(css, r"@page\s*{[^}]*counter\(page\)")
        self.assertRegex(css, r"\.cover\s*{[^}]*page:\s*cover")
        self.assertRegex(
            css, r"\.chapter\s*{[^}]*break-before:\s*page")
        chapters = re.findall(
            r'<section class="chapter" id="', self.book)
        self.assertEqual(len(chapters), 2)

    # ------------------------------------------------ deck

    def _frames(self):
        return re.findall(
            r'<section class="(frame[^"]*)" id="(frame-\d+)"',
            self.deck)

    def test_deck_frame_plan(self):
        frames = self._frames()
        ids = [fid for _cls, fid in frames]
        self.assertEqual(
            ids, [f"frame-{i:04d}" for i in range(len(ids))])
        # cover + alpha (divider + 1 section) + beta (divider
        # + 2 sections) + manifest
        self.assertEqual(len(frames), 7)
        classes = [cls for cls, _fid in frames]
        self.assertIn("frame-cover", classes[0])
        self.assertIn("frame-manifest", classes[-1])
        self.assertEqual(
            sum("frame-divider" in c for c in classes), 2)

    def test_deck_links_land_on_frames(self):
        ids = {fid for _cls, fid in self._frames()}
        hrefs = re.findall(r'<a class="wl" href="#(frame-\d+)"',
                           self.deck)
        self.assertTrue(hrefs, "deck carries no page links")
        for href in hrefs:
            self.assertIn(href, ids)
        # Alpha's [[beta]] lands on Beta's divider frame.
        beta_divider = re.search(
            r'<section class="frame frame-divider" '
            r'id="(frame-\d+)" data-page="wiki/concepts/'
            r'beta\.md"', self.deck).group(1)
        self.assertIn(beta_divider, hrefs)
        # boundary + missing marks survive in the deck too
        self.assertIn('class="wl-boundary"', self.deck)
        self.assertIn('class="wl-missing"', self.deck)
        notes = " ".join(self.deck_manifest.get("notes", []))
        self.assertIn("divider frame", notes)

    def test_deck_print_pagination(self):
        css = re.search(r"<style>(.*?)</style>", self.deck,
                        re.S).group(1)
        pm = re.search(r"@media print\s*{(.*)\n}", css, re.S)
        self.assertIsNotNone(pm)
        self.assertRegex(pm.group(1),
                         r"\.frame\s*{[^}]*display:\s*block")
        self.assertRegex(pm.group(1),
                         r"\.frame\s*{[^}]*break-after:\s*page")

    # ------------------------------------------------ shared

    def test_determinism(self):
        r1, k1, p1 = BB.resolve_edition(self.root, self.spec)
        book2, _m = BB.build_book(self.root, self.spec, r1,
                                  k1, p1)
        r2, k2, p2 = BB.resolve_edition(self.root, self.spec)
        deck2, _m2 = BB.build_deck(self.root, self.spec, r2,
                                   k2, p2)
        self.assertEqual(self.book, book2)
        self.assertEqual(self.deck, deck2)

    def test_split_sections_honours_fences(self):
        body = ("Lead.\n\n## Real\n\n```\n## Not a heading\n"
                "```\n\n## Next\n")
        segs = BB.split_sections(body)
        self.assertEqual([h for h, _t in segs],
                         ["", "Real", "Next"])

    def test_embedded_manifest_json(self):
        m = re.search(
            r'<script type="application/json" '
            r'id="edition-manifest">(.*?)</script>',
            self.book, re.S)
        data = json.loads(m.group(1).replace("<\\/", "</"))
        self.assertEqual(data["format"], "edition")
        self.assertEqual(data["title"], "Fixture Edition")
        self.assertIn("commit", data["corpus"])
        self.assertEqual(data["compiled_pages_total"], 3)
        self.assertEqual(data["pages_not_in_edition"], 1)


class BookbuilderCliCase(unittest.TestCase):
    def setUp(self):
        self.base = _mkdtemp()
        self.addCleanup(shutil.rmtree, self.base,
                        ignore_errors=True)
        self.root = self.base / "corpus"
        wiki = self.root / "wiki" / "concepts"
        wiki.mkdir(parents=True)
        (wiki / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (wiki / "beta.md").write_text(BETA, encoding="utf-8")
        (wiki / "gamma.md").write_text(GAMMA, encoding="utf-8")
        (wiki / "dot.png").write_bytes(PNG_1PX)

    def _run(self, spec_obj, out_name="out.html", cmd="build"):
        spec_path = self.base / "spec.json"
        spec_path.write_text(
            spec_obj if isinstance(spec_obj, str)
            else json.dumps(spec_obj), encoding="utf-8")
        out = self.base / out_name
        proc = subprocess.run(
            [sys.executable, str(TOOL), cmd, "--spec",
             str(spec_path), "--out", str(out), "--root",
             str(self.root)],
            capture_output=True, text=True, timeout=120)
        return proc, out

    def test_cli_build_and_present(self):
        before = _tree_hash(self.root)
        proc, out = self._run(SPEC)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Fixture Edition",
                      out.read_text(encoding="utf-8"))
        proc2, out2 = self._run(SPEC, "deck.html", "present")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        self.assertIn('class="frame', out2.read_text(
            encoding="utf-8"))
        self.assertEqual(before, _tree_hash(self.root),
                         "an export modified the corpus")

    def test_cli_unknown_page_exits_1(self):
        proc, out = self._run(
            {"title": "X", "pages": ["alpha", "nope-page"]})
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertFalse(out.exists())

    def test_cli_duplicate_page_exits_2(self):
        proc, out = self._run(
            {"title": "X", "pages": ["alpha", "alpha"]})
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(out.exists())

    def test_cli_malformed_spec_exits_2(self):
        proc, out = self._run("{not json")
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(out.exists())
        proc, out = self._run({"pages": ["alpha"]})
        self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
