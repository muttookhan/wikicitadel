#!/usr/bin/env python3
"""Tests for scripts/wiki_standards_bundles.py (build
wave 6, item W6: standards bundles pack — PROV-DM,
RFC 9264 linkset, UUIDv7, PREMIS).

Pins:
  - UUIDv7 against the RFC 9562 Appendix A vector, the
    fixed all-zero illustrative id, string-order ==
    time-order, timestamp round-trip, and rejection of
    v4 / garbage;
  - the PROV builder: revision chains (newer
    wasRevisionOf older), agent dedupe by author string,
    the gateway author typed prov:SoftwareAgent, and
    referential integrity of the emitted graph;
  - the gap discipline: pages missing from the page-
    history artefact are NAMED; the PREMIS gaps name the
    empty reverify / erasure registers and the absent
    bags instead of asserting events for them;
  - the linkset builder over synthetic door edges:
    predicate URIs from the linked-data table, the wk:
    extension URI for an unmapped relation, citation
    targets resolved vs dangling via the corpus, titles
    carried, duplicates collapsed;
  - the PREMIS event derivation: one event per grounded
    act, anchor outcomes copied verbatim (a failure
    stays a failure), replication only where a witness
    artefact is in the verified set;
  - the fixture-corpus integration: all six artefacts
    build, byte-identical on rebuild, the corpus tree
    untouched, the CLI build/check round-trip incl. a
    tampered artefact failing check;
  - one real-corpus gate: the four substantive check
    gates pass over the live tree (counts pinned loosely).

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SB = load_module("wiki_standards_bundles_under_test",
                 SCRIPTS / "wiki_standards_bundles.py")
LD = load_module("wiki_linked_data_for_sb_tests",
                 SCRIPTS / "wiki_linked_data.py")
BASE = LD.BASE


# ---------------------------------------------------------------------------
# UUIDv7
# ---------------------------------------------------------------------------

class TestUuid7(unittest.TestCase):
    def test_rfc_9562_vector(self):
        ms, ra, rb, expect = SB.UUID7_RFC_VECTOR
        self.assertEqual(SB.uuid7_from_parts(ms, ra, rb),
                         expect)

    def test_illustrative_zero_id(self):
        self.assertEqual(SB.uuid7_from_parts(0, 0, 0),
                         SB.UUID7_ILLUSTRATIVE)
        self.assertTrue(SB.is_uuid7(SB.UUID7_ILLUSTRATIVE))

    def test_ordering_and_roundtrip(self):
        ids = [SB.uuid7_from_parts(1700000000000 + i, 3, 4)
               for i in range(30)]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(SB.uuid7_timestamp_ms(ids[11]),
                         1700000000011)

    def test_rejects_v4_and_garbage(self):
        self.assertFalse(SB.is_uuid7(
            "123e4567-e89b-42d3-a456-426614174000"))
        self.assertFalse(SB.is_uuid7("not-a-uuid"))
        self.assertFalse(SB.is_uuid7(None))
        with self.assertRaises(ValueError):
            SB.uuid7_timestamp_ms(
                "123e4567-e89b-42d3-a456-426614174000")

    def test_parts_ranges(self):
        with self.assertRaises(ValueError):
            SB.uuid7_from_parts(1 << 48, 0, 0)
        with self.assertRaises(ValueError):
            SB.uuid7_from_parts(0, 1 << 12, 0)
        with self.assertRaises(ValueError):
            SB.uuid7_from_parts(0, 0, 1 << 62)

    def test_gate(self):
        ok, _detail = SB.gate_uuid7()
        self.assertTrue(ok)

    def test_policy_render_deterministic(self):
        census = {"register_uuids_by_version": {"v4": 2},
                  "uuid4_minting_files": ["scripts/x.py"]}
        a = SB.render_uuid7_policy(census)
        b = SB.render_uuid7_policy(census)
        self.assertEqual(a, b)
        self.assertIn("cp-NNNNNN", a)
        self.assertIn(SB.UUID7_ILLUSTRATIVE, a)
        self.assertIn("never rewritten", a)


# ---------------------------------------------------------------------------
# PROV builder (pure)
# ---------------------------------------------------------------------------

HISTORY = {"kind": "page-history", "pages": {
    "wiki/entities/alpha.md": {"commits": 2, "history": [
        {"commit": "b" * 40, "date": "2026-10-21T10:00:00+00:00",
         "author": "Hark", "subject": "second edit"},
        {"commit": "a" * 40, "date": "2026-10-20T10:00:00+00:00",
         "author": "Hark", "subject": "first edit"}]},
    "wiki/concepts/gamma.md": {"commits": 1, "history": [
        {"commit": "c" * 40, "date": "2026-10-19T10:00:00+00:00",
         "author": "Gateway Promotion (mehmed)",
         "subject": "promoted"}]},
}}


class TestProv(unittest.TestCase):
    def setUp(self):
        self.doc, self.counts, self.covered = \
            SB.build_prov(HISTORY, LD)
        self.by_id = {g["@id"]: g for g in self.doc["@graph"]}

    def test_counts(self):
        self.assertEqual(self.counts["pages"], 2)
        self.assertEqual(self.counts["revision_entities"], 3)
        self.assertEqual(self.counts["activities"], 3)
        self.assertEqual(self.counts["agents"], 2)

    def test_revision_chain(self):
        newer = LD.iri("revisions/" + "b" * 40
                       + "/wiki/entities/alpha.md")
        older = LD.iri("revisions/" + "a" * 40
                       + "/wiki/entities/alpha.md")
        self.assertEqual(self.by_id[newer]["prov:wasRevisionOf"],
                         older)
        self.assertNotIn("prov:wasRevisionOf",
                         self.by_id[older])
        self.assertEqual(
            self.by_id[newer]["prov:specializationOf"],
            LD.iri("wiki/entities/alpha.md"))

    def test_agent_dedupe_and_software_agent(self):
        hark = [g for g in self.doc["@graph"]
                if g.get("wk:authorString") == "Hark"]
        self.assertEqual(len(hark), 1)
        gw = [g for g in self.doc["@graph"]
              if g.get("wk:authorString", "")
              .startswith("Gateway")][0]
        self.assertIn("prov:SoftwareAgent", gw["@type"])

    def test_gate(self):
        ok, detail = SB.gate_prov(self.doc)
        self.assertTrue(ok, detail)

    def test_gaps_name_missing_pages(self):
        gaps = SB.prov_gaps(
            ["wiki/entities/alpha.md", "wiki/orphan.md"],
            self.covered)
        self.assertEqual(
            gaps["pages_not_in_page_history_artefact"],
            ["wiki/orphan.md"])
        self.assertEqual(
            gaps["pages_not_in_page_history_count"], 1)


# ---------------------------------------------------------------------------
# Linkset builder (pure over synthetic door edges)
# ---------------------------------------------------------------------------

class TestLinkset(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "raw" / "sources").mkdir(parents=True)
        (self.tmp / "raw" / "sources" / "note.md").write_text(
            "note\n", encoding="utf-8")
        pages = {
            "wiki/entities/alpha.md":
                ({"title": "Alpha"}, "", ""),
            "wiki/entities/beta.md":
                ({"title": "Beta"}, "", ""),
        }
        edges = [
            {"src": "wiki/entities/alpha.md",
             "dst": "wiki/entities/beta.md",
             "kind": "wikilink", "relation": "mentions"},
            {"src": "wiki/entities/alpha.md",
             "dst": "raw/sources/note.md",
             "kind": "citation", "relation": "cites"},
            {"src": "wiki/entities/alpha.md",
             "dst": "raw/sources/gone.md",
             "kind": "citation", "relation": "cites"},
            {"src": "wiki/entities/beta.md",
             "dst": "wiki/entities/alpha.md",
             "kind": "typed", "relation": "exemplifies"},
            {"src": "wiki/entities/alpha.md",
             "dst": "wiki/entities/beta.md",
             "kind": "wikilink", "relation": "mentions"},
        ]
        self.doc, self.counts, self.dangling = \
            SB.build_linkset(edges, pages, self.tmp, LD)

    def test_counts_and_dupe_collapse(self):
        self.assertEqual(self.counts["links"], 4)
        self.assertEqual(self.counts["duplicates_collapsed"], 1)
        self.assertEqual(self.counts["anchors"], 2)
        self.assertEqual(
            self.counts["per_target_kind"],
            {"page": 2, "raw": 1, "dangling": 1})

    def test_relation_uris(self):
        alpha = next(i for i in self.doc["linkset"]
                     if i["anchor"]
                     == LD.iri("wiki/entities/alpha.md"))
        self.assertIn(LD.NS["wk"] + "mentions", alpha)
        self.assertIn("http://purl.org/spar/cito/cites", alpha)
        beta = next(i for i in self.doc["linkset"]
                    if i["anchor"]
                    == LD.iri("wiki/entities/beta.md"))
        self.assertIn(LD.NS["wk"] + "exemplifies", beta)
        target = alpha[LD.NS["wk"] + "mentions"][0]
        self.assertEqual(target["title"], "Beta")

    def test_dangling_named(self):
        self.assertEqual(len(self.dangling), 1)
        self.assertEqual(self.dangling[0]["target_as_written"],
                         "raw/sources/gone.md")
        ok, detail = SB.gate_linkset(self.doc, self.dangling)
        self.assertTrue(ok, detail)


# ---------------------------------------------------------------------------
# PREMIS derivation (pure over synthetic register rows)
# ---------------------------------------------------------------------------

ROWS = [
    {"kind": "header", "purpose": "fixture"},
    {"kind": "checkpoint", "id": "cp-000001",
     "created_utc": "2026-10-20T09:23:04Z",
     "signer": "mehmed@llm-wiki",
     "git_head": "a" * 40, "line_hash": "f" * 64,
     "provenance": {"manifest": "evaluation/merkle-manifest.jsonl",
                    "manifest_sha256": "b" * 64,
                    "corpus_root": "c" * 64, "sources": 231}},
    {"kind": "checkpoint", "id": "cp-000002",
     "created_utc": "2026-10-21T09:23:04Z",
     "signer": "mehmed@llm-wiki",
     "git_head": "d" * 40, "line_hash": "e" * 64,
     "provenance": {"manifest": "evaluation/merkle-manifest.jsonl",
                    "manifest_sha256": "b" * 64,
                    "corpus_root": "c" * 64, "sources": 240}},
    {"kind": "anchor", "checkpoint": "cp-000001",
     "attempted_utc": "2026-10-20T09:24:15Z",
     "line_hash": "1" * 64,
     "anchors": [
         {"mechanism": "opentimestamps", "status": "failed",
          "detail": "need at least 2 attestations"},
         {"mechanism": "rfc3161", "status": "success",
          "detail": "receipt held"}]},
]


class TestPremis(unittest.TestCase):
    def test_events_grounded_and_verbatim(self):
        events, counts = SB.build_premis_events(
            ROWS, {"cp-000001"})
        types = [e["eventType"] for e in events]
        self.assertEqual(counts["checkpoint_lines"], 2)
        self.assertEqual(types.count("creation"), 2)
        self.assertEqual(types.count("fixity check"), 2)
        # replication only for the witnessed checkpoint
        self.assertEqual(types.count("replication"), 1)
        rep = next(e for e in events
                   if e["eventType"] == "replication")
        self.assertTrue(rep["eventIdentifier"]
                        .startswith("cp-000001/"))
        # anchor outcomes copied verbatim — failure stays failed
        anchors = {e["eventIdentifier"]: e["eventOutcome"]
                   for e in events
                   if e["eventType"] == "timestamp anchor"}
        self.assertEqual(anchors["cp-000001/anchor-opentimestamps"],
                         "failed")
        self.assertEqual(anchors["cp-000001/anchor-rfc3161"],
                         "success")
        ok, detail = SB.gate_premis(events, ROWS)
        self.assertTrue(ok, detail)

    def test_no_witness_no_replication(self):
        events, _ = SB.build_premis_events(ROWS, set())
        self.assertNotIn("replication",
                         [e["eventType"] for e in events])
        gaps = SB.premis_gaps(ROWS, set(), REPO)
        joined = " ".join(gaps)
        self.assertIn("reverify-history", joined)
        self.assertIn("erasure-certificates", joined)
        self.assertIn("bagging", joined)
        self.assertIn("cp-000001", joined)  # unwitnessed, named

    def test_alignment_renders(self):
        text = SB.render_premis_alignment()
        self.assertIn("eventOutcomeInformation", text)
        self.assertIn("DOCUMENTATION ONLY", text)


# ---------------------------------------------------------------------------
# Fixture-corpus integration
# ---------------------------------------------------------------------------

ALPHA = """---
title: Alpha
type: entity
created: 2026-10-20
updated: 2026-10-21
sources: [raw/sources/note.md, raw/sources/gone.md]
tags: []
---

# Alpha

Alpha mentions [[beta]].
"""

BETA = """---
title: Beta
type: entity
created: 2026-10-20
updated: 2026-10-20
sources: []
tags: []
---

# Beta

Beta stands alone.
"""

FIXTURE_HISTORY = {"kind": "page-history", "pages": {
    "wiki/entities/alpha.md": {"commits": 1, "history": [
        {"commit": "a" * 40, "date": "2026-10-20T10:00:00+00:00",
         "author": "Hark", "subject": "fixture commit"}]},
}}

FIXTURE_REGISTER = [
    {"kind": "header", "purpose": "fixture register"},
    {"kind": "checkpoint", "id": "cp-000001",
     "created_utc": "2026-10-20T09:23:04Z",
     "signer": "mehmed@llm-wiki", "git_head": "a" * 40,
     "line_hash": "f" * 64,
     "note": "see 123e4567-e89b-42d3-a456-426614174000",
     "provenance": {"manifest": "evaluation/merkle-manifest.jsonl",
                    "manifest_sha256": "b" * 64,
                    "corpus_root": "c" * 64, "sources": 3}},
]


def write_fixture(root: Path):
    def mk(*parts):
        d = root.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d
    mk("scripts")
    for name in ("wiki_traverse.py", "wiki_validate.py",
                 "wiki_graph_export.py", "wiki_edge_labels.py",
                 "wiki_linked_data.py",
                 "wiki_standards_bundles.py"):
        shutil.copy(SCRIPTS / name, root / "scripts" / name)
    mk("tools", "lens")
    shutil.copy(REPO / "tools" / "lens" / "lenslib.py",
                root / "tools" / "lens" / "lenslib.py")
    (mk("wiki", "entities") / "alpha.md").write_text(
        ALPHA, encoding="utf-8")
    (mk("wiki", "entities") / "beta.md").write_text(
        BETA, encoding="utf-8")
    (mk("raw", "sources") / "note.md").write_text(
        "A fixture note.\n", encoding="utf-8")
    ev = mk("evaluation")
    (ev / "page-history.json").write_text(
        json.dumps(FIXTURE_HISTORY), encoding="utf-8")
    (ev / "checkpoints.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in FIXTURE_REGISTER),
        encoding="utf-8")
    witness = root / "witness"
    (witness / "checkpoints.d").mkdir(parents=True)
    (witness / "checkpoints.d" / "cp-000001.json").write_text(
        "{}\n", encoding="utf-8")
    return witness


def tree_digest(root: Path):
    """Content digest of the fixture corpus. Bytecode
    caches are excluded — derived artefacts of importing
    the copied scripts, per the wiki_bag.py precedent."""
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if p.is_file() and "exports" not in rel.parts \
                and "__pycache__" not in rel.parts \
                and p.suffix != ".pyc":
            h.update(str(rel).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


class TestFixtureIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.witness = write_fixture(self.root)

    def test_build_all_and_determinism(self):
        before = tree_digest(self.root)
        a, report = SB.build_all(self.root, self.witness)
        b, _ = SB.build_all(self.root, self.witness)
        self.assertEqual(a, b)  # byte-identical rebuild
        self.assertEqual(set(a), set(SB.ARTEFACTS))
        self.assertEqual(before, tree_digest(self.root))
        ls = report["bundles"]["linkset"]
        self.assertEqual(ls["counts"]["dangling"], 1)
        self.assertEqual(ls["dangling"][0]["target_as_written"],
                         "raw/sources/gone.md")
        census = report["bundles"]["uuid7"]["census"]
        self.assertEqual(census["register_uuids_by_version"],
                         {"v4": 1})
        premis = report["bundles"]["premis"]["counts"]
        self.assertEqual(premis["by_type"]["replication"], 1)
        prov_gaps = report["bundles"]["prov"]["gaps"]
        self.assertEqual(
            prov_gaps["pages_not_in_page_history_artefact"],
            ["wiki/entities/beta.md"])

    def test_cli_build_check_and_tamper(self):
        out = self.tmp / "out"
        rc = SB.main(["--root", str(self.root), "--out",
                      str(out), "--witness", str(self.witness),
                      "build"])
        self.assertEqual(rc, 0)
        for name in SB.ARTEFACTS:
            self.assertTrue((out / name).is_file(), name)
        rc = SB.main(["--root", str(self.root), "--out",
                      str(out), "--witness", str(self.witness),
                      "check"])
        self.assertEqual(rc, 0)
        (out / "citation-linkset.json").write_text(
            "{}\n", encoding="utf-8")
        rc = SB.main(["--root", str(self.root), "--out",
                      str(out), "--witness", str(self.witness),
                      "check"])
        self.assertEqual(rc, 1)


class TestRealCorpus(unittest.TestCase):
    def test_real_corpus_gates(self):
        witness = SB.DEFAULT_WITNESS if \
            SB.DEFAULT_WITNESS.is_dir() else Path("/nonexistent")
        _artefacts, report = SB.build_all(REPO, witness)
        prov = report["bundles"]["prov"]["counts"]
        self.assertGreater(prov["pages"], 10)
        self.assertGreater(prov["revision_entities"], 20)
        premis = report["bundles"]["premis"]["counts"]
        # WikiCitadel has cut no checkpoints of its own: the
        # checkpoint register does not exist in this tree (the
        # private tree's register is its own signed state
        # history and never ports). The honest count is zero.
        self.assertEqual(premis["checkpoint_lines"], 0)
        self.assertEqual(premis["events"], 0)
        ls = report["bundles"]["linkset"]["counts"]
        self.assertGreater(ls["links"], 100)


if __name__ == "__main__":
    unittest.main()
