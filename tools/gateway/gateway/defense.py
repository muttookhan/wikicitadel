"""Memory Defense: secrets/PII scan for staged content.

Pattern (2026-10-19, adapted from Hindsight's opt-in "Memory
Defense", vectorize-io/hindsight, MIT): every memory entering the
store is scanned for secrets and PII, and a hit stops the write.
Hindsight redacts or blocks; the governed behaviour here is BLOCK —
the proposal is quarantined on the spot (see store.stage_proposal),
recorded with its pattern classes, and can never be promoted. A
human may re-submit a cleaned version as a new proposal.

This is the matching lock on the staging door next to sanitize.py:
the sanitiser stops content that carries INSTRUCTIONS to a future
reader; this scan stops content that carries CREDENTIALS or PII.
Different payloads, same choke point — store.stage_proposal is the
only path by which staged content enters, so both scans run there.

Discipline (mirrors the Black Box rule in ledger.py: secrets are
never stored):

  - Findings name the pattern CLASS and a count only. The matched
    value is never copied into a finding, an error message, a
    proposal meta, or a ledger entry — anywhere it could be
    re-read later is a place a secret must not land.
  - Detection is deterministic regex/pattern matching (stdlib
    only), calibrated like the sanitiser: a closed list of named,
    high-signal shapes, not a general "looks secret-ish" guess.
  - Normalise first, like the sanitiser: zero-width / bidi
    codepoints are stripped before matching, so a token cannot
    hide from the scan by splitting its characters with invisible
    codepoints.
  - The credential-assignment pattern is value-filtered: obvious
    placeholders (your-api-key-here, changeme, <...> templates,
    ${ENV} references) and local file paths (~/.ssh/...) are not
    secrets and do not block. A value that survives the filter is
    treated as a real credential and blocks.
  - Card numbers are verified with the Luhn check, so an arbitrary
    long digit string (an order number, a hash prefix) does not
    block; a Luhn-valid 13–19 digit number does.

Standalone (stdlib only), deterministic: same input, same findings,
on every machine.
"""
from __future__ import annotations

import re

from . import sanitize as _sanitize

# Attribution: the scan-every-incoming-memory gate shape is adapted
# from Hindsight's Memory Defense (vectorize-io/hindsight, MIT).
# Implementation is original.

# Normalise like the sanitiser does: invisibles stripped first.
_INVIS_RE = re.compile("[" + re.escape(_sanitize.INVISIBLES) + "]")

# -- high-signal token shapes -------------------------------------------
# Each entry: (pattern class, regex). Classes are the ONLY thing a
# finding ever reports — never the matched text.
SECRET_PATTERNS = [
    ("private-key",
     re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("aws-access-key-id",
     re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token",
     re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,255}\b"
                r"|\bgithub_pat_[A-Za-z0-9_]{22,255}\b")),
    ("slack-token",
     re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("provider-api-key",
     re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"
                r"|\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt",
     re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
                r"\.[A-Za-z0-9_-]{5,}\b")),
    ("bearer-token",
     re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I)),
    ("connection-string",
     re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@]+:[^\s/@]{3,}@"
                r"[^\s/]")),
    ("ssn",
     re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")),
]

# -- credential assignments ----------------------------------------------
# key = value / key: value, where the key names a credential. The
# VALUE is captured only so it can be filtered for placeholders and
# paths; it is never stored or reported.
_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|apikey|api[_-]?secret|client[_-]?secret|"
    r"secret[_-]?access[_-]?key|secret|access[_-]?key|"
    r"auth[_-]?token|access[_-]?token|refresh[_-]?token|"
    r"session[_-]?token|token|password|passwd|pwd)\b"
    r"\s*[:=]\s*[\"']?([^\s\"'`,;]{8,})",
    re.I)

_PLACEHOLDER_VALUES = {
    "none", "null", "nil", "true", "false", "undefined", "n/a", "na",
    "redacted", "password", "secret", "token",
}
_PLACEHOLDER_HINTS = (
    "example", "placeholder", "redacted", "changeme", "change-me",
    "your-", "your_", "xxxx", "dummy", "sample", "not-a-real",
    "insert-", "replace-", "todo",
)
_PATH_PREFIXES = ("~/", "/", "./", "../")
_PATH_SUFFIXES = (".pem", ".key", ".pub", ".md", ".json", ".txt",
                  ".yaml", ".yml", ".toml")


def _is_real_value(value: str) -> bool:
    """True if an assignment value looks like an actual credential
    rather than a placeholder, a template, an env reference, or a
    local file path."""
    low = value.lower()
    if low in _PLACEHOLDER_VALUES:
        return False
    if any(hint in low for hint in _PLACEHOLDER_HINTS):
        return False
    # Templates and references, not values: <...>, ${...}, {{...}},
    # $(...), %ENV%.
    if value[0] in "<{$(%" :
        return False
    # A local path to a key FILE is a reference, not the key.
    if low.startswith(_PATH_PREFIXES) or low.endswith(_PATH_SUFFIXES):
        return False
    # One repeated character is a mask, not a credential.
    if len(set(value)) == 1:
        return False
    return True


# -- card numbers (Luhn-verified) -----------------------------------------
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _card_hits(text: str) -> int:
    hits = 0
    for m in _CARD_CANDIDATE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and len(set(digits)) > 1 \
                and _luhn_ok(digits):
            hits += 1
    return hits


def scan_secrets(text: str) -> dict:
    """Scan WITHOUT modifying. Returns {verdict, findings} where
    verdict is clean | blocked and every finding is
    {"kind": "secret", "pattern": <class>, "count": n} — the class
    name and count ONLY. The matched value is never copied into the
    report, so the report is safe to store in proposal meta, error
    messages, and the Black Box ledger."""
    normalised = _INVIS_RE.sub("", text)
    counts: dict[str, int] = {}
    for name, rx in SECRET_PATTERNS:
        n = len(rx.findall(normalised))
        if n:
            counts[name] = counts.get(name, 0) + n
    assignments = sum(
        1 for m in _ASSIGNMENT_RE.finditer(normalised)
        if _is_real_value(m.group(2)))
    if assignments:
        counts["credential-assignment"] = assignments
    cards = _card_hits(normalised)
    if cards:
        counts["credit-card"] = cards
    findings = [{"kind": "secret", "pattern": name, "count": counts[name]}
                for name in sorted(counts)]
    return {"verdict": "blocked" if findings else "clean",
            "findings": findings}
