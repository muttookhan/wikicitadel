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
                    trace: dict = None) -> dict:
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
             "citation_details (see answer_contract.py).",
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
