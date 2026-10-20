#!/usr/bin/env python3
"""Tests for scripts/wiki_rot.py — the rot census
(consolidated queue item 21, 2030-10-20).

One fixture per rot class, each asserted from its named
observable signal only, plus the control: a healthy page
carries NO class. The census's honesty rule is that a class
is asserted from a signal, never from a vibe — so each
fixture page is built to trip exactly its own signal and
no other.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
TODAY = date(2030, 10, 20)


def load_rot_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_rot_under_test", SCRIPTS / "wiki_rot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wr = load_rot_module()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _page(title, body, extra_fm="", sources=("raw/sources/real.md",)):
    src = "\n".join(f"  - {s}" for s in sources)
    return (f"---\ntitle: {title}\ntype: source\n"
            "created: 2030-10-01\nupdated: 2030-10-01\n"
            f"sources:\n{src}\ntags: [fixture]\n{extra_fm}---\n\n"
            f"# {title}\n\n{body}\n")


def build_fixture(root):
    """A miniature wiki with one page per rot class, one
    healthy control, a hub linking the class pages (so only
    the orphan is link-isolated), and the raw source most
    pages cite."""
    _write(root / "raw" / "sources" / "real.md", "a real source\n")
    w = root / "wiki"
    hub_links = ("[[expired-page]] [[ghost-page]] [[fork-one]]"
                 " [[fork-two]] [[control-page]] [[hub]]")
    _write(w / "sources" / "hub.md",
           _page("Hub", f"Links: {hub_links}"))
    # expired: its own horizon field has passed.
    _write(w / "sources" / "expired-page.md",
           _page("Expired Page", "See [[hub]].",
                 extra_fm="verified_until: 2030-01-01\n"))
    # ghost: cites a source that is not on disk.
    _write(w / "sources" / "ghost-page.md",
           _page("Ghost Page", "See [[hub]].",
                 sources=("raw/sources/gone.md",)))
    # fork: two live pages, one title, one claim.
    _write(w / "sources" / "fork-one.md",
           _page("Forked Title", "See [[hub]].",
                 extra_fm='claim: "The same settled claim."\n'))
    _write(w / "sources" / "fork-two.md",
           _page("Forked Title", "See [[hub]].",
                 extra_fm='claim: "The same settled claim."\n'))
    # orphan: no links in, no links out (and not in the hub).
    _write(w / "queries" / "orphan-page.md",
           _page("Orphan Page", "No links at all.",
                 sources=()))
    # control: linked both ways, source on disk, no horizon.
    _write(w / "sources" / "control-page.md",
           _page("Control Page", "See [[hub]]."))
    return root


class RotCensusFixtureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = build_fixture(Path(self._tmp.name))
        self.rep = wr.census(self.root, today=TODAY)

    def tearDown(self):
        self._tmp.cleanup()

    def classes(self, rel):
        return self.rep["pages"].get(rel, {})

    def test_expired_from_its_own_horizon(self):
        c = self.classes("wiki/sources/expired-page.md")
        self.assertIn("expired", c)
        self.assertIn("verified_until", c["expired"][0])
        self.assertNotIn("ghost", c)
        self.assertNotIn("orphan", c)

    def test_ghost_from_missing_cited_source(self):
        c = self.classes("wiki/sources/ghost-page.md")
        self.assertIn("ghost", c)
        self.assertIn("gone.md", c["ghost"][0])
        self.assertNotIn("expired", c)

    def test_fork_from_shared_title_and_claim(self):
        for rel in ("wiki/sources/fork-one.md",
                    "wiki/sources/fork-two.md"):
            c = self.classes(rel)
            self.assertIn("fork", c)
            joined = " ".join(c["fork"])
            self.assertIn("title", joined)
            self.assertIn("claim", joined)

    def test_orphan_island(self):
        c = self.classes("wiki/queries/orphan-page.md")
        self.assertIn("orphan", c)
        self.assertEqual(set(c), {"orphan"})

    def test_control_and_hub_carry_no_signal(self):
        self.assertNotIn("wiki/sources/control-page.md",
                         self.rep["pages"])
        self.assertNotIn("wiki/sources/hub.md", self.rep["pages"])

    def test_counts(self):
        self.assertEqual(self.rep["counts"],
                         {"expired": 1, "ghost": 1, "fork": 2,
                          "orphan": 1})
        self.assertEqual(self.rep["layer_pages"], 7)
        self.assertEqual(self.rep["no_rot_signal"], 2)

    def test_future_horizon_is_not_expired(self):
        _write(self.root / "wiki" / "sources" / "fresh-page.md",
               _page("Fresh Page", "See [[hub]].",
                     extra_fm="verified_until: 2031-01-20\n"))
        rep = wr.census(self.root, today=TODAY)
        self.assertNotIn("expired",
                         rep["pages"].get(
                             "wiki/sources/fresh-page.md", {}))

    def test_retired_twin_breaks_the_fork(self):
        # A superseded twin is a settled succession, not a
        # fork: rewrite fork-two as retired and re-run.
        _write(self.root / "wiki" / "sources" / "fork-two.md",
               _page("Forked Title", "See [[hub]].",
                     extra_fm='claim: "The same settled claim."\n'
                              "status: superseded\n"))
        rep = wr.census(self.root, today=TODAY)
        self.assertNotIn("fork", rep["pages"].get(
            "wiki/sources/fork-one.md", {}))
        self.assertNotIn("fork", rep["pages"].get(
            "wiki/sources/fork-two.md", {}))

    def test_bare_slug_source_resolves_by_token_set(self):
        # A bare slug whose tokens match a raw/sources file
        # (date-last naming) is on disk for census purposes.
        _write(self.root / "raw" / "sources" / "2030-01-01-slug-source.md",
               "x\n")
        _write(self.root / "wiki" / "sources" / "slug-page.md",
               _page("Slug Page", "See [[hub]].",
                     sources=("slug-source-2030-01-01",)))
        rep = wr.census(self.root, today=TODAY)
        self.assertNotIn("ghost", rep["pages"].get(
            "wiki/sources/slug-page.md", {}))


if __name__ == "__main__":
    unittest.main()
