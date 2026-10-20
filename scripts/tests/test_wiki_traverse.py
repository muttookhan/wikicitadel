#!/usr/bin/env python3
"""Tests for scripts/wiki_traverse.py (consolidated-queue
item 66: the read-only traversal door for agents).

Pins, on a FIXTURE repo in a temp dir:

  - page reads resolve by stem and by title;
  - neighbours walk the Lens's typed edges: a wikilink under
    an Evidence heading is `grounds`, under Disagreements is
    `contradicts`, and frontmatter declarations (`links:`,
    relation-vocabulary fields) are typed edges too;
  - path finds the directed route and labels each step;
  - census counts relations and kinds;
  - claim lists claim pages with their lifecycle status;
  - cite returns the lockfile's verbatim passage, and
    WITHHOLDS the passage (not the citation) when the cited
    source's sensitivity class bars the identity;
  - the sensitivity gate: a filings-seat identity is refused
    a credential-adjacent raw (exit 1) and a personal raw,
    the owner reads both, and an unclassified raw is served
    stamped UNCLASSIFIED, never silently as public;
  - an unadmitted identity is refused everything;
  - search delegates and a filings-seat identity's scope is
    restricted to the compiled layer, with the note printed;
  - THE NO-WRITE PROOF: sha256 of every content file in the
    fixture tree is identical before and after a battery of
    every command (interpreter bytecode caches excluded —
    they are artefacts of running Python at all, not of this
    tool); the command surface holds no mutating verb; and
    the tool's source names no write API.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
TOOL = "wiki_traverse.py"

ALPHA = """---
title: Alpha
type: entity
claim: "Alpha is the first fixture page."
sources:
  - raw/sources/open-note.md
---

# Alpha

## Evidence

The case rests on [[beta]].

## Disagreements

See [[gamma]] for the other side.
"""

BETA = """---
title: Beta
type: entity
links:
  extends:
    - wiki/entities/alpha.md
supersedes:
  - wiki/entities/gamma.md
---

# Beta

Beta body text about traversal graphs.
"""

GAMMA = """---
title: Gamma
type: entity
---

# Gamma

Gamma links back to [[alpha]].
"""

SENSITIVITY = {
    "classes": [{"id": c} for c in
                ("public", "internal", "personal",
                 "family-sensitive", "export-only",
                 "credential-adjacent")],
    "assignments": [
        {"path": "raw/sources/open-note.md", "class": "internal"},
        {"path": "raw/sources/secret-note.md",
         "class": "credential-adjacent"},
        {"path": "raw/sources/diary/", "class": "personal"},
    ],
}

LOCKFILE = {
    "tool": "fixture lockfile", "generated": "2030-10-20",
    "citations": [
        {"id": "c9001", "page": "wiki/entities/alpha.md",
         "page_line": 12, "claim": "Alpha rests on the open note.",
         "source": "raw/sources/open-note.md", "range": [1, 1],
         "selector": {"type": "TextQuoteSelector",
                      "exact": "VERBATIM OPEN PASSAGE",
                      "prefix": "", "suffix": ""}},
        {"id": "c9002", "page": "wiki/entities/alpha.md",
         "page_line": 13, "claim": "Alpha cites the key record.",
         "source": "raw/sources/secret-note.md", "range": [1, 1],
         "selector": {"type": "TextQuoteSelector",
                      "exact": "VERBATIM SECRET PASSAGE",
                      "prefix": "", "suffix": ""}},
    ],
}


def tree_checksums(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            out[p.relative_to(root).as_posix()] = \
                hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class TraverseFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="traverse-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self._mk("scripts")
        for name in (TOOL, "wiki_validate.py", "wiki_claims.py",
                     "wiki_search.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        lens = self._mk("tools", "lens")
        shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                    lens / "lenslib.py")
        ent = self._mk("wiki", "entities")
        (ent / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (ent / "beta.md").write_text(BETA, encoding="utf-8")
        (ent / "gamma.md").write_text(GAMMA, encoding="utf-8")
        src = self._mk("raw", "sources")
        (src / "open-note.md").write_text("open note body\n",
                                          encoding="utf-8")
        (src / "secret-note.md").write_text("the key lives here\n",
                                            encoding="utf-8")
        (src / "plain.md").write_text("unclassified body\n",
                                      encoding="utf-8")
        diary = self._mk("raw", "sources", "diary")
        (diary / "entry.md").write_text("personal entry\n",
                                        encoding="utf-8")
        ev = self._mk("evaluation")
        (ev / "sensitivity.json").write_text(
            json.dumps(SENSITIVITY), encoding="utf-8")
        (ev / "citation-lockfile.json").write_text(
            json.dumps(LOCKFILE), encoding="utf-8")
        (ev / "outcomes.jsonl").write_text("", encoding="utf-8")

    def _mk(self, *parts):
        d = self.tmp.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / TOOL),
             *args], capture_output=True, text=True)

    def as_(self, identity, *args):
        return self.run_tool("--as", identity, *args)


class TestReads(TraverseFixture):
    def test_page_by_stem_and_title(self):
        for name in ("alpha", "Alpha", "wiki/entities/alpha.md"):
            r = self.as_("agent", "page", name)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("The case rests on", r.stdout)

    def test_neighbours_typed_edges(self):
        r = self.as_("agent", "neighbours", "alpha", "--dir", "out")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("grounds", r.stdout)
        self.assertIn("contradicts", r.stdout)
        self.assertIn("beta", r.stdout)
        r = self.as_("agent", "neighbours", "beta", "--dir", "out")
        self.assertIn("extends", r.stdout)       # links: field
        self.assertIn("supersedes", r.stdout)    # relation field
        r = self.as_("agent", "neighbours", "alpha", "--dir", "out",
                      "--type", "grounds")
        self.assertIn("beta", r.stdout)
        self.assertNotIn("gamma", r.stdout)

    def test_path_labels_steps(self):
        r = self.as_("agent", "path", "gamma", "beta")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("2 step(s)", r.stdout)
        self.assertIn("grounds", r.stdout)

    def test_census(self):
        r = self.as_("agent", "census", "--json")
        data = json.loads(r.stdout)
        self.assertEqual(data["pages"], 3)
        self.assertGreaterEqual(data["by_relation"]["cites"], 1)
        self.assertGreaterEqual(data["by_relation"]["grounds"], 1)
        self.assertGreaterEqual(data["by_kind"]["typed"], 2)

    def test_claim_lists_with_status(self):
        r = self.as_("agent", "claim")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alpha", r.stdout)
        self.assertIn("candidate", r.stdout)
        self.assertIn("Alpha is the first fixture page.", r.stdout)

    def test_search_delegates_and_restricts_scope(self):
        r = self.as_("galen", "search", "traversal graphs",
                      "--top", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("scope restricted to the compiled layer",
                      r.stdout)
        self.assertIn("beta", r.stdout.lower())
        r = self.as_("owner", "search", "traversal graphs",
                      "--scope", "wiki", "--top", "3")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("scope restricted", r.stdout)


class TestGate(TraverseFixture):
    def test_credential_adjacent_refused_for_filings_seat(self):
        r = self.as_("galen", "source",
                      "raw/sources/secret-note.md")
        self.assertEqual(r.returncode, 1)
        self.assertIn("credential-adjacent", r.stderr)
        self.assertNotIn("the key lives here", r.stdout)

    def test_owner_reads_credential_adjacent(self):
        r = self.as_("owner", "source",
                      "raw/sources/secret-note.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the key lives here", r.stdout)

    def test_personal_refused_for_hugo_read_by_agent(self):
        r = self.as_("hugo", "source", "raw/sources/diary/entry.md")
        self.assertEqual(r.returncode, 1)
        r = self.as_("agent", "source",
                      "raw/sources/diary/entry.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("personal entry", r.stdout)

    def test_unclassified_served_stamped(self):
        r = self.as_("galen", "source", "raw/sources/plain.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("UNCLASSIFIED", r.stdout)
        self.assertIn("unclassified body", r.stdout)

    def test_unadmitted_identity_refused(self):
        r = self.as_("nobody", "census")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not admitted", r.stderr)

    def test_cite_withholds_gated_passage(self):
        r = self.as_("galen", "cite", "alpha")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VERBATIM OPEN PASSAGE", r.stdout)
        self.assertNotIn("VERBATIM SECRET PASSAGE", r.stdout)
        self.assertIn("withheld", r.stdout)
        r = self.as_("owner", "cite", "--id", "c9002")
        self.assertIn("VERBATIM SECRET PASSAGE", r.stdout)


class TestNoWrite(TraverseFixture):
    def test_checksums_survive_every_command(self):
        before = tree_checksums(self.tmp)
        battery = [
            ("agent", "page", "alpha"),
            ("agent", "source", "raw/sources/open-note.md"),
            ("galen", "source", "raw/sources/secret-note.md"),
            ("agent", "neighbours", "alpha"),
            ("agent", "path", "gamma", "beta"),
            ("agent", "census"),
            ("agent", "claim"),
            ("galen", "cite", "alpha"),
            ("owner", "cite", "--id", "c9002"),
            ("galen", "search", "traversal graphs"),
            ("agent", "page", "alpha", "--json"),
            ("agent", "census", "--json"),
        ]
        for ident, *args in battery:
            self.as_(ident, *args)
        self.assertEqual(before, tree_checksums(self.tmp))

    def test_surface_has_no_mutating_verb(self):
        r = self.run_tool("--as", "agent", "frobnicate")
        self.assertEqual(r.returncode, 2)  # argparse: invalid choice
        for verb in ("set", "add", "write", "delete", "remove",
                     "update", "create", "apply", "retire",
                     "stage", "promote", "edit"):
            r = self.run_tool("--as", "agent", verb)
            self.assertEqual(r.returncode, 2, verb)

    def test_source_names_no_write_api(self):
        text = (SCRIPTS / TOOL).read_text(encoding="utf-8")
        for token in ("write_text", "write_bytes", "os.remove",
                      ".unlink(", "import shutil", "os.replace",
                      "os.rename", ".mkdir(", "open(", "'a')",
                      '"a")', "'w')", '"w")'):
            self.assertNotIn(token, text, token)


if __name__ == "__main__":
    unittest.main()
