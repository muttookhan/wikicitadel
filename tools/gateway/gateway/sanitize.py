"""Prompt-injection defence: sanitiser for untrusted content.

Pattern (Phase-2 harvest item 1): NicoBleh/secure-llm-wiki (MIT) —
its design centre is that untrusted source content must never reach
a channel later treated as trusted. This module is the deterministic
core of that defence for our stack (no LLM endpoint exists on this
machine, so the gate is pattern-based and fail-visible rather than
model-based):

  - NORMALISE first: zero-width characters and Unicode bidi
    controls are stripped before any detection runs, so an
    instruction cannot hide from the pattern checks by splitting
    its letters with invisible codepoints.
  - Hidden HTML is surfaced: comments and elements hidden with
    display:none / visibility:hidden / opacity:0 / font-size:0 /
    white-on-white styling are removed from cleaned output, and
    their text is scanned like any other text.
  - Base64 blocks that decode to mostly-printable text are
    inspected; a block whose payload carries an instruction
    pattern is a smuggling finding, not data.
  - Instruction patterns (override directives, chat-template
    markers, exfiltration phrasing) are detected on the normalised
    text.

Two consumers:
  - the ingest/convert path (scripts/wiki_convert.py) CLEANS with
    clean_text(): the markdown that enters the wiki has the
    obfuscation removed and the findings reported;
  - the gateway staging path (store.stage_proposal) SCANS with
    scan_text(): staged bytes are never altered (review hashes
    must keep meaning what they meant), but a blocked verdict
    quarantines the proposal on the spot.

Standalone (stdlib only) so scripts can load it by path, the same
way the validator loads profile.py. Deterministic: same input,
same findings, on every machine.
"""
from __future__ import annotations

import base64
import binascii
import re

# Attribution: defence pipeline shape adapted from
# NicoBleh/secure-llm-wiki (MIT). Implementation is original.

# -- invisible / directional codepoints --------------------------------
ZERO_WIDTH = "​‌‍⁠﻿­"
BIDI = "‪‫‬‭‮⁦⁧⁨⁩‎‏؜"
INVISIBLES = ZERO_WIDTH + BIDI
_INVIS_RE = re.compile("[" + re.escape(INVISIBLES) + "]")

# -- instruction patterns ------------------------------------------------
# Calibrated tight on purpose: these are phrases whose ordinary use
# in a source document is to address the READER MODEL, not a human
# reader. Legitimate security prose ("attackers embed hidden
# directives") does not match; quoted attack strings do — which is
# the point: quoted or not, they do not pass the gate as data.
INSTRUCTION_PATTERNS = [
    ("ignore-instructions",
     re.compile(r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier|"
                r"preceding)\s+(instructions?|prompts?|directions?|rules?)", re.I)),
    ("disregard-instructions",
     re.compile(r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above|earlier|"
                r"system)\b[^.\n]{0,40}", re.I)),
    ("forget-instructions",
     re.compile(r"forget\s+(everything|all\s+(previous|prior)\b[^.\n]{0,30}|"
                r"your\s+instructions?)", re.I)),
    ("override",
     re.compile(r"\boverride\s+(the\s+)?(system|instructions?|rules?|"
                r"safety|prompt)\b", re.I)),
    ("new-instructions",
     re.compile(r"^\s*(new|updated|revised)\s+instructions?\s*:", re.I | re.M)),
    ("system-prompt-reference",
     re.compile(r"\b(reveal|print|show|repeat|leak)\b[^.\n]{0,40}"
                r"\b(system\s+prompt|your\s+instructions?)\b", re.I)),
    ("role-hijack",
     re.compile(r"\byou\s+are\s+now\s+(an?\s+)?(ai|assistant|language\s+model|"
                r"unrestricted|jailbroken|different\s+ai)\b|"
                r"\byou\s+are\s+now\s+in\s+(developer|debug|unrestricted|"
                r"jailbreak)\s+mode\b", re.I)),
    ("chat-template-marker",
     re.compile(r"<\|im_(start|end)\|>|\[INST\]|<<SYS>>|<\|system\|>|"
                r"<\|user\|>|<\|assistant\|>")),
    ("exfiltration",
     re.compile(r"\b(send|post|upload|exfiltrate)\b[^.\n]{0,50}"
                r"\b(to\s+https?://|via\s+https?://|the\s+following\s+"
                r"(url|address|endpoint))", re.I)),
    ("silence-directive",
     re.compile(r"\bdo\s+not\s+(tell|inform|mention\s+(this|it)\s+to|"
                r"reveal\s+this\s+to)\b[^.\n]{0,30}\b(user|owner|human)\b", re.I)),
]

# -- hidden HTML -----------------------------------------------------------
_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_HIDDEN_STYLE_RE = re.compile(
    r"style\s*=\s*(\"[^\"]*\"|'[^']*')", re.I)
_HIDDEN_STYLE_MARKERS = (
    "display:none", "display: none", "visibility:hidden",
    "visibility: hidden", "opacity:0", "opacity: 0",
    "font-size:0", "font-size: 0",
    "color:#fff", "color:#ffffff", "color:white",
    "color: white", "color:#fefefe", "text-indent:-",
)
_ELEMENT_RE = re.compile(
    r"<(div|span|p|section|aside|font)\b([^>]*)>(.*?)</\1\s*>", re.S | re.I)

# -- base64 ------------------------------------------------------------------
_B64_RUN_RE = re.compile(r"[A-Za-z0-9+/=_-]{48,}")


def _instruction_hits(text: str) -> list[dict]:
    hits = []
    for name, rx in INSTRUCTION_PATTERNS:
        for m in rx.finditer(text):
            hits.append({"kind": "instruction-pattern", "pattern": name,
                         "excerpt": " ".join(m.group(0).split())[:80]})
    return hits


def _hidden_html(text: str) -> tuple[str, list[dict], list[str]]:
    """Remove comments + hidden elements. Returns (text_without,
    findings, hidden_texts) — hidden texts are scanned separately
    because an instruction that was hidden is worse, not better."""
    findings: list[dict] = []
    hidden_texts: list[str] = []

    def _comment(m):
        inner = m.group(1)
        if inner.strip():
            findings.append({"kind": "html-comment",
                             "excerpt": " ".join(inner.split())[:80]})
            hidden_texts.append(inner)
        return ""

    text = _COMMENT_RE.sub(_comment, text)

    def _element(m):
        attrs = m.group(2) or ""
        inner = m.group(3) or ""
        style_m = _HIDDEN_STYLE_RE.search(attrs)
        style = style_m.group(1).lower() if style_m else ""
        is_hidden = ("hidden" in attrs.split()
                     or any(marker in style for marker in _HIDDEN_STYLE_MARKERS))
        if not is_hidden:
            return m.group(0)
        plain = _TAG_RE.sub("", inner).strip()
        if plain:
            findings.append({"kind": "hidden-html",
                             "excerpt": " ".join(plain.split())[:80]})
            hidden_texts.append(plain)
        return ""

    text = _ELEMENT_RE.sub(_element, text)
    return text, findings, hidden_texts


def _b64_findings(text: str) -> list[dict]:
    findings = []
    for m in _B64_RUN_RE.finditer(text):
        run = m.group(0)
        if len(run) % 4 == 1:
            continue
        candidate = run.rstrip("=")
        candidate += "=" * (-len(candidate) % 4)
        try:
            raw = base64.b64decode(candidate, validate=False)
        except (binascii.Error, ValueError):
            continue
        if len(raw) < 16:
            continue
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        printable = sum(1 for c in decoded if c.isprintable() or c in "\n\t")
        if printable / max(1, len(decoded)) < 0.9:
            continue
        hits = _instruction_hits(decoded)
        if hits:
            findings.append({"kind": "base64-smuggle",
                             "pattern": hits[0]["pattern"],
                             "excerpt": " ".join(decoded.split())[:80]})
        else:
            findings.append({"kind": "base64-block",
                             "excerpt": " ".join(decoded.split())[:80]})
    return findings


def scan_text(text: str) -> dict:
    """Scan WITHOUT modifying. Returns {verdict, findings} where
    verdict is clean | flagged | blocked. Detection runs on the
    normalised text (invisibles stripped), so obfuscation cannot
    hide an instruction from the patterns — but the presence of
    invisibles is itself a finding."""
    findings: list[dict] = []
    if _INVIS_RE.search(text):
        n = len(_INVIS_RE.findall(text))
        findings.append({"kind": "invisible-chars", "count": n,
                         "excerpt": f"{n} zero-width/bidi codepoint(s)"})
    normalised = _INVIS_RE.sub("", text)
    _stripped, html_findings, hidden_texts = _hidden_html(normalised)
    findings.extend(html_findings)
    findings.extend(_instruction_hits(normalised))
    for hidden in hidden_texts:
        for hit in _instruction_hits(hidden):
            hit = dict(hit)
            hit["kind"] = "hidden-instruction"
            findings.append(hit)
    findings.extend(_b64_findings(normalised))
    return {"verdict": verdict_of(findings), "findings": findings}


def verdict_of(findings: list[dict]) -> str:
    kinds = {f["kind"] for f in findings}
    if kinds & {"instruction-pattern", "hidden-instruction", "base64-smuggle"}:
        return "blocked"
    if findings:
        return "flagged"
    return "clean"


def clean_text(text: str) -> tuple[str, dict]:
    """Clean for the ingest path: strip invisibles, drop comments
    and hidden elements, replace base64 blocks whose payload is an
    instruction with a visible removal marker. Returns
    (cleaned_text, scan_report_of_the_ORIGINAL)."""
    report = scan_text(text)
    cleaned = _INVIS_RE.sub("", text)
    cleaned, _f, _h = _hidden_html(cleaned)
    if any(f["kind"] == "base64-smuggle" for f in report["findings"]):
        def _neutralise(m):
            run = m.group(0)
            # Only the smuggled runs are replaced; benign base64
            # (hashes, encoded data) is data and stays.
            probe = _b64_findings(run)
            if any(f["kind"] == "base64-smuggle" for f in probe):
                return "[sanitised: base64-smuggled instruction removed]"
            return run
        cleaned = _B64_RUN_RE.sub(_neutralise, cleaned)
    return cleaned, report
