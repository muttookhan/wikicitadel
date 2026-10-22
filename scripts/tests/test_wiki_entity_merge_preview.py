"""Tests for scripts/wiki_entity_merge_preview.py (implementation
wave W5, 2026-10-22; Zotero-style merge preview).

Pins, on a FIXTURE tree in a temp dir:
  - the frontmatter comparison is field-by-field: scalar
    CONFLICTs carry BOTH values and are never resolved; list
    fields show shared / only / merged-union;
  - every reference category is enumerated by scanning —
    inbound links, outbound duplicates, prose + path mentions,
    sources-field refs, index / log / ledger / filings refs,
    claims on and mentioning the absorbed page, citations
    (body markers + lockfile), alias + canonical registers,
    evaluation mentions, graph edges — and zero-hit categories
    are PRESENT with zero counts, not omitted;
  - sections: append vs combine split;
  - merge-never-delete: the absorbed title would join the
    survivor's aliases;
  - READ-ONLY: the fixture tree's content hash is identical
    before/after a preview run, and --out inside the tree is
    refused;
  - determinism: two previews of the same pair are
    byte-identical (JSON and MD render);
  - --suggest re-orders the pair by the proposals rule.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
DATE = "2026-10-22"


def load_module(root, name="wiki_entity_merge_preview"):
    spec = importlib.util.spec_from_file_location(
        name, root / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


ASTER = """---
title: Aster Vale
type: entity
created: 2026-01-01
updated: 2026-01-05
aliases:
  - A. Vale
sources:
  - raw/sources/a.md
  - raw/sources/shared.md
tags: [person, vale]
stage: budding
---
# Aster Vale

The senior keeper of the vale, with a long body of record
that goes on for several sentences so the proposals rule
has something to weigh when it picks a suggested survivor
between the two pages of this fixture pair.

## Family

The Vales of the valley.

## Work

Keeping. See [[birch-vale]] for the junior branch and
[[cedar]] for the neighbour.
"""

BIRCH = """---
title: Birch Vale
type: entity
created: 2026-02-01
updated: 2026-01-05
sources:
  - raw/sources/shared.md
  - raw/sources/b.md
tags: [person, birch]
stage: seedling
claim: "Birch Vale maintains the vale archive."
as_of: 2026-02-02
---
# Birch Vale

## Family

The Vales of the valley, junior branch.

## Archive

The archive claim rests on the source.^[cite: raw/sources/b.md#L3-L4]
Works with [[cedar]] and [[date-palm]].
"""

CEDAR = """---
title: Cedar
type: entity
created: 2026-03-01
sources:
  - raw/sources/shared.md
  - wiki/entities/birch-vale.md
tags: [person]
---
# Cedar

A neighbour. Birch Vale spoke at the meeting.
The record lives at wiki/entities/birch-vale.md for now.
See [[birch-vale]].
"""


class TestEntityMergePreview(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="merge-preview-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in ("wiki_entity_merge_preview.py",
                     "wiki_entity_merge.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        ent = self.tmp / "wiki" / "entities"
        ent.mkdir(parents=True)
        (ent / "aster-vale.md").write_text(ASTER, encoding="utf-8")
        (ent / "birch-vale.md").write_text(BIRCH, encoding="utf-8")
        (ent / "cedar.md").write_text(CEDAR, encoding="utf-8")
        wiki = self.tmp / "wiki"
        (wiki / "index.md").write_text(
            "# Index\n\n- [[birch-vale]] — Birch Vale\n",
            encoding="utf-8")
        (wiki / "log.md").write_text(
            "## [2026-02-01] ingest | Birch Vale\n"
            "Created wiki/entities/birch-vale.md.\n", encoding="utf-8")
        rules = wiki / "rules"
        rules.mkdir()
        (rules / "corrections-ledger.md").write_text(
            "- 2026-02-03: name fixed on wiki/entities/birch-vale.md\n",
            encoding="utf-8")
        filings = wiki / "filings"
        filings.mkdir()
        (filings / "note.md").write_text(
            "Discussed wiki/entities/birch-vale.md at length.\n",
            encoding="utf-8")
        ev = self.tmp / "evaluation"
        ev.mkdir()
        (ev / "claim-index.jsonl").write_text(
            json.dumps({"claim_id": "wiki/entities/birch-vale.md",
                        "text": "Birch Vale maintains the vale "
                                "archive.",
                        "stated": "2026-02-02"}) + "\n" +
            json.dumps({"claim_id": "wiki/entities/cedar.md",
                        "text": "Cedar defers to Birch Vale on "
                                "archives.",
                        "stated": "2026-03-01"}) + "\n",
            encoding="utf-8")
        (ev / "citation-lockfile.json").write_text(json.dumps(
            {"citations": [{"id": "c0099",
                            "page": "wiki/entities/birch-vale.md",
                            "page_line": 21,
                            "source": "raw/sources/b.md"}]},
            indent=2), encoding="utf-8")
        (ev / "entity-aliases.json").write_text(json.dumps(
            {"version": 1, "aliases": {"birch": "birch-vale"}}),
            encoding="utf-8")
        (ev / "canonical-names.json").write_text(json.dumps(
            {"canonical_names": [{"canonical": "Cedar",
                                  "variants": ["cedar tree"]}]}),
            encoding="utf-8")
        (self.tmp / "CONVERSATION-LOG.md").write_text(
            "We discussed wiki/entities/birch-vale.md today.\n",
            encoding="utf-8")
        self.mod = load_module(self.tmp)

    def preview(self):
        from datetime import date
        entities = self.mod.load_entities(self.tmp)
        a = self.mod.resolve_entity(self.tmp, "aster-vale", entities)
        b = self.mod.resolve_entity(self.tmp, "birch-vale", entities)
        return self.mod.build_preview(self.tmp, dict(a), dict(b),
                                      date(2026, 10, 22))

    def test_frontmatter_field_by_field(self):
        rows = {r["field"]: r for r in self.preview()["frontmatter"]}
        self.assertEqual(rows["title"]["relation"], "CONFLICT")
        self.assertEqual(rows["title"]["survivor"], "Aster Vale")
        self.assertEqual(rows["title"]["absorbed"], "Birch Vale")
        self.assertEqual(rows["created"]["relation"], "CONFLICT")
        self.assertEqual(rows["stage"]["relation"], "CONFLICT")
        self.assertEqual(rows["updated"]["relation"], "same")
        self.assertEqual(rows["type"]["relation"], "same")
        src = rows["sources"]
        self.assertEqual(src["shared"], ["raw/sources/shared.md"])
        self.assertEqual(src["survivor_only"], ["raw/sources/a.md"])
        self.assertEqual(src["absorbed_only"], ["raw/sources/b.md"])
        self.assertEqual(src["merged_union"],
                         ["raw/sources/a.md", "raw/sources/b.md",
                          "raw/sources/shared.md"])
        tags = rows["tags"]
        self.assertEqual(tags["shared"], ["person"])
        self.assertEqual(tags["merged_union"],
                         ["birch", "person", "vale"])
        self.assertEqual(rows["claim"]["relation"], "absorbed-only")
        self.assertEqual(rows["aliases"]["merged_union"], ["A. Vale"])
        self.assertEqual(self.preview()["counts"]["conflicts"], 3)

    def test_merge_never_delete_aliases(self):
        p = self.preview()
        self.assertEqual(p["would_add_aliases"], ["Birch Vale"])
        self.assertIn("never deleted", p["merge_never_delete"])
        self.assertEqual(p["status"], "awaiting-review")

    def test_sections_append_vs_combine(self):
        s = self.preview()["sections"]
        self.assertEqual(s["only_in_absorbed_would_append"],
                         ["Archive"])
        self.assertEqual(s["in_both_would_combine"], ["Family"])

    def test_reference_categories_all_present(self):
        p = self.preview()
        ref = p["references"]
        # aster + cedar + the index page itself all link to B
        self.assertEqual(p["counts"]["inbound_link_pages"], 3)
        self.assertEqual(p["counts"]["inbound_links"], 3)
        by_page = {e["page"]: e for e in ref["inbound_wikilinks"]}
        self.assertTrue(
            by_page["wiki/entities/aster-vale.md"]["from_survivor"])
        out = ref["outbound_links"]
        self.assertEqual([e["stem"] for e in out["would_duplicate"]],
                         ["cedar"])
        self.assertEqual([e["stem"] for e in out["would_be_new"]],
                         ["date-palm"])
        # cedar's prose + the index summary text + the log
        # entry's heading, which names the title in prose
        self.assertEqual([e["page"] for e in ref["prose_mentions"]],
                         ["wiki/entities/cedar.md", "wiki/index.md",
                          "wiki/log.md"])
        self.assertIn("wiki/entities/cedar.md",
                      [e["page"] for e in ref["path_mentions"]])
        self.assertEqual(ref["sources_field_refs"],
                         ["wiki/entities/cedar.md"])
        self.assertEqual(len(ref["index_listing"]), 1)
        self.assertEqual(len(ref["log_references"]), 1)
        self.assertEqual(len(ref["ledger_references"]), 1)
        self.assertEqual(len(ref["filings_references"]), 1)
        self.assertEqual(len(ref["conversation_log_mentions"]), 1)
        self.assertEqual(p["counts"]["claims_on_absorbed"], 2)
        self.assertEqual(p["counts"]["claims_mentioning_absorbed"], 1)
        self.assertEqual(p["counts"]["citation_markers"], 1)
        self.assertEqual(p["counts"]["citation_lockfile_records"], 1)
        self.assertEqual(ref["citations_on_absorbed"]
                         ["lockfile_records"][0]["id"], "c0099")
        self.assertEqual(len(ref["alias_register"]), 1)
        # zero-hit categories are present as evidence:
        self.assertEqual(ref["canonical_names"], [])
        g = ref["graph"]
        self.assertEqual(g["edges_in"], ["wiki/entities/aster-vale.md",
                                         "wiki/entities/cedar.md",
                                         "wiki/index.md"])
        self.assertEqual(g["source_edges_moving"],
                         ["raw/sources/b.md", "raw/sources/shared.md"])
        self.assertEqual(g["source_edges_shared_with_survivor"],
                         ["raw/sources/shared.md"])
        self.assertEqual([c["page"] for c in
                          g["co_citation_partners"]],
                         ["wiki/entities/cedar.md"])
        self.assertEqual({e["file"] for e in
                          ref["evaluation_mentions"]},
                         {"evaluation/claim-index.jsonl",
                          "evaluation/citation-lockfile.json"})

    def test_read_only_and_out_refused_inside_tree(self):
        before = tree_hash(self.tmp)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.main(["aster-vale", "birch-vale",
                                "--root", str(self.tmp),
                                "--date", DATE, "--format", "json"])
        self.assertEqual(rc, 0)
        json.loads(buf.getvalue())
        self.assertEqual(tree_hash(self.tmp), before)
        with contextlib.redirect_stderr(io.StringIO()):
            rc = self.mod.main(["aster-vale", "birch-vale",
                                "--root", str(self.tmp),
                                "--date", DATE,
                                "--out", str(self.tmp / "wiki" /
                                             "preview.md")])
        self.assertEqual(rc, 2)
        self.assertEqual(tree_hash(self.tmp), before)

    def test_deterministic_bytes(self):
        p1 = self.preview()
        p2 = self.preview()
        self.assertEqual(json.dumps(p1, indent=2, sort_keys=True),
                         json.dumps(p2, indent=2, sort_keys=True))
        self.assertEqual(self.mod.render_md(p1),
                         self.mod.render_md(p2))
        self.assertIn("DRY RUN", self.mod.render_md(p1))

    def test_suggest_reorders_pair(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.main(["birch-vale", "aster-vale",
                                "--root", str(self.tmp),
                                "--date", DATE, "--format", "json",
                                "--suggest"])
        self.assertEqual(rc, 0)
        p = json.loads(buf.getvalue())
        self.assertEqual(p["pair"]["survivor"],
                         "wiki/entities/aster-vale.md")
        self.assertIn("suggested by the proposals rule",
                      p["pair"]["survivor_basis"])


if __name__ == "__main__":
    unittest.main()
