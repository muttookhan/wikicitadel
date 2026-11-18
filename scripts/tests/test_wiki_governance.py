#!/usr/bin/env python3
"""Truth-aware retrieval governance (W1.5).

Pins the governance layer on fixture corpora:

  * the successor exemption inside severance (a page carrying
    a severed claim's current form survives that claim's
    text-match exclusion, and the exemption is recorded);
  * stage-6 page-state withholding with named reasons;
  * governed-but-live pages carrying their state in the
    result detail (candidate = proposed, rule = accepted);
  * UNGOVERNED pages — no lifecycle signal — kept and
    unannotated, never treated as superseded;
  * governance=False restoring the pre-governance pipeline
    exactly (paths, scores and details);
  * absence certificates verifying against the state hash,
    and going stale when the corpus state moves;
  * retire-and-replace as one operation, with all-or-nothing
    validation (an invalid act changes zero bytes);
  * the Lens mirror agreeing with the reference ranker.

Run:  python3 -m unittest discover -s scripts/tests
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ws = _load("wiki_search", ROOT / "scripts" / "wiki_search.py")
gov = _load("wiki_governance", ROOT / "scripts" / "wiki_governance.py")
L = _load("lenslib", ROOT / "tools" / "lens" / "lenslib.py")

SEV_FORM = {
    "kind": "retrieval-severance", "version": 1,
    "entries": [{
        "id": "sev-0001", "kind": "decision-form",
        "page": "wiki/severed-home.md",
        "claim": "Vega's seat stays RESERVED",
        "cues": {"phrases": [["seat", "stays", "reserved"],
                             ["seat", "reserved"],
                             ["vega", "reserved"]],
                 "terms": ["vega", "reserved", "seat", "stays"]},
        "source": {"register": "evaluation/decisions-register.jsonl",
                   "line": 2, "record_id": "d1-old",
                   "signal": "superseded form"},
    }],
}

GOV_CHAIN = {
    "kind": "retrieval-governance", "version": 1,
    "chains": {"sev-0001": {
        "successors": ["wiki/control.md"],
        "via": "decisions register: source page + the "
               "superseded_by record",
        "dangling": []}},
    "pages": {"wiki/control.md": {
        "state": "governed",
        "reasons": ["named successor for sev-0001 "
                    "(carries the current form)"],
        "successor_of": ["sev-0001"]}},
}

DOC_CARRIER = ("# Seat record\n\nVega's seat stays RESERVED, the "
               "original form said. Notes on the vega seat "
               "question.\n")
DOC_SUCCESSOR = ("# Current record\n\nVega's seat stays RESERVED "
                 "was the original form; this page records the "
                 "later ruling that the seat is open now.\n")

FIXED_TODAY = date(2026, 10, 22)


class SearchFixture(unittest.TestCase):
    """Base: a temp repo root wired into wiki_search the way
    the severance tests wire theirs, with the governance
    artefact path pointed at the fixture (absent by default,
    so defaults in the fixture are the legacy pipeline)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "wiki").mkdir(parents=True)
        (self.root / "evaluation").mkdir(parents=True)
        self._old_root = ws.ROOT
        self._old_gov_path = ws.GOVERNANCE_PATH
        ws.ROOT = self.root
        ws.GOVERNANCE_PATH = self.root / "evaluation" \
            / "retrieval-governance.json"

    def tearDown(self):
        ws.ROOT = self._old_root
        ws.GOVERNANCE_PATH = self._old_gov_path
        self._tmp.cleanup()

    def paths(self, ranked):
        return [str(p.relative_to(self.root))
                for _s, p, _t, _d in ranked]


class SuccessorExemptionTests(SearchFixture):
    def setUp(self):
        super().setUp()
        self.docs = [
            (self.root / "wiki" / "severed-home.md", DOC_CARRIER),
            (self.root / "wiki" / "control.md", DOC_SUCCESSOR),
        ]
        self.adj = ws.build_link_graph(self.docs)

    def test_successor_survives_the_claim_it_succeeds(self):
        ranked = ws.hybrid_rank(
            ws.tokenize("vega seat reserved"), self.docs, self.adj,
            severance=SEV_FORM, governance=GOV_CHAIN)
        paths = self.paths(ranked)
        self.assertNotIn("wiki/severed-home.md", paths)
        self.assertIn("wiki/control.md", paths)
        self.assertEqual(
            ws.LAST_SEVERANCE["excluded"],
            [{"path": "wiki/severed-home.md",
              "entries": ["sev-0001"]}])
        # The exemption is recorded, never silent.
        self.assertEqual(
            ws.LAST_GOVERNANCE["exempted"],
            [{"path": "wiki/control.md", "entries": ["sev-0001"]}])
        self.assertTrue(ws.LAST_GOVERNANCE["applied"])

    def test_governance_off_restores_the_exclusion(self):
        # Flag-off equivalence for the exemption: with
        # governance=False the successor is excluded exactly as
        # before W1.5 — the pre-change pipeline, byte for byte.
        off = ws.hybrid_rank(
            ws.tokenize("vega seat reserved"), self.docs, self.adj,
            severance=SEV_FORM, governance=False)
        legacy = ws.hybrid_rank(
            ws.tokenize("vega seat reserved"), self.docs, self.adj,
            severance=SEV_FORM, governance=False)
        self.assertEqual(off, legacy)
        self.assertNotIn("wiki/control.md", self.paths(off))
        self.assertFalse(ws.LAST_GOVERNANCE["applied"])
        self.assertEqual(ws.LAST_GOVERNANCE["exempted"], [])


class GovernanceFilterTests(SearchFixture):
    GOV = {
        "kind": "retrieval-governance", "version": 1,
        "chains": {},
        "pages": {
            "wiki/severed-home.md": {
                "state": "withheld",
                "reasons": ["superseded-by wiki/control.md"],
                "successor": "wiki/control.md"},
            "wiki/control.md": {
                "state": "governed",
                "reasons": ["claim-rule (accepted)"],
                "proposition": "accepted"},
        },
    }

    def setUp(self):
        super().setUp()
        self.docs = [
            (self.root / "wiki" / "severed-home.md",
             "# Old record\n\nAlpha beta retired record.\n"),
            (self.root / "wiki" / "control.md",
             "# Current record\n\nAlpha beta current record.\n"),
            (self.root / "wiki" / "overview.md",
             "# Legacy record\n\nAlpha beta legacy record with "
             "no lifecycle signal.\n"),
        ]
        self.adj = ws.build_link_graph(self.docs)

    def test_withheld_page_leaves_default_retrieval_with_reason(self):
        ranked = ws.hybrid_rank(
            ws.tokenize("alpha beta"), self.docs, self.adj,
            severance=False, governance=self.GOV)
        paths = self.paths(ranked)
        self.assertNotIn("wiki/severed-home.md", paths)
        self.assertEqual(
            ws.LAST_GOVERNANCE["withheld"],
            [{"path": "wiki/severed-home.md",
              "reasons": ["superseded-by wiki/control.md"]}])

    def test_governed_page_keeps_rank_and_carries_state(self):
        ranked = ws.hybrid_rank(
            ws.tokenize("alpha beta"), self.docs, self.adj,
            severance=False, governance=self.GOV)
        by_path = {str(p.relative_to(self.root)): d
                   for _s, p, _t, d in ranked}
        self.assertEqual(
            by_path["wiki/control.md"]["governance"]["proposition"],
            "accepted")

    def test_ungoverned_page_is_kept_and_unannotated(self):
        # Absence of lifecycle state = UNGOVERNED: kept, and no
        # governance key is invented for it.
        ranked = ws.hybrid_rank(
            ws.tokenize("alpha beta"), self.docs, self.adj,
            severance=False, governance=self.GOV)
        by_path = {str(p.relative_to(self.root)): d
                   for _s, p, _t, d in ranked}
        self.assertIn("wiki/overview.md", by_path)
        self.assertNotIn("governance", by_path["wiki/overview.md"])

    def test_governance_off_is_exactly_the_legacy_pipeline(self):
        off = ws.hybrid_rank(
            ws.tokenize("alpha beta"), self.docs, self.adj,
            severance=False, governance=False)
        empty = ws.hybrid_rank(
            ws.tokenize("alpha beta"), self.docs, self.adj,
            severance=False,
            governance={"kind": "retrieval-governance",
                        "chains": {}, "pages": {}})
        self.assertEqual(off, empty)
        self.assertIn("wiki/severed-home.md", self.paths(off))


class PageGovernanceTests(unittest.TestCase):
    def test_bare_working_status_is_ungoverned(self):
        text = ("---\ntitle: Plain page\ntype: concept\n"
                "status: draft\n---\n\n# Plain\n")
        self.assertIsNone(gov.page_governance(
            "wiki/control.md", text, FIXED_TODAY))

    def test_candidate_claim_is_proposed_not_withheld(self):
        text = ("---\ntitle: Claim page\ntype: concept\n"
                "claim: The old form stands.\n"
                "as_of: 2026-10-01\n---\n\n# Claim\n")
        record = gov.page_governance(
            "wiki/severed-home.md", text, FIXED_TODAY)
        self.assertEqual(record["state"], "governed")
        self.assertEqual(record["proposition"], "proposed")
        self.assertTrue(any("claim-candidate" in r
                            for r in record["reasons"]))

    def test_rule_claim_is_accepted(self):
        text = ("---\ntitle: Claim page\ntype: concept\n"
                "claim: The old form stands.\n"
                "as_of: 2026-10-01\n---\n\n# Claim\n")
        record = gov.page_governance(
            "wiki/severed-home.md", text, FIXED_TODAY,
            outcome_status="rule")
        self.assertEqual(record["proposition"], "accepted")
        self.assertEqual(record["state"], "governed")

    def test_retired_claim_is_withheld(self):
        text = ("---\ntitle: Claim page\ntype: concept\n"
                "claim: The old form stands.\n"
                "as_of: 2026-10-01\n---\n\n# Claim\n")
        record = gov.page_governance(
            "wiki/severed-home.md", text, FIXED_TODAY,
            outcome_status="retired")
        self.assertEqual(record["state"], "withheld")
        self.assertTrue(any("claim-retired" in r
                            for r in record["reasons"]))

    def test_superseded_page_is_withheld_with_pointer_reason(self):
        text = ("---\ntitle: Old page\ntype: concept\n"
                "status: superseded\n"
                "superseded_by: wiki/control.md\n---\n\n# Old\n")
        record = gov.page_governance(
            "wiki/severed-home.md", text, FIXED_TODAY)
        self.assertEqual(record["state"], "withheld")
        self.assertIn("superseded-by wiki/control.md",
                      record["reasons"])

    def test_expired_intention_closes_its_validity_window(self):
        text = ("---\ntitle: Intention\ntype: concept\n"
                "claim: We will ship the thing.\n"
                "claim_type: intention\n"
                "expires: 2020-01-01\n---\n\n# Intention\n")
        record = gov.page_governance(
            "wiki/severed-home.md", text, FIXED_TODAY)
        self.assertEqual(record["state"], "withheld")
        self.assertTrue(any(r.startswith("validity-window-closed")
                            for r in record["reasons"]))

    def test_live_intention_stays_governed(self):
        text = ("---\ntitle: Intention\ntype: concept\n"
                "claim: We will ship the thing.\n"
                "claim_type: intention\n"
                "expires: 2027-01-01\n---\n\n# Intention\n")
        record = gov.page_governance(
            "wiki/severed-home.md", text, FIXED_TODAY)
        self.assertEqual(record["state"], "governed")
        self.assertEqual(record["validity"],
                         {"kind": "intention",
                          "expires": "2027-01-01"})


class ArtefactAndCertificateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "wiki").mkdir(parents=True)
        (self.root / "evaluation").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_artefact_build_is_deterministic(self):
        first = gov.build_artefact(self.root, FIXED_TODAY)
        second = gov.build_artefact(self.root, FIXED_TODAY)
        self.assertEqual(first, second)
        self.assertEqual(first["state_hash"],
                         gov.state_hash(first))
        self.assertEqual(first["census"]["ungoverned"], 0)

    def test_absence_certificate_matches_then_goes_stale(self):
        artefact = gov.build_artefact(self.root, FIXED_TODAY)
        cert = gov.absence_certificate(
            "what is the airspeed of a swallow",
            ["airspeed", "swallow"], artefact, FIXED_TODAY)
        verdict = gov.verify_certificate(cert, self.root)
        self.assertEqual(verdict["status"], "match")
        self.assertEqual(verdict["certificate_state_hash"],
                         artefact["state_hash"])
        # The corpus state moves: a claim page appears. The
        # certificate must now read STALE, naming both hashes.
        (self.root / "wiki" / "severed-home.md").write_text(
            "---\ntitle: Claim page\ntype: concept\n"
            "claim: The old form stands.\n"
            "as_of: 2026-10-01\n---\n\n# Claim\n",
            encoding="utf-8")
        verdict = gov.verify_certificate(cert, self.root)
        self.assertEqual(verdict["status"], "stale")
        self.assertNotEqual(verdict["current_state_hash"],
                            verdict["certificate_state_hash"])


OLD_PAGE = ("---\ntitle: Old claim\ntype: concept\n"
            "created: 2026-10-01\nupdated: 2026-10-01\n"
            "claim: The old form stands.\n"
            "as_of: 2026-10-01\nstatus: draft\n"
            "sources: []\ntags: []\n---\n\n# Old claim\n\n"
            "The old form stands.\n")
NEW_PAGE = ("---\ntitle: Current claim\ntype: concept\n"
            "created: 2026-10-02\nupdated: 2026-10-02\n"
            "claim: The current form stands.\n"
            "as_of: 2026-10-02\nstatus: draft\n"
            "sources: []\ntags: []\n---\n\n# Current claim\n\n"
            "The current form stands.\n")


class RetireReplaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "wiki").mkdir(parents=True)
        (self.root / "evaluation").mkdir(parents=True)
        # retire-replace regenerates the derived artefacts
        # through the tree's own tools: the severance builder
        # loads the treatment module by a root-relative path
        # (scripts/wiki_treatment.py under the tree it judges),
        # so the fixture tree must carry that sibling closure,
        # as the repo's other fixture harnesses carry theirs.
        # (Coordinator integration glue, 2026-10-22.)
        scripts = self.root / "scripts"
        scripts.mkdir()
        real_scripts = Path(__file__).resolve().parents[1]
        for name in ("wiki_treatment.py", "wiki_observe.py",
                     "wiki_validate.py"):
            shutil.copy(real_scripts / name, scripts / name)
        (self.root / "wiki" / "severed-home.md").write_text(
            OLD_PAGE, encoding="utf-8")
        (self.root / "wiki" / "control.md").write_text(
            NEW_PAGE, encoding="utf-8")
        (self.root / "wiki" / "log.md").write_text(
            "# Log\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _tree_bytes(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in sorted(self.root.rglob("*"))
                if p.is_file()}

    def test_invalid_act_writes_nothing(self):
        # The replacement already declares a supersedes
        # relation: the act must refuse before any write.
        (self.root / "wiki" / "control.md").write_text(
            NEW_PAGE.replace("status: draft\n",
                             "status: draft\n"
                             "supersedes: wiki/overview.md\n"),
            encoding="utf-8")
        before = self._tree_bytes()
        ok, lines, code = gov.retire_replace(
            self.root, "wiki/severed-home.md", "wiki/control.md",
            "the owner ruled the form open", FIXED_TODAY)
        self.assertFalse(ok)
        self.assertEqual(code, 1)
        self.assertEqual(self._tree_bytes(), before)

    def test_missing_replacement_writes_nothing(self):
        before = self._tree_bytes()
        ok, _lines, code = gov.retire_replace(
            self.root, "wiki/severed-home.md", "wiki/overview.md",
            "the owner ruled the form open", FIXED_TODAY)
        self.assertFalse(ok)
        self.assertEqual(code, 1)
        self.assertEqual(self._tree_bytes(), before)

    def test_valid_act_lands_as_one_operation(self):
        ok, _lines, code = gov.retire_replace(
            self.root, "wiki/severed-home.md", "wiki/control.md",
            "the owner ruled the form open", FIXED_TODAY)
        self.assertTrue(ok)
        self.assertEqual(code, 0)
        old_text = (self.root / "wiki" / "severed-home.md") \
            .read_text(encoding="utf-8")
        self.assertIn("status: superseded", old_text)
        self.assertIn("superseded_by: wiki/control.md", old_text)
        new_text = (self.root / "wiki" / "control.md") \
            .read_text(encoding="utf-8")
        self.assertIn("supersedes: wiki/severed-home.md", new_text)
        events = [json.loads(line) for line in
                  (self.root / "evaluation"
                   / "treatment-register.jsonl")
                  .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["subject"],
                         {"page": "wiki/severed-home.md",
                          "claim": "The old form stands."})
        self.assertEqual(events[0]["grade"], "negative")
        self.assertIn("Retire-and-replace",
                      (self.root / "wiki" / "log.md")
                      .read_text(encoding="utf-8"))
        # The outcomes log is reality's record: untouched.
        self.assertFalse((self.root / "evaluation"
                          / "outcomes.jsonl").exists())
        # Both derived artefacts regenerated in the same act.
        artefact = gov.load_governance(
            gov.GOVERNANCE_PATH_FOR(self.root))
        self.assertIsNotNone(artefact)
        self.assertEqual(
            artefact["pages"]["wiki/severed-home.md"]["state"],
            "withheld")
        chain_successors = [page for chain
                            in artefact["chains"].values()
                            for page in chain["successors"]]
        self.assertIn("wiki/control.md", chain_successors)
        severance = json.loads(
            (self.root / "evaluation" / "retrieval-severance.json")
            .read_text(encoding="utf-8"))
        self.assertTrue(any(
            e.get("page") == "wiki/severed-home.md"
            for e in severance["entries"]))


class LensGovernanceParityTests(SearchFixture):
    def test_mirror_exempts_and_withholds_identically(self):
        docs = [
            (self.root / "wiki" / "severed-home.md", DOC_CARRIER),
            (self.root / "wiki" / "control.md", DOC_SUCCESSOR),
        ]
        adj = ws.build_link_graph(docs)
        terms = ws.tokenize("vega seat reserved")
        ref = ws.hybrid_rank(terms, docs, adj, severance=SEV_FORM,
                             governance=GOV_CHAIN)
        ref_paths = self.paths(ref)
        idx = L.PostingsIndex(
            [{"key": str(p), "text": t} for p, t in docs],
            severance=SEV_FORM, governance=GOV_CHAIN)
        mine = idx.hybrid_rank(terms, adj)
        my_paths = [L._sev_relpath(idx.docs[i]["key"])
                    for _s, i, _d in mine]
        self.assertEqual(ref_paths, my_paths)
        self.assertEqual(idx.last_governance["exempted"],
                         ws.LAST_GOVERNANCE["exempted"])
        self.assertEqual(idx.last_severance["excluded"],
                         ws.LAST_SEVERANCE["excluded"])


if __name__ == "__main__":
    unittest.main()
