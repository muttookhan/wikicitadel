#!/usr/bin/env python3
"""Pickup helper for the Ask door (Lens Ask) — reference deployment.

Stdlib-only helper used by the pickup agent (see pickup.md /
pickup-instructions.md in this directory). The harness in this
directory (this helper, the procedure, the agent instructions)
describes ONE reference deployment of the Ask door: a static-web-app
host with a small service API in front of a question store. The
answer pipeline it drives (answer_contract.py, evidence_packing.py,
clarification.py, severance.py, standing.py) is deployment-neutral.

The owner asks questions in the Lens. In the reference deployment,
questions live in a table store behind a service API on the static
web app:

    GET  {base}/api/questions?status=pending
    POST {base}/api/questions/<id>/answered   {"answer_ref": "<ref>"}

Both calls carry the service token in the ``x-ask-token`` header. The
token is read at runtime from ``ask-service.token`` in the gateway state
dir (default ``~/.local/state/wikicitadel-gateway``). Its value is never
printed by this module.

Answered Q&A is recorded, append-only, in ``wiki/access/qa-2026.jsonl``
(the Lens build renders that file), and a substantive answer is also
staged as a query-page proposal for the wiki gateway's normal
review/promotion path.

Every recorded answer satisfies the **abstention contract**
(``answer_contract.py``, batch 2.1): it carries citations to wiki
pages actually read, or it is an explicit abstention
(``abstained`` + ``abstention_reason``). ``record-answer`` validates
the answer file against the contract — citations present and
resolving, sub-answers (for decomposed compound questions) each
cited or abstained — and refuses anything that fails. The
``validate`` subcommand checks already-stored records the same way.

The record also carries the question's Ask **mode** (from the
question entry), any **scored citations** (``citation_details``:
per-citation relevance score + the exact supporting passage,
validated against the cited pages' text), and a deterministic
**trust_verdict** (``ok`` / ``hold`` / ``review``) computed at
record time. Evidence is packed to a token budget before composing
with ``evidence_packing.py`` (see pickup.md).

The pure functions (``build_qa_record``, ``append_record``,
``read_records``, ``stage_proposal_markdown``, ``load_service_token``)
are importable and testable without any network access. The network
surface is deliberately thin: ``list_pending`` and ``mark_answered``.

The staged proposal also renders, when the record carries the
structure for it, a claim-grouped citation section (W3):
citations attached per claim above the flat "Sources used"
list, grouped from the record's own provenance sentence links
or sub-answer decomposition by ``tools/ask/claim_grouping.py``
— presentation only, read from the record, never re-derived
from the prose. Records without that structure render
byte-identically to before.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_contract  # noqa: E402  (same directory; the abstention contract)

DEFAULT_BASE_URL = "https://wikicitadel.example.invalid"
DEFAULT_STATE_DIR = "~/.local/state/wikicitadel-gateway"
TOKEN_FILENAME = "ask-service.token"
AUTHORISATION_REF = "owner-directive-build-the-ask-door"
QA_RELATIVE_PATH = "wiki/access/qa-2026.jsonl"


def repo_root() -> Path:
    """Repository root, derived from this script's location.

    tools/ask/pickup.py -> parents[0]=ask, [1]=tools, [2]=repo root.
    """
    return Path(__file__).resolve().parents[2]


def default_qa_file() -> Path:
    return repo_root() / "wiki" / "access" / "qa-2026.jsonl"


def default_staging_dir() -> Path:
    return repo_root() / "staging" / "proposed"


# ---------------------------------------------------------------------------
# Pure / filesystem functions
# ---------------------------------------------------------------------------

def load_service_token(state_dir) -> str:
    """Read the Ask service token from ``<state_dir>/ask-service.token``.

    Returns the token with surrounding whitespace stripped. The value is
    a secret: callers must never print or log it.
    """
    path = Path(state_dir).expanduser() / TOKEN_FILENAME
    return path.read_text(encoding="utf-8").strip()


def build_qa_record(question_entry: dict, answer_text: str,
                    citations: list, answered_at: str,
                    question_type: str = None,
                    abstention_reason: str = None,
                    sub_answers: list = None,
                    mode: str = None,
                    citation_details: list = None,
                    trust_verdict: str = None,
                    clarification: dict = None,
                    coverage: dict = None,
                    two_phase: dict = None,
                    trace: dict = None,
                    provenance: dict = None,
                    depth=None) -> dict:
    """Build one Q&A record for ``wiki/access/qa-2026.jsonl``.

    The abstention contract (``answer_contract.py``) fields are added
    only when supplied, so a plain cited answer keeps the original
    record shape: ``abstained``/``abstention_reason`` when the answer
    is an abstention, ``question_type`` when the answerer classified
    the question, and ``sub_answers`` when a compound question was
    decomposed (each sub-answer keeps its own citations or its own
    abstention).

    The rest of batch 2.1 rides the same additive rule: ``mode``
    (the Ask mode the asker chose — taken from the explicit argument
    or the question entry; stamped only when it is a valid mode),
    ``citation_details`` (per-citation relevance score + supporting
    passage, as ``{page, score, passage}`` entries) and
    ``trust_verdict`` (the deterministic verdict computed by
    ``answer_contract.compute_trust_verdict``) are stamped only when
    supplied.

    Item 61 rides the same rule: ``clarification`` — the reference-
    interview exchange that preceded this answer (paraphrase the
    asker confirmed, the neutral stem, the asker's reply, the
    timing route; built by ``clarification.qa_clarification_field``)
    — is stamped only when the answer followed a clarification.

    Marathon R2 lane B1 rides the same rule: ``coverage`` — the
    computed coverage-gap record built by
    ``tools/ask/coverage.py`` (searched facets with zero hits +
    the newest packed evidence date + its one line) — is stamped
    only when supplied. It lives on the RECORD and in the staged
    proposal (the pickup report), never appended to the answer
    text; see coverage.py for the placement decision.

    Marathon R3 lane TB1 rides the same rule twice more:
    ``two_phase`` — the two-phase verification block built by
    ``tools/ask/two_phase.py`` (present only when the two-phase
    flag was ON for this answer; the flag defaults OFF and the
    standing contract is unchanged without it) — and ``trace``
    — the per-answer structured trace built by
    ``tools/ask/trace.py`` (EU6a), which is ALSO appended as a
    JSONL record beside the Q&A file by the record-answer flow.
    Both are stamped only when supplied.

    W3 (2026-10-22) rides the same rule once more:
    ``provenance`` — the answer provenance pack built by
    ``tools/ask/provenance.py`` (per-citation document hashes
    and retrieval/scoring paths, per-sentence support, the
    policy snapshot, absent terms on a zero result, the
    source-type label and a verify block) — is stamped only
    when supplied. It is recorded from answer-time pipeline
    state, never reconstructed afterwards; see provenance.py.

    W6 (2026-10-22) adds ``depth`` — the query depth ladder
    (``tools/ask/depth_ladder.py``: quick / standard / deep).
    Depth is DECLARED state, known before the answer is
    composed, so it is resolved here — from the explicit
    ``depth`` argument or the question entry's own ``depth``
    field — and stamped as the level's full bundle whenever
    a declaration exists. No declaration stamps nothing: the
    record is the default (standard) depth and keeps the
    pre-ladder shape byte for byte. An invalid declaration
    stamps nothing here; the record-answer CLI refuses it
    by name before a record is built (see
    ``depth_declaration_error``).
    """
    record = {
        "id": question_entry["id"],
        "question": question_entry["question"],
        "asker": question_entry.get("asker"),
        "asked_at": question_entry.get("asked_at"),
        "answered_at": answered_at,
        "answer": answer_text,
        "citations": list(citations),
        "status": "answered",
    }
    if question_type is not None:
        record["question_type"] = question_type
    if abstention_reason is not None:
        record["abstained"] = True
        record["abstention_reason"] = abstention_reason
    if sub_answers:
        record["sub_answers"] = [
            _build_sub_answer_record(sub) for sub in sub_answers
        ]
    resolved_mode = mode if mode is not None else question_entry.get("mode")
    if resolved_mode in answer_contract.ASK_MODES:
        record["mode"] = resolved_mode
    ladder = _depth_ladder_module()
    resolved_depth, depth_basis = ladder.resolve_depth(
        depth, question_entry.get("depth"))
    if resolved_depth is not None and depth_basis == "declared":
        record["depth"] = ladder.depth_block(
            resolved_depth, depth_basis)
    if citation_details:
        record["citation_details"] = [
            _build_citation_detail(detail) for detail in citation_details
        ]
    if trust_verdict is not None:
        record["trust_verdict"] = trust_verdict
    if clarification is not None:
        record["clarification"] = clarification
    if coverage is not None:
        record["coverage"] = coverage
    if two_phase is not None:
        record["two_phase"] = two_phase
    if trace is not None:
        record["trace"] = trace
    if provenance is not None:
        record["provenance"] = provenance
    return record


def _build_citation_detail(detail: dict) -> dict:
    """Normalise one scored-citation detail for the Q&A record."""
    record = {"page": detail.get("page") or detail.get("id") or ""}
    if detail.get("score") is not None:
        record["score"] = detail["score"]
    if detail.get("passage") is not None:
        record["passage"] = detail["passage"]
    # Marathon R2 lane B1 (additive, only when supplied): the
    # chunk's section anchor (read by tools/ask/show_chunks.py)
    # and its evidence date (read by tools/ask/coverage.py).
    if detail.get("anchor") is not None:
        record["anchor"] = detail["anchor"]
    if detail.get("date") is not None:
        record["date"] = detail["date"]
    return record


def _build_sub_answer_record(sub: dict) -> dict:
    """Normalise one decomposed sub-answer for the Q&A record."""
    record = {
        "question": sub.get("question", ""),
        "answer": sub.get("answer", ""),
        "citations": list(sub.get("citations") or []),
    }
    reason = sub.get("abstention_reason")
    if reason is not None:
        record["abstained"] = True
        record["abstention_reason"] = reason
    if sub.get("question_type") is not None:
        record["question_type"] = sub["question_type"]
    if sub.get("citation_details"):
        record["citation_details"] = [
            _build_citation_detail(d) for d in sub["citation_details"]
        ]
    return record


def append_record(path, record: dict) -> None:
    """Append ``record`` as one JSON line to ``path``, flush + fsync."""
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def read_records(path) -> list:
    """Read all Q&A records from ``path``. A missing file gives ``[]``."""
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def stage_proposal_markdown(record: dict) -> str:
    """Render a query-page proposal (markdown) for the wiki gateway."""
    question = str(record.get("question", ""))
    answer = str(record.get("answer", ""))
    answered_at = str(record.get("answered_at", ""))
    answered_date = answered_at[:10]
    title = "Question \u2014 " + question[:60]

    lines = []
    lines.append("---")
    # json.dumps gives a safely quoted YAML scalar for the title.
    lines.append("title: " + json.dumps(title, ensure_ascii=False))
    lines.append("type: query")
    lines.append("created: " + answered_date)
    lines.append("updated: " + answered_date)
    lines.append("sources: []")
    lines.append("tags: [lens-ask]")
    lines.append("---")
    lines.append("")
    lines.append("# " + title)
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append(question)
    lines.append("")
    if record.get("mode"):
        lines.append(
            "Asked in **" + str(record["mode"]) + "** mode."
        )
        lines.append("")
    depth = record.get("depth")
    if isinstance(depth, dict) and depth.get("level"):
        lines.append(
            "Answered at **" + str(depth.get("label") or depth["level"])
            + "** depth (" + str(depth.get("basis") or "declared")
            + ") — candidate pool "
            + str(depth.get("candidate_pool"))
            + ", evidence budget "
            + str(depth.get("pack_budget_tokens"))
            + " tokens; sentence scoring "
            + str(depth.get("sentence_scoring")) + ". Cost: "
            + str(depth.get("cost") or "") + " "
            + str(depth.get("abstention_invariant") or "")
        )
        lines.append("")
    if record.get("trust_verdict"):
        lines.append(
            "Trust verdict: **" + str(record["trust_verdict"]) + "** "
            "(deterministic — see tools/ask/answer_contract.py)."
        )
        lines.append("")
    coverage = record.get("coverage")
    if coverage:
        lines.append("## Coverage")
        lines.append("")
        if isinstance(coverage, dict):
            lines.append(str(coverage.get("line", "")))
        else:
            lines.append(str(coverage))
        lines.append("")
    if record.get("two_phase"):
        lines.append("## Two-phase verification")
        lines.append("")
        lines.append(
            "This answer ran in two-phase mode (tools/ask/"
            "two_phase.py): a marked preliminary, then a final "
            "verified claim by claim against the re-opened "
            "sources."
        )
        lines.append("")
    if record.get("trace"):
        lines.append("## Trace")
        lines.append("")
        lines.append(
            "A structured trace of this answer's retrieval, "
            "packing and gate decisions was filed beside the "
            "Q&A record (tools/ask/trace.py, EU6a)."
        )
        lines.append("")
    provenance = record.get("provenance")
    if provenance:
        lines.append("## Provenance")
        lines.append("")
        source_type = provenance.get("source_type") or {}
        if source_type.get("label"):
            lines.append(str(source_type["label"]))
            lines.append("")
        snapshot = provenance.get("policy_snapshot") or {}
        if snapshot:
            bits = []
            if snapshot.get("git_head"):
                bits.append("git " + str(snapshot["git_head"])[:12])
            if snapshot.get("governance_state_hash"):
                bits.append(
                    "governance state "
                    + str(snapshot["governance_state_hash"])[:12]
                )
            if snapshot.get("abstain_threshold") is not None:
                bits.append(
                    "abstention threshold "
                    + str(snapshot["abstain_threshold"])
                )
            if bits:
                lines.append(
                    "Assembled against: " + "; ".join(bits) + "."
                )
                lines.append("")
        for citation in provenance.get("citations") or []:
            if not isinstance(citation, dict):
                continue
            bits = []
            document = citation.get("document") or {}
            if document.get("sha256"):
                bits.append("sha256 " + str(document["sha256"])[:12])
            path = citation.get("path") or {}
            packing = path.get("packing") or {}
            if packing.get("decision"):
                bits.append("packing: " + str(packing["decision"]))
            governance = path.get("governance") or {}
            if governance.get("state"):
                bits.append("governance: " + str(governance["state"]))
            summary = citation.get("support_summary") or {}
            if summary.get("sentences"):
                bits.append(
                    "supports %d sentence(s), %d fully"
                    % (summary["sentences"], summary.get("supported", 0))
                )
            lines.append(
                "- [[" + str(citation.get("page")) + "]]"
                + (" — " + "; ".join(bits) if bits else "")
            )
        lines.append("")
        if provenance.get("absent_terms"):
            lines.append(
                "Absent terms (in no document): "
                + ", ".join(
                    str(t) for t in provenance["absent_terms"]
                )
                + "."
            )
            lines.append("")
        verify = provenance.get("verify") or {}
        checks = verify.get("checks") or []
        if checks:
            lines.append("Verify (do not trust — check):")
            lines.append("")
            for check in checks:
                if isinstance(check, dict) and check.get("command"):
                    lines.append("- `" + str(check["command"]) + "`")
            lines.append("")
    clarification = record.get("clarification")
    if clarification:
        lines.append("## Clarification")
        lines.append("")
        lines.append(
            "This answer followed a reference-interview clarification "
            "(item 61): the question's evidence measurably split, so "
            "the door asked before answering."
        )
        lines.append("")
        lines.append(str(clarification.get("paraphrase", "")))
        lines.append("")
        lines.append("Asker's reply: " + str(clarification.get("reply", "")))
        lines.append("")
    lines.append("## Answer")
    lines.append("")
    lines.append(answer)
    lines.append("")

    if record.get("abstained"):
        lines.append("## Abstention")
        lines.append("")
        lines.append(
            "This answer is an abstention under the Ask abstention "
            "contract: the wiki does not hold sufficient evidence to "
            "answer. Missing: " + str(record.get("abstention_reason", ""))
        )
        lines.append("")

    sub_answers = record.get("sub_answers") or []
    if sub_answers:
        lines.append("## Sub-answers")
        lines.append("")
        for sub in sub_answers:
            lines.append("### " + str(sub.get("question", "")))
            lines.append("")
            lines.append(str(sub.get("answer", "")))
            lines.append("")
            if sub.get("abstained"):
                lines.append(
                    "Abstained — missing: "
                    + str(sub.get("abstention_reason", ""))
                )
                lines.append("")

    claim_lines = _claim_group_lines(record)
    if claim_lines:
        lines.extend(claim_lines)

    lesson_lines = _lesson_lines(record)
    if lesson_lines:
        lines.extend(lesson_lines)

    lines.append("## Sources used")
    lines.append("")
    citations = record.get("citations") or []
    details = {
        str(d.get("page")): d
        for d in (record.get("citation_details") or [])
        if isinstance(d, dict)
    }
    if citations:
        for citation in citations:
            detail = details.get(str(citation))
            if detail and detail.get("score") is not None:
                lines.append(
                    "- [[" + str(citation) + "]] — relevance "
                    + str(detail["score"])
                )
                if detail.get("passage"):
                    lines.append("")
                    lines.append("> " + str(detail["passage"]))
                    lines.append("")
            else:
                lines.append("- [[" + str(citation) + "]]")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append(
        "Filed from the Lens Ask panel. Owner authorisation ref: "
        + AUTHORISATION_REF + "."
    )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Network-thin functions (urllib only)
# ---------------------------------------------------------------------------

def _request_json(request: urllib.request.Request, what: str):
    """Run ``request``; raise with the HTTP status in the message on non-2xx.

    Transport-level failures (connection dropped/reset before a response,
    timeouts) are retried with backoff — the Azure endpoint intermittently
    drops connections (seen repeatedly in production use), and a
    single drop must not fail a pickup run. HTTP error statuses are real
    answers and are NOT retried.
    """
    import http.client
    import time

    transport_errors = (
        http.client.RemoteDisconnected,
        ConnectionResetError,
        ConnectionAbortedError,
        TimeoutError,
    )
    delays = (2, 5, 12)
    last_exc = None
    status = body = None
    for attempt in range(len(delays) + 1):
        try:
            with urllib.request.urlopen(request) as response:
                status = getattr(response, "status", 200)
                body = response.read()
            break
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                "%s failed: HTTP %s" % (what, exc.code)
            ) from exc
        except transport_errors as exc:
            last_exc = exc
            if attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise RuntimeError("%s failed: %s" % (what, exc)) from exc
        except urllib.error.URLError as exc:
            # URLError wraps some transport failures in .reason.
            if isinstance(getattr(exc, "reason", None), transport_errors):
                last_exc = exc
                if attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
            raise RuntimeError("%s failed: %s" % (what, exc)) from exc
    if status is not None and not (200 <= int(status) < 300):
        raise RuntimeError("%s failed: HTTP %s" % (what, status))
    if not body:
        return None
    text = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    if not text.strip():
        return None
    return json.loads(text)


def list_pending(base_url: str, token: str):
    """GET {base}/api/questions?status=pending with the x-ask-token header."""
    base = str(base_url).rstrip("/")
    url = base + "/api/questions?status=pending"
    request = urllib.request.Request(
        url,
        headers={
            "x-ask-token": token,
            "Accept": "application/json",
        },
        method="GET",
    )
    return _request_json(request, "list pending questions")


def mark_answered(base_url: str, token: str, qid, answer_ref: str):
    """POST {base}/api/questions/<id>/answered with {"answer_ref": ...}."""
    base = str(base_url).rstrip("/")
    url = (
        base
        + "/api/questions/"
        + urllib.parse.quote(str(qid), safe="")
        + "/answered"
    )
    data = json.dumps({"answer_ref": answer_ref}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "x-ask-token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    return _request_json(request, "mark question %s answered" % qid)


_COVERAGE_MODULE = None


def _coverage_module():
    """Load tools/ask/coverage.py by path (the lazy pattern
    answer_contract uses), so this module stays importable on
    its own and coverage stays an opt-in, additive field."""
    global _COVERAGE_MODULE
    if _COVERAGE_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "coverage.py"
        spec = importlib.util.spec_from_file_location(
            "ask_coverage", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _COVERAGE_MODULE = module
    return _COVERAGE_MODULE


def _payload_coverage(payload: dict):
    """The coverage record for a record-answer payload, or None.

    An explicit ``coverage`` dict in the payload is stamped
    as-is; a payload carrying ``searched_facets`` (what the
    pickup searched, with hit counts) gets its coverage
    computed from its own citation details by coverage.py.
    Anything else records no coverage — the field is additive
    and its absence changes nothing.
    """
    coverage = payload.get("coverage")
    if isinstance(coverage, dict):
        return coverage
    if payload.get("searched_facets") is not None:
        return _coverage_module().coverage_for_record(
            payload, payload.get("searched_facets")
        )
    return None


_TRACE_MODULE = None


def _trace_module():
    """Load tools/ask/trace.py by path (the lazy pattern used
    for coverage), so the trace seam stays opt-in and additive."""
    global _TRACE_MODULE
    if _TRACE_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "trace.py"
        spec = importlib.util.spec_from_file_location("ask_trace", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TRACE_MODULE = module
    return _TRACE_MODULE


def _payload_trace(payload: dict, record: dict, qa_file):
    """Append the payload's trace beside the Q&A file, if any.

    An explicit ``trace`` dict in the payload is filed as-is;
    the caller may instead set ``emit_trace: true`` to have the
    trace built from the finished record. Anything else files
    no trace — the seam is additive and its absence changes
    nothing.
    """
    trace_mod = _trace_module()
    trace = payload.get("trace")
    if not isinstance(trace, dict) and payload.get("emit_trace"):
        trace = trace_mod.build_trace(record)
    if isinstance(trace, dict):
        trace_mod.append_trace(trace_mod.trace_path_beside(qa_file), trace)
        return trace
    return None


_CLAIM_GROUPING_MODULE = None


def _claim_grouping_module():
    """Load tools/ask/claim_grouping.py by path (the lazy
    pattern used for coverage, trace and provenance), so the
    claim-grouped presentation stays opt-in and additive:
    records carrying no claim structure render exactly as
    before."""
    global _CLAIM_GROUPING_MODULE
    if _CLAIM_GROUPING_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "claim_grouping.py"
        spec = importlib.util.spec_from_file_location(
            "ask_claim_grouping", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _CLAIM_GROUPING_MODULE = module
    return _CLAIM_GROUPING_MODULE


def _claim_group_lines(record: dict):
    """The claim-grouped citation section lines for a staged
    proposal, or None when the record carries no recorded
    claim structure (see claim_grouping.py)."""
    return _claim_grouping_module().render_claim_groups(record)


_LESSONS_MODULE = None


def _lessons_module():
    """Load tools/ask/lessons.py by path (the lazy pattern
    used for claim grouping and provenance), so the lessons
    seam stays opt-in and additive."""
    global _LESSONS_MODULE
    if _LESSONS_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "lessons.py"
        spec = importlib.util.spec_from_file_location(
            "ask_lessons", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _LESSONS_MODULE = module
    return _LESSONS_MODULE


def _lesson_lines(record: dict):
    """The lessons section lines for a staged proposal, or
    None when the record carries no matched lessons (see
    lessons.py)."""
    return _lessons_module().render_lessons(record)


def _payload_lessons(payload: dict, record: dict):
    """The lessons block for a finished record, or None.

    An explicit ``lessons`` dict in the payload is stamped
    as-is. A payload carrying ``emit_lessons: true`` (or a
    ``lessons_inputs`` dict, whose question/pages override
    the record's own) gets its block built from the finished
    record against the corrections ledger. Anything else
    records no lessons — the field is additive and its
    absence changes nothing. The block is computed HERE,
    after the answer exists and its trust verdict is
    stamped, from the record alone: it cannot have
    influenced retrieval, scoring or the abstention
    decision (see lessons.py). A failure in the seam drops
    the block, never the answer: lessons are advisory
    presentation, and no answer loses its record to them.
    """
    lessons = payload.get("lessons")
    if isinstance(lessons, dict):
        return lessons
    inputs = payload.get("lessons_inputs")
    if isinstance(inputs, dict) or payload.get("emit_lessons"):
        inputs = inputs if isinstance(inputs, dict) else {}
        probe = dict(record)
        if inputs.get("question") is not None:
            probe["question"] = inputs["question"]
        if inputs.get("pages") is not None:
            probe["citations"] = list(inputs["pages"])
            probe.pop("citation_details", None)
            probe.pop("provenance", None)
        try:
            return _lessons_module().build_lessons_block(
                probe, repo_root())
        except Exception:
            return None
    return None


_DEPTH_LADDER_MODULE = None


def _depth_ladder_module():
    """Load tools/ask/depth_ladder.py by path (the lazy
    pattern used for lessons and provenance), so the ladder
    stays a declared, additive seam."""
    global _DEPTH_LADDER_MODULE
    if _DEPTH_LADDER_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "depth_ladder.py"
        spec = importlib.util.spec_from_file_location(
            "ask_depth_ladder", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _DEPTH_LADDER_MODULE = module
    return _DEPTH_LADDER_MODULE


def depth_declaration_error(payload: dict):
    """The named error for a payload's depth declaration, or
    None. A declaration is the payload's own ``depth`` (a
    level name or a full block dict) or its question entry's
    ``depth`` field; anything else that is not a ladder level
    is refused by name — a door never silently answers at a
    different depth than the one declared."""
    ladder = _depth_ladder_module()
    error = ladder.declaration_error(payload.get("depth"))
    if error:
        return error
    entry = payload.get("question_entry") or {}
    return ladder.declaration_error(
        entry.get("depth"), where="question depth")


_PROVENANCE_MODULE = None


def _provenance_module():
    """Load tools/ask/provenance.py by path (the lazy pattern
    used for coverage and trace), so the provenance seam stays
    opt-in and additive."""
    global _PROVENANCE_MODULE
    if _PROVENANCE_MODULE is None:
        import importlib.util

        path = Path(__file__).resolve().parent / "provenance.py"
        spec = importlib.util.spec_from_file_location(
            "ask_provenance", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _PROVENANCE_MODULE = module
    return _PROVENANCE_MODULE


def _payload_provenance(payload: dict, record: dict):
    """The provenance envelope for a finished record, or None.

    An explicit ``provenance`` dict in the payload is stamped
    as-is. A payload carrying ``provenance_inputs`` — the
    answer-time pipeline state (``pack_result`` from
    evidence_packing and ``retrieval`` diagnostics from the
    search stages) — gets its envelope built from the finished
    record against the real wiki tree; ``emit_provenance:
    true`` builds it from the record alone. Anything else
    records no provenance — the field is additive and its
    absence changes nothing. Provenance is built HERE, at
    record time, from the state the answer was actually made
    with — never reconstructed later (see provenance.py).
    """
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        return provenance
    inputs = payload.get("provenance_inputs")
    if isinstance(inputs, dict) or payload.get("emit_provenance"):
        inputs = inputs if isinstance(inputs, dict) else {}
        return _provenance_module().build_provenance(
            record,
            pack_result=inputs.get("pack_result"),
            retrieval=inputs.get("retrieval"),
            wiki_dir=repo_root() / "wiki",
            root=repo_root(),
        )
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Lens Ask pickup helper (see tools/ask/pickup.md)."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Lens / service API base URL (default: %(default)s)",
    )
    parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help="Gateway state dir holding ask-service.token "
             "(default: %(default)s)",
    )
    parser.add_argument(
        "--qa-file",
        default=None,
        help="Q&A record file (default: <repo>/wiki/access/qa-2026.jsonl)",
    )
    parser.add_argument(
        "--staging-dir",
        default=None,
        help="Where record-answer writes proposal markdown "
             "(default: <repo>/staging/proposed)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list", help="Print pending questions from the service API as JSON."
    )

    record_parser = subparsers.add_parser(
        "record-answer",
        help="Append a Q&A record and write its proposal markdown.",
    )
    record_parser.add_argument(
        "--answer-file",
        required=True,
        help="JSON file with {question_entry, answer, citations} plus "
             "the optional contract fields question_type, "
             "abstention_reason, sub_answers, mode and "
             "citation_details (see answer_contract.py), the "
             "optional provenance / provenance_inputs / "
             "emit_provenance fields (see provenance.py), "
             "the optional lessons / emit_lessons fields "
             "(see lessons.py), and the optional depth "
             "declaration (a ladder level name or block; "
             "see depth_ladder.py).",
    )

    subparsers.add_parser(
        "validate",
        help="Check stored Q&A records against the abstention contract.",
    )

    mark_parser = subparsers.add_parser(
        "mark", help="Mark a question answered via the service API."
    )
    mark_parser.add_argument("qid", help="Question id.")
    mark_parser.add_argument("answer_ref", help="Answer reference string.")

    args = parser.parse_args(argv)

    qa_file = Path(args.qa_file) if args.qa_file else default_qa_file()
    staging_dir = (
        Path(args.staging_dir) if args.staging_dir else default_staging_dir()
    )

    if args.command == "list":
        token = load_service_token(args.state_dir)
        pending = list_pending(args.base_url, token)
        print(json.dumps(pending, ensure_ascii=False, indent=2))
        return 0

    if args.command == "validate":
        records = read_records(qa_file)
        wiki_dir = repo_root() / "wiki"
        failures = 0
        for record in records:
            errors = answer_contract.validate_answer(record, wiki_dir)
            if errors:
                failures += 1
                print("%s: FAIL" % record.get("id"))
                for error in errors:
                    print("  - %s" % error)
            else:
                print("%s: ok" % record.get("id"))
            # Informational only: a stored trust verdict can drift
            # when the evidence state moves (e.g. a cited page gains
            # a contradiction callout). Drift is reported, not failed.
            stored_verdict = record.get("trust_verdict")
            if stored_verdict is not None:
                current = answer_contract.compute_trust_verdict(
                    record, wiki_dir
                )
                if current != stored_verdict:
                    print(
                        "  note: trust_verdict drift — stored %r, "
                        "evidence now computes %r"
                        % (stored_verdict, current)
                    )
        print(
            "%d record(s), %d failing the abstention contract"
            % (len(records), failures)
        )
        return 1 if failures else 0

    if args.command == "record-answer":
        with open(args.answer_file, encoding="utf-8") as fh:
            payload = json.load(fh)
        # The abstention contract is enforced here, deterministically:
        # an answer with no citations and no abstention is refused —
        # nothing is appended and no proposal is written.
        errors = answer_contract.validate_answer(
            payload, repo_root() / "wiki"
        )
        if errors:
            for error in errors:
                print("record-answer refused: %s" % error, file=sys.stderr)
            return 1
        depth_error = depth_declaration_error(payload)
        if depth_error:
            print("record-answer refused: %s" % depth_error,
                  file=sys.stderr)
            return 1
        question_entry = payload["question_entry"]
        record = build_qa_record(
            question_entry,
            payload["answer"],
            payload.get("citations") or [],
            _utc_now_iso(),
            question_type=payload.get("question_type"),
            abstention_reason=payload.get("abstention_reason"),
            sub_answers=payload.get("sub_answers"),
            mode=payload.get("mode"),
            depth=(payload.get("depth")
                   if isinstance(payload.get("depth"), str)
                   else None),
            citation_details=payload.get("citation_details"),
            clarification=payload.get("clarification"),
            coverage=_payload_coverage(payload),
            two_phase=(
                payload.get("two_phase")
                if isinstance(payload.get("two_phase"), dict)
                else ({"phase": payload.get("phase"),
                       "verification": payload.get("verification")}
                      if payload.get("two_phase") is True
                      and isinstance(payload.get("verification"), dict)
                      else None)
            ),
            trace=payload.get("trace")
            if isinstance(payload.get("trace"), dict) else None,
        )
        # Every newly recorded answer carries its trust verdict,
        # computed deterministically from the finished record
        # against the real wiki tree.
        record["trust_verdict"] = answer_contract.compute_trust_verdict(
            record, repo_root() / "wiki"
        )
        # An explicit depth block dict in the payload is
        # stamped as-is (the lessons/provenance rule for
        # explicit blocks); a level-name declaration was
        # already resolved into its block by build_qa_record.
        if isinstance(payload.get("depth"), dict):
            record["depth"] = payload["depth"]
        # The lessons block (W5) rides the same additive rule,
        # one step earlier than provenance so the envelope can
        # name it: matched from the finished record against
        # the corrections ledger, stamped before the record is
        # appended. It is computed after the answer and its
        # trust verdict exist, so it cannot have influenced
        # either (see lessons.py).
        lessons = _payload_lessons(payload, record)
        if lessons is not None:
            record["lessons"] = lessons
        # The provenance pack (W3) rides the same additive rule:
        # built from the answer-time state the payload carries,
        # stamped on the record before it is appended — never
        # reconstructed afterwards.
        provenance = _payload_provenance(payload, record)
        if provenance is not None:
            record["provenance"] = provenance
        append_record(qa_file, record)
        _payload_trace(payload, record, qa_file)
        staging_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = staging_dir / ("qa-%s.md" % record["id"])
        proposal_path.write_text(
            stage_proposal_markdown(record), encoding="utf-8"
        )
        print("%s#%s" % (QA_RELATIVE_PATH, record["id"]))
        return 0

    if args.command == "mark":
        token = load_service_token(args.state_dir)
        mark_answered(args.base_url, token, args.qid, args.answer_ref)
        print("OK")
        return 0

    parser.error("unknown command: %s" % args.command)
    return 2


if __name__ == "__main__":
    sys.exit(main())
