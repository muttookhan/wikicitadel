#!/usr/bin/env python3
"""CaMeLS-style quarantined extractor for the Ask door.

The one named unbuilt remainder of the wave 1-10 feature survey
(see ``tools/ask/QUARANTINE.md`` for the documented design vs
what is built here, with the survey paths).

THE DESIGN IN ONE LINE. Untrusted captured content is never fed
directly to a privileged model/context. A quarantined extraction
step — no tools, no access to private context — pulls structured
facts out against a declared schema, and only the validated
structured output crosses into the trusted side, with provenance.

WHAT THIS MODULE IS. The extraction *boundary*, as pure stdlib
machinery around an INJECTABLE extractor callable:

    extract_quarantined(untrusted_text, schema, extractor, ...)

- The extractor is a callable supplied by the caller. In
  production that would wrap a model instance holding no
  capabilities; in tests it is a fake. This module ships NO model
  and calls NO network — the injectable seam is the deliverable.
- The module enforces the boundary mechanically: the extractor
  is called with EXACTLY two positional arguments — the
  untrusted text and a normalised copy of the declared schema —
  and nothing else. No wiki context, no question, no source id,
  no caller state, no keyword arguments cross to it. (A test
  proves this with a fake that asserts its exact inputs.)
- Whatever the extractor returns is treated as untrusted too.
  Every field is type-checked against the schema; unknown
  fields are dropped and recorded; oversized or mistyped values
  are rejected and recorded.

WHAT CROSSES, AND WHAT DOES NOT. The return value is always a
provenance envelope (a plain JSON-serialisable dict):

    {
      "kind": "quarantined-extraction", "version": 1,
      "status": "trusted" | "quarantined",
      "trusted": <bool>, "quarantined": <bool>,
      "data": {<validated fields>} | None,
      "provenance": {source_id, source_sha256, source_chars,
                     extractor_id, extracted_at, schema},
      "validation": {dropped_fields, rejected_fields,
                     tripwire_hits, missing_required,
                     missing_optional, errors},
      "quarantine": None | {"reason": ..., "detail": ...},
    }

``data`` is not-None ONLY when ``status == "trusted"``.
Downstream code must check the flag — :func:`is_trusted` /
:func:`trusted_data` are the check; ``trusted_data`` raises
:class:`QuarantineError` instead of returning held data.

FAIL CLOSED. Any of these produces a quarantine record with
``data is None``, never a partial trusted output:

- the extractor raises, returns a non-mapping, or returns None;
- a declared field is mistyped, oversized, or a required field
  is missing (a *schema mismatch*);
- an extracted string trips an injection tripwire (below);
- the untrusted input itself exceeds the size limit (the
  extractor is not even called).

The single non-quarantining anomaly is an UNKNOWN field (one
the schema does not declare): it is dropped, recorded in
``validation.dropped_fields``, and never crosses. Dropping is
not passing: the value appears nowhere in ``data``.

INJECTION TRIPWIRES. Extracted string values (and string-list
items) are scanned for instruction-shaped patterns in
``_TRIPWIRE_PATTERNS``: classic instruction overrides,
imperatives/secrecy directives addressed to an agent, tool-call
shapes, URLs carrying credentials, credential assignments,
role impersonation, and datamark escapes. A hit flags the FIELD
(field name, pattern id, truncated excerpt) in
``validation.tripwire_hits`` and quarantines the whole envelope
— partial trust in the same extraction would let an attacker
keep the fields that did not trip. Tripwire hits are DATA about
the extraction: they are recorded, never executed, never
followed, and the matched value itself is withheld from
``data``. The patterns are a documented, deliberately narrow
heuristic — a tripwire is a hold for human eyes, the same
posture as the datamarking layer's ``review`` verdict in
``answer_contract.py``, tightened to a hold because here the
value would otherwise cross as structured data.

SCHEMA. A schema is a list of field dicts::

    {"name": "title", "type": "string", "required": True}
    {"name": "year",  "type": "integer"}            # optional
    {"name": "tags",  "type": "string_list",
     "max_items": 10, "max_length": 80}              # per-item cap

Supported types: ``string``, ``integer``, ``number``,
``boolean``, ``string_list``. ``required`` defaults to False.
``max_length`` caps a string field's length (or each item of a
string_list); ``max_items`` caps a string_list's length.
Defaults: ``DEFAULT_MAX_STRING`` per string/item,
``DEFAULT_MAX_ITEMS`` per list, ``DEFAULT_MAX_INPUT_CHARS``
for the untrusted input. Booleans are NOT integers/numbers
(Python's ``bool`` subclassing is explicitly rejected), numbers
must be finite, and an integer field rejects floats even when
integral — strictness is the point of a typed crossing.

A malformed SCHEMA (duplicate names, unknown types, bad field
names, no fields) is a caller bug, not untrusted data: it
raises ``ValueError`` before the extractor is ever called, as
does a non-string ``untrusted_text`` (``TypeError``).

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping

ENVELOPE_KIND = "quarantined-extraction"
ENVELOPE_VERSION = 1

SUPPORTED_TYPES = ("string", "integer", "number", "boolean",
                   "string_list")

DEFAULT_MAX_INPUT_CHARS = 200_000
DEFAULT_MAX_STRING = 4_000
DEFAULT_MAX_ITEMS = 50

_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class QuarantineError(Exception):
    """Raised when code asks for the trusted data of an envelope
    that is quarantined (see :func:`trusted_data`)."""


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def normalize_schema(schema) -> list:
    """Validate and normalise a declared extraction schema.

    Returns a list of field dicts with exactly the keys
    ``name`` / ``type`` / ``required`` plus ``max_length`` /
    ``max_items`` when the declaration sets them. Raises
    ``ValueError`` on any malformed declaration — a schema is
    written by the trusted side, so its defects are caller bugs,
    surfaced loudly, never quarantined data.
    """
    if isinstance(schema, (str, bytes)) or not schema:
        raise ValueError("schema must be a non-empty list of fields")
    fields = []
    seen = set()
    for raw in schema:
        if not isinstance(raw, Mapping):
            raise ValueError("schema field must be a mapping: %r" % (raw,))
        name = raw.get("name")
        if not isinstance(name, str) or not _FIELD_NAME_RE.match(name):
            raise ValueError("schema field has a bad name: %r" % (name,))
        if name in seen:
            raise ValueError("schema field name duplicated: %r" % name)
        seen.add(name)
        ftype = raw.get("type")
        if ftype not in SUPPORTED_TYPES:
            raise ValueError(
                "schema field %r has unsupported type %r (supported: %s)"
                % (name, ftype, ", ".join(SUPPORTED_TYPES)))
        field = {"name": name, "type": ftype,
                 "required": bool(raw.get("required", False))}
        for key in ("max_length", "max_items"):
            if key in raw and raw[key] is not None:
                value = raw[key]
                if (isinstance(value, bool)
                        or not isinstance(value, int) or value <= 0):
                    raise ValueError(
                        "schema field %r: %s must be a positive int"
                        % (name, key))
                field[key] = value
        fields.append(field)
    return fields


def _schema_view(fields: list) -> tuple:
    """The schema as the extractor sees it: a tuple of fresh
    dicts. A copy on purpose — an extractor that mutates what it
    was handed cannot reach the schema validation runs against.
    """
    return tuple(dict(f) for f in fields)


# ---------------------------------------------------------------------------
# Injection tripwires
# ---------------------------------------------------------------------------

# (pattern id, compiled pattern). Deliberately narrow, in the
# same spirit as answer_contract's instruction patterns: classic
# override phrasing and agent-directed directives, not any use
# of the word "instructions" in ordinary prose.
_TRIPWIRE_PATTERNS = [
    ("instruction_override", re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above|preceding)\s+"
        r"(instructions?|directions?|prompts?|rules?)", re.I)),
    ("instruction_override", re.compile(
        r"disregard\s+(the\s+)?(above|previous|prior|earlier|"
        r"system)\b", re.I)),
    ("instruction_override", re.compile(
        r"forget\s+(everything|all\s+previous|your\s+instructions)",
        re.I)),
    ("instruction_override", re.compile(
        r"new\s+instructions?\s*[:\-]", re.I)),
    ("instruction_override", re.compile(
        r"\bsystem\s+prompt\b", re.I)),
    ("imperative_to_agent", re.compile(
        r"note\s+to\s+(the\s+)?(agent|assistant|ai|model|reader)"
        r"\s*[:\-]", re.I)),
    ("imperative_to_agent", re.compile(
        r"\byou\s+(must|shall)\s+", re.I)),
    ("secrecy_directive", re.compile(
        r"\bdo\s+not\s+(mention|reveal|share|disclose|tell|say|"
        r"cite)\b", re.I)),
    ("secrecy_directive", re.compile(
        r"\bnever\s+(reveal|disclose|share|mention|tell|say)\b",
        re.I)),
    ("secrecy_directive", re.compile(
        r"\b(reveal|disclose|print|output|leak|send|post)\s+"
        r"(the\s+|your\s+)?(token|password|secret|api[ _-]?key|"
        r"credentials?)\b", re.I)),
    # Tool-call shapes: JSON-ish invocations, tagged calls, and
    # explicit call syntax — a value shaped like a tool call is
    # an attempt to make the trusted side execute it.
    ("tool_call_shape", re.compile(
        r'"(?:tool|function)(?:_call|Call)?"\s*:', re.I)),
    ("tool_call_shape", re.compile(r"\btool_call\b", re.I)),
    ("tool_call_shape", re.compile(r"\bfunction_call\b", re.I)),
    ("tool_call_shape", re.compile(
        r"<\s*/?\s*(tool|function)[_ ]?call\b", re.I)),
    ("tool_call_shape", re.compile(
        r"\bcall\s+(the\s+)?(tool|function)\s*[:\(]", re.I)),
    # URLs carrying credentials, and credential assignments.
    ("credential_url", re.compile(
        r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.I)),
    ("credential_url", re.compile(
        r"https?://[^\s]*[?&](?:token|api[_-]?key|password|"
        r"secret|passwd)=[^\s&]+", re.I)),
    ("credential_assignment", re.compile(
        r"\b(?:api[_-]?key|password|passwd|secret|access[_-]?token)"
        r"\s*[:=]\s*\S+", re.I)),
    ("credential_assignment", re.compile(
        r"\bBearer\s+[A-Za-z0-9._\-]{12,}", re.I)),
    # Role impersonation at the start of a line, and attempts to
    # break out of the datamark scheme of answer_contract.py.
    ("role_impersonation", re.compile(
        r"(?m)^\s*(system|developer)\s*:\s", re.I)),
    ("datamark_escape", re.compile(
        r"<<<\s*/?\s*DATA\b|<<</DATA>>>", re.I)),
]

_TRIPWIRE_EXCERPT_CHARS = 120


def scan_string(value: str) -> list:
    """Tripwire hits in one string value: a list of
    ``{"pattern": <id>, "excerpt": <truncated match context>}``.
    Pure detection — a hit is recorded, never acted on.
    """
    hits = []
    seen = set()
    for pattern_id, pattern in _TRIPWIRE_PATTERNS:
        match = pattern.search(value)
        if match and pattern_id not in seen:
            seen.add(pattern_id)
            start = max(0, match.start() - 20)
            excerpt = value[start:match.end() + 40].strip()
            hits.append({"pattern": pattern_id,
                         "excerpt": excerpt[:_TRIPWIRE_EXCERPT_CHARS]})
    return hits


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def _check_value(field: dict, value):
    """Type/size-check one extracted value against its field.

    Returns ``(ok, reason)`` — reason is None when ok. Strict:
    ``bool`` is neither an integer nor a number; numbers must be
    finite; a string_list must be a list of strings, each inside
    its length cap.
    """
    ftype = field["type"]
    max_length = field.get("max_length", DEFAULT_MAX_STRING)
    if ftype == "string":
        if not isinstance(value, str):
            return False, "expected string, got %s" % type(value).__name__
        if len(value) > max_length:
            return False, ("string of %d chars exceeds max_length %d"
                           % (len(value), max_length))
        return True, None
    if ftype == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            return False, "expected integer, got %s" % type(value).__name__
        return True, None
    if ftype == "number":
        if (isinstance(value, bool)
                or not isinstance(value, (int, float))):
            return False, "expected number, got %s" % type(value).__name__
        if not math.isfinite(float(value)):
            return False, "number is not finite"
        return True, None
    if ftype == "boolean":
        if not isinstance(value, bool):
            return False, "expected boolean, got %s" % type(value).__name__
        return True, None
    if ftype == "string_list":
        max_items = field.get("max_items", DEFAULT_MAX_ITEMS)
        if not isinstance(value, list):
            return False, ("expected string_list (a list), got %s"
                           % type(value).__name__)
        if len(value) > max_items:
            return False, ("list of %d items exceeds max_items %d"
                           % (len(value), max_items))
        for item in value:
            if not isinstance(item, str):
                return False, ("string_list item is not a string: %r"
                               % (item,))
            if len(item) > max_length:
                return False, ("string_list item of %d chars exceeds "
                               "max_length %d" % (len(item), max_length))
        return True, None
    return False, "unsupported type %r" % (ftype,)  # unreachable


def validate_extraction(raw, fields: list):
    """Validate an extractor's raw return against *fields* (a
    normalised schema from :func:`normalize_schema`).

    Returns ``(clean, report)``: ``clean`` holds exactly the
    declared fields that passed every check and tripped no wire
    (values copied — lists are copied too, so later mutation of
    the extractor's structures cannot reach the trusted side);
    ``report`` is the validation report dict carried in the
    envelope. Whether ``clean`` may actually cross is the
    caller's fail-closed decision (see :func:`extract_quarantined`):
    any rejected field, tripwire hit, or missing required field
    in the report means it may not.
    """
    report = {"dropped_fields": [], "rejected_fields": [],
              "tripwire_hits": [], "missing_required": [],
              "missing_optional": [], "errors": []}
    clean = {}
    if not isinstance(raw, Mapping):
        report["errors"].append(
            "extractor returned %s, not a mapping"
            % type(raw).__name__)
        return clean, report
    declared = {f["name"]: f for f in fields}
    for key in raw:
        if key not in declared:
            report["dropped_fields"].append(str(key))
    report["dropped_fields"].sort()
    for field in fields:
        name = field["name"]
        if name not in raw:
            if field["required"]:
                report["missing_required"].append(name)
            else:
                report["missing_optional"].append(name)
            continue
        value = raw[name]
        ok, reason = _check_value(field, value)
        if not ok:
            report["rejected_fields"].append(
                {"field": name, "reason": reason})
            continue
        strings = []
        if field["type"] == "string":
            strings = [value]
        elif field["type"] == "string_list":
            strings = list(value)
        flagged = False
        for text in strings:
            for hit in scan_string(text):
                report["tripwire_hits"].append(
                    {"field": name, "pattern": hit["pattern"],
                     "excerpt": hit["excerpt"]})
                flagged = True
        if flagged:
            continue
        clean[name] = list(value) if field["type"] == "string_list" \
            else value
    return clean, report


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _extractor_id(extractor, given):
    if given:
        return str(given)
    return (getattr(extractor, "__name__", None)
            or type(extractor).__name__)


def extract_quarantined(untrusted_text, schema, extractor, *,
                        source_id, extractor_id=None,
                        extracted_at=None,
                        max_input_chars=DEFAULT_MAX_INPUT_CHARS):
    """Run one quarantined extraction and return its envelope.

    ``extractor`` is called as ``extractor(untrusted_text,
    schema_view)`` — two positional arguments, nothing else (see
    the module docstring). ``source_id`` names the captured
    source for provenance; it is recorded on the envelope and is
    deliberately NOT passed to the extractor. ``extracted_at``
    (ISO string) may be supplied for determinism; the UTC now is
    used otherwise.

    Never raises for untrusted-side failures: an extractor
    exception, a schema mismatch, a tripwire hit, or an
    oversized input all return a quarantined envelope with
    ``data is None``. Raises ``ValueError`` / ``TypeError`` only
    for trusted-side caller bugs (a malformed schema, a
    non-string input, a non-callable extractor).
    """
    if not isinstance(untrusted_text, str):
        raise TypeError("untrusted_text must be a string, got %s"
                        % type(untrusted_text).__name__)
    if not callable(extractor):
        raise TypeError("extractor must be callable")
    fields = normalize_schema(schema)
    provenance = {
        "source_id": str(source_id),
        "source_sha256": hashlib.sha256(
            untrusted_text.encode("utf-8")).hexdigest(),
        "source_chars": len(untrusted_text),
        "extractor_id": _extractor_id(extractor, extractor_id),
        "extracted_at": extracted_at or _utc_now_iso(),
        "schema": [dict(f) for f in fields],
    }
    report = {"dropped_fields": [], "rejected_fields": [],
              "tripwire_hits": [], "missing_required": [],
              "missing_optional": [], "errors": []}

    def envelope(data, quarantine):
        quarantined = quarantine is not None
        return {
            "kind": ENVELOPE_KIND,
            "version": ENVELOPE_VERSION,
            "status": "quarantined" if quarantined else "trusted",
            "trusted": not quarantined,
            "quarantined": quarantined,
            "data": data,
            "provenance": provenance,
            "validation": report,
            "quarantine": quarantine,
        }

    if len(untrusted_text) > max_input_chars:
        report["errors"].append(
            "untrusted input of %d chars exceeds the %d-char limit; "
            "extractor not called" % (len(untrusted_text),
                                      max_input_chars))
        return envelope(None, {
            "reason": "input_oversized",
            "detail": report["errors"][-1]})

    try:
        raw = extractor(untrusted_text, _schema_view(fields))
    except Exception as exc:  # the extractor is untrusted-side
        report["errors"].append(
            "extractor raised %s: %s" % (type(exc).__name__, exc))
        return envelope(None, {
            "reason": "extractor_error",
            "detail": report["errors"][-1]})

    clean, report = validate_extraction(raw, fields)

    if report["errors"]:
        return envelope(None, {
            "reason": "extractor_bad_return",
            "detail": "; ".join(report["errors"])})
    if report["tripwire_hits"]:
        names = sorted({h["field"] for h in report["tripwire_hits"]})
        return envelope(None, {
            "reason": "tripwire",
            "detail": "instruction-shaped value(s) in field(s): %s"
                      % ", ".join(names)})
    if report["rejected_fields"] or report["missing_required"]:
        parts = []
        if report["rejected_fields"]:
            parts.append("rejected: " + ", ".join(
                "%s (%s)" % (r["field"], r["reason"])
                for r in report["rejected_fields"]))
        if report["missing_required"]:
            parts.append("missing required: "
                         + ", ".join(report["missing_required"]))
        return envelope(None, {
            "reason": "schema_mismatch",
            "detail": "; ".join(parts)})
    return envelope(clean, None)


def is_trusted(envelope) -> bool:
    """The downstream check: True only for an envelope whose
    validated data crossed (status ``trusted``, not quarantined,
    data present). Anything else — including a non-envelope —
    is not trusted.
    """
    return (isinstance(envelope, Mapping)
            and envelope.get("kind") == ENVELOPE_KIND
            and envelope.get("status") == "trusted"
            and envelope.get("trusted") is True
            and envelope.get("quarantined") is False
            and envelope.get("data") is not None)


def trusted_data(envelope):
    """The validated data of a trusted envelope, or raise
    :class:`QuarantineError`. The only sanctioned way for
    downstream code to consume an extraction.
    """
    if not is_trusted(envelope):
        quarantine = (envelope.get("quarantine")
                      if isinstance(envelope, Mapping) else None)
        raise QuarantineError(
            "extraction is not trusted (quarantine: %r)" % (quarantine,))
    return envelope["data"]
