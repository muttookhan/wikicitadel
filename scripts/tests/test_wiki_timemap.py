#!/usr/bin/env python3
"""Memento TimeMap over page history (Round-7 research
candidates; built 2026-10-22): scripts/wiki_timemap.py.

Pins (against the live repo's own history — read-only;
history only grows, so assertions are structural, never
counts):
  - a long-lived page has mementos, newest first, each
    carrying a commit, a UTC datetime, an HTTP-date and a
    git-show retrieval route naming that commit + page;
  - the link-format serialisation carries the original,
    timegate and memento relations (RFC 7089 shape);
  - the timegate answers the newest memento at or before
    the requested time, and a named no-memento answer for
    a time before the page existed;
  - an uncommitted path has no mementos (empty history,
    not an error in the library function).
"""
import importlib.util
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tm = _load("wiki_timemap_under_test", "wiki_timemap.py")
PAGE = "wiki/log.md"


class TimeMapTests(unittest.TestCase):

    def test_mementos_newest_first_and_shaped(self):
        m = tm.timemap(PAGE)
        self.assertEqual(m["original"], PAGE)
        self.assertGreaterEqual(len(m["mementos"]), 2)
        dts = [x["datetime"] for x in m["mementos"]]
        self.assertEqual(dts, sorted(dts, reverse=True))
        for x in m["mementos"]:
            self.assertEqual(len(x["commit"]), 40)
            self.assertTrue(x["http_date"].endswith("GMT"))
            self.assertEqual(
                x["retrieve"],
                f"git show {x['commit']}:{PAGE}")

    def test_link_format_relations(self):
        text = tm.render_link(PAGE)
        self.assertIn('rel="original"', text)
        self.assertIn('rel="timegate"', text)
        self.assertIn('rel="memento"', text)
        self.assertIn('datetime="', text)

    def test_timegate(self):
        future = datetime(2999, 1, 1, tzinfo=timezone.utc)
        ans = tm.at(PAGE, future)
        self.assertIsNotNone(ans["memento"])
        newest = tm.timemap(PAGE)["mementos"][0]
        self.assertEqual(ans["memento"], newest["commit"])
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        ans = tm.at(PAGE, past)
        self.assertIsNone(ans["memento"])
        self.assertIn("did not yet exist", ans["note"])

    def test_uncommitted_path_has_no_mementos(self):
        self.assertEqual(
            tm.page_history("wiki/no-such-page-zzz.md"), [])


if __name__ == "__main__":
    unittest.main()
