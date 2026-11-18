#!/usr/bin/env python3
"""wiki_factcheck.py — atomic-fact factual-precision audit.

Pattern: shmsw25/FActScore (MIT)
decomposes a text into atomic facts, verifies each against a
registered trusted corpus, and scores the fraction supported,
with a length penalty so a nearly-empty page cannot score well
by saying almost nothing.

Adapted to this machine honestly: no LLM endpoint exists here,
so decomposition is DETERMINISTIC (sentence-level claims) and
verification is LEXICAL (a claim is supported when enough of its
content vocabulary appears in the page's own cited raw sources).
That is a weaker instrument than FActScore's model estimator and
the report says so on its face: it catches fabrications and
drift (claims whose words come from nowhere in the evidence),
not subtle paraphrase errors.

For each content page:
  claims      — declarative sentences in the body (headings,
                code, link-only lines and callout markers excluded)
  supported   — claims whose content-token overlap with the
                cited sources' text clears the threshold
  fraction    — supported / verifiable claims
  adjusted    — fraction * min(1, claims / gamma): the
                FActScore-style length penalty (gamma default 10)
  unverifiable — claims whose cited sources could not be read
                as text (excluded from the fraction, counted)

REPORT-ONLY: output goes to evaluation/factcheck-<date>.json and
.md; no wiki page is ever modified by this tool.

    python3 scripts/wiki_factcheck.py [--page wiki/concepts/x.md]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN_RE = re.compile(r"[a-z0-9]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
STOPWORDS = set("""the a an and or of to in is are was were be been being
for on with as by at from this that it its has have had not no do does
did will would can could should may might must shall than then so such
into over under more most other some any only also just very he she we
they you i his her their our your my who whom which what when where why
how all each both few many much own same don now""".split())
STRUCTURAL = {"wiki/index.md", "wiki/log.md"}
EXCLUDED_DIRS = {"access", "talk"}


def _load_validate():
    spec = importlib.util.spec_from_file_location(
        "wiki_validate", ROOT / "scripts" / "wiki_validate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tokenize(text: str):
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) >= 2]


def content_tokens(text: str):
    return {t for t in tokenize(text) if t not in STOPWORDS and len(t) >= 3}


def decompose(body: str) -> list[str]:
    """Deterministic sentence-level claim decomposition."""
    text = re.sub(r"```.*?```", "", body, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    text = re.sub(r"\^\[cite:[^\]]*\]", "", text)
    text = re.sub(r"!\[\[[^\]]*\]\]", "", text)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    claims = []
    # Paragraph-wise: markdown wraps sentences across physical
    # lines, so lines are joined within a blank-line block before
    # sentence splitting (splitting per line would count every
    # wrapped fragment as its own claim).
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        first = lines[0]
        if first.startswith("#") or first.startswith("|") \
                or first.startswith("> [!") or first.startswith("---"):
            continue
        cleaned = []
        for ln in lines:
            ln = re.sub(r"^>\s?", "", ln)
            ln = re.sub(r"^[-*]\s+", "", ln)
            cleaned.append(ln)
        s = " ".join(cleaned)
        for sent in SENTENCE_RE.split(s):
            sent = " ".join(sent.split())
            if len(sent) < 25:
                continue
            if len(content_tokens(sent)) < 3:
                continue
            claims.append(sent)
    return claims


def _slug_tokens(s: str):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def resolve_source(root: Path, entry: str):
    """Resolve a frontmatter sources entry to a file under root,
    following the validator's convention (path, else slug match
    against raw/sources stems). None when unresolvable."""
    if entry.startswith(("http://", "https://")):
        return None
    if "/" in entry:
        p = root / entry
        return p if p.is_file() else None
    want = frozenset(_slug_tokens(entry))
    raw_sources = root / "raw" / "sources"
    if raw_sources.exists():
        for p in sorted(raw_sources.rglob("*")):
            if p.is_file() and frozenset(_slug_tokens(p.stem)) == want:
                return p
    return None


def source_text(root: Path, path: Path) -> str | None:
    """Readable text of a cited source, or None when this machine
    cannot read it as text. PDFs fall back to their PageIndex
    artefact (extractive node summaries) when one exists."""
    suffix = path.suffix.lower()
    if suffix in (".md", ".txt", ".text", ".json"):
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join((pg.extract_text() or "") for pg in reader.pages)
        except ImportError:
            pass
        # PageIndex fallback: the artefact's extractive summaries
        # are verbatim source sentences — partial but real evidence.
        import importlib.util as iu
        pi_path = ROOT / "scripts" / "wiki_pageindex.py"
        if pi_path.is_file():
            try:
                spec = iu.spec_from_file_location("wiki_pageindex", pi_path)
                pi = iu.module_from_spec(spec)
                spec.loader.exec_module(pi)
                slug = pi.slug_for(path)
                art_file = ROOT / "evaluation" / "pageindex" / f"{slug}.json"
                if art_file.is_file():
                    art = json.loads(art_file.read_text(encoding="utf-8"))
                    parts = [n.get("summary") or ""
                             for n, _t in pi.flatten(art["tree"])]
                    return "\n".join(parts)
            except Exception:
                return None
        return None
    return None


def factcheck_page(root: Path, rel_page: str, wv,
                   threshold: float = 0.6, gamma: float = 10.0) -> dict:
    text = (root / rel_page).read_text(encoding="utf-8", errors="ignore")
    fields, body = wv.parse_frontmatter(text)
    claims = decompose(body)
    sources = wv.as_list(fields.get("sources")) if fields else []
    corpus_tokens: Counter = Counter()
    readable, unreadable = [], []
    for entry in sources:
        p = resolve_source(root, entry)
        if p is None:
            unreadable.append(entry)
            continue
        st = source_text(root, p)
        if st is None:
            unreadable.append(entry)
        else:
            readable.append(entry)
            corpus_tokens.update(tokenize(st))
    corpus_vocab = set(corpus_tokens)
    supported, unsupported, unverifiable = [], [], []
    for claim in claims:
        toks = content_tokens(claim)
        if not readable:
            unverifiable.append(claim)
            continue
        overlap = len(toks & corpus_vocab) / max(1, len(toks))
        rec = {"claim": claim[:200], "overlap": round(overlap, 3)}
        (supported if overlap >= threshold else unsupported).append(rec)
    verifiable = len(supported) + len(unsupported)
    fraction = (len(supported) / verifiable) if verifiable else None
    adjusted = (fraction * min(1.0, len(claims) / gamma)
                if fraction is not None else None)
    return {
        "page": rel_page,
        "claims": len(claims),
        "supported": len(supported),
        "unsupported": unsupported,
        "unverifiable_claims": len(unverifiable),
        "fraction": (round(fraction, 3) if fraction is not None else None),
        "adjusted": (round(adjusted, 3) if adjusted is not None else None),
        "sources_readable": readable,
        "sources_unreadable": unreadable,
    }


def run(root: Path, pages: list[str] | None, threshold: float,
        gamma: float) -> dict:
    wv = _load_validate()
    if pages is None:
        pages = []
        wiki = root / "wiki"
        for p in sorted(wiki.rglob("*.md")):
            rel = p.relative_to(root).as_posix()
            if rel in STRUCTURAL:
                continue
            if any(part in EXCLUDED_DIRS
                   for part in Path(rel).parts[1:-1]):
                continue
            pages.append(rel)
    records = [factcheck_page(root, rel, wv, threshold, gamma)
               for rel in pages]
    scored = [r for r in records if r["adjusted"] is not None]
    summary = {
        "pages": len(records),
        "pages_scored": len(scored),
        "claims": sum(r["claims"] for r in records),
        "supported": sum(r["supported"] for r in records),
        "mean_fraction": (round(sum(r["fraction"] for r in scored)
                                / len(scored), 3) if scored else None),
        "mean_adjusted": (round(sum(r["adjusted"] for r in scored)
                                / len(scored), 3) if scored else None),
        "threshold": threshold,
        "gamma": gamma,
    }
    return {"kind": "factcheck", "date": str(date.today()),
            "instrument": "deterministic sentence decomposition + "
                          "lexical support (no LLM estimator)",
            "summary": summary, "records": records}


def render_md(report: dict) -> str:
    s = report["summary"]
    lines = [f"# Atomic-fact audit — {report['date']}",
             "",
             "Instrument: deterministic sentence-level decomposition + "
             "lexical support against each page's cited raw sources "
             "(pattern: shmsw25/FActScore, MIT). Weaker than a model "
             "estimator by design and by necessity — it catches claims "
             "whose vocabulary comes from nowhere in the evidence.",
             "",
             f"Pages audited: {s['pages']} (scored: {s['pages_scored']}) · "
             f"claims: {s['claims']} · supported: {s['supported']} · "
             f"mean supported-fraction: {s['mean_fraction']} · "
             f"mean length-adjusted: {s['mean_adjusted']} "
             f"(gamma={s['gamma']}, threshold={s['threshold']})",
             "",
             "| Page | Claims | Supported | Fraction | Adjusted |",
             "|---|---|---|---|---|"]
    for r in sorted(report["records"],
                    key=lambda r: (r["adjusted"] is None, r["adjusted"])):
        lines.append(f"| {r['page']} | {r['claims']} | {r['supported']} | "
                     f"{r['fraction']} | {r['adjusted']} |")
    lines.append("")
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--page", default=None,
                    help="one repo-relative wiki page (default: all)")
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--gamma", type=float, default=10.0)
    ap.add_argument("--out-dir", default=str(ROOT / "evaluation"))
    args = ap.parse_args(argv)
    pages = [args.page] if args.page else None
    report = run(ROOT, pages, args.threshold, args.gamma)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"factcheck-{report['date']}"
    (out_dir / f"{stem}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (out_dir / f"{stem}.md").write_text(render_md(report), encoding="utf-8")
    s = report["summary"]
    print(f"factcheck: {s['pages']} pages, {s['claims']} claims, "
          f"mean fraction {s['mean_fraction']}, "
          f"mean adjusted {s['mean_adjusted']} -> {out_dir / stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
