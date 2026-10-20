#!/usr/bin/env python3
"""Tests for scripts/wiki_close.py — the periodic close
(consolidated-queue item 22: balance assertions + periodic
close, Beancount pattern, wave 4).

Each assertion is exercised against a small fixture corpus
where it can be made to fail individually: the fixture starts
healthy, and each test breaks exactly one book.

Run:  python3 -m unittest discover -s scripts/tests -v
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


close = load("wiki_close")
prov = load("wiki_provenance")
cite = load("wiki_cite_lock")

sys.path.insert(0, str(REPO / "tools" / "gateway"))
from gateway.ledger import GENESIS_PREV, canonical, entry_digest  # noqa: E402


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_jsonl(path, records):
    write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n"
                        for r in records))


def bind(module, root, **paths):
    saved = {}
    for k, v in paths.items():
        if hasattr(module, k):
            saved[k] = getattr(module, k)
            setattr(module, k, v)
    return saved


def restore(module, saved):
    for k, v in saved.items():
        setattr(module, k, v)


class Fixture(unittest.TestCase):
    """A minimal healthy corpus: one raw source (recorded in
    a provenance manifest), one citing page with the lockfile
    built over it, a two-entry Black Box chain, well-formed
    registers whose evidence resolves, a decisions register
    whose current form is stated on the citing page, an ideas
    board with a bare unbuilt item, and a small MEMORY.md."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        r = self.root
        # raw + provenance manifest
        write(r / "raw/a.txt", "fixture source line\n")
        data = (r / "raw/a.txt").read_bytes()
        manifest = {"files": {"raw/a.txt": {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}}}
        write(r / "raw/sources/provenance-manifest.json",
              json.dumps(manifest, indent=2) + "\n")
        # citing page (also states the decision's current form)
        write(r / "wiki/page.md",
              "# Fixture page\n\n"
              "The fixture widget stays open under the fixture"
              " rules at all times. ^[cite: raw/a.txt#L1-L1]\n")
        # lockfile + source manifest, built by the real tool
        saved = bind(cite, r, ROOT=r, WIKI=r / "wiki",
                     LOCK_PATH=r / "evaluation/citation-lockfile.json",
                     MANIFEST_PATH=r / "evaluation/source-manifest.jsonl")
        try:
            cite.cmd_build(None)
        finally:
            restore(cite, saved)
        # Black Box: a valid 2-entry chain
        entries = []
        prev = GENESIS_PREV
        for seq in range(2):
            e = {"seq": seq, "action": "genesis" if seq == 0 else "note",
                 "actor": "test", "prev_hash": prev}
            e["entry_hash"] = entry_digest(prev, e)
            entries.append(e)
            prev = e["entry_hash"]
        write_jsonl(r / "wiki/access/black-box-2030.jsonl", entries)
        # registers
        write_jsonl(r / "evaluation/decisions-register.jsonl", [
            {"kind": "header", "register": "decisions-register"},
            {"kind": "decision", "id": "fx-d1", "status": "active",
             "current_form": "The fixture widget stays open under"
                             " the fixture rules at all times.",
             "superseded_forms": [{
                 "form_id": "fx-d1-closed",
                 "superseded_by": "fixture ruling (test)"}]},
        ])
        write_jsonl(r / "evaluation/treatment-register.jsonl", [
            {"kind": "header", "register": "treatment-register"},
            {"kind": "treatment", "id": "treat-0001",
             "subject": {"page": "wiki/page.md", "claim": "x"},
             "treated_by": {"source": "evaluation/decisions-register.jsonl"}},
        ])
        write_jsonl(r / "evaluation/source-grades.jsonl", [
            {"kind": "header", "register": "source-grades"},
            {"kind": "grade", "source": "wiki/page.md",
             "evidence": [{"ref": "raw/a.txt", "note": "fixture"}]},
        ])
        write_jsonl(r / "evaluation/research-log.jsonl", [
            {"kind": "header", "register": "research-log"},
            {"kind": "search", "page": "raw/a.txt (§1)",
             "result": "found"},
        ])
        write_jsonl(r / "evaluation/outcomes.jsonl", [])
        # ideas board: one built, one queued by reference, one bare
        write(r / "wiki/ideas.md",
              "# Ideas\n\n## Approved\n\n"
              "- **Built thing** — approved — **BUILT 2030-10-20**\n"
              "- **Queued thing** — approved (the build of the"
              " consolidated queue)\n"
              "- **Bare thing** — approved, nothing further said\n\n"
              "## Disapproved\n")
        # memory within budget
        self.memory = r / "MEMORY.md"
        write(self.memory, "lean\n")

    # -- assertion 1 ------------------------------------------------
    def test_provenance_passes_then_fails_on_unrecorded_file(self):
        a = close.assertion_provenance(self.root)
        self.assertEqual(a["verdict"], "PASS", a)
        write(self.root / "raw/b.txt", "unrecorded\n")
        a = close.assertion_provenance(self.root)
        self.assertEqual(a["verdict"], "FAIL")
        self.assertTrue(any("raw/b.txt" in e for e in a["exceptions"]))

    # -- assertion 2 ------------------------------------------------
    def test_citations_pass_then_fail_on_unlocked_marker(self):
        a = close.assertion_citations(self.root)
        self.assertEqual(a["verdict"], "PASS", a)
        write(self.root / "wiki/page2.md",
              "# Second page\n\nAnother claim."
              " ^[cite: raw/a.txt#L1-L1]\n")
        a = close.assertion_citations(self.root)
        self.assertEqual(a["verdict"], "FAIL")
        self.assertTrue(any("UNLOCKED" in e for e in a["exceptions"]))

    # -- assertion 3 ------------------------------------------------
    def test_black_box_passes_then_fails_on_tamper(self):
        a = close.assertion_black_box(self.root)
        self.assertEqual(a["verdict"], "PASS", a)
        p = self.root / "wiki/access/black-box-2030.jsonl"
        entries = [json.loads(ln) for ln in
                   p.read_text(encoding="utf-8").splitlines()]
        entries[1]["actor"] = "forged"
        write_jsonl(p, entries)
        a = close.assertion_black_box(self.root)
        self.assertEqual(a["verdict"], "FAIL")

    # -- assertion 4 ------------------------------------------------
    def test_registers_pass_then_fail_on_bad_line(self):
        a, _counts = close.assertion_registers(self.root, None)
        self.assertEqual(a["verdict"], "PASS", a)
        p = self.root / "evaluation/outcomes.jsonl"
        write(p, "{not json\n")
        a, _counts = close.assertion_registers(self.root, None)
        self.assertEqual(a["verdict"], "FAIL")
        self.assertTrue(any("outcomes.jsonl" in e
                            for e in a["exceptions"]))

    def test_registers_fail_on_shrink_vs_previous_close(self):
        prev = {"date": "2030-10-19",
                "register_lines": {"treatment-register.jsonl": 5}}
        a, _counts = close.assertion_registers(self.root, prev)
        self.assertEqual(a["verdict"], "FAIL")
        self.assertTrue(any("treatment-register" in e
                            for e in a["exceptions"]))

    # -- assertion 5 ------------------------------------------------
    def test_decisions_pass_then_fail_without_successor(self):
        a = close.assertion_decisions(self.root)
        self.assertEqual(a["verdict"], "PASS", a)
        p = self.root / "evaluation/decisions-register.jsonl"
        records = [json.loads(ln) for ln in
                   p.read_text(encoding="utf-8").splitlines()]
        records[1]["superseded_forms"] = [{"form_id": "fx-d1-old"}]
        write_jsonl(p, records)
        a = close.assertion_decisions(self.root)
        self.assertEqual(a["verdict"], "FAIL")
        self.assertTrue(any("fx-d1-old" in e for e in a["exceptions"]))

    def test_decisions_fail_when_current_form_unstated(self):
        p = self.root / "evaluation/decisions-register.jsonl"
        records = [json.loads(ln) for ln in
                   p.read_text(encoding="utf-8").splitlines()]
        records[1]["current_form"] = \
            "Zebra quasar jamboree whistles sideways forever."
        write_jsonl(p, records)
        a = close.assertion_decisions(self.root)
        self.assertEqual(a["verdict"], "FAIL")

    # -- assertion 6 ------------------------------------------------
    def test_evidence_passes_then_fails_on_missing_path(self):
        a = close.assertion_evidence(self.root)
        self.assertEqual(a["verdict"], "PASS", a)
        p = self.root / "evaluation/treatment-register.jsonl"
        records = [json.loads(ln) for ln in
                   p.read_text(encoding="utf-8").splitlines()]
        records[1]["subject"]["page"] = "wiki/no-such-page.md"
        write_jsonl(p, records)
        a = close.assertion_evidence(self.root)
        self.assertEqual(a["verdict"], "FAIL")
        self.assertTrue(any("no-such-page" in e
                            for e in a["exceptions"]))

    # -- assertion 7 ------------------------------------------------
    def test_ideas_accounts_and_names_the_bare_item(self):
        a = close.assertion_ideas(self.root)
        self.assertEqual(a["verdict"], "PASS", a)  # surfaces, not forces
        self.assertEqual(a["exceptions"], ["Bare thing"])
        self.assertIn("3 Approved", a["declared"])

    def test_ideas_queue_of_record_note_covers_named_waves(self):
        # The board's own shape: wave blocks headed by preambles
        # ("the wave-4 shortlist"), and a later queue-of-record
        # note folding waves 4-9 into the consolidated queue.
        write(self.root / "wiki/ideas.md",
              "# Ideas\n\n## Approved\n\n"
              "*Approved — the wave-4 shortlist:*\n\n"
              "- **Wave four thing** — approved under delegation\n\n"
              "*Approved — the wave-10 additions. **Queue of"
              " record: the synthesis deduplicates the approved"
              " wave 4–9 items into the consolidated queue.***\n\n"
              "- **Wave ten thing** — approved under delegation\n\n"
              "## Disapproved\n")
        a = close.assertion_ideas(self.root)
        self.assertEqual(a["verdict"], "PASS", a)
        self.assertEqual(a["exceptions"], [])
        self.assertIn("queue-of-record", a["detail"])

    # -- assertion 8 ------------------------------------------------
    def test_memory_budget(self):
        a = close.assertion_memory(self.memory)
        self.assertEqual(a["verdict"], "PASS", a)
        write(self.memory, "x" * (close.MEMORY_BUDGET + 1))
        a = close.assertion_memory(self.memory)
        self.assertEqual(a["verdict"], "FAIL")
        self.assertIn(str(close.MEMORY_BUDGET + 1), a["computed"])

    # -- the whole close ---------------------------------------------
    def test_full_close_writes_filing_and_history(self):
        assertions, history = close.run_close(
            self.root, self.memory, "2030-10-20")
        self.assertEqual(history["assertions"]["failed"], 0, assertions)
        filing = self.root / "wiki/filings/periodic-close-2030-10-20.md"
        self.assertTrue(filing.is_file())
        text = filing.read_text(encoding="utf-8")
        self.assertIn("Bare thing", text)  # exceptions named
        hist = [json.loads(ln) for ln in
                (self.root / "evaluation/close-history.jsonl")
                .read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(hist[0]["kind"], "header")
        self.assertEqual(hist[-1]["kind"], "close")
        self.assertEqual(
            hist[-1]["register_lines"]["treatment-register.jsonl"], 2)
        # a second close compares against the first: no shrink
        a4, _ = close.assertion_registers(
            self.root, close.previous_close(self.root))
        self.assertEqual(a4["verdict"], "PASS", a4)


if __name__ == "__main__":
    unittest.main()
