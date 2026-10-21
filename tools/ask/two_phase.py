#!/usr/bin/env python3
"""Two-phase answering for the Ask door (Marathon R3 lane TB1,
row 2).

Pattern adapted with credit from AutoRAG Agent 2.0 (Marker
Inc. / NomaDamas, Apache-2.0): a fast PRELIMINARY answer from
retrieval alone, then a VERIFIED final answer that re-opens
the cited sources claim by claim; a user correction (AutoRAG's
``steer()``) forces re-verification — a corrected final can
never be the pre-correction draft re-labelled.

Standing-contract discipline (the lane's hard rule):

- The mode is BEHIND A FLAG, default OFF. ``two_phase_enabled``
  is true only when a payload/record explicitly carries
  ``two_phase: true`` (or the caller passes ``enabled=True``).
  With the flag off, every function here is inert and the
  standing single-phase contract is byte-for-byte the record
  shape that existed before this module.
- A preliminary is NEVER a final answer: it carries
  ``phase: "preliminary"``, ``verified: false`` and the
  UNVERIFIED banner text, and :func:`validate_two_phase`
  refuses any record that presents a preliminary as answered.
- The final must pass the UNCHANGED abstention/conflict gate:
  :func:`verify_final` runs ``answer_contract.validate_answer``
  and ``compute_trust_verdict`` on the finished record; a
  ``hold`` verdict, a contract error, or a failed claim
  verification turns the final into an explicit ABSTENTION
  naming what failed — the gate is never weakened to let a
  two-phase answer through.
- Claim-by-claim verification re-opens each cited page and
  checks the cited passage verbatim (the contract's own
  normalisation), exactly the phase-2 act the sketch states.
  Plain (unscored, passage-less) citations verify as
  "resolves-only": the page exists; no passage claim was made.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_contract  # noqa: E402

UNVERIFIED_BANNER = (
    "UNVERIFIED — preliminary answer (two-phase mode): the "
    "verified final answer has not landed yet."
)


def two_phase_enabled(payload=None, enabled=None) -> bool:
    """The flag: explicit caller choice, else the payload's
    ``two_phase`` field, else OFF (the standing default)."""
    if enabled is not None:
        return bool(enabled)
    if isinstance(payload, dict):
        return payload.get("two_phase") is True
    return False


def make_preliminary(question_entry: dict, answer_text: str,
                     citations: list, citation_details: list = None) -> dict:
    """Phase 1: the fast preliminary event/record.

    Deliberately NOT a Q&A record: it is marked preliminary and
    unverified on its face, and carries the banner the portal
    renders until phase 2 lands.
    """
    return {
        "phase": "preliminary",
        "preliminary": True,
        "verified": False,
        "banner": UNVERIFIED_BANNER,
        "id": question_entry.get("id"),
        "question": question_entry.get("question"),
        "answer": answer_text,
        "citations": list(citations or []),
        "citation_details": list(citation_details or []),
    }


def verify_claims(record: dict, wiki_dir) -> list:
    """Re-open every cited source and verify claim by claim.

    Returns one verdict per citation entry (top-level plus
    sub-answers): ``{"page", "status"}`` where status is
    ``verified`` (passage found verbatim in the re-opened
    page), ``resolves-only`` (plain citation; the page
    resolves, no passage was claimed), ``failed-passage``
    (the passage is NOT in the page), or ``unresolved`` (the
    citation names no real page).
    """
    verdicts = []
    entries = []
    details = record.get("citation_details") or []
    by_page = {str(d.get("page")): d for d in details
               if isinstance(d, dict)}
    for citation in record.get("citations") or []:
        detail = by_page.get(str(citation))
        if detail and detail.get("passage"):
            entries.append({"page": str(citation),
                            "passage": detail["passage"]})
        else:
            entries.append({"page": str(citation), "passage": None})
    for sub in record.get("sub_answers") or []:
        if isinstance(sub, dict):
            entries.extend(
                {"page": str(c), "passage": None}
                for c in sub.get("citations") or [])
    for entry in entries:
        path = answer_contract.citation_path(entry["page"], wiki_dir)
        if path is None:
            verdicts.append({"page": entry["page"], "status": "unresolved"})
            continue
        if entry["passage"] is None:
            verdicts.append({"page": entry["page"],
                             "status": "resolves-only"})
            continue
        text = path.read_text(encoding="utf-8")
        ok = answer_contract._passage_in_page(entry["passage"], text)
        verdicts.append({"page": entry["page"],
                         "status": "verified" if ok else "failed-passage"})
    return verdicts


def verify_final(preliminary: dict, final_payload: dict, wiki_dir,
                 correction: str = None) -> dict:
    """Phase 2: build the verified final record, or an abstention.

    *final_payload* is a normal answer payload (answer,
    citations, optional citation_details / sub_answers /
    question_type / mode). The preliminary is never mutated;
    when *correction* is supplied the run is a RE-verification:
    the preliminary is recorded as superseded, the correction
    is carried verbatim on the final, and the verification run
    count increments — a final whose correction was not
    re-verified is refused by :func:`validate_two_phase`.

    Gate (unchanged): claim verification must have no
    ``failed-passage`` / ``unresolved`` verdicts, the payload
    must satisfy ``answer_contract.validate_answer``, and the
    trust verdict must not be ``hold``. Any failure produces an
    explicit abstention record naming the failure — never a
    weakened pass.
    """
    runs = 1
    if correction:
        runs = 2
    verdicts = verify_claims(final_payload, wiki_dir)
    failed = [v for v in verdicts
              if v["status"] in ("failed-passage", "unresolved")]
    errors = answer_contract.validate_answer(final_payload, wiki_dir)
    record = dict(final_payload)
    record["phase"] = "final"
    record["two_phase"] = True
    verification = {
        "claims": verdicts,
        "runs": runs,
        "correction_applied": bool(correction),
    }
    if correction:
        verification["correction"] = correction
        verification["preliminary_superseded"] = True
    record["verification"] = verification
    gate_reasons = []
    if failed:
        gate_reasons.append(
            "claim verification failed for: "
            + ", ".join(sorted({v["page"] for v in failed})))
    if errors:
        gate_reasons.append("contract: " + "; ".join(errors))
    verdict = None
    if not gate_reasons:
        verdict = answer_contract.compute_trust_verdict(record, wiki_dir)
        if verdict == "hold":
            gate_reasons.append("trust verdict is hold")
    if gate_reasons:
        record["abstained"] = True
        record["abstention_reason"] = "; ".join(gate_reasons)
        record["verified"] = False
        # An abstention keeps its answer text (the contract's
        # rule 2): state the outcome plainly for the reader.
        record["answer"] = (
            "Abstained after two-phase verification: "
            + record["abstention_reason"] + ".")
        record["citations"] = []
        record.pop("citation_details", None)
    else:
        record["verified"] = True
        record["trust_verdict"] = verdict
    return record


def validate_two_phase(record: dict) -> list:
    """Shape checks specific to two-phase records.

    - a preliminary presented as a stored/answered final is an
      error;
    - a final must carry its verification block with at least
      one verification run;
    - a final carrying a correction must show the correction
      was applied in a re-verification run (runs >= 2 and
      ``correction_applied``) — the steer-and-reverify rule;
    - a non-abstained final must be marked verified.
    """
    if not isinstance(record, dict):
        return ["two-phase record must be a JSON object"]
    errors = []
    if record.get("phase") == "preliminary" or record.get("preliminary"):
        if record.get("status") == "answered" or record.get("verified"):
            errors.append(
                "a preliminary answer may not be presented as an "
                "answered/verified final")
        return errors
    if record.get("phase") != "final":
        return errors
    verification = record.get("verification")
    if not isinstance(verification, dict):
        errors.append("final record carries no verification block")
        return errors
    if not isinstance(verification.get("runs"), int) \
            or verification["runs"] < 1:
        errors.append("verification block names no verification run")
    correction = verification.get("correction")
    if correction:
        if not verification.get("correction_applied") \
                or verification.get("runs", 0) < 2:
            errors.append(
                "a user correction forces re-verification: the "
                "final must show a second verification run with "
                "the correction applied")
        if not verification.get("preliminary_superseded"):
            errors.append(
                "a corrected final must record the preliminary "
                "as superseded")
    if not record.get("abstained") and record.get("verified") is not True:
        errors.append("a non-abstained final must be marked verified")
    return errors
