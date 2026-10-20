"""Item 61 — Ask-door clarification (the reference interview).

Covers the brief's test list for the item:

- split detection on fixtures: a measurable split fires; a
  one-topic evidence set stays silent; a lopsided split (share
  or strength below threshold) stays silent;
- the clarification text's form: the question paraphrased back
  for confirmation + the neutral stem (situation / gap /
  intended use), and NEVER the split's internals or any
  candidate facet (C3 — facets are the trigger, not the wording);
- the clarification state round-trip on the stored record:
  (none) -> clarifying -> replied -> closed, with the pickup's
  route at each state, the reply slot, and the refusals
  (double-open, reply-without-open, close-before-reply);
- timing routing: asked preserved, route queued, an instant
  request recorded honestly rather than faked;
- the Q&A record's additive `clarification` field (pickup).

The round-trip is fixture-driven against a temp event log: the
pickup is a batch loop over the service's question store and no
live service exists in this environment to test against, so the
stored record is the round-trip surface (see clarification.py).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import clarification as C  # noqa: E402
import pickup  # noqa: E402


def annotated(rows):
    """rows: [(page, score, community, label)] -> detector input."""
    return [{"page": p, "score": s, "community": c,
             "community_label": lab} for p, s, c, lab in rows]


SPLIT_ROWS = [
    ("wiki/entities/collaborator.md", 1.00, 3, "Cluster around Collaborator"),
    ("wiki/syntheses/decision-register.md", 0.91, 3,
     "Cluster around Collaborator"),
    ("wiki/concepts/multi-agent-memory.md", 0.83, 7,
     "Cluster around WikiCitadel Brain"),
    ("wiki/entities/codex.md", 0.79, 7, "Cluster around WikiCitadel Brain"),
    ("wiki/overview.md", 0.40, 3, "Cluster around Collaborator"),
]

ONE_TOPIC_ROWS = [
    ("wiki/entities/collaborator.md", 1.00, 3, "Cluster around Collaborator"),
    ("wiki/syntheses/decision-register.md", 0.88, 3,
     "Cluster around Collaborator"),
    ("wiki/entities/codex.md", 0.71, 3, "Cluster around Collaborator"),
    ("wiki/overview.md", 0.52, 3, "Cluster around Collaborator"),
]

LOPSIDED_SHARE_ROWS = [
    ("wiki/a.md", 1.00, 1, "Cluster around A"),
    ("wiki/b.md", 0.30, 2, "Cluster around B"),
    ("wiki/c.md", 0.28, 2, "Cluster around B"),
    ("wiki/d.md", 0.90, 1, "Cluster around A"),
    ("wiki/e.md", 0.85, 1, "Cluster around A"),
]

WEAK_SECOND_ROWS = [
    # Second community holds the share but none of its pages is
    # comparably strong — a long tail, not a split.
    ("wiki/a.md", 1.00, 1, "Cluster around A"),
    ("wiki/b.md", 0.65, 2, "Cluster around B"),
    ("wiki/c.md", 0.62, 2, "Cluster around B"),
    ("wiki/d.md", 0.60, 2, "Cluster around B"),
    ("wiki/e.md", 0.95, 1, "Cluster around A"),
]


class SplitDetectionTests(unittest.TestCase):
    def test_split_fires_on_comparable_two_cluster_evidence(self):
        detail = C.detect_split(annotated(SPLIT_ROWS))
        self.assertIsNotNone(detail)
        comms = detail["communities"]
        self.assertEqual(len(comms), 2)
        self.assertEqual({c["community"] for c in comms}, {3, 7})
        for c in comms:
            self.assertGreaterEqual(c["share"], C.MIN_SECOND_SHARE
                                    if c is comms[1] else 0)
        self.assertEqual(detail["thresholds"]["top_k"], C.TOP_K)

    def test_no_split_one_topic(self):
        self.assertIsNone(C.detect_split(annotated(ONE_TOPIC_ROWS)))

    def test_no_split_when_second_share_too_small(self):
        self.assertIsNone(C.detect_split(annotated(LOPSIDED_SHARE_ROWS)))

    def test_no_split_when_second_cluster_has_no_strong_page(self):
        self.assertIsNone(C.detect_split(annotated(WEAK_SECOND_ROWS)))

    def test_no_split_on_empty_or_single_result(self):
        self.assertIsNone(C.detect_split([]))
        self.assertIsNone(C.detect_split(annotated(SPLIT_ROWS[:1])))


class ClarificationFormTests(unittest.TestCase):
    QUESTION = "What did we decide about the gateway?"

    def test_paraphrase_hands_the_question_back(self):
        text = C.clarification_text(self.QUESTION)
        self.assertIn(self.QUESTION, text)
        self.assertIn("As I understand it", text)
        self.assertIn("is that the question?", text)

    def test_stem_covers_situation_gap_and_use(self):
        text = C.clarification_text(self.QUESTION)
        self.assertIn("what are you working on", text)   # situation
        self.assertIn("where did you get stuck", text)   # gap
        self.assertIn("how would you use the answer", text)  # use

    def test_text_carries_no_split_internals_or_facets(self):
        detail = C.detect_split(annotated(SPLIT_ROWS))
        text = C.clarification_text(self.QUESTION)
        for comm in detail["communities"]:
            self.assertNotIn(comm["label"], text)
            for page in comm["pages"]:
                self.assertNotIn(page, text)
        self.assertNotIn("cluster", text.lower())
        self.assertNotIn("split", text.lower())


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Path(self.tmp.name) / "clarifications-2026.jsonl"
        self.entry = {"id": "q_test61", "question": "Gateway?",
                      "asker": "owner", "asked_at": "2026-10-20T10:00:00Z"}
        self.detail = C.detect_split(annotated(SPLIT_ROWS))

    def _state(self):
        return C.fold_state(C.load_events(self.store), "q_test61")

    def test_full_round_trip(self):
        # No state + split -> clarify.
        self.assertIsNone(self._state())
        self.assertEqual(C.route_question(None, True), "clarify")
        self.assertEqual(C.route_question(None, False), "answer")

        record = C.open_clarification(self.store, self.entry,
                                      self.detail, "2026-10-20T10:05:00Z")
        self.assertEqual(record["status"], "clarifying")
        self.assertIsNone(record["reply"])  # the reply slot, empty
        self.assertIn("Gateway?", record["clarification_text"])
        state = self._state()
        self.assertEqual(state["status"], "clarifying")
        self.assertEqual(C.route_question(state, True), "await_reply")

        # A second open while one is open is refused.
        with self.assertRaises(ValueError):
            C.open_clarification(self.store, self.entry, self.detail,
                                 "2026-10-20T10:06:00Z")
        # Closing before a reply is refused.
        with self.assertRaises(ValueError):
            C.close_clarification(self.store, "q_test61", "answered",
                                  "wiki/access/qa-2026.jsonl#q_test61",
                                  "2026-10-20T10:07:00Z")

        event = C.record_reply(self.store, "q_test61",
                               "The hosted door — for the business plan.",
                               "2026-10-20T11:00:00Z", replied_by="owner")
        self.assertEqual(event["status"], "replied")
        state = self._state()
        self.assertEqual(state["status"], "replied")
        self.assertEqual(state["reply"],
                         "The hosted door — for the business plan.")
        self.assertEqual(C.route_question(state, True), "answer")

        # The Q&A record's additive field carries the exchange.
        field = C.qa_clarification_field(state)
        self.assertEqual(field["reply"], state["reply"])
        self.assertIn("Gateway?", field["paraphrase"])

        C.close_clarification(self.store, "q_test61", "answered",
                              "wiki/access/qa-2026.jsonl#q_test61",
                              "2026-10-20T11:05:00Z")
        state = self._state()
        self.assertEqual(state["status"], "closed")
        self.assertEqual(state["outcome"], "answered")
        self.assertEqual(state["answer_ref"],
                         "wiki/access/qa-2026.jsonl#q_test61")
        self.assertEqual(C.route_question(state, True), "skip_closed")

    def test_reply_without_open_clarification_refused(self):
        with self.assertRaises(ValueError):
            C.record_reply(self.store, "q_nope", "hello",
                           "2026-10-20T11:00:00Z")

    def test_events_are_append_only_jsonl(self):
        C.open_clarification(self.store, self.entry, self.detail,
                             "2026-10-20T10:05:00Z")
        C.record_reply(self.store, "q_test61", "reply",
                       "2026-10-20T11:00:00Z")
        lines = self.store.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        kinds = [json.loads(l)["event"] for l in lines]
        self.assertEqual(kinds, ["clarification_asked",
                                 "clarification_reply"])


class TimingRouteTests(unittest.TestCase):
    def test_no_timing_defaults_to_queued(self):
        t = C.timing_route({})
        self.assertIsNone(t["asked"])
        self.assertEqual(t["route"], "queued")

    def test_queued_timing(self):
        t = C.timing_route({"timing": "queued"})
        self.assertEqual(t["asked"], "queued")
        self.assertEqual(t["route"], "queued")
        self.assertIsNone(t["note"])

    def test_instant_request_recorded_not_faked(self):
        t = C.timing_route({"timing": "now"})
        self.assertEqual(t["asked"], "now")
        # No instant lane exists; the record must not claim one.
        self.assertEqual(t["route"], "queued")
        self.assertIn("no instant lane", t["note"])


class PickupRecordTests(unittest.TestCase):
    def test_qa_record_stamps_clarification_only_when_supplied(self):
        entry = {"id": "q_x", "question": "Q?", "asker": "owner",
                 "asked_at": "2026-10-20T10:00:00Z", "status": "pending"}
        plain = pickup.build_qa_record(entry, "A.", ["overview"],
                                       "2026-10-20T11:00:00Z")
        self.assertNotIn("clarification", plain)
        field = {"paraphrase": "As I understand it…", "stem": C.STEM,
                 "reply": "For the plan.", "clarified_at": "2026-10-20T10:05:00Z",
                 "timing": {"asked": None, "route": "queued", "note": None}}
        withc = pickup.build_qa_record(entry, "A.", ["overview"],
                                       "2026-10-20T11:00:00Z",
                                       clarification=field)
        self.assertEqual(withc["clarification"]["reply"], "For the plan.")
        md = pickup.stage_proposal_markdown(withc)
        self.assertIn("## Clarification", md)
        self.assertIn("For the plan.", md)


if __name__ == "__main__":
    unittest.main()
