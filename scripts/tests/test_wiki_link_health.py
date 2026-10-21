#!/usr/bin/env python3
"""Tests for scripts/wiki_link_health.py — per-page link
health (broken wikilinks, missing targets, orphan status)
+ the Lens-inspector data file (Marathon Round 3, Tier A:
Quartz / LeafWiki link-health in the Lens inspector).

Fixture-based: a tiny wiki in a temp dir with a known link
graph — a healthy linked pair, a page with a broken target,
a true orphan, a page linked only from wiki/index.md (NOT
an orphan: structural pages count as linkers), a link inside
a fenced code block (never counted), a [[raw/...]] link to a
file on disk (resolved-non-page, not broken), and filing /
talk pages (out of scope as subjects).

Pins: the per-page records, the summary counts, title-based
resolution, --strict exit behaviour, and that `emit` writes
exactly the report's records keyed by page path.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

ALPHA = """---
title: Alpha
type: entity
---

# Alpha

Alpha links to [[beta]] and to [[Beta]] by title, and cites
[[raw/sources/note.md]] on disk.
"""

BETA = """---
title: Beta
type: entity
---

# Beta

Beta links back to [[alpha]].
"""

BROKEN = """---
title: Broken
type: entity
---

# Broken

This page links to [[no-such-page]] and to [[alpha]].

```
[[also-not-a-link]]
```
"""

ORPHAN = """---
title: Orphan
type: entity
---

# Orphan

Nothing links here and this page links nowhere.
"""

INDEX_ONLY = """---
title: IndexOnly
type: entity
---

# IndexOnly

Linked only from the index.
"""

INDEX = """# Index

- [[index-only]] — the index-only page
- [[alpha]]
"""


class LinkHealthFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "scripts").mkdir(parents=True)
        shutil.copy(SCRIPTS / "wiki_link_health.py",
                    self.root / "scripts" / "wiki_link_health.py")
        self.tool = self.root / "scripts" / "wiki_link_health.py"
        ent = self.root / "wiki" / "entities"
        ent.mkdir(parents=True)
        (ent / "alpha.md").write_text(ALPHA, encoding="utf-8")
        (ent / "beta.md").write_text(BETA, encoding="utf-8")
        (ent / "broken.md").write_text(BROKEN, encoding="utf-8")
        (ent / "orphan.md").write_text(ORPHAN, encoding="utf-8")
        (ent / "index-only.md").write_text(INDEX_ONLY,
                                           encoding="utf-8")
        (self.root / "wiki" / "index.md").write_text(
            INDEX, encoding="utf-8")
        (self.root / "wiki" / "log.md").write_text(
            "# Log\n", encoding="utf-8")
        src = self.root / "raw" / "sources"
        src.mkdir(parents=True)
        (src / "note.md").write_text("note\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        return subprocess.run(
            [sys.executable, str(self.tool), *argv],
            capture_output=True, text=True)

    def report(self):
        proc = self.run_cli("report", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        return {r["page"]: r for r in data["pages"]}, data["summary"]


class TestLinkHealth(LinkHealthFixture):
    def test_healthy_pair(self):
        pages, _ = self.report()
        a = pages["wiki/entities/alpha.md"]
        self.assertEqual(a["health"], "ok")
        self.assertIn("wiki/entities/beta.md", a["outbound_resolved"])
        self.assertGreaterEqual(a["inbound_count"], 2)  # beta + index
        b = pages["wiki/entities/beta.md"]
        self.assertEqual(b["health"], "ok")
        self.assertFalse(b["orphan"])

    def test_raw_link_is_nonpage_not_broken(self):
        pages, _ = self.report()
        a = pages["wiki/entities/alpha.md"]
        self.assertEqual(a["outbound_nonpage"], ["raw/sources/note.md"])
        self.assertEqual(a["broken_targets"], [])

    def test_broken_target_named_code_link_ignored(self):
        pages, summary = self.report()
        br = pages["wiki/entities/broken.md"]
        self.assertEqual(br["broken_targets"], ["no-such-page"])
        self.assertEqual(br["health"], "broken-links")
        self.assertEqual(summary["broken_links_total"], 1)

    def test_orphan_and_index_only(self):
        pages, summary = self.report()
        self.assertTrue(pages["wiki/entities/orphan.md"]["orphan"])
        self.assertEqual(pages["wiki/entities/orphan.md"]["health"],
                         "orphan")
        io = pages["wiki/entities/index-only.md"]
        self.assertFalse(io["orphan"])  # the index links it
        self.assertGreaterEqual(io["inbound_count"], 1)
        self.assertEqual(summary["orphans"], 1)
        self.assertEqual(summary["pages"], 5)

    def test_strict_exit(self):
        proc = self.run_cli("report", "--strict")
        self.assertEqual(proc.returncode, 1)
        proc = self.run_cli("report")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_emit_matches_report(self):
        pages, summary = self.report()
        out = self.root / "lens-data"
        proc = self.run_cli("emit", "--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(
            (out / "link-health.json").read_text(encoding="utf-8"))
        self.assertTrue(payload["inspector_data"])
        self.assertEqual(payload["summary"], summary)
        self.assertEqual(
            payload["pages"]["wiki/entities/broken.md"]["broken_targets"],
            ["no-such-page"])
        self.assertEqual(set(payload["pages"]), set(pages))


if __name__ == "__main__":
    unittest.main()
