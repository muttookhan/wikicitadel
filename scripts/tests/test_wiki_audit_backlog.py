#!/usr/bin/env python3
"""Tests for scripts/wiki_audit_backlog.py — backlog +
never-retrieved audit (item 44).

Fixture layer only: a toy tree (manifest, exemptions note, three
pages, a one-probe baseline, a one-line Ask log) through the
audit's classification, aging, never-retrieved set, cross-tab and
Obst numbers. The toy root is not a git repository, so ingest
dates exercise the filename-prefix fallback.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]


def load_audit():
    spec = importlib.util.spec_from_file_location(
        "wiki_audit_backlog", SCRIPTS / "wiki_audit_backlog.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["wiki_audit_backlog"] = module
    spec.loader.exec_module(module)
    return module


audit = load_audit()
AS_OF = date(2030, 10, 20)


def page(title, sources, stage, work_type, body="Body."):
    src = "\n".join(f"  - {s}" for s in sources)
    return (f"---\ntitle: {title}\ntype: source\n"
            f"created: 2030-10-10\nupdated: 2030-10-10\nsources:\n{src}\n"
            f"tags: [test]\nstage: {stage}\nwork_type: {work_type}\n"
            f"---\n\n{body}\n")


def build_toy(root: Path):
    src = root / "raw" / "sources"
    src.mkdir(parents=True)
    (root / "wiki" / "sources").mkdir(parents=True)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "wiki" / "entities").mkdir(parents=True)
    (root / "wiki" / "access").mkdir(parents=True)
    (root / "evaluation").mkdir(parents=True)
    files = {
        "raw/sources/2030-10-01-alpha.md": "alpha",
        "raw/sources/2030-10-02-beta.md": "beta",
        "raw/sources/2030-10-03-gamma.md": "gamma",
        "raw/sources/2030-10-19-delta.md": "delta",
        "raw/sources/exempt-dir/2030-10-05-epsilon.md": "epsilon",
    }
    (src / "exempt-dir").mkdir()
    for rel, text in files.items():
        (root / rel).write_text(text, encoding="utf-8")
    # on disk but NOT in the manifest
    (src / "2030-10-06-zeta.md").write_text("zeta", encoding="utf-8")
    files["raw/sources/tools-record.md"] = "note"
    manifest = {"generated_at": "2030-10-20T00:00:00+00:00",
                "files": {rel: {"bytes": 1} for rel in files}}
    (src / "provenance-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8")
    (src / "tools-record.md").write_text(
        "# note\n\n## Coverage exemptions\n\n"
        "- `raw/sources/exempt-dir/` — held deliberately\n",
        encoding="utf-8")
    # The note's ingest date comes from git first-add (the
    # collector's primary aging basis): commit just the note,
    # dated 2030-10-13, so it ages 7 days at the as-of date.
    env = dict(os.environ,
               GIT_AUTHOR_DATE="2030-10-13T12:00:00+00:00",
               GIT_COMMITTER_DATE="2030-10-13T12:00:00+00:00")

    def git(*args):
        subprocess.run(["git", "-C", str(root), *args],
                       check=True, env=env, capture_output=True)
    git("init", "-q")
    git("-c", "user.email=fixture@example.com", "-c",
        "user.name=Fixture", "add", "raw/sources/tools-record.md")
    git("-c", "user.email=fixture@example.com", "-c",
        "user.name=Fixture", "commit", "-q", "-m", "note")
    (root / "wiki/sources/page-beta.md").write_text(
        page("Beta", ["raw/sources/2030-10-02-beta.md"],
             "budding", "record"), encoding="utf-8")
    (root / "wiki/entities/page-retrieved.md").write_text(
        page("Retrieved", ["raw/sources/2030-10-01-alpha.md"],
             "evergreen", "synthesis"), encoding="utf-8")
    (root / "wiki/concepts/page-gamma.md").write_text(
        page("Gamma", [], "seedling", "synthesis",
             body="Compiled from raw/sources/2030-10-03-gamma.md "
                  "in prose only."), encoding="utf-8")
    baseline = {"per_query": {"Q1": {
        "result_count": 42, "question": "q",
        "top10": ["wiki/entities/page-retrieved.md",
                  "wiki/sources/page-beta.md"]}}}
    (root / "evaluation/retrieval-baseline.json").write_text(
        json.dumps(baseline), encoding="utf-8")
    (root / "wiki/access/qa-2030.jsonl").write_text(
        json.dumps({"id": "q1", "question": "?", "status": "answered",
                    "citations": ["page-beta"]}) + "\n",
        encoding="utf-8")
    return root


class BacklogFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = build_toy(Path(cls._tmp.name))
        cls.a = audit.run_audit(cls.root, AS_OF)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_obst_numbers(self):
        self.assertEqual(self.a["obst"],
                         {"captured": 6, "compiled": 3, "retrieved": 2})

    def test_backlog_classification(self):
        by_path = {e["path"]: e for e in self.a["backlog"]}
        self.assertEqual(len(by_path), 4)
        note = by_path["raw/sources/tools-record.md"]
        self.assertEqual(note["class"], "uncited")
        self.assertEqual(
            by_path["raw/sources/2030-10-03-gamma.md"]["class"],
            "cited-but-not-compiled")
        self.assertEqual(
            by_path["raw/sources/2030-10-19-delta.md"]["class"],
            "uncited")
        eps = by_path["raw/sources/exempt-dir/2030-10-05-epsilon.md"]
        self.assertEqual(eps["class"], "uncited")
        self.assertEqual(eps["exemption"], "raw/sources/exempt-dir/")
        self.assertEqual(self.a["backlog_exempted"], 1)
        self.assertEqual(self.a["cited_count"], 2)

    def test_aging_from_filename_prefix(self):
        by_path = {e["path"]: e for e in self.a["backlog"]}
        gamma = by_path["raw/sources/2030-10-03-gamma.md"]
        self.assertEqual(gamma["ingest_basis"], "filename prefix")
        self.assertEqual(gamma["age_days"], 17)
        self.assertEqual(self.a["age_buckets"].get("8+ days"), 2)
        self.assertEqual(self.a["age_buckets"].get("4–7 days"), 1)
        self.assertEqual(self.a["age_buckets"].get("1–3 days"), 1)

    def test_unmanifested_listed_separately(self):
        self.assertEqual(self.a["unmanifested"],
                         ["raw/sources/2030-10-06-zeta.md"])

    def test_never_retrieved(self):
        never = [e["path"] for e in self.a["never"]]
        self.assertEqual(never, ["wiki/concepts/page-gamma.md"])
        self.assertEqual(self.a["never"][0]["stage"], "seedling")
        self.assertEqual(self.a["stage_counts"], {"seedling": 1})
        self.assertEqual(self.a["worktype_counts"], {"synthesis": 1})
        self.assertEqual(self.a["probes"], 1)
        self.assertEqual(self.a["qa_count"], 1)

    def test_render_states_the_caveat(self):
        flat = " ".join(audit.render(self.a, AS_OF).split())
        self.assertIn("no retrieval on the available records", flat)
        # the only "never used" in the filing is inside the caveat
        # that disclaims it
        self.assertEqual(flat.count("never used"), 1)
        self.assertIn("it does not say the page was never used", flat)
        self.assertIn("preserved ≠ known", flat)


if __name__ == "__main__":
    unittest.main()
