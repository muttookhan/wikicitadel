#!/usr/bin/env python3
"""Tests for scripts/wiki_review_threads.py (Wave 6 —
anchored review threads).

Fixture corpus (tempfile root):

  wiki/concepts/alpha.md — body carries:
    "guides the ships home"     (unique passage)
    "The same words recur."     (twice — ambiguous)
    "alpha beta gamma"          (once at open time)

Lifecycle proven: open -> reply -> resolve; the passage
moved -> anchor moved; the passage deleted -> ORPHANED
with its words preserved; a duplicated passage
disambiguated by stored context -> moved, duplicated
with identical context -> orphaned. Refusals are named.
The Review Center gains the page with an
open-review-threads reason; a threadless corpus gains
nothing.

Run:  python3 -m unittest \
    scripts.tests.test_wiki_review_threads
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rt = _load("wiki_review_threads")
rs = _load("wiki_review_state")

ALPHA = """---
title: Alpha
type: concept
created: 2026-10-01
updated: 2026-10-01
sources: []
tags: []
---

The harbour light guides the ships home each night.
The committee voted to keep it lit through winter.
The same words recur. The same words recur.
North field alpha beta gamma south field.
"""

BETA = """---
title: Beta
type: concept
created: 2026-10-01
updated: 2026-10-01
sources: []
tags: []
---

A quiet page with nothing under review.
"""


def make_root(tmp):
    root = Path(tmp)
    (root / "wiki" / "concepts").mkdir(parents=True)
    (root / "evaluation").mkdir(parents=True)
    (root / "wiki" / "concepts" / "alpha.md").write_text(
        ALPHA, encoding="utf-8")
    (root / "wiki" / "concepts" / "beta.md").write_text(
        BETA, encoding="utf-8")
    return root


def open_alpha(root, quote="guides the ships home"):
    return rt.open_thread(root, {
        "page": "wiki/concepts/alpha.md", "quote": quote,
        "opened_by": "agent", "opened_on": "2026-10-22",
        "note": "check this passage"})


class OpenTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_builds_margin_notes_selectors(self):
        rec = open_alpha(self.root)
        self.assertEqual(rec["id"], "rt-000001")
        sels = rec["anchor"]["selector"]
        self.assertEqual([s["type"] for s in sels],
                         ["TextQuoteSelector",
                          "TextPositionSelector",
                          "FragmentSelector"])
        q, pos = sels[0], sels[1]
        self.assertEqual(q["exact"],
                         "guides the ships home")
        body = rt.page_body(self.root,
                            "wiki/concepts/alpha.md")
        self.assertEqual(body[pos["start"]:pos["end"]],
                         "guides the ships home")
        self.assertTrue(body[:pos["start"]]
                        .endswith(q["prefix"]))
        self.assertTrue(body[pos["end"]:]
                        .startswith(q["suffix"]))
        # Register created, header first.
        lines = (self.root / rt.REGISTER_REL).read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["kind"],
                         "header")
        self.assertEqual(json.loads(lines[1])["id"],
                         "rt-000001")

    def test_open_page_level_thread(self):
        rec = rt.open_thread(self.root, {
            "page": "wiki/concepts/beta.md",
            "opened_by": "grok",
            "opened_on": "2026-10-22"})
        self.assertIsNone(rec["anchor"])
        _p, states, _f, _pr = rt.thread_states(self.root)
        self.assertEqual(states[0]["anchor_state"],
                         "page")

    def test_open_refusals_are_named(self):
        r = open_alpha(self.root, "words that are absent")
        self.assertEqual(r["refused"], "quote-not-found")
        r = open_alpha(self.root, "The same words recur.")
        self.assertEqual(r["refused"], "quote-ambiguous")
        self.assertIn("2", r["detail"])
        r = rt.open_thread(self.root, {
            "page": "wiki/concepts/ghost.md",
            "opened_by": "agent",
            "opened_on": "2026-10-22"})
        self.assertEqual(r["refused"], "page-missing")
        r = rt.open_thread(self.root, {
            "page": "raw/sources/x.md",
            "opened_by": "agent",
            "opened_on": "2026-10-22"})
        self.assertEqual(r["refused"], "bad-page")

    def test_ids_sequence(self):
        self.assertEqual(open_alpha(self.root)["id"],
                         "rt-000001")
        rec = rt.open_thread(self.root, {
            "page": "wiki/concepts/beta.md",
            "opened_by": "agent",
            "opened_on": "2026-10-22"})
        self.assertEqual(rec["id"], "rt-000002")


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)
        open_alpha(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_reply_and_resolve(self):
        rec = rt.append_reply(self.root, {
            "thread": "rt-000001", "by": "grok",
            "on": "2026-10-22", "body": "looks right"})
        self.assertEqual(rec["id"], "rr-000001")
        _p, states, _f, _pr = rt.thread_states(self.root)
        self.assertEqual(states[0]["state"], "open")
        self.assertEqual(states[0]["replies"], 1)
        self.assertEqual(states[0]["participants"],
                         ["agent", "grok"])
        counts = rt.open_threads_by_page(self.root)
        self.assertEqual(
            counts["wiki/concepts/alpha.md"]["open"], 1)

        rec = rt.append_resolution(self.root, {
            "thread": "rt-000001", "by": "agent",
            "on": "2026-10-22",
            "note": "passage verified against source"})
        self.assertEqual(rec["id"], "rs-000001")
        _p, states, _f, _pr = rt.thread_states(self.root)
        self.assertEqual(states[0]["state"], "resolved")
        self.assertEqual(
            states[0]["resolution"]["note"],
            "passage verified against source")
        self.assertEqual(
            rt.open_threads_by_page(self.root), {})

        r = rt.append_reply(self.root, {
            "thread": "rt-000001", "by": "grok",
            "on": "2026-10-22", "body": "one more"})
        self.assertEqual(r["refused"], "thread-resolved")
        r = rt.append_resolution(self.root, {
            "thread": "rt-000001", "by": "agent",
            "on": "2026-10-22", "note": "again"})
        self.assertEqual(r["refused"],
                         "duplicate-resolution")
        r = rt.append_reply(self.root, {
            "thread": "rt-999999", "by": "grok",
            "on": "2026-10-22", "body": "hello"})
        self.assertEqual(r["refused"], "unknown-thread")

    def test_anchor_moved_when_passage_moves(self):
        page = self.root / "wiki/concepts/alpha.md"
        text = page.read_text(encoding="utf-8")
        text = text.replace(
            "The harbour light guides the ships home "
            "each night.\nThe committee voted to keep "
            "it lit through winter.",
            "The committee voted to keep it lit "
            "through winter.\nThe harbour light guides "
            "the ships home each night.")
        page.write_text(text, encoding="utf-8")
        _p, states, _f, _pr = rt.thread_states(self.root)
        self.assertEqual(states[0]["anchor_state"],
                         "moved")

    def test_anchor_orphaned_when_passage_deleted(self):
        page = self.root / "wiki/concepts/alpha.md"
        text = page.read_text(encoding="utf-8")
        text = text.replace(
            "The harbour light guides the ships home "
            "each night.\n", "")
        page.write_text(text, encoding="utf-8")
        artefact = rt.build_artefact(self.root)
        self.assertEqual(artefact["counts"]["orphaned"],
                         1)
        t = artefact["threads"][0]
        self.assertEqual(t["anchor_state"], "orphaned")
        # The quoted words are preserved on the record.
        self.assertEqual(t["quote"],
                         "guides the ships home")
        counts = rt.open_threads_by_page(self.root)
        self.assertEqual(
            counts["wiki/concepts/alpha.md"],
            {"open": 1, "orphaned": 1})
        # The rendered view shows the orphan + its words.
        md = rt.render_md(artefact)
        self.assertIn("ORPHANED", md)
        self.assertIn("guides the ships home", md)

    def test_context_disambiguates_a_duplicate(self):
        # A dedicated page: the quote sits deep inside a
        # long block, so its stored 32-char prefix and
        # suffix lie wholly inside the block.
        block = ("Minutes of the harbour committee, "
                 "recorded in full: the alpha beta gamma "
                 "reading was entered into the record "
                 "without objection.")
        page = self.root / "wiki/concepts/gamma.md"
        page.write_text(
            "---\ntitle: Gamma\ntype: concept\n"
            "created: 2026-10-01\nupdated: 2026-10-01\n"
            "sources: []\ntags: []\n---\n\n"
            "Standing text before the block.\n"
            + block + "\nStanding text after the block."
            "\n", encoding="utf-8")
        rec = rt.open_thread(self.root, {
            "page": "wiki/concepts/gamma.md",
            "quote": "alpha beta gamma",
            "opened_by": "agent",
            "opened_on": "2026-10-22"})
        self.assertEqual(rec["id"], "rt-000002")
        # Shift every offset (a new opening line) and
        # put a same-quote block before the original
        # whose lead differs INSIDE the stored 32-char
        # prefix window: the stored offsets no longer
        # hold the quote, two hits exist, and the
        # stored context names the original -> moved.
        variant = block.replace("recorded in full",
                                "recorded in brief")
        text = page.read_text(encoding="utf-8")
        text = text.replace(
            "Standing text before the block.",
            "A new opening line shifts everything.\n"
            + variant + "\nStanding text before "
            "the block.")
        page.write_text(text, encoding="utf-8")
        _p, states, _f, _pr = rt.thread_states(self.root)
        by_id = {t["id"]: t for t in states}
        self.assertEqual(
            by_id["rt-000002"]["anchor_state"], "moved")
        # Make the other block an exact copy: both hits
        # now match the stored context -> ambiguous ->
        # orphaned, never silently re-anchored.
        text = text.replace(variant, block)
        page.write_text(text, encoding="utf-8")
        _p, states, _f, _pr = rt.thread_states(self.root)
        by_id = {t["id"]: t for t in states}
        self.assertEqual(
            by_id["rt-000002"]["anchor_state"],
            "orphaned")


class RegisterShapeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_register(self, records):
        path = self.root / rt.REGISTER_REL
        header = {"kind": "header",
                  "register": "review-threads",
                  "version": 1}
        path.write_text(
            "".join(json.dumps(r) + "\n"
                    for r in [header] + records),
            encoding="utf-8")

    def test_asserted_state_is_a_finding(self):
        self._write_register([
            {"kind": "thread", "id": "rt-000001",
             "page": "wiki/concepts/alpha.md",
             "anchor": None, "opened_by": "agent",
             "opened_on": "2026-10-22",
             "state": "resolved"},
            {"kind": "resolution", "id": "rs-000001",
             "thread": "rt-999999", "by": "agent",
             "on": "2026-10-22", "note": "n"}])
        _t, findings = rt.derive_threads(
            rt.load_register(self.root)[1])
        names = {f["finding"] for f in findings}
        self.assertIn("state-asserted-not-derived",
                      names)
        self.assertIn("unknown-thread", names)

    def test_absent_register_is_the_honest_zero(self):
        artefact = rt.build_artefact(self.root)
        self.assertFalse(artefact["register_present"])
        self.assertEqual(artefact["counts"]["threads"],
                         0)
        self.assertEqual(
            rt.open_threads_by_page(self.root), {})

    def test_determinism(self):
        open_alpha(self.root)
        a = json.dumps(rt.build_artefact(self.root),
                       sort_keys=True)
        b = json.dumps(rt.build_artefact(self.root),
                       sort_keys=True)
        self.assertEqual(a, b)


class CenterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_root(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_thread_worklists_the_page(self):
        open_alpha(self.root)
        center = rs.build_review_center(
            self.root, date(2026, 10, 22))
        items = {i["page"]: i
                 for i in center["worklist"]}
        self.assertIn("wiki/concepts/alpha.md", items)
        reasons = {r["reason"]: r["detail"]
                   for r in
                   items["wiki/concepts/alpha.md"]
                   ["reasons"]}
        self.assertIn("open-review-threads", reasons)
        self.assertIn("1 open review thread",
                      reasons["open-review-threads"])
        beta = items.get("wiki/concepts/beta.md")
        if beta is not None:
            self.assertNotIn(
                "open-review-threads",
                {r["reason"] for r in beta["reasons"]})

    def test_zero_threads_adds_no_reason(self):
        center = rs.build_review_center(
            self.root, date(2026, 10, 22))
        for item in center["worklist"]:
            self.assertNotIn(
                "open-review-threads",
                {r["reason"] for r in item["reasons"]})
        self.assertNotIn("open-review-threads",
                         center["stats"]["by_reason"])


if __name__ == "__main__":
    unittest.main()
