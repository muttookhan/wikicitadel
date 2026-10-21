#!/usr/bin/env python3
"""wiki_script_norm.py — IndicTrans2-pattern script unification.

Marathon Round 3, lane TB7, row 8. Pattern: IndicTrans2's script
unification for multilingual retrieval (re-implemented from the
idea): text in different scripts is normalised into ONE script
space before indexing, so a query in one script matches a page
in another. The normaliser, applied in this fixed order:

  1. Unicode NFKC — folds compatibility variants, including
     CJK fullwidth forms (ＡＢＣ -> ABC) and halfwidth kana forms;
  2. Devanagari transliteration — the stated romanisation table
     below (simplified IAST without diacritics: inherent 'a' is
     always written, the virama suppresses it, vowel signs
     replace it — रामायण -> ramayana, कृष्ण -> krishna — the
     table is data, printed by `table`, and pinned by tests);
  3. case folding;
  4. NFKD + combining-mark stripping — diacritic folding
     (café -> cafe, naïve -> naive, ā -> a).

The search integration is a WRAPPER, not a change to the
canonical ranker: normalised copies of the documents and the
query are fed to wiki_search.bm25_rank, whose own tokenizer and
scoring are untouched — cross-script matching is a property of
the normalised text, measured separately from the golden set.

    python3 scripts/wiki_script_norm.py normalize "रामायण Café ＡＢＣ"
    python3 scripts/wiki_script_norm.py table
    python3 scripts/wiki_script_norm.py search --root DIR --q "ramayana"

Stdlib only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_RE = re.compile(r"[a-z0-9]+")

# --- The stated Indic (Devanagari) romanisation table --------------
# Simplified, diacritic-free, stated in full so it can be audited:
# consonant -> base (the inherent vowel 'a' is added unless a
# virama suppresses it or a vowel sign replaces it).
DEV_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "ळ": "l",
}
DEV_VOWELS = {  # independent vowels
    "अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
}
DEV_MATRAS = {  # dependent vowel signs (replace the inherent 'a')
    "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
}
DEV_SIGNS = {"ं": "n", "ँ": "n", "ः": "h"}
DEV_VIRAMA = "्"
DEV_DIGITS = {"०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
              "५": "5", "६": "6", "७": "7", "८": "8", "९": "9"}


def transliterate_devanagari(text):
    """Devanagari -> roman per the stated table. Characters
    outside the table (and outside Devanagari) pass through."""
    out = []
    i = 0
    chars = list(text)
    while i < len(chars):
        ch = chars[i]
        if ch in DEV_CONSONANTS:
            base = DEV_CONSONANTS[ch]
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if nxt == DEV_VIRAMA:
                out.append(base)
                i += 2
                continue
            if nxt in DEV_MATRAS:
                out.append(base + DEV_MATRAS[nxt])
                i += 2
                # a sign may follow the vowel sign (e.g. ां)
                if i < len(chars) and chars[i] in DEV_SIGNS:
                    out.append(DEV_SIGNS[chars[i]])
                    i += 1
                continue
            out.append(base + "a")
            i += 1
            continue
        if ch in DEV_VOWELS:
            out.append(DEV_VOWELS[ch])
        elif ch in DEV_SIGNS:
            out.append(DEV_SIGNS[ch])
        elif ch in DEV_DIGITS:
            out.append(DEV_DIGITS[ch])
        elif ch == DEV_VIRAMA or ch in DEV_MATRAS:
            pass  # stray sign with no consonant: no sound of its own
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def normalize_text(text):
    """The full unification pipeline (see module docstring)."""
    s = unicodedata.normalize("NFKC", text or "")
    s = transliterate_devanagari(s)
    s = s.casefold()
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def normalize_tokens(text):
    return [t for t in TOKEN_RE.findall(normalize_text(text))
            if len(t) >= 2]


def _load_search():
    spec = importlib.util.spec_from_file_location(
        "wiki_search_for_script_norm",
        Path(__file__).with_name("wiki_search.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def search_normalized(query, docs):
    """BM25 over normalised text: docs [(path, text)] -> the
    canonical ranker's [(score, path, text)] over NORMALISED
    copies (paths are the originals')."""
    ws = _load_search()
    norm_docs = [(p, normalize_text(t)) for p, t in docs]
    terms = normalize_tokens(query)
    return ws.bm25_rank(terms, norm_docs)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("normalize")
    n.add_argument("text")
    sub.add_parser("table")
    s = sub.add_parser("search")
    s.add_argument("--root", default=None)
    s.add_argument("--q", required=True)
    s.add_argument("--top", type=int, default=10)
    args = ap.parse_args(argv)
    if args.cmd == "normalize":
        print(normalize_text(args.text))
        return 0
    if args.cmd == "table":
        print(json.dumps({
            "kind": "romanisation-table", "script": "Devanagari",
            "consonants": DEV_CONSONANTS, "vowels": DEV_VOWELS,
            "matras": DEV_MATRAS, "signs": DEV_SIGNS,
            "digits": DEV_DIGITS,
            "rules": ["NFKC first (CJK width folds)",
                      "inherent 'a' always written",
                      "virama suppresses the inherent 'a'",
                      "a vowel sign replaces the inherent 'a'",
                      "casefold, then NFKD diacritic stripping"],
        }, indent=2, ensure_ascii=False))
        return 0
    root = Path(args.root).resolve() if args.root else ROOT
    docs = []
    for p in sorted((root / "wiki").rglob("*.md")):
        docs.append((p, p.read_text(encoding="utf-8", errors="ignore")))
    ranked = search_normalized(args.q, docs)
    print(json.dumps([{"path": str(p.relative_to(root))
                       if p.is_relative_to(root) else str(p),
                      "score": round(s, 4)}
                     for s, p, _t in ranked[: args.top]],
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
