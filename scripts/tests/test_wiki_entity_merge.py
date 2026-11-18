#!/usr/bin/env python3
"""Tests for scripts/wiki_entity_merge.py (Marathon R3 TA5;
sage-wiki entity-resolution merge PROPOSALS).

Pins, on a FIXTURE tree in a temp dir:
  - an alias-match pair and a name-similarity pair are found,
    with the signals and corroborating evidence stated;
  - an unrelated entity produces no proposal;
  - the suggested survivor follows the stated rule
    (more sources wins);
  - PROPOSAL-ONLY: running the tool (filing included) leaves
    every fixture page byte-identical — nothing is merged;
  - the filing + manifest are written with kind
    "entity-merge-proposals".

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


def load_module(root):
    spec = importlib.util.spec_from_file_location(
        "wiki_entity_merge", root / "scripts" / "wiki_entity_merge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def page(title, sources=(), aliases=(), body="Body text."):
    src = "\n".join(f"  - {s}" for s in sources) or "[]"
    al = "\n".join(f"  - {a}" for a in aliases)
    fm = f"---\ntitle: {title}\ntype: entity\ncreated: 2026-01-01\n"
    fm += f"sources:\n{src}\n" if sources else "sources: []\n"
    if aliases:
        fm += f"aliases:\n{al}\n"
    return fm + f"tags: [fixture]\n---\n\n# {title}\n\n{body}\n"


class TestEntityMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="entity-merge-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        scripts = self.tmp / "scripts"
        scripts.mkdir(parents=True)
        for name in ("wiki_entity_merge.py", "wiki_validate.py"):
            shutil.copy(SCRIPTS / name, scripts / name)
        ent = self.tmp / "wiki" / "entities"
        ent.mkdir(parents=True)
        (ent / "aster-vale.md").write_text(page(
            "Aster Vale",
            sources=["raw/sources/a.md", "raw/sources/b.md"],
            body="The longer, better-sourced page about Aster."), encoding="utf-8")
        (ent / "aster-vail.md").write_text(page(
            "Aster Vail", sources=["raw/sources/a.md"],
            body="Short stub under a misspelt name."), encoding="utf-8")
        (ent / "bramble-hedge.md").write_text(page(
            "Bramble Hedge", sources=["raw/sources/c.md"]), encoding="utf-8")
        (ent / "bramble-hedges.md").write_text(page(
            "Bramble Hedges", sources=["raw/sources/c.md"]), encoding="utf-8")
        (ent / "unrelated-pond.md").write_text(page(
            "Unrelated Pond"), encoding="utf-8")
        self.mod = load_module(self.tmp)
        self.before = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in ent.glob("*.md")}

    def test_candidates_found_with_evidence(self):
        props = self.mod.find_candidates(self.tmp)
        pairs = {tuple(p["pair"]) for p in props}
        self.assertIn(("wiki/entities/aster-vail.md",
                       "wiki/entities/aster-vale.md"), pairs)
        self.assertIn(("wiki/entities/bramble-hedge.md",
                       "wiki/entities/bramble-hedges.md"), pairs)
        self.assertFalse(any("unrelated-pond" in p["pair"][0]
                             or "unrelated-pond" in p["pair"][1]
                             for p in props))
        vale = [p for p in props
                if "aster-vail" in p["pair"][0]][0]
        self.assertEqual(vale["evidence"]["shared_sources"],
                         ["raw/sources/a.md"])
        self.assertIn("name-similarity",
                      {s["signal"] for s in vale["signals"]})

    def test_survivor_rule_more_sources(self):
        props = self.mod.find_candidates(self.tmp)
        vale = [p for p in props
                if "aster-vail" in p["pair"][0]][0]
        self.assertEqual(vale["suggested_survivor"],
                         "wiki/entities/aster-vale.md")
        self.assertIn("more sources", vale["survivor_reason"])

    def test_alias_match_signal(self):
        ent = self.tmp / "wiki" / "entities"
        (ent / "aster-vale.md").write_text(page(
            "Aster Vale", sources=["raw/sources/a.md"],
            aliases=["Aster Vail"]), encoding="utf-8")
        props = self.mod.find_candidates(self.tmp)
        vale = [p for p in props
                if set(p["pair"]) == {"wiki/entities/aster-vail.md",
                                      "wiki/entities/aster-vale.md"}][0]
        self.assertIn("alias-match",
                      {s["signal"] for s in vale["signals"]})

    def test_proposal_only_pages_untouched(self):
        manifest = self.mod.analyse(self.tmp)
        md_path, json_path = self.mod.write_filing(self.tmp, manifest)
        self.assertTrue(md_path.is_file() and json_path.is_file())
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["kind"], "entity-merge-proposals")
        after = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (self.tmp / "wiki" / "entities").glob("*.md")}
        self.assertEqual(self.before, after)


if __name__ == "__main__":
    unittest.main()
