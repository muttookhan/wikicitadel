#!/usr/bin/env python3
"""Tests for scripts/wiki_okf_export.py — the OKF v0.2 conformance
export (the build). Builds a fixture wiki in a temp dir (the real
scripts copied in, so ROOT resolves to the fixture) and drives the
CLI; mapping and conformance rules are also unit-tested by import.

The discriminations that matter: our status vocabulary mapped into
OKF's (draft|stable|deprecated) with the original preserved when
the mapping changed it; fields OKF lacks (confidence, claim, as_of,
dates) preserved under the llm_wiki: namespace instead of being
dropped or dressed up as OKF trust fields (`verified` is never
fabricated); sources becoming {id, resource} entries; reserved
index.md/log.md following SPEC sections 8/9; and the checker
failing a bundle whose concepts lack `type`, whose sources entries
lack `resource`, or whose status leaves the OKF vocabulary.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

PLAIN_PAGE = """---
title: Plain Fixture Page
type: source
created: 2030-10-12
updated: 2030-10-13
sources:
  - raw/sources/2030-10-12-plain.md
tags: [fixture, plain]
---

# Plain Fixture Page

Body text with no markers.
"""

LIFECYCLE_PAGE = """---
title: "Lifecycle Page: opted in"
type: synthesis
created: 2030-10-13
updated: 2030-10-14
sources: [raw/sources/a.md, raw/sources/deep/b.md]
tags: [fixture]
status: superseded
confidence: observed
claim: "The fixture claim holds."
as_of: 2030-10-14
outcome_status: candidate
---

# Lifecycle Page

A claim rests on one passage.^[cite: raw/sources/a.md#L3-L5]
See also [[plain]] for the base page.
"""

DRAFT_PAGE = """---
title: Draft Page
type: concept
created: 2030-10-15
updated: 2030-10-15
sources: []
tags: []
status: draft
---

# Draft Page
"""

INDEX_MD = """# Index

Catalog of every page in the wiki.

## Overview

- [[overview]] — the living synthesis

## Sources

- [[plain]] — Plain Fixture Page, the base
"""

LOG_MD = """# Log

Append-only record. Newest at the bottom.
Entry format: `## [YYYY-MM-DD] <kind> | <title>`

## [2030-10-12] setup | Wiki created

Created the fixture wiki.

## [2030-10-13] ingest | Plain page

Ingested the plain page.

## [2030-10-13] query | A question

Answered a question.
"""

OVERVIEW_PAGE = """---
title: Overview
type: synthesis
created: 2030-10-12
updated: 2030-10-13
sources: []
tags: [overview]
---

# Overview
"""

ACCESS_PAGE = """---
title: Ledger, not a concept
type: query
created: 2030-10-12
updated: 2030-10-12
sources: []
tags: []
---

# Ledger
"""


def load_module():
    spec = importlib.util.spec_from_file_location(
        "wiki_okf_export", SCRIPTS / "wiki_okf_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FixtureWiki(unittest.TestCase):
    """A temp-dir repo with the real scripts and a small wiki."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="okf-fixture-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in ("wiki_okf_export.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        wiki = self.tmp / "wiki"
        (wiki / "sources").mkdir(parents=True)
        (wiki / "concepts").mkdir(parents=True)
        (wiki / "entities").mkdir(parents=True)
        (wiki / "access").mkdir(parents=True)
        (wiki / "sources" / "plain.md").write_text(
            PLAIN_PAGE, encoding="utf-8")
        (wiki / "concepts" / "lifecycle.md").write_text(
            LIFECYCLE_PAGE, encoding="utf-8")
        (wiki / "entities" / "draft-page.md").write_text(
            DRAFT_PAGE, encoding="utf-8")
        (wiki / "overview.md").write_text(
            OVERVIEW_PAGE, encoding="utf-8")
        (wiki / "index.md").write_text(INDEX_MD, encoding="utf-8")
        (wiki / "log.md").write_text(LOG_MD, encoding="utf-8")
        (wiki / "access" / "ledger.md").write_text(
            ACCESS_PAGE, encoding="utf-8")
        self.bundle = self.tmp / "exports" / "okf-bundle"

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable,
             str(self.tmp / "scripts" / "wiki_okf_export.py"),
             *args],
            capture_output=True, text=True)

    def export(self):
        proc = self.run_cli("export")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc


class TestExport(FixtureWiki):

    def test_export_writes_bundle_and_manifest(self):
        self.export()
        for rel in ("sources/plain.md", "concepts/lifecycle.md",
                    "entities/draft-page.md", "overview.md",
                    "index.md", "log.md", "manifest.json"):
            self.assertTrue((self.bundle / rel).exists(), rel)
        self.assertFalse((self.bundle / "access").exists(),
                         "access/ must be excluded")
        manifest = json.loads(
            (self.bundle / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["okf_version"], "0.2")
        self.assertEqual(manifest["counts"]["concepts"], 4)
        self.assertEqual(manifest["counts"]["reserved_files"], 2)
        by_path = {f["path"]: f for f in manifest["files"]}
        self.assertEqual(by_path["sources/plain.md"]["source"],
                         "wiki/sources/plain.md")
        data = (self.bundle / "sources/plain.md").read_bytes()
        self.assertEqual(by_path["sources/plain.md"]["sha256"],
                         hashlib.sha256(data).hexdigest())
        self.assertEqual(by_path["sources/plain.md"]["bytes"],
                         len(data))

    def test_plain_page_frontmatter_mapping(self):
        self.export()
        text = (self.bundle / "sources" / "plain.md").read_text(
            "utf-8")
        self.assertIn("type: source\n", text)
        self.assertIn("title: Plain Fixture Page\n", text)
        self.assertIn("tags: [fixture, plain]\n", text)
        self.assertIn("  - id: 2030-10-12-plain\n", text)
        self.assertIn(
            "    resource: raw/sources/2030-10-12-plain.md\n", text)
        self.assertIn("llm_wiki:\n", text)
        self.assertIn('  created: "2030-10-12"\n', text)
        self.assertIn('  updated: "2030-10-13"\n', text)
        # No invented OKF fields.
        for absent in ("status:", "description:", "generated:",
                       "verified:", "stale_after:"):
            self.assertNotIn("\n" + absent, "\n" + text)
        # Body verbatim.
        self.assertTrue(text.endswith(
            "# Plain Fixture Page\n\nBody text with no markers.\n"))

    def test_lifecycle_page_mapping(self):
        self.export()
        text = (self.bundle / "concepts" / "lifecycle.md").read_text(
            "utf-8")
        # superseded -> deprecated, original preserved.
        self.assertIn("status: deprecated\n", text)
        self.assertIn("  status: superseded\n", text)
        # Sources: flow list became entries with distinct ids.
        self.assertIn("  - id: a\n", text)
        self.assertIn("    resource: raw/sources/a.md\n", text)
        self.assertIn("  - id: b\n", text)
        self.assertIn("    resource: raw/sources/deep/b.md\n", text)
        # Claim-lifecycle fields namespaced, never OKF trust fields.
        self.assertIn("  confidence: observed\n", text)
        self.assertIn("  claim: The fixture claim holds.\n", text)
        self.assertIn('  as_of: "2030-10-14"\n', text)
        self.assertIn("  outcome_status: candidate\n", text)
        self.assertIn("  inline_citations: 1\n", text)
        self.assertNotIn("verified:", text)
        self.assertNotIn("stale_after:", text)
        # Title with a colon is safely quoted.
        self.assertIn('title: "Lifecycle Page: opted in"\n', text)
        # Body verbatim, markers intact.
        self.assertIn("^[cite: raw/sources/a.md#L3-L5]", text)
        self.assertIn("[[plain]]", text)

    def test_draft_status_passes_through_unnamespaced(self):
        self.export()
        text = (self.bundle / "entities" / "draft-page.md").read_text(
            "utf-8")
        self.assertIn("status: draft\n", text)
        # Mapping did not change it -> no namespace copy of status.
        fm = text.split("---")[1]
        self.assertEqual(fm.count("status:"), 1)

    def test_reserved_index_transform(self):
        self.export()
        text = (self.bundle / "index.md").read_text("utf-8")
        self.assertTrue(text.startswith(
            '---\nokf_version: "0.2"\n---\n'))
        self.assertIn("* [overview](overview.md) - the living "
                      "synthesis", text)
        self.assertIn("* [plain](sources/plain.md) - Plain Fixture "
                      "Page, the base", text)
        self.assertNotIn("[[", text)

    def test_reserved_log_transform(self):
        self.export()
        text = (self.bundle / "log.md").read_text("utf-8")
        self.assertIn("## 2030-10-13\n", text)
        self.assertIn("## 2030-10-12\n", text)
        # Newest first (SPEC section 9).
        self.assertLess(text.index("## 2030-10-13"),
                        text.index("## 2030-10-12"))
        self.assertIn("* **Ingest**: Plain page", text)
        self.assertIn("* **Query**: A question", text)
        self.assertIn("* **Setup**: Wiki created", text)
        self.assertIn("Ingested the plain page.", text)
        self.assertNotIn("## [2030", text)

    def test_check_passes_fixture_bundle(self):
        self.export()
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        self.assertIn("FAIL 0", proc.stdout)
        self.assertIn("PASS-WITH-OMISSIONS", proc.stdout)

    def test_check_json_report(self):
        self.export()
        report_path = self.tmp / "report.json"
        proc = self.run_cli("check", "--json", str(report_path))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        report = json.loads(report_path.read_text("utf-8"))
        by_path = {f["path"]: f for f in report["files"]}
        life = by_path["concepts/lifecycle.md"]
        self.assertEqual(life["verdict"], "PASS-WITH-OMISSIONS")
        notes = " ".join(life["omissions"])
        self.assertIn("wikilinks", notes)
        self.assertIn("cite:", notes)
        self.assertIn("llm_wiki", notes)
        self.assertIn("outside the bundle", notes)
        self.assertEqual(by_path["index.md"]["verdict"], "PASS")
        self.assertEqual(by_path["log.md"]["verdict"], "PASS")

    def test_export_refuses_page_without_type(self):
        bad = self.tmp / "wiki" / "concepts" / "bad.md"
        bad.write_text("---\ntitle: No type\n---\n\n# Bad\n",
                       encoding="utf-8")
        proc = self.run_cli("export")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no type", proc.stdout + proc.stderr)


class TestCheckFailures(FixtureWiki):
    """The checker must FAIL bundles that break SPEC section 11
    or the section 5 family rules."""

    def _tampered_check(self, rel, old, new):
        self.export()
        path = self.bundle / rel
        text = path.read_text("utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")
        return self.run_cli("check")

    def test_missing_type_fails(self):
        proc = self._tampered_check(
            "sources/plain.md", "type: source\n", "")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("non-empty type", proc.stdout)

    def test_status_outside_vocabulary_fails(self):
        proc = self._tampered_check(
            "entities/draft-page.md", "status: draft",
            "status: published")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("not in the OKF vocabulary", proc.stdout)

    def test_source_entry_without_resource_fails(self):
        proc = self._tampered_check(
            "sources/plain.md",
            "    resource: raw/sources/2030-10-12-plain.md\n", "")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("lacks the required resource", proc.stdout)

    def test_unparseable_frontmatter_fails(self):
        self.export()
        path = self.bundle / "overview.md"
        path.write_text("---\ntype: [unclosed\n---\n\n# X\n",
                        encoding="utf-8")
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("not parseable YAML", proc.stdout)

    def test_no_frontmatter_fails(self):
        self.export()
        path = self.bundle / "overview.md"
        path.write_text("# No frontmatter at all\n", encoding="utf-8")
        proc = self.run_cli("check")
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("no YAML frontmatter block", proc.stdout)


class TestMappingUnits(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module()

    def map(self, fields, body=""):
        return self.mod.map_page(fields, body)

    def test_status_map(self):
        for ours, okf in (("draft", "draft"),
                          ("deprecated", "deprecated"),
                          ("superseded", "deprecated"),
                          ("archived", "deprecated"),
                          ("verified", "stable"),
                          ("published", "stable"),
                          ("active", "stable"),
                          ("needs-verification", "stable")):
            out = self.map({"type": "source", "status": ours})
            self.assertEqual(out["status"], okf, ours)
            ns = out.get("llm_wiki", {})
            if okf != ours:
                self.assertEqual(ns.get("status"), ours)
            else:
                self.assertNotIn("status", ns)

    def test_unknown_status_preserved_not_guessed(self):
        out = self.map({"type": "source", "status": "limbo"})
        self.assertNotIn("status", out)
        self.assertEqual(out["llm_wiki"]["status"], "limbo")

    def test_absent_status_omitted(self):
        out = self.map({"type": "source"})
        self.assertNotIn("status", out)
        self.assertNotIn("llm_wiki", out)

    def test_empty_sources_and_tags_omitted(self):
        out = self.map({"type": "query", "sources": [], "tags": []})
        self.assertNotIn("sources", out)
        self.assertNotIn("tags", out)

    def test_source_ids_deduped(self):
        out = self.map({"type": "source", "sources": [
            "raw/x/report.md", "raw/y/report.md"]})
        ids = [e["id"] for e in out["sources"]]
        self.assertEqual(ids, ["report", "report-2"])

    def test_extra_keys_namespaced(self):
        out = self.map({"type": "query", "_schema_version": "2",
                        "about": "wiki/entities/x.md"})
        self.assertEqual(out["llm_wiki"]["_schema_version"], "2")
        self.assertEqual(out["llm_wiki"]["about"],
                         "wiki/entities/x.md")

    def test_emitted_frontmatter_is_parseable_yaml(self):
        yaml = importlib.import_module("yaml")
        fields = {"title": 'Tricky: "quoted" — title',
                  "type": "synthesis",
                  "created": "2030-10-13", "updated": "2030-10-14",
                  "sources": ["raw/sources/a.md"],
                  "tags": ["a b", "c:d"],
                  "status": "needs-verification",
                  "confidence": "observed",
                  "claim": "A claim with a colon: yes.",
                  "as_of": "2030-10-14"}
        text = self.mod.render_concept(fields, "\n# Body\n")
        fm = yaml.safe_load(text.split("---")[1])
        self.assertEqual(fm["type"], "synthesis")
        self.assertEqual(fm["status"], "stable")
        self.assertEqual(fm["title"], 'Tricky: "quoted" — title')
        self.assertEqual(fm["sources"][0]["resource"],
                         "raw/sources/a.md")
        self.assertEqual(fm["llm_wiki"]["created"], "2030-10-13")
        self.assertEqual(fm["llm_wiki"]["status"],
                         "needs-verification")
        self.assertEqual(fm["tags"], ["a b", "c:d"])


if __name__ == "__main__":
    unittest.main()
