#!/usr/bin/env python3
"""Tests for scripts/wiki_slice_export.py (Wave 6 build item:
single-file wiki-slice export, quine pattern).

Pins, on a FIXTURE corpus in a temp dir (the tool itself is
imported from the real scripts/ tree; only --root points at
the fixture):

  - slice selection: tag / folder / seed+hops (undirected) /
    explicit page list / --all, over the compiled-layer set
    (access/, talk/, index.md, log.md excluded);
  - selection errors: an unknown explicit page and an empty
    slice both exit 2 and write nothing;
  - link honesty in the render: an in-slice wikilink becomes
    an in-file anchor (heading anchors namespaced per page);
    a wikilink to a corpus page outside the slice becomes a
    boundary chip (no dead anchor) and lands in the manifest's
    boundary_references with its linking pages; a wikilink to
    no page becomes a missing chip and an unresolved_targets
    entry;
  - self-containment: no external resource references at all
    (no <script src>, no <link>, no <img src="http...">, no
    @import, no url(http...)); a small local image is inlined
    as a data URI; an external image, a missing local image
    and an over-cap local image are omitted with named reasons
    in the manifest and in place;
  - the manifest: included pages with anchors, corpus commit
    field present (None + note when the root is not a git
    checkout), pages_left_out_by_spec counted;
  - determinism: two builds over the same fixture are
    byte-identical;
  - the corpus is untouched: the fixture tree's bytes are
    identical before and after an export.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import base64
import hashlib
import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = SCRIPTS / "wiki_slice_export.py"

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

ALPHA = """---
title: Alpha
type: concept
tags: [fixture, core]
---

# Alpha

Alpha links to [[beta]], to [[gamma]], to [[beta#Details]]
and to [[missing-page]]. An external
[reference](https://example.org/paper) stays a link.

![dot](dot.png)

![ext](https://example.com/x.png)

![gone](nope.png)
"""

BETA = """---
title: Beta
type: concept
tags: [fixture]
---

# Beta

Beta links back to [[alpha]].

## Details

The details section.
"""

GAMMA = """---
title: Gamma
type: concept
tags: [other]
---

# Gamma

Gamma stands alone.
"""

DELTA = """---
title: Delta
type: entity
tags: [fixture]
---

# Delta

Delta links only to [[beta]].
"""


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "wiki_slice_export", TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class TestWikiSliceExport(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        wiki = self.root / "wiki"
        (wiki / "concepts").mkdir(parents=True)
        (wiki / "entities").mkdir(parents=True)
        (wiki / "access").mkdir(parents=True)
        (wiki / "talk").mkdir(parents=True)
        (wiki / "concepts" / "alpha.md").write_text(
            ALPHA, encoding="utf-8")
        (wiki / "concepts" / "beta.md").write_text(
            BETA, encoding="utf-8")
        (wiki / "concepts" / "gamma.md").write_text(
            GAMMA, encoding="utf-8")
        (wiki / "entities" / "delta.md").write_text(
            DELTA, encoding="utf-8")
        (wiki / "concepts" / "dot.png").write_bytes(PNG_1PX)
        (wiki / "index.md").write_text("# Index\n", encoding="utf-8")
        (wiki / "log.md").write_text("# Log\n", encoding="utf-8")
        (wiki / "access" / "secret.md").write_text(
            "# Secret\n", encoding="utf-8")
        (wiki / "talk" / "t.md").write_text(
            "# Talk\n", encoding="utf-8")
        self.tool = _load_tool()

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, spec, name="test", max_bytes=262144):
        return self.tool.build_slice_html(
            self.root, spec, name, max_bytes)

    # ------------------------------------------------ selection

    def test_tag_slice(self):
        _doc, m = self.build({"mode": "tag", "tag": "fixture"})
        ids = [p["id"] for p in m["pages"]]
        self.assertEqual(ids, ["wiki/concepts/alpha.md",
                               "wiki/concepts/beta.md",
                               "wiki/entities/delta.md"])
        self.assertEqual(m["pages_included"], 3)
        self.assertEqual(m["corpus"]["compiled_pages_total"], 4)
        self.assertEqual(m["pages_left_out_by_spec"], 1)

    def test_folder_slice(self):
        _doc, m = self.build({"mode": "folder",
                              "folder": "entities"})
        self.assertEqual([p["id"] for p in m["pages"]],
                         ["wiki/entities/delta.md"])
        boundary = {b["target"] for b in m["boundary_references"]}
        self.assertEqual(boundary, {"wiki/concepts/beta.md"})

    def test_seed_hops(self):
        _d, m1 = self.build({"mode": "seed", "seed": "alpha",
                             "hops": 1})
        self.assertEqual(
            {p["id"] for p in m1["pages"]},
            {"wiki/concepts/alpha.md", "wiki/concepts/beta.md",
             "wiki/concepts/gamma.md"})
        _d, m2 = self.build({"mode": "seed", "seed": "alpha",
                             "hops": 2})
        self.assertEqual(
            {p["id"] for p in m2["pages"]},
            {"wiki/concepts/alpha.md", "wiki/concepts/beta.md",
             "wiki/concepts/gamma.md", "wiki/entities/delta.md"})

    def test_pages_list_and_all(self):
        _d, m = self.build({"mode": "pages",
                            "pages": ["alpha", "gamma"]})
        self.assertEqual([p["id"] for p in m["pages"]],
                         ["wiki/concepts/alpha.md",
                          "wiki/concepts/gamma.md"])
        _d, m_all = self.build({"mode": "all"})
        self.assertEqual(m_all["pages_included"], 4)

    def test_unknown_page_and_empty_slice_are_errors(self):
        with self.assertRaises(ValueError):
            self.build({"mode": "pages",
                        "pages": ["alpha", "nope"]})
        with self.assertRaises(ValueError):
            self.build({"mode": "tag", "tag": "nosuchtag"})

    def test_cli_exit_codes(self):
        out = self.root / "out.html"
        ok = subprocess.run(
            [sys.executable, str(TOOL), "--root", str(self.root),
             "--tag", "fixture", "--out", str(out)],
            capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(out.is_file())
        bad_out = self.root / "bad.html"
        bad = subprocess.run(
            [sys.executable, str(TOOL), "--root", str(self.root),
             "--pages", "alpha,nope", "--out", str(bad_out)],
            capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertFalse(bad_out.exists())

    # ------------------------------------------------ rendering

    def test_link_honesty(self):
        doc, m = self.build({"mode": "tag", "tag": "fixture"})
        # In-slice wikilink -> in-file anchor.
        self.assertIn('href="#page-concepts-beta"', doc)
        # Heading anchor namespaced per page, and the anchored
        # wikilink points at the namespaced id.
        self.assertIn('id="page-concepts-beta--details"', doc)
        self.assertIn('href="#page-concepts-beta--details"', doc)
        # Out-of-slice target -> boundary chip, never an anchor.
        self.assertIn('class="wl-boundary"', doc)
        self.assertNotIn('href="#page-concepts-gamma"', doc)
        # Unresolved target -> missing chip.
        self.assertIn('class="wl-missing"', doc)
        # Manifest records both, with linking pages.
        gamma = [b for b in m["boundary_references"]
                 if b["target"] == "wiki/concepts/gamma.md"]
        self.assertEqual(len(gamma), 1)
        self.assertIn("wiki/concepts/alpha.md",
                      gamma[0]["linked_from"])
        self.assertEqual(
            m["unresolved_targets"],
            [{"target": "missing-page",
              "linked_from": ["wiki/concepts/alpha.md"]}])

    def test_self_containment_and_images(self):
        doc, m = self.build({"mode": "tag", "tag": "fixture"})
        self.assertNotIn("<script src", doc)
        self.assertNotIn("<link", doc)
        self.assertNotIn("@import", doc)
        self.assertIsNone(re.search(r"<img[^>]+src=\"https?:", doc))
        self.assertIsNone(re.search(r"url\(\s*https?:", doc))
        # Small local image inlined as a data URI.
        self.assertIn('src="data:image/png;base64,', doc)
        inlined = {(a["page"], a["src"])
                   for a in m["assets"]["inlined"]}
        self.assertIn(("wiki/concepts/alpha.md", "dot.png"),
                      inlined)
        omitted = {(a["src"]): a["reason"]
                   for a in m["assets"]["omitted"]}
        self.assertIn("external", omitted["https://example.com/x.png"])
        self.assertIn("not found", omitted["nope.png"])
        # The omissions are visible in place, not silent.
        self.assertIn("image omitted from slice export", doc)

    def test_image_over_cap_is_omitted_with_reason(self):
        _doc, m = self.build({"mode": "tag", "tag": "fixture"},
                             max_bytes=8)
        reasons = {a["src"]: a["reason"]
                   for a in m["assets"]["omitted"]}
        self.assertIn("over the inline cap", reasons["dot.png"])
        self.assertEqual(m["assets"]["inlined"], [])

    # ------------------------------------------------ guarantees

    def test_embedded_manifest_json_parses(self):
        doc, m = self.build({"mode": "tag", "tag": "fixture"})
        raw = re.search(
            r'<script type="application/json" id="slice-manifest">'
            r"(.*?)</script>", doc, re.S).group(1)
        parsed = __import__("json").loads(raw)
        self.assertEqual(parsed["pages"], m["pages"])
        self.assertEqual(parsed["slice"]["spec"]["tag"], "fixture")

    def test_manifest_state_fields(self):
        _doc, m = self.build({"mode": "all"})
        self.assertIn("commit", m["corpus"])
        if m["corpus"]["commit"] is None:
            self.assertTrue(m["corpus"]["state_note"])

    def test_determinism(self):
        doc1, _m = self.build({"mode": "seed", "seed": "alpha",
                               "hops": 2})
        doc2, _m = self.build({"mode": "seed", "seed": "alpha",
                               "hops": 2})
        self.assertEqual(doc1, doc2)

    def test_corpus_untouched(self):
        before = _tree_digest(self.root)
        out = self.root / "exports-out.html"
        run = subprocess.run(
            [sys.executable, str(TOOL), "--root", str(self.root),
             "--all", "--out", str(out)],
            capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        out.unlink()
        self.assertEqual(_tree_digest(self.root), before)


if __name__ == "__main__":
    unittest.main()
