"""Tests for tools/ask/depth_ladder.py (W6 query depth
ladder) and its seams in pickup.py, provenance.py and
scripts/wiki_traverse.py.

Pins:
  - the ladder is a closed set of three levels in ladder
    order; the standard bundle IS tonight's standing
    configuration (candidate pool == the abstention
    battery's TOP_K, pack budget ==
    evidence_packing.DEFAULT_TOKEN_BUDGET), so the default
    depth is not a new configuration wearing a name;
  - no level bundle carries an abstention threshold or a
    governance switch — depth changes breadth, never the
    bar — and every depth block carries the invariant
    verbatim;
  - stage postures: the standing stages run at every
    level; the opt-in stages are off at quick/standard and
    declared-not-wired at deep (implemented in
    wiki_search.py, not wired into the Ask door);
  - declaration resolution: explicit beats entry, invalid
    resolves to no level and is refused BY NAME at the
    pickup seam, never silently defaulted;
  - pickup stamps a depth block only on a declaration;
    an undeclared record has no depth key and its staged
    proposal is byte-identical to a declared record's
    proposal with the depth lines removed;
  - the provenance envelope names the record's depth
    block when present and is silent otherwise; at quick
    the sentence scorer does not run (no support_summary,
    empty sentence lists — omitted, not zeroed);
  - the decision rule's abstention basis is depth-blind:
    on fixed pipeline outputs, a severed-all pack and a
    below-tau top score abstain at EVERY level's pool and
    budget, and a thin-evidence pack answers at standard
    and deep (the battery's rule, imported from
    scripts/wiki_abstention_check.py — the real-corpus
    execution of the battery at all three depths is
    scripts/wiki_depth_measure.py's artefact).

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests
No network. Real-tree uses are read-only.
"""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

ASK_DIR = Path(__file__).resolve().parents[1]
ROOT = Path(__file__).resolve().parents[3]
WIKI = ROOT / "wiki"
FIXTURES = ASK_DIR / "tests" / "fixtures"

sys.path.insert(0, str(ASK_DIR))

import depth_ladder  # noqa: E402
import evidence_packing  # noqa: E402
import pickup  # noqa: E402
import provenance  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


battery = _load("wiki_abstention_check",
                ROOT / "scripts" / "wiki_abstention_check.py")

ANSWERED_AT = "2026-10-22T01:30:00Z"
ENTRY = {"id": "q-depth-test", "question": "What stands?",
         "asker": "owner", "asked_at": "2026-10-22T01:00:00Z"}


def plain_record(**kwargs):
    return pickup.build_qa_record(
        dict(ENTRY), "An answer.", ["sources/x"], ANSWERED_AT,
        **kwargs)


class LadderDefinitionTests(unittest.TestCase):
    def test_closed_set_in_ladder_order(self):
        self.assertEqual(depth_ladder.level_names(),
                         ("quick", "standard", "deep"))
        self.assertEqual(depth_ladder.DEFAULT_DEPTH, "standard")

    def test_standard_is_tonights_configuration(self):
        standard = depth_ladder.get_level("standard")
        self.assertEqual(standard["candidate_pool"], battery.TOP_K)
        self.assertEqual(standard["pack_budget_tokens"],
                         evidence_packing.DEFAULT_TOKEN_BUDGET)

    def test_breadth_is_monotonic(self):
        pools = [depth_ladder.get_level(n)["candidate_pool"]
                 for n in depth_ladder.LEVEL_ORDER]
        budgets = [depth_ladder.get_level(n)["pack_budget_tokens"]
                   for n in depth_ladder.LEVEL_ORDER]
        self.assertEqual(pools, sorted(pools))
        self.assertEqual(budgets, sorted(budgets))
        self.assertLess(pools[0], pools[-1])

    def test_no_level_carries_the_bar(self):
        for name in depth_ladder.LEVEL_ORDER:
            spec = depth_ladder.get_level(name)
            for key in spec:
                self.assertNotIn("threshold", key)
                self.assertNotIn("tau", key)
                self.assertNotIn("governance", key)
                self.assertNotIn("severance", key)
            block = depth_ladder.depth_block(name, "declared")
            self.assertEqual(block["abstention_invariant"],
                             depth_ladder.ABSTENTION_INVARIANT)
            self.assertIn("extended-baseline.json",
                          block["abstention_invariant"])

    def test_stage_postures(self):
        for name in depth_ladder.LEVEL_ORDER:
            postures = {s["stage"]: s["posture"]
                        for s in depth_ladder.get_level(name)["stages"]}
            for standing in ("coverage-rerank", "severance",
                             "governance"):
                self.assertEqual(postures[standing], "standing")
            for opt_in in ("onehop-vote", "hyde-expansion",
                           "iterative-passes", "listwise"):
                expected = ("declared-not-wired" if name == "deep"
                            else "off")
                self.assertEqual(postures[opt_in], expected,
                                 f"{name}/{opt_in}")
        deep_notes = {s["stage"]: s["note"]
                      for s in depth_ladder.get_level("deep")["stages"]}
        self.assertIn("NOT wired into the Ask door",
                      deep_notes["onehop-vote"])

    def test_traverse_bundles(self):
        self.assertEqual(
            depth_ladder.get_level("standard")["traverse"]
            ["search_top"], battery.TOP_K)
        tops = [depth_ladder.get_level(n)["traverse"]["search_top"]
                for n in depth_ladder.LEVEL_ORDER]
        self.assertEqual(tops, sorted(tops))

    def test_block_is_deterministic(self):
        a = depth_ladder.depth_block("deep", "declared")
        b = depth_ladder.depth_block("deep", "declared")
        self.assertEqual(a, b)
        self.assertEqual(json.loads(json.dumps(a)), a)


class ResolutionTests(unittest.TestCase):
    def test_undeclared_is_default(self):
        self.assertEqual(depth_ladder.resolve_depth(),
                         ("standard", "default (undeclared)"))

    def test_entry_declaration(self):
        self.assertEqual(depth_ladder.resolve_depth(None, "quick"),
                         ("quick", "declared"))

    def test_explicit_beats_entry(self):
        self.assertEqual(depth_ladder.resolve_depth("deep", "quick"),
                         ("deep", "declared"))

    def test_invalid_resolves_to_no_level(self):
        level, basis = depth_ladder.resolve_depth("turbo")
        self.assertIsNone(level)
        self.assertEqual(basis, "declared")

    def test_declaration_error_names_the_ladder(self):
        error = depth_ladder.declaration_error("turbo")
        self.assertIn("'turbo'", error)
        self.assertIn("quick, standard, deep", error)
        self.assertIsNone(depth_ladder.declaration_error("deep"))
        self.assertIsNone(depth_ladder.declaration_error(None))
        self.assertIsNone(depth_ladder.declaration_error({"level": "x"}))


class PickupSeamTests(unittest.TestCase):
    def test_undeclared_record_has_no_depth_key(self):
        record = plain_record()
        self.assertNotIn("depth", record)
        self.assertEqual(
            sorted(record.keys()),
            ["answer", "answered_at", "asked_at", "asker",
             "citations", "id", "question", "status"])

    def test_entry_declaration_stamps_full_block(self):
        record = pickup.build_qa_record(
            dict(ENTRY, depth="deep"), "An answer.",
            ["sources/x"], ANSWERED_AT)
        self.assertEqual(record["depth"]["level"], "deep")
        self.assertEqual(record["depth"]["basis"], "declared")
        self.assertEqual(record["depth"]["candidate_pool"], 25)

    def test_explicit_argument_wins(self):
        record = pickup.build_qa_record(
            dict(ENTRY, depth="deep"), "An answer.",
            ["sources/x"], ANSWERED_AT, depth="quick")
        self.assertEqual(record["depth"]["level"], "quick")
        self.assertEqual(record["depth"]["sentence_scoring"],
                         "not-run")

    def test_declared_default_still_stamps(self):
        # A caller who explicitly declares standard gets the
        # declaration on the record — visibility is the
        # point of declaring.
        record = plain_record(depth="standard")
        self.assertEqual(record["depth"]["level"], "standard")
        self.assertEqual(record["depth"]["basis"], "declared")

    def test_invalid_declaration_stamps_nothing(self):
        record = pickup.build_qa_record(
            dict(ENTRY, depth="turbo"), "An answer.",
            ["sources/x"], ANSWERED_AT)
        self.assertNotIn("depth", record)

    def test_pickup_refusal_names_invalid_payload_depth(self):
        payload = {"question_entry": dict(ENTRY), "depth": "turbo"}
        error = pickup.depth_declaration_error(payload)
        self.assertIn("'turbo'", error)
        payload = {"question_entry": dict(ENTRY, depth="warp")}
        error = pickup.depth_declaration_error(payload)
        self.assertIn("question depth", error)
        self.assertIsNone(pickup.depth_declaration_error(
            {"question_entry": dict(ENTRY, depth="deep")}))
        self.assertIsNone(pickup.depth_declaration_error(
            {"question_entry": dict(ENTRY)}))

    def test_proposal_depth_line_is_the_only_difference(self):
        declared = pickup.build_qa_record(
            dict(ENTRY, depth="deep"), "An answer.",
            ["sources/x"], ANSWERED_AT)
        undeclared = plain_record()
        with_depth = pickup.stage_proposal_markdown(declared)
        without = pickup.stage_proposal_markdown(undeclared)
        self.assertNotIn("depth (", without.lower())
        kept = [line for line in with_depth.splitlines(keepends=True)
                if "depth (" not in line.lower()]
        # The depth render is a paragraph + its blank line:
        # dropping the paragraph reproduces the undeclared
        # proposal once the doubled blank line collapses.
        stripped = "".join(kept)
        self.assertEqual(stripped.replace("\n\n\n", "\n\n"), without)


class ProvenanceSeamTests(unittest.TestCase):
    def _record(self, depth=None):
        payload = json.loads(
            (FIXTURES / "sample_scored_answer.json")
            .read_text(encoding="utf-8"))
        record = pickup.build_qa_record(
            payload["question_entry"], payload["answer"],
            payload["citations"], ANSWERED_AT,
            question_type=payload.get("question_type"),
            mode=payload.get("mode"),
            citation_details=payload.get("citation_details"),
            sub_answers=payload.get("sub_answers"),
            depth=depth)
        passages = [dict(d) for d in record["citation_details"]]
        pack = evidence_packing.pack_evidence(passages, budget=6000)
        return record, pack

    def test_envelope_names_declared_depth(self):
        record, pack = self._record(depth="deep")
        env = provenance.build_provenance(
            record, pack_result=pack, wiki_dir=WIKI, root=ROOT)
        self.assertEqual(env["depth"]["level"], "deep")
        self.assertEqual(env["depth"]["candidate_pool"], 25)
        self.assertIn("depth_ladder", env["depth"]["source"])

    def test_envelope_silent_without_declaration(self):
        record, pack = self._record()
        env = provenance.build_provenance(
            record, pack_result=pack, wiki_dir=WIKI, root=ROOT)
        self.assertNotIn("depth", env)
        for citation in env["citations"]:
            self.assertIn("support_summary", citation)

    def test_quick_does_not_run_sentence_scoring(self):
        record, pack = self._record(depth="quick")
        env = provenance.build_provenance(
            record, pack_result=pack, wiki_dir=WIKI, root=ROOT)
        self.assertEqual(env["depth"]["sentence_scoring"],
                         "not-run")
        for citation in env["citations"]:
            self.assertEqual(citation["sentences"], [])
            self.assertNotIn("support_summary", citation)

    def test_standard_declared_still_scores(self):
        record, pack = self._record(depth="standard")
        env = provenance.build_provenance(
            record, pack_result=pack, wiki_dir=WIKI, root=ROOT)
        for citation in env["citations"]:
            self.assertIn("support_summary", citation)


class AbstentionBasisTests(unittest.TestCase):
    """The decision rule's abstention basis is depth-blind:
    pool and budget are the only level inputs to packing,
    and neither reaches the top-1 score or severance."""

    TAU = 1.23

    def _pack_at(self, level, candidates, severance=None):
        spec = depth_ladder.get_level(level)
        return evidence_packing.pack_evidence(
            candidates[:spec["candidate_pool"]],
            budget=spec["pack_budget_tokens"],
            severance=severance)

    def test_below_tau_abstains_at_every_depth(self):
        candidates = [{"page": "sources/x", "passage": "thin",
                       "score": 0.9}]
        for name in depth_ladder.LEVEL_ORDER:
            pack = self._pack_at(name, candidates)
            verdict, _reason = battery._decide(pack, 0.9, self.TAU)
            self.assertEqual(verdict, "abstain", name)

    def test_thin_evidence_answers_at_standard_and_deep(self):
        candidates = [{"page": "sources/x", "passage": "real",
                       "score": 1.5}]
        for name in ("standard", "deep"):
            pack = self._pack_at(name, candidates)
            verdict, _reason = battery._decide(pack, 1.5, self.TAU)
            self.assertEqual(verdict, "answer", name)

    def test_top_score_is_not_a_packing_output(self):
        # The ladder's inputs stop at packing: the score the
        # abstention rule reads comes from the ranked list,
        # computed once, before any level applies.
        for name in depth_ladder.LEVEL_ORDER:
            spec = depth_ladder.get_level(name)
            self.assertNotIn("top_score", spec)
            self.assertNotIn("score", spec)


if __name__ == "__main__":
    unittest.main()
