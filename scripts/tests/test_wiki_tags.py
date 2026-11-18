#!/usr/bin/env python3
"""Tests for scripts/wiki_tags.py (consolidated-queue item 47:
the SKOS tag registry) and for the travelling-labels
enrichment it feeds in scripts/wiki_okf_export.py.

Pins, on FIXTURE repos in temp dirs:

  - census counts the fixture tree's tags (flow lists);
  - register adds a concept and maintains broader/narrower
    symmetry on the concepts it points at;
  - register REFUSES label clashes (a string that is
    already a prefLabel or another concept's altLabel), a
    relation target that does not exist, and a deprecation
    with no replacedBy — a governed vocabulary never forks
    a label;
  - resolve finds a concept by prefLabel and by altLabel,
    and reports no-match for an unknown string;
  - check REPORTS (never rewrites): an unregistered tag
    in use is named with its pages, a deprecated tag still
    in use is named with its replacedBy pointer, and the
    qSKOS battery flags a hand-broken asymmetric relation
    and a label clash with exit 1;
  - the OKF export carries registered tags as
    llm_wiki.tag_concepts (prefLabel + scopeNote; an
    altLabel use recorded as used_as), contributes NO
    entry for an unregistered tag, and omits the block
    entirely when no registry exists.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1]
TOOL = "wiki_tags.py"
EXPORTER = "wiki_okf_export.py"
REGISTRY = "evaluation/tag-registry.jsonl"

HEADER = {"kind": "header", "register": "tag-registry",
          "version": 1, "created": "2030-10-20",
          "purpose": "fixture", "maintenance": "fixture",
          "judgement_calls": []}


def concept(label, **kw):
    base = {"kind": "concept", "id": label, "prefLabel": label,
            "altLabels": [], "hiddenLabels": [],
            "definition": "def of " + label,
            "scopeNote": "scope of " + label,
            "broader": [], "narrower": [], "related": [],
            "status": "preferred",
            "changeNote": ["2030-10-20: fixture."],
            "usage": {"count": 0, "pages": []},
            "registered": "2030-10-20"}
    base.update(kw)
    return base


def page(tags, title="Fixture Page"):
    return ("---\ntitle: %s\ntype: source\ntags: [%s]\n---\n\n"
            "# %s\n\nBody.\n" % (title, ", ".join(tags), title))


class FixtureRepo(unittest.TestCase):
    """A temp repo: the real scripts copied in, a small wiki,
    and a seeded registry written directly as jsonl."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="tagfix-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in (TOOL, EXPORTER, "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        (self.tmp / "evaluation").mkdir()
        wiki = self.tmp / "wiki"
        (wiki / "sources").mkdir(parents=True)
        (wiki / "concepts").mkdir(parents=True)
        (wiki / "sources" / "one.md").write_text(
            page(["agents", "filings"], "One"), encoding="utf-8")
        (wiki / "sources" / "two.md").write_text(
            page(["filing", "galen"], "Two"), encoding="utf-8")
        (wiki / "concepts" / "three.md").write_text(
            page(["agents"], "Three"), encoding="utf-8")
        self.write_registry([
            concept("agents"),
            concept("filings", altLabels=["filing"]),
            concept("galen", broader=["agents"]),
        ])
        # symmetry the seed owes: agents.narrower names galen
        self.fix_symmetry()

    # -- helpers ------------------------------------------------

    def write_registry(self, concepts):
        lines = [json.dumps(HEADER, ensure_ascii=False)]
        lines += [json.dumps(c, ensure_ascii=False)
                  for c in concepts]
        (self.tmp / REGISTRY).write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    def read_registry(self):
        out = []
        for line in (self.tmp / REGISTRY).read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def fix_symmetry(self):
        objs = self.read_registry()
        by_id = {o["id"]: o for o in objs
                 if o.get("kind") == "concept"}
        for obj in by_id.values():
            for parent in obj["broader"]:
                if obj["id"] not in by_id[parent]["narrower"]:
                    by_id[parent]["narrower"].append(obj["id"])
        self.write_registry(
            [o for o in objs if o.get("kind") == "concept"])

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, str(self.tmp / "scripts" / TOOL),
             "--root", str(self.tmp), *args],
            capture_output=True, text=True)

    def check_json(self):
        proc = self.run_tool("check", "--json")
        return proc, json.loads(proc.stdout)


class TestCensus(FixtureRepo):

    def test_census_counts(self):
        proc = self.run_tool("census", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        live = json.loads(proc.stdout)
        self.assertEqual(live["pages_scanned"], 3)
        self.assertEqual(live["pages_tagged"], 3)
        self.assertEqual(live["distinct_tags"], 4)
        self.assertEqual(live["tags"]["agents"]["count"], 2)
        self.assertEqual(live["tags"]["filing"]["count"], 1)


class TestRegister(FixtureRepo):

    def test_register_adds_and_mirrors_symmetry(self):
        proc = self.run_tool(
            "register", "--label", "hugo", "--broader", "agents",
            "--definition", "the agent Hugo",
            "--scope-note", "narrower than agents")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        objs = {o["id"]: o for o in self.read_registry()
                if o.get("kind") == "concept"}
        self.assertIn("hugo", objs)
        self.assertEqual(objs["hugo"]["broader"], ["agents"])
        self.assertIn("hugo", objs["agents"]["narrower"])

    def test_register_refuses_existing_label(self):
        proc = self.run_tool("register", "--label", "agents")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("already resolves", proc.stderr)

    def test_register_refuses_altlabel_of_another(self):
        proc = self.run_tool("register", "--label", "filing")
        self.assertEqual(proc.returncode, 2)

    def test_register_refuses_altlabel_clash_with_preflabel(self):
        proc = self.run_tool("register", "--label", "newtag",
                             "--alt-label", "galen")
        self.assertEqual(proc.returncode, 2)

    def test_register_refuses_unknown_relation_target(self):
        proc = self.run_tool("register", "--label", "newtag",
                             "--broader", "nosuch")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a registered concept", proc.stderr)

    def test_register_refuses_deprecated_without_replaced_by(self):
        proc = self.run_tool("register", "--label", "oldtag",
                             "--status", "deprecated")
        self.assertEqual(proc.returncode, 2)


class TestResolve(FixtureRepo):

    def test_resolve_by_preflabel_and_altlabel(self):
        proc = self.run_tool("resolve", "filings")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["resolved_via"], "prefLabel")
        proc = self.run_tool("resolve", "filing")
        out = json.loads(proc.stdout)
        self.assertEqual(out["prefLabel"], "filings")
        self.assertEqual(out["resolved_via"], "altLabel")
        # Live usage is the concept's, across all its label
        # forms: one.md via 'filings', two.md via 'filing'.
        self.assertEqual(out["live_usage"]["count"], 2)

    def test_resolve_unknown(self):
        proc = self.run_tool("resolve", "nosuchtag")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no registered concept", proc.stdout)


class TestCheck(FixtureRepo):

    def test_check_clean_fixture(self):
        proc, report = self.check_json()
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertEqual(report["unregistered"], [])
        self.assertEqual(report["deprecated_in_use"], [])
        self.assertEqual(report["integrity"], [])
        self.assertEqual(report["never_used"], [])

    def test_check_names_unregistered_tag(self):
        (self.tmp / "wiki" / "sources" / "four.md").write_text(
            page(["mystery"], "Four"), encoding="utf-8")
        proc, report = self.check_json()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual([u["tag"] for u in report["unregistered"]],
                         ["mystery"])
        self.assertEqual(report["unregistered"][0]["count"], 1)

    def test_check_names_deprecated_in_use(self):
        objs = [o for o in self.read_registry()
                if o.get("kind") == "concept"]
        for obj in objs:
            if obj["id"] == "galen":
                obj["status"] = "deprecated"
                obj["replacedBy"] = "agents"
        self.write_registry(objs)
        proc, report = self.check_json()
        self.assertEqual([d["tag"] for d in
                          report["deprecated_in_use"]], ["galen"])
        self.assertEqual(
            report["deprecated_in_use"][0]["replacedBy"], "agents")

    def test_check_flags_asymmetry(self):
        objs = [o for o in self.read_registry()
                if o.get("kind") == "concept"]
        for obj in objs:
            if obj["id"] == "agents":
                obj["narrower"] = []  # break the mirror by hand
        self.write_registry(objs)
        proc, report = self.check_json()
        self.assertEqual(proc.returncode, 1)
        self.assertTrue(any("asymmetric" in p
                            for p in report["integrity"]))

    def test_check_flags_label_clash(self):
        objs = [o for o in self.read_registry()
                if o.get("kind") == "concept"]
        objs.append(concept("other", altLabels=["galen"]))
        self.write_registry(objs)
        _proc, report = self.check_json()
        self.assertTrue(any("label clash" in p
                            for p in report["integrity"]))

    def test_deprecate_then_check(self):
        proc = self.run_tool("deprecate", "galen",
                             "--replaced-by", "agents")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        _proc, report = self.check_json()
        self.assertEqual([d["concept"] for d in
                          report["deprecated_in_use"]], ["galen"])
        proc = self.run_tool("deprecate", "galen",
                             "--replaced-by", "agents")
        self.assertEqual(proc.returncode, 2,
                         "double deprecation is refused")


class TestExportEnrichment(FixtureRepo):

    def export(self):
        proc = subprocess.run(
            [sys.executable,
             str(self.tmp / "scripts" / EXPORTER), "export",
             "--out", str(self.tmp / "bundle")],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         proc.stdout + proc.stderr)
        return self.tmp / "bundle"

    def frontmatter(self, bundle, rel):
        text = (bundle / rel).read_text(encoding="utf-8")
        return yaml.safe_load(text.split("---\n")[1])

    def test_registered_tags_travel(self):
        bundle = self.export()
        fm = self.frontmatter(bundle, "sources/one.md")
        entries = {e["label"]: e
                   for e in fm["llm_wiki"]["tag_concepts"]}
        self.assertEqual(set(entries), {"agents", "filings"})
        self.assertEqual(entries["agents"]["scope_note"],
                         "scope of agents")
        self.assertNotIn("used_as", entries["filings"])

    def test_altlabel_travels_with_used_as(self):
        bundle = self.export()
        fm = self.frontmatter(bundle, "sources/two.md")
        entries = {e["label"]: e
                   for e in fm["llm_wiki"]["tag_concepts"]}
        self.assertEqual(entries["filings"]["used_as"], "filing")
        self.assertEqual(entries["galen"]["scope_note"],
                         "scope of galen")

    def test_unregistered_tag_contributes_nothing(self):
        (self.tmp / "wiki" / "sources" / "four.md").write_text(
            page(["mystery", "agents"], "Four"), encoding="utf-8")
        bundle = self.export()
        fm = self.frontmatter(bundle, "sources/four.md")
        labels = [e["label"]
                  for e in fm["llm_wiki"]["tag_concepts"]]
        self.assertEqual(labels, ["agents"])
        self.assertEqual(fm["tags"], ["mystery", "agents"],
                         "the tags themselves stay verbatim")

    def test_no_registry_no_enrichment(self):
        (self.tmp / REGISTRY).unlink()
        bundle = self.export()
        fm = self.frontmatter(bundle, "sources/one.md")
        self.assertNotIn("tag_concepts",
                         fm.get("llm_wiki", {}))


def load_exporter():
    spec = importlib.util.spec_from_file_location(
        "wiki_okf_export", SCRIPTS / "wiki_okf_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTagConceptsFor(unittest.TestCase):

    def test_dedupes_and_sorts(self):
        exporter = load_exporter()
        tags_mod = exporter.TAGS
        self.assertIsNotNone(tags_mod)
        concepts = [concept("filings", altLabels=["filing"]),
                    concept("agents")]
        entries = tags_mod.tag_concepts_for(
            ["filing", "filings", "agents", "ghost"], concepts)
        self.assertEqual([e["label"] for e in entries],
                         ["agents", "filings"])
        self.assertEqual(entries[1]["used_as"], "filing")


if __name__ == "__main__":
    unittest.main()
