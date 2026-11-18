#!/usr/bin/env python3
"""\"Show me the chunks\" — the Ask door's evidence debug view
(Marathon R2 lane B1).

An answer record already knows what was packed for it: the
scored ``citation_details`` (page, score, the exact supporting
passage) — or, for a record that embeds a pack result, its
``packed`` list. This reader lists those exact evidence chunks
for a recorded answer, one per line:

    <page> §<anchor> score=<score> — <verbatim first line>

so a human auditing an answer can see, without opening the
record's JSON, exactly which chunks of which pages the answer
was composed from.

CLI shape follows the door's existing convention (flat stdlib
scripts in this directory, like ``pickup.py``)::

    python3 tools/ask/show_chunks.py <answer-record>

The record file may be a single ``.json`` answer payload/record
or a ``.jsonl`` Q&A file (every record in it is listed, headed
by its id). With ``-`` the record is read from stdin. The same
listing is importable: :func:`chunks_for_record` and
:func:`format_chunks`.

The § anchor is the chunk's own ``anchor`` / ``section`` field
when the record carries one; records whose chunks carry no
anchor print ``§—`` rather than inventing one.

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _first_line(passage) -> str:
    """The first non-empty line of *passage*, verbatim."""
    for line in str(passage or "").splitlines():
        if line.strip():
            return line
    return ""


def _chunk_from_entry(entry: dict) -> dict:
    passage = entry.get("passage", "")
    anchor = entry.get("anchor") or entry.get("section") or ""
    score = entry.get("score")
    return {
        "page": str(entry.get("page") or entry.get("id") or ""),
        "anchor": str(anchor),
        "score": (
            float(score)
            if isinstance(score, (int, float))
            and not isinstance(score, bool)
            else None
        ),
        "passage": str(passage),
        "first_line": _first_line(passage),
    }


def chunks_for_record(record: dict) -> list:
    """The exact evidence chunks packed for *record*.

    Source of truth, in order: an embedded pack result
    (``packed``, then ``evidence``, then ``chunks``) when the
    record carries one; otherwise the record's
    ``citation_details`` — top-level first, then each
    sub-answer's in record order. Each chunk is a dict:
    ``{"page", "anchor", "score", "passage", "first_line"}``.
    """
    if not isinstance(record, dict):
        return []
    entries = []
    for key in ("packed", "evidence", "chunks"):
        value = record.get(key)
        if isinstance(value, list) and value:
            entries = [e for e in value if isinstance(e, dict)]
            break
    if not entries:
        details = record.get("citation_details") or []
        entries.extend(
            d for d in details if isinstance(d, dict)
        )
        for sub in record.get("sub_answers") or []:
            if isinstance(sub, dict):
                details = sub.get("citation_details") or []
                entries.extend(
                    d for d in details if isinstance(d, dict)
                )
    return [_chunk_from_entry(e) for e in entries]


def format_chunk(chunk: dict, index: int = None) -> str:
    """One chunk as a debug line:
    ``<page> §<anchor> score=<score> — <first line>``."""
    anchor = "§%s" % chunk["anchor"] if chunk["anchor"] else "§—"
    score = (
        "score=%.2f" % chunk["score"]
        if chunk["score"] is not None
        else "score=-"
    )
    prefix = "%d. " % index if index is not None else ""
    return "%s%s %s %s — %s" % (
        prefix, chunk["page"], anchor, score, chunk["first_line"]
    )


def format_chunks(record: dict) -> str:
    """The debug listing for one record: a header naming the
    record (when it carries an id / question) and one line per
    chunk, numbered in packed order."""
    lines = []
    record_id = record.get("id") if isinstance(record, dict) else None
    question = (
        record.get("question") if isinstance(record, dict) else None
    )
    if record_id or question:
        header = "Chunks for %s" % (record_id or "answer")
        if question:
            header += " — %s" % question
        lines.append(header)
    chunks = chunks_for_record(record)
    if not chunks:
        lines.append("(no packed chunks recorded)")
    for index, chunk in enumerate(chunks, start=1):
        lines.append(format_chunk(chunk, index))
    return "\n".join(lines)


def load_records(path) -> list:
    """Records from *path*: a ``.jsonl`` file gives one record
    per non-empty line; anything else is parsed as one JSON
    document — a single record dict, or a payload carrying a
    ``question_entry`` plus ``citation_details``."""
    text = (
        sys.stdin.read() if str(path) == "-"
        else Path(path).read_text(encoding="utf-8")
    )
    if str(path).endswith(".jsonl"):
        return [
            json.loads(line)
            for line in text.splitlines() if line.strip()
        ]
    data = json.loads(text)
    return [data] if isinstance(data, dict) else list(data)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="List the exact evidence chunks packed for "
                    "a recorded Ask answer (see show_chunks.py)."
    )
    parser.add_argument(
        "record",
        help="Answer-record file (.json or .jsonl); - for stdin.",
    )
    args = parser.parse_args(argv)
    try:
        records = load_records(args.record)
    except (OSError, ValueError) as exc:
        print("show_chunks: %s" % exc, file=sys.stderr)
        return 1
    blocks = [format_chunks(record) for record in records]
    print("\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
