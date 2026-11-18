#!/usr/bin/env python3
"""Tests for scripts/wiki_ghostcite.py — fabricated-citation
detection at ingest (report-only) + revision-pair
citation-change events.

The discrimination that matters:
  * a citation the citation lockfile verifies is NEVER flagged
    (the corpus is ground truth — even when a page quotation
    beside it has been tampered with, vouching wins);
  * a citation invented at ingest IS flagged by kind: source
    that does not exist, locator outside the file, quote that
    is not in the cited range, range over blank lines, path
    escaping the repo, marker with no parseable locator;
  * honest new citations (unlocked, but real) pass clean;
  * revision pairs produce the deterministic event kinds
    (added / removed / moved / retargeted / content-changed)
    with source lineage, and identical revisions produce none.

Fixture pattern follows test_wiki_cite_lock.py: the real
scripts copied into a temp tree so ROOT resolves to the
fixture, CLI driven by subprocess.

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

SOURCE_LINES = [
    "Fixture source title",
    "alpha bravo charlie",
    "delta echo foxtrot",
    "golf hotel india",
    "juliet kilo lima",
    'The engineer said "the server hums quietly" during rounds.',
    "",
    "",
]

FRONTMATTER = """---
title: {title}
type: source
created: 2026-10-22
updated: 2026-10-22
sources:
  - raw/sources/fixture-source.md
tags: [fixture]
---

"""

GOOD_PAGE = FRONTMATTER.format(title="Good page") + """Alpha claim sentence.^[cite: raw/sources/fixture-source.md#L2-L3]

The report said "the server hums quietly" in the log.^[cite: raw/sources/fixture-source.md#L6]
"""


def page(title, body):
    return FRONTMATTER.format(title=title) + body


class GhostCiteFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "scripts").mkdir()
        for name in ("wiki_ghostcite.py", "wiki_cite_lock.py",
                     "wiki_observe.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, self.tmp / "scripts" / name)
        (self.tmp / "wiki" / "sources").mkdir(parents=True)
        (self.tmp / "raw" / "sources").mkdir(parents=True)
        (self.tmp / "evaluation").mkdir()
        self.source = self.tmp / "raw" / "sources" / "fixture-source.md"
        self.source.write_text("\n".join(SOURCE_LINES) + "\n",
                               encoding="utf-8")
        self.good_page = self.tmp / "wiki" / "sources" / "good.md"
        self.good_page.write_text(GOOD_PAGE, encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, script, *argv):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / script),
             *argv], capture_output=True, text=True)

    def lock(self):
        proc = self.run_cli("wiki_cite_lock.py", "build")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def add_page(self, name, body):
        path = self.tmp / "wiki" / "sources" / name
        path.write_text(body, encoding="utf-8")
        return path

    def scan(self):
        out = self.tmp / "evaluation" / "ghostcite-report.json"
        proc = self.run_cli("wiki_ghostcite.py", "scan",
                            "--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return json.loads(out.read_text(encoding="utf-8"))

    @staticmethod
    def flag_kinds(report):
        return [(f["page"], k["kind"]) for f in report["flags"]
                for k in f["kinds"]]


class TestDetection(GhostCiteFixture):

    def test_locked_and_clean_citations_pass(self):
        self.lock()
        report = self.scan()
        cov = report["coverage"]
        self.assertEqual(cov["lockfile_verified"], 2)
        self.assertEqual(cov["flagged"], 0)
        self.assertEqual(report["flags"], [])
        self.assertEqual(report["malformed_markers"], [])

    def test_honest_unlocked_citation_is_clean(self):
        self.lock()
        self.add_page("new.md", page(
            "New page",
            "A fresh claim.^[cite: raw/sources/fixture-source.md#L4]\n"))
        report = self.scan()
        self.assertEqual(report["coverage"]["clean"], 1)
        self.assertEqual(report["flags"], [])

    def test_fabricated_source_flagged(self):
        self.lock()
        self.add_page("bad.md", page(
            "Bad page",
            "Invented.^[cite: raw/sources/no-such-file.md#L1-L2]\n"))
        report = self.scan()
        kinds = self.flag_kinds(report)
        self.assertIn(("wiki/sources/bad.md", "source-missing"), kinds)
        # The locked citations are untouched by the flag list.
        self.assertFalse(any(p.endswith("good.md")
                             for p, _k in kinds))
        rec = report["flags"][0]
        self.assertFalse(rec["lineage"]["exists"])

    def test_out_of_range_locator_flagged(self):
        self.lock()
        self.add_page("bad.md", page(
            "Bad page",
            "Too far.^[cite: raw/sources/fixture-source.md#L90-L99]\n"
            "\n"
            "Backwards.^[cite: raw/sources/fixture-source.md#L5-L3]\n"))
        report = self.scan()
        kinds = [k for p, k in self.flag_kinds(report)
                 if p.endswith("bad.md")]
        self.assertEqual(kinds.count("locator-out-of-range"), 2)

    def test_escaping_locator_flagged(self):
        self.lock()
        self.add_page("bad.md", page(
            "Bad page",
            "Escape.^[cite: ../outside.md#L1]\n"))
        report = self.scan()
        self.assertIn(("wiki/sources/bad.md", "locator-escapes-repo"),
                      self.flag_kinds(report))

    def test_fabricated_quote_flagged_true_quote_clean(self):
        self.lock()
        self.add_page("bad.md", page(
            "Bad page",
            'The report said "the server sings loudly" in the'
            " log.^[cite: raw/sources/fixture-source.md#L6]\n"))
        self.add_page("ok.md", page(
            "Ok page",
            'The report said "the server hums quietly" in the'
            " log.^[cite: raw/sources/fixture-source.md#L6]\n"))
        report = self.scan()
        kinds = self.flag_kinds(report)
        self.assertIn(("wiki/sources/bad.md", "quote-not-in-range"),
                      kinds)
        self.assertFalse(any(p.endswith("ok.md") for p, _k in kinds))
        self.assertEqual(report["coverage"]["quotes_diverged"], 1)

    def test_locked_verified_never_flagged(self):
        """The quality bar: tamper with the page's quotation
        after locking — the marker key is unchanged and the
        lockfile entry still verifies, so the detector must
        stay silent on it."""
        self.lock()
        self.good_page.write_text(
            GOOD_PAGE.replace("the server hums quietly",
                              "the server sings loudly"),
            encoding="utf-8")
        report = self.scan()
        self.assertEqual(report["flags"], [])
        self.assertEqual(report["coverage"]["lockfile_verified"], 2)

    def test_vacuous_range_flagged(self):
        self.lock()
        self.add_page("bad.md", page(
            "Bad page",
            "Nothing here.^[cite: raw/sources/fixture-source.md#L7-L8]\n"))
        report = self.scan()
        self.assertIn(("wiki/sources/bad.md", "vacuous-range"),
                      self.flag_kinds(report))

    def test_malformed_markers_flagged_fences_ignored(self):
        self.lock()
        self.add_page("bad.md", page(
            "Bad page",
            "No locator.^[cite: raw/sources/fixture-source.md]\n"
            "\n"
            "Empty.^[cite:]\n"
            "\n"
            "```\n"
            "Syntax example: ^[cite: raw/sources/nowhere.md]\n"
            "```\n"))
        report = self.scan()
        raws = [m["raw"] for m in report["malformed_markers"]
                if m["page"].endswith("bad.md")]
        self.assertEqual(len(raws), 2)
        self.assertIn("^[cite:]", raws)

    def test_scan_requires_lockfile_baseline(self):
        proc = self.run_cli("wiki_ghostcite.py", "scan", "--no-write")
        self.assertEqual(proc.returncode, 2)
        proc = self.run_cli("wiki_ghostcite.py", "scan", "--no-write",
                            "--no-lockfile-ok")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_ingest_check_scoped_with_sidecar_lineage(self):
        self.lock()
        # A second source with its own bad citation: out of
        # scope for an ingest-check over fixture-source.
        other = self.tmp / "raw" / "sources" / "other.md"
        other.write_text("only line\n", encoding="utf-8")
        self.add_page("bad.md", page(
            "Bad page",
            "Too far.^[cite: raw/sources/fixture-source.md#L90]\n"
            "\n"
            "Other.^[cite: raw/sources/other.md#L9]\n"))
        sidecar = Path(str(self.source) + ".ingest.json")
        sidecar.write_text(json.dumps({
            "source": "fixture-source.docx",
            "sha256": "ab" * 32,
            "converter": {"tool": "wiki_convert.py",
                          "script_sha256": "cd" * 32,
                          "sanitizer_sha256": None,
                          "format": "docx"},
            "extraction": {"state": "native-text"},
        }), encoding="utf-8")
        out = self.tmp / "evaluation" / "ingest-report.json"
        proc = self.run_cli("wiki_ghostcite.py", "ingest-check",
                            "--source",
                            "raw/sources/fixture-source.md",
                            "--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        report = json.loads(out.read_text(encoding="utf-8"))
        # Examined = every citation over this source in the
        # corpus (the good page's two, vouched for by the
        # lockfile + manifest, plus the bad page's one); the
        # other source's citation is out of scope.
        self.assertEqual(report["coverage"]["examined"], 3)
        self.assertEqual(report["coverage"]["lockfile_verified"], 2)
        self.assertEqual(report["coverage"]["flagged"], 1)
        self.assertIn(("wiki/sources/bad.md", "locator-out-of-range"),
                      self.flag_kinds(report))
        lineage = report["source_lineage"]
        self.assertEqual(lineage["converter"]["kind"], "wiki_convert")
        self.assertEqual(lineage["extraction"],
                         {"state": "native-text"})
        self.assertTrue(lineage["sha256"])


# -- Revision-pair events -------------------------------------------------------

EV_PAGE = """Claim one rests here.^[cite: raw/sources/s.md#L2-L3]

Claim two rests here.^[cite: raw/sources/s.md#L6]

Claim three rests here.^[cite: raw/sources/s.md#L4]
"""

EV_SOURCE_BASE = ["title", "alpha bravo", "delta echo",
                  "golf hotel", "juliet kilo",
                  "the final line"]


def make_tree(root, source_lines, page_text):
    (root / "wiki" / "sources").mkdir(parents=True)
    (root / "raw" / "sources").mkdir(parents=True)
    (root / "raw" / "sources" / "s.md").write_text(
        "\n".join(source_lines) + "\n", encoding="utf-8")
    (root / "wiki" / "sources" / "p.md").write_text(
        page_text, encoding="utf-8")


class TestEvents(GhostCiteFixture):

    def events(self, base_root, head_root):
        out = self.tmp / "events.jsonl"
        proc = self.run_cli("wiki_ghostcite.py", "events",
                            "--base-root", str(base_root),
                            "--head-root", str(head_root),
                            "--out", str(out))
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        text = out.read_text(encoding="utf-8").strip()
        return [json.loads(ln) for ln in text.splitlines()] if text \
            else []

    def test_identical_revisions_no_events(self):
        base = self.tmp / "base"
        make_tree(base, EV_SOURCE_BASE, EV_PAGE)
        self.assertEqual(self.events(base, base), [])

    def test_moved_removed_changed_added(self):
        base = self.tmp / "base"
        head = self.tmp / "head"
        make_tree(base, EV_SOURCE_BASE, EV_PAGE)
        # Head: a line inserted at the top moves claim one's
        # block (L2-L3 content now at L3-L4) and claim two's;
        # claim two is dropped from the page; claim three's
        # range is rewritten to follow its line (now L5) whose
        # text was ALSO edited -> retarget-free content change
        # is exercised separately below; here claim three is
        # left citing L4, whose content changed ('golf hotel'
        # shifted out, 'delta echo' shifted in).
        head_source = ["inserted"] + EV_SOURCE_BASE
        head_page = (
            "Claim one rests here.^[cite: raw/sources/s.md#L3-L4]\n"
            "\n"
            "Claim three rests here.^[cite: raw/sources/s.md#L4]\n"
            "\n"
            "Claim four rests here.^[cite: raw/sources/s.md#L1]\n")
        make_tree(head, head_source, head_page)
        events = self.events(base, head)
        kinds = sorted(e["event"] for e in events)
        self.assertEqual(kinds, ["citation-added",
                                 "citation-content-changed",
                                 "citation-moved",
                                 "citation-removed"])
        moved = next(e for e in events
                     if e["event"] == "citation-moved")
        self.assertEqual(moved["base"]["range"], [2, 3])
        self.assertEqual(moved["head"]["range"], [3, 4])
        self.assertFalse(moved["content_changed"])
        changed = next(e for e in events
                       if e["event"] == "citation-content-changed")
        self.assertNotEqual(changed["lineage"]["base"]["sha256"],
                            changed["lineage"]["head"]["sha256"])
        self.assertEqual(changed["lineage"]["base"]["lines"], 6)
        self.assertEqual(changed["lineage"]["head"]["lines"], 7)

    def test_content_changed_same_locator(self):
        base = self.tmp / "base"
        head = self.tmp / "head"
        make_tree(base, EV_SOURCE_BASE, EV_PAGE)
        edited = list(EV_SOURCE_BASE)
        edited[3] = "golf hotel REWRITTEN"
        make_tree(head, edited, EV_PAGE)
        events = self.events(base, head)
        self.assertEqual([e["event"] for e in events],
                         ["citation-content-changed"])
        ev = events[0]
        self.assertEqual(ev["base"]["range"], [4, 4])
        self.assertNotEqual(ev["base"]["block_hash"],
                            ev["head"]["block_hash"])
        self.assertNotEqual(ev["lineage"]["base"]["sha256"],
                            ev["lineage"]["head"]["sha256"])

    def test_retargeted(self):
        base = self.tmp / "base"
        head = self.tmp / "head"
        make_tree(base, EV_SOURCE_BASE, EV_PAGE)
        head_page = EV_PAGE.replace("raw/sources/s.md#L2-L3",
                                    "raw/sources/t.md#L2-L3")
        make_tree(head, EV_SOURCE_BASE, head_page)
        (head / "raw" / "sources" / "t.md").write_text(
            "\n".join(EV_SOURCE_BASE) + "\n", encoding="utf-8")
        events = self.events(base, head)
        self.assertEqual([e["event"] for e in events],
                         ["citation-retargeted"])
        self.assertEqual(events[0]["head"]["source"],
                         "raw/sources/t.md")
        self.assertIn("lineage_old_source", events[0])

    def test_events_git_mode(self):
        repo = self.tmp / "repo"
        make_tree(repo, EV_SOURCE_BASE, EV_PAGE)

        def git(*argv):
            return subprocess.run(
                ["git", "-C", str(repo),
                 "-c", "user.name=Fixture", "-c",
                 "user.email=fixture@example.com", *argv],
                capture_output=True, text=True)

        if git("init", "-q").returncode != 0:
            self.skipTest("git unavailable")
        self.assertEqual(git("add", "wiki", "raw").returncode, 0)
        self.assertEqual(git("commit", "-qm", "base").returncode, 0)
        edited = list(EV_SOURCE_BASE)
        edited[1] = "alpha bravo EDITED"
        (repo / "raw" / "sources" / "s.md").write_text(
            "\n".join(edited) + "\n", encoding="utf-8")
        self.assertEqual(git("add", "raw").returncode, 0)
        self.assertEqual(git("commit", "-qm", "edit").returncode, 0)
        # The CLI's git mode works in the script's own tree;
        # the fixture root is the repo here, so point the CLI
        # at it by running the copied script from this root and
        # giving it a shim root: use --base/--head with the
        # fixture scripts (their ROOT is this fixture tmp, not
        # the repo) — so instead run the module in-process with
        # ROOT patched to the repo.
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fixture_ghostcite",
            self.tmp / "scripts" / "wiki_ghostcite.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = repo
        base = module.snapshot_from_git("HEAD~1")
        head = module.snapshot_from_git("HEAD")
        events = module.diff_snapshots(base, head, "HEAD~1", "HEAD")
        self.assertEqual([e["event"] for e in events],
                         ["citation-content-changed"])


if __name__ == "__main__":
    unittest.main()
