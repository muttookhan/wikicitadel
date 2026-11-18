#!/usr/bin/env python3
"""Tests for scripts/wiki_a2a.py (Wave 6 — A2A handoff
vocabulary + agent cards).

Fixture corpus (tempfile root): one page, the seeded
agent-card directory, one review thread (via
wiki_review_threads). Every refusal class is exercised
by name: unknown act / field / state, missing required
field, uncarded sender, act the sender's card does not
declare, unknown page / thread / replied-to message,
duplicate id. The owner participates without a card.

Run:  python3 -m unittest scripts.tests.test_wiki_a2a
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


a2a = _load("wiki_a2a")
rt = _load("wiki_review_threads")

PAGE = """---
title: Alpha
type: concept
created: 2026-10-01
updated: 2026-10-01
sources: []
tags: []
---

The harbour light guides the ships home each night.
"""


def make_root(tmp):
    root = Path(tmp)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "evaluation").mkdir(parents=True)
    (root / "wiki" / "concepts" / "alpha.md").write_text(
        PAGE, encoding="utf-8")
    return root


def msg(**kw):
    base = {"id": "rm-000001", "act": "request-review",
            "from": "galen", "to": "agent",
            "state": "submitted", "date": "2026-10-22",
            "summary": "please review alpha",
            "page": "wiki/concepts/alpha.md"}
    base.update(kw)
    return base


class VocabularyTests(unittest.TestCase):
    def test_vocabulary_is_closed_and_named(self):
        doc = a2a.vocabulary_doc()
        self.assertEqual(set(doc["acts"]), {
            "request-review", "raise-finding",
            "contest-finding", "propose-resolution",
            "accept-resolution", "reject-resolution",
            "hand-off"})
        # The pair the gap map found undistinguished.
        self.assertIn("input-required",
                      doc["task_states"])
        self.assertIn("auth-required",
                      doc["task_states"])

    def test_determinism(self):
        self.assertEqual(
            json.dumps(a2a.vocabulary_doc(),
                       sort_keys=True),
            json.dumps(a2a.vocabulary_doc(),
                       sort_keys=True))


class CardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_seed_cards_one_public_rest_loopback(self):
        out = a2a.seed_cards(self.root)
        self.assertIn("agent", out["seeded"])
        _p, cards, records, _pr = a2a.load_cards(
            self.root)
        self.assertEqual(len(cards), 7)
        public = [a for a, c in cards.items()
                  if c["exposure"] == "public"]
        self.assertEqual(public, ["agent"])
        self.assertEqual(
            a2a.validate_cards(records), [])
        # Seeding never overwrites a standing directory.
        out = a2a.seed_cards(self.root)
        self.assertEqual(out["refused"],
                         "cards-register-exists")

    def test_card_findings_are_named(self):
        records = [
            {"kind": "agent-card", "agent": "a1",
             "name": "A", "role": "r",
             "exposure": "public", "may_send": [],
             "may_receive": [], "tools": ["x"],
             "declared_on": "2026-10-22"},
            {"kind": "agent-card", "agent": "a2",
             "name": "B", "role": "r",
             "exposure": "public",
             "may_send": ["fly-to-moon"],
             "may_receive": [], "tools": ["x"],
             "declared_on": "2026-10-22"}]
        names = {f["finding"]
                 for f in a2a.validate_cards(records)}
        self.assertIn("multiple-public-cards", names)
        self.assertIn("unknown-act:fly-to-moon", names)


class RecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)
        a2a.seed_cards(self.root)
        rt.open_thread(self.root, {
            "page": "wiki/concepts/alpha.md",
            "quote": "guides the ships home",
            "opened_by": "agent",
            "opened_on": "2026-10-22"})

    def tearDown(self):
        self._tmp.cleanup()

    def test_valid_messages_record(self):
        rec = a2a.record_message(self.root, msg())
        self.assertEqual(rec["kind"], "review-message")
        rec = a2a.record_message(self.root, msg(
            id="rm-000002", act="raise-finding",
            **{"from": "agent", "to": "galen"},
            finding="the date is unsourced"))
        self.assertEqual(rec["act"], "raise-finding")
        rec = a2a.record_message(self.root, msg(
            id="rm-000003", act="accept-resolution",
            **{"from": "hugo", "to": "agent"},
            thread_id="rt-000001"))
        self.assertEqual(rec["thread_id"], "rt-000001")
        out = a2a.check_all(self.root)
        self.assertEqual(out["findings"], [])
        self.assertEqual(out["messages"], 3)

    def test_owner_needs_no_card(self):
        rec = a2a.record_message(self.root, msg(
            **{"from": "owner"}))
        self.assertEqual(rec["kind"], "review-message")

    def test_refusals_are_named(self):
        cases = [
            (msg(act="teleport"),
             "unknown-act:teleport"),
            (msg(state="pending"),
             "unknown-state:pending"),
            (msg(**{"from": "jules"}),
             "sender-not-carded:jules"),
            (msg(**{"from": "codex"}),
             "act-not-permitted:codex:request-review"),
            (msg(page="wiki/concepts/ghost.md"),
             "unknown-page:wiki/concepts/ghost.md"),
            (msg(surprise="x"), "unknown-field:surprise"),
        ]
        for m, expected in cases:
            out = a2a.record_message(self.root, m)
            self.assertEqual(out.get("refused"), expected,
                             m)
        # Missing a required field, per act
        # (raise-finding carries its page but no
        # finding text).
        m = msg(act="raise-finding")
        out = a2a.record_message(self.root, m)
        self.assertEqual(out["refused"],
                         "missing-field:finding")
        # A thread that does not stand.
        out = a2a.record_message(self.root, msg(
            id="rm-000009", act="accept-resolution",
            **{"from": "hugo"},
            thread_id="rt-999999"))
        self.assertEqual(out["refused"],
                         "unknown-thread:rt-999999")
        # A reply to a message that does not stand.
        out = a2a.record_message(self.root, msg(
            id="rm-000010", act="contest-finding",
            **{"from": "agent", "to": "galen"},
            in_reply_to="rm-999999",
            grounds="the source says otherwise"))
        self.assertEqual(
            out["refused"],
            "in-reply-to-unknown:rm-999999")
        # Duplicate id.
        a2a.record_message(self.root, msg())
        out = a2a.record_message(self.root, msg())
        self.assertEqual(out["refused"], "duplicate-id")

    def test_check_names_a_dirty_register(self):
        a2a.record_message(self.root, msg())
        path = self.root / a2a.MESSAGES_REL
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "kind": "review-message",
                "id": "rm-000777", "act": "teleport",
                "from": "agent", "to": "galen",
                "state": "submitted",
                "date": "2026-10-22",
                "summary": "bad"}) + "\n")
        out = a2a.check_all(self.root)
        names = {f["finding"] for f in out["findings"]}
        self.assertIn("unknown-act:teleport", names)


if __name__ == "__main__":
    unittest.main()
