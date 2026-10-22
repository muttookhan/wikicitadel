"""Build-list W2 (2026-10-22) — Lens margin notes (W3C Web
Annotation model, house-store only).

Two halves. The wiring half inspects the source assets, in the
style of test_reader_view: a class, handler, or caption renamed
away fails here, not silently in the browser. The model half
extracts the pure model block from app.js (between the
MARGIN-NOTES-MODEL markers — no DOM, no storage) and exercises
it under node: annotation shapes, selector construction,
anchored / moved / orphaned resolution, and the export ->
import round trip with every field intact.

Run from anywhere:
    python3 -m unittest tools.lens.tests.test_margin_notes
    python3 tools/lens/tests/test_margin_notes.py
"""

import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve()
LENS_DIR = HERE.parents[1]
ASSETS = LENS_DIR / "assets"

JS = (ASSETS / "app.js").read_text(encoding="utf-8")
CSS = (ASSETS / "lens.css").read_text(encoding="utf-8")
README = (LENS_DIR / "README.md").read_text(encoding="utf-8")


def section(marker_start, marker_end):
    return JS[JS.index(marker_start):JS.index(marker_end)]


def css_block(marker):
    start = CSS.index("*/", CSS.index(marker)) + 2
    rest = CSS[start:]
    nxt = rest.find("\n/* ----------", 10)
    block = rest if nxt < 0 else rest[:nxt]
    return re.sub(r"/\*.*?\*/", "", block, flags=re.S)


NOTES_SECTION = section("Margin notes (Build-list W2, 2026-10-22)",
                        "/* ---------------- Router")
MODEL = section("/* MARGIN-NOTES-MODEL-BEGIN",
                "/* MARGIN-NOTES-MODEL-END */")


class Wiring(unittest.TestCase):
    def test_panel_rendered_in_read_view(self):
        self.assertIn("${marginNotesHtml(p)}", JS)
        self.assertIn("function marginNotesHtml(p)", JS)
        self.assertIn('class="margin-notes"', JS)

    def test_setup_called_with_the_article(self):
        self.assertIn("setupMarginNotes(p, lfArticle)", JS)
        self.assertIn("function setupMarginNotes(p, article)", JS)

    def test_plain_words_boundary_caption(self):
        self.assertIn("kept only in this browser", JS)
        self.assertIn("never in the wiki, never sent anywhere", JS)
        self.assertIn("marked orphaned below and keeps its words",
                      JS)


class StoreAndPrivacy(unittest.TestCase):
    def test_browser_local_store_only(self):
        self.assertIn('MARGIN_NOTES_KEY = "lens-annotations"', JS)
        self.assertIn("localStorage.getItem(MARGIN_NOTES_KEY)", JS)
        self.assertIn("localStorage.setItem(MARGIN_NOTES_KEY", JS)

    def test_no_network_path_in_the_section(self):
        for bad in ("fetch(", "XMLHttpRequest", "/api/", "sendBeacon"):
            self.assertNotIn(bad, NOTES_SECTION,
                             f"margin notes must not reach for {bad}")

    def test_no_row_cap_on_the_store(self):
        # The feedback log caps at 60 rows; notes are records,
        # and saveMarginNotes must not inherit a silent cap.
        save = section("function saveMarginNotes",
                       "function marginNoteId")
        self.assertNotIn("slice(0, 60)", save)


class ModelShape(unittest.TestCase):
    def test_w3c_shapes_present(self):
        for token in ("http://www.w3.org/ns/anno.jsonld",
                      '"Annotation"', "TextualBody",
                      "SpecificResource", "TextQuoteSelector",
                      "TextPositionSelector", "FragmentSelector",
                      "AnnotationCollection", "AnnotationPage"):
            self.assertIn(token, MODEL, f"model must carry {token}")

    def test_orphan_states_named(self):
        for state in ('"page"', '"anchored"', '"moved"', '"orphaned"'):
            self.assertIn(state, MODEL)


NODE_ASSERTIONS = r"""
let failures = 0;
function ok(cond, name) {
  if (!cond) { failures++; console.error("FAIL: " + name); }
}
function eq(a, b, name) {
  ok(JSON.stringify(a) === JSON.stringify(b),
     name + " | got " + JSON.stringify(a));
}

/* --- normalisation + offset map --- */
const raw = "The  quick\n\nbrown   fox jumps.";
const nm = marginNormalizeWithMap(raw);
eq(nm.text, "The quick brown fox jumps.", "normalised collapses runs");
ok(nm.map.length === nm.text.length, "map length matches text");
ok(nm.text.split("").every((c, i) => c === " " || raw[nm.map[i]] === c),
   "map points at the source char");
eq(marginRawOffset(nm.map, nm.rawLength, nm.text.length), raw.length,
   "end offset maps to raw end");

/* --- selectors over a phrase --- */
const doc = marginNormalizeText(
  "Alpha beta gamma. The settled claim stands here. Delta epsilon.");
const start = doc.indexOf("The settled claim");
const end = start + "The settled claim".length;
const sels = marginSelectorsFor(doc, start, end);
eq(sels[0].type, "TextQuoteSelector", "first selector is the quote");
eq(sels[0].exact, "The settled claim", "quote exact");
eq(sels[0].prefix, "Alpha beta gamma. ", "quote prefix");
eq(sels[0].suffix, " stands here. Delta epsilon.", "quote suffix");
eq([sels[1].type, sels[1].start, sels[1].end],
   ["TextPositionSelector", start, end], "position selector");
ok(sels[2].type === "FragmentSelector" &&
   sels[2].value.startsWith(":~:text="), "fragment selector");
eq(decodeURIComponent(sels[2].value.slice(":~:text=".length)),
   "The settled claim", "fragment carries the quote");

/* --- annotation shapes --- */
const pageNote = marginMakeAnnotation({
  id: "urn:test:1", created: "2026-10-22T00:00:00.000Z",
  source: "wiki/concepts/x.md", noteText: "a page note" });
eq(pageNote.type, "Annotation", "annotation type");
eq(pageNote["@context"], MARGIN_NOTES_CONTEXT, "anno context");
eq(pageNote.target, "wiki/concepts/x.md",
   "page target is the source string");
eq(pageNote.body.type, "TextualBody", "body type");
eq(marginBodyText(pageNote), "a page note", "body text reads back");
eq(pageNote.creator.type, "Person", "creator is a local label");
const passNote = marginMakeAnnotation({
  id: "urn:test:2", created: "2026-10-22T00:00:00.000Z",
  source: "wiki/concepts/x.md", noteText: "a passage note",
  selector: sels });
eq(passNote.target.type, "SpecificResource",
   "passage target is a SpecificResource");
eq(marginTargetSource(passNote), "wiki/concepts/x.md",
   "target source reads through");
eq(marginQuote(passNote), "The settled claim", "quote reads through");

/* --- resolution: page / anchored / moved / orphaned --- */
eq(marginResolve(pageNote, doc).state, "page",
   "page note resolves as page");
let r = marginResolve(passNote, doc);
ok(r.state === "anchored" && r.start === start && r.end === end,
   "anchored at the stored offsets");
const lead = "Inserted lead-in changes everything before it. ";
r = marginResolve(passNote, lead + doc);
ok(r.state === "moved" &&
   (lead + doc).slice(r.start, r.end) === "The settled claim",
   "moved follows the same words");
const twice = lead + doc +
  " Again: The settled claim stands here. Delta epsilon.";
r = marginResolve(passNote, twice);
ok(r.state === "moved" && r.start === lead.length + start,
   "stored context disambiguates the repeat");
eq(marginResolve(passNote,
   doc.replace("The settled claim", "A different wording")).state,
   "orphaned", "changed words orphan the note");
const amb = marginMakeAnnotation({
  id: "urn:test:3", created: "2026-10-22T00:00:00.000Z",
  source: "wiki/concepts/x.md", noteText: "amb",
  selector: [
    { type: "TextQuoteSelector", exact: "The settled claim",
      prefix: "zzz ", suffix: " qqq" },
    { type: "TextPositionSelector", start: 0, end: 3 }] });
eq(marginResolve(amb, twice).state, "orphaned",
   "ambiguous repeats orphan rather than guess");

/* --- SVG selectors (the IIIF-aware case): carried, page-listed --- */
const svgNote = {
  "@context": MARGIN_NOTES_CONTEXT, id: "urn:test:svg",
  type: "Annotation", created: "2026-10-22T00:00:00.000Z",
  motivation: "commenting",
  body: { type: "TextualBody", value: "on the figure" },
  target: { type: "SpecificResource", source: "wiki/concepts/x.md",
            selector: [{ type: "SvgSelector",
                         value: "<svg><rect x='1'/></svg>" }] } };
eq(marginResolve(svgNote, doc).state, "page",
   "svg-only selectors list as a page note, not an orphan");

/* --- export -> import round trip, fields intact --- */
const all = [pageNote, passNote, svgNote];
const exported = marginExportCollection(all);
eq(exported.type, "AnnotationCollection", "export is a collection");
eq(exported["@context"], MARGIN_NOTES_CONTEXT, "export context");
eq(exported.total, 3, "export total");
const back = marginParseImport(JSON.stringify(exported));
eq(back.refused, 0, "round trip refuses nothing");
eq(back.annotations, all, "round trip preserves every field verbatim");
eq(marginParseImport(JSON.stringify(all)).annotations.length, 3,
   "bare array imports");
eq(marginParseImport(JSON.stringify(pageNote)).annotations.length, 1,
   "single annotation imports");
const junk = marginParseImport(
  JSON.stringify([pageNote, { type: "Thing" }, null]));
ok(junk.annotations.length === 1 && junk.refused === 2,
   "junk items are refused and counted");
eq(marginParseImport("not json").refused, 1,
   "unparseable import refused whole");

if (failures) {
  console.error(failures + " model failures");
  process.exit(1);
}
console.log("MARGIN-NOTES-MODEL-OK");
"""


class ModelBehaviour(unittest.TestCase):
    def test_model_under_node(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "node is required for the model tests")
        scratch = Path.home() / "workspace" / ".tmp-margin-notes-tests"
        scratch.mkdir(parents=True, exist_ok=True)
        runner = scratch / "model-test.js"
        runner.write_text(MODEL + "\n" + NODE_ASSERTIONS,
                          encoding="utf-8")
        proc = subprocess.run([node, str(runner)],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        self.assertIn("MARGIN-NOTES-MODEL-OK", proc.stdout)


class Css(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.block = css_block(
            "Build-list W2 (2026-10-22): Lens margin notes")

    def test_note_styles_present(self):
        self.assertIn(".margin-notes", self.block)
        self.assertIn(".margin-note-orphan", self.block)
        self.assertIn("mark.margin-note-mark", self.block)

    def test_orphan_visually_distinct(self):
        self.assertIn("border-left-style: dashed", self.block)

    def test_no_typography_fork(self):
        for bad in ("--read-", "!important", "nowrap", "line-height"):
            self.assertNotIn(bad, self.block,
                             f"margin CSS must not declare {bad}")


class DefaultsUnchanged(unittest.TestCase):
    def test_article_render_untouched(self):
        self.assertIn(
            '<article class="reading-body">${bodyHtml}</article>', JS)

    def test_notes_section_is_outside_the_article(self):
        art = JS.index('<article class="reading-body">')
        panel = JS.index("${marginNotesHtml(p)}")
        self.assertGreater(panel, art,
                           "the panel renders after the article, "
                           "never inside the page body")

    def test_readme_records_the_surface(self):
        self.assertIn("Margin notes (W2)", README)
        self.assertIn("ORPHANED", README)


if __name__ == "__main__":
    unittest.main()
