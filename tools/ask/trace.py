#!/usr/bin/env python3
"""Per-answer structured traces for the Ask door (Marathon R3
lane TB1, row EU6a — Tier A queue).

Pattern: Langfuse-shaped answer tracing (Europe harvest §6,
MIT core — schema re-implemented, nothing copied): every Ask
answer can emit ONE structured trace record — a JSON object
that rides BESIDE the answer as a JSONL line, replaying the
answer path: what was retrieved, what packing decided, and
what the gates decided.

Trace shape (``kind: "ask-trace"``, ``version: 1``):

- ``question_id`` / ``question`` — the answer this trace is of;
- ``mode`` — the Ask mode the record carries (or the default);
- ``retrieved_ids`` — every candidate page id the retrieval
  offered, in offered order (packed, dropped and severed
  alike: the trace shows the road not taken too);
- ``packing`` — the packing decision per passage
  (``packed`` / ``dropped`` / ``severed`` lists with page,
  tokens, score and the drop/sever reason), plus the budget,
  tokens used and the Lost-in-the-Middle flag, read straight
  from an ``evidence_packing.pack_evidence`` result;
- ``gates`` — the gate verdicts the answer passed through:
  the abstention-contract errors for the record, its trust
  verdict, chain-hedge and instruction-leak finding counts,
  and whether it abstained;
- ``coverage_line`` — when the record carries a coverage
  field, its one line (the gap statement is part of the path).

Placement (the recorded seam decision, mirroring coverage.py):
the trace is NOT folded into the answer text and does NOT
change the Q&A record's contract fields. ``pickup.py`` stamps
a supplied trace onto the record as an additive ``trace``
field (like ``coverage`` before it) AND appends it as a JSONL
record to the trace file beside the Q&A file
(``<qa-file stem>.traces.jsonl`` — see :func:`trace_path_beside`).

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_contract  # noqa: E402


def trace_path_beside(qa_file) -> Path:
    """The trace JSONL file beside a Q&A record file:
    ``qa-2026.jsonl`` -> ``qa-2026.traces.jsonl``."""
    qa_file = Path(qa_file)
    name = qa_file.name
    stem = name[:-len(".jsonl")] if name.endswith(".jsonl") else qa_file.stem
    return qa_file.with_name(stem + ".traces.jsonl")


def _packing_block(pack_result) -> dict:
    """Normalise a pack_evidence result into the trace's
    packing block (empty decisions when no pack is supplied)."""
    if not isinstance(pack_result, dict):
        return {"packed": [], "dropped": [], "severed": [],
                "budget": None, "tokens_used": None,
                "lost_in_middle_applied": False,
                "all_evidence_severed": False}

    def entry(p, decision):
        return {"page": p.get("page"), "decision": decision,
                "tokens": p.get("tokens"), "score": p.get("score"),
                "reason": p.get("reason")}

    return {
        "packed": [entry(p, "packed") for p in pack_result.get("packed") or []],
        "dropped": [entry(p, "dropped")
                    for p in pack_result.get("dropped") or []],
        "severed": [entry(p, "severed")
                    for p in pack_result.get("severed") or []],
        "budget": pack_result.get("budget"),
        "tokens_used": pack_result.get("tokens_used"),
        "lost_in_middle_applied":
            bool(pack_result.get("lost_in_middle_applied")),
        "all_evidence_severed":
            bool(pack_result.get("all_evidence_severed")),
    }


def build_trace(record: dict, pack_result=None, wiki_dir=None) -> dict:
    """The structured trace for one answer *record*.

    *pack_result* is an ``evidence_packing.pack_evidence``
    result when the caller has one; without it the packing
    block is honestly empty and the retrieved ids fall back to
    the record's own citations. Gate verdicts are computed
    with the contract's own functions (structural verdict —
    no page text unless *wiki_dir* is supplied).
    """
    record = record if isinstance(record, dict) else {}
    packing = _packing_block(pack_result)
    retrieved = []
    for group in ("packed", "dropped", "severed"):
        for item in packing[group]:
            if item["page"] and item["page"] not in retrieved:
                retrieved.append(item["page"])
    if not retrieved:
        retrieved = [str(c) for c in record.get("citations") or []]
    errors = answer_contract.validate_answer(record)
    coverage = record.get("coverage")
    trace = {
        "kind": "ask-trace",
        "version": 1,
        "question_id": record.get("id"),
        "question": record.get("question"),
        "mode": record.get("mode") or answer_contract.DEFAULT_ASK_MODE,
        "retrieved_ids": retrieved,
        "packing": packing,
        "gates": {
            "contract_errors": errors,
            "contract_ok": not errors,
            "trust_verdict": answer_contract.compute_trust_verdict(
                record, wiki_dir),
            "chain_hedge_findings":
                len(answer_contract.chain_hedge_findings(record)),
            "instruction_leak_findings":
                len(answer_contract.instruction_leak_findings(record)),
            "abstained": bool(record.get("abstained")),
        },
    }
    if isinstance(coverage, dict) and coverage.get("line"):
        trace["coverage_line"] = coverage["line"]
    if record.get("two_phase") or record.get("phase"):
        verification = record.get("verification") or {}
        trace["two_phase"] = {
            "phase": record.get("phase"),
            "verified": record.get("verified"),
            "verification_runs": verification.get("runs"),
            "correction_applied":
                bool(verification.get("correction_applied")),
        }
    return trace


def append_trace(path, trace: dict) -> None:
    """Append *trace* as one JSON line to *path*, flush + fsync
    (the pickup.append_record discipline)."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(trace, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_traces(path) -> list:
    """All trace records in *path*; a missing file gives []."""
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
