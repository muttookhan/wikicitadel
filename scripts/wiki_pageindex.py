#!/usr/bin/env python3
"""wiki_pageindex.py — PageIndex for long documents.

Pattern: VectifyAI/OpenKB (Apache-2.0)
routes PDFs at/above a page threshold (default 20) away from
whole-text reading into a hierarchical tree index with per-node
summaries, and retrieval reasons over the tree. Adapted to this
machine honestly:

  - segmentation is STRUCTURE-BASED: the PDF outline when one
    exists, else heading-shaped lines detected in the extracted
    text, else fixed page-range chunks;
  - summaries are EXTRACTIVE: each node's summary is its own
    highest-value sentences, verbatim. No LLM endpoint exists on
    this VM, so nothing abstractive is generated or faked;
  - extraction prefers pypdf when importable and falls back to a
    built-in stdlib extractor (FlateDecode streams, Tj/TJ text);
    the artefact records which extractor produced it.

Artefacts land in evaluation/pageindex/<slug>.json (+ a rendered
<slug>.md view). scripts/wiki_search.py traverses them: a query
can land on the exact section of a long source, with page range.

    python3 scripts/wiki_pageindex.py build raw/sources/<doc>.pdf
    python3 scripts/wiki_pageindex.py build-all
    python3 scripts/wiki_pageindex.py show <slug>

Stdlib only (pypdf used opportunistically, never required).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zlib
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "evaluation" / "pageindex"
DEFAULT_MIN_PAGES = 20
CHUNK_PAGES = 5
TOKEN_RE = re.compile(r"[a-z0-9]+")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
STOPWORDS = set("""the a an and or of to in is are was were be been being
for on with as by at from this that it its it is has have had not no yes
do does did will would can could should may might must shall than then
so such into over under more most other some any only also just very
""".split())


# ------------------------------------------------------------ extraction

def _pdf_unescape(s: bytes) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\" and i + 1 < len(s):
            nxt = s[i + 1:i + 2]
            if nxt in b"01234567":
                j = i + 1
                oct_digits = b""
                while j < len(s) and s[j:j + 1] in b"01234567" \
                        and len(oct_digits) < 3:
                    oct_digits += s[j:j + 1]
                    j += 1
                out.append(bytes([int(oct_digits, 8)]))
                i = j
                continue
            mapping = {b"n": b"\n", b"r": b"\r", b"t": b"\t",
                       b"(": b"(", b")": b")", b"\\": b"\\"}
            out.append(mapping.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return b"".join(out).decode("latin-1", errors="replace")


def _content_text(stream: bytes) -> str:
    """Extract text lines from one PDF content stream (Tj / TJ)."""
    lines = []
    # Tokenise: literal strings, hex strings, and the operators we
    # care about. This is a reader for machine-generated PDFs, not
    # a full PDF interpreter — good enough for structure detection.
    token_re = re.compile(rb"\((?:\\.|[^\\()])*\)|<([0-9A-Fa-f\s]+)>|"
                          rb"(Tj|TJ|Td|TD|T\*)")
    cur: list[str] = []
    pending: list[str] = []

    def flush_line():
        if pending:
            lines.append("".join(pending))
            pending.clear()

    pos = 0
    for m in token_re.finditer(stream):
        tok = m.group(0)
        if tok.startswith(b"("):
            pending.append(_pdf_unescape(tok[1:-1]))
        elif tok.startswith(b"<") and m.group(1):
            try:
                pending.append(bytes.fromhex(
                    re.sub(rb"\s+", b"", m.group(1)).decode()).decode(
                        "latin-1", errors="replace"))
            except ValueError:
                pass
        elif tok in (b"Td", b"TD", b"T*"):
            flush_line()
        elif tok in (b"Tj", b"TJ"):
            flush_line()
        pos = m.end()
    flush_line()
    return "\n".join(lines)


def _stdlib_pdf_pages(data: bytes) -> list[str]:
    objects = {}
    for m in re.finditer(rb"(\d+)\s+0\s+obj(.*?)endobj", data, re.S):
        objects[int(m.group(1))] = m.group(2)
    page_objs = []
    kids_order = []
    for num, body in objects.items():
        if re.search(rb"/Type\s*/Pages\b", body):
            km = re.search(rb"/Kids\s*\[(.*?)\]", body, re.S)
            if km:
                kids_order = [int(x) for x in
                              re.findall(rb"(\d+)\s+0\s+R", km.group(1))]
        if re.search(rb"/Type\s*/Page\b", body) \
                and not re.search(rb"/Type\s*/Pages\b", body):
            page_objs.append(num)
    ordered = [n for n in kids_order if n in page_objs] or sorted(page_objs)
    pages = []
    for num in ordered:
        body = objects[num]
        cm = re.search(rb"/Contents\s+(\d+)\s+0\s+R", body)
        texts = []
        if cm:
            cbody = objects.get(int(cm.group(1)), b"")
            sm = re.search(rb"stream\r?\n(.*?)\r?\nendstream", cbody, re.S)
            if sm:
                raw = sm.group(1)
                if b"FlateDecode" in cbody:
                    try:
                        raw = zlib.decompress(raw)
                    except zlib.error:
                        pass
                texts.append(_content_text(raw))
        pages.append("\n".join(texts))
    return pages


def _pypdf_pages(path: Path):
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = [(page.extract_text() or "") for page in reader.pages]
    outline = []

    def walk(items, level):
        for it in items:
            if isinstance(it, list):
                walk(it, level + 1)
            else:
                try:
                    pg = reader.get_destination_page_number(it)
                    outline.append({"title": str(it.title), "page": pg + 1,
                                    "level": level})
                except Exception:
                    continue

    try:
        walk(reader.outline, 0)
    except Exception:
        outline = []
    return pages, outline


def extract(path: Path):
    """-> (pages: [str], outline: [{title, page, level}], extractor)"""
    try:
        pages, outline = _pypdf_pages(path)
        return pages, outline, "pypdf"
    except ImportError:
        pass
    data = path.read_bytes()
    return _stdlib_pdf_pages(data), [], "stdlib"


# ------------------------------------------------------------ segmentation

_HEADING_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+[A-Z][\w ,:&'()-]{2,70}$")
_HEADING_WORD_RE = re.compile(
    r"^(Chapter|Section|Part|Unit|Lesson|Week|Appendix|Introduction|"
    r"Conclusion|Preface)\b.{0,70}$", re.I)


def _heading(line: str):
    """-> (title, depth) when the line is heading-shaped."""
    s = " ".join(line.split())
    if len(s) < 3 or len(s) > 80:
        return None
    m = _HEADING_NUM_RE.match(s)
    if m:
        return s, m.group(1).count(".") + 1
    if _HEADING_WORD_RE.match(s) and not s.endswith("."):
        return s, 1
    if s.isupper() and 3 <= len(s) <= 60 and not s.endswith("."):
        return s, 1
    return None


def _sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    return [s.strip() for s in SENTENCE_RE.split(flat)
            if 30 <= len(s.strip()) <= 400]


def _extractive_summary(text: str, all_texts: list[str], n: int = 3) -> str:
    """The node's own most informative sentences, verbatim, in
    original order. Scored by term rarity across the document's
    nodes (a poor man's TF-IDF) with a small lead bonus — the
    first sentence of a section usually states its business."""
    sents = _sentences(text)
    if not sents:
        return ""
    df = Counter()
    for t in all_texts:
        for tok in set(TOKEN_RE.findall(t.lower())):
            df[tok] += 1
    total = max(1, len(all_texts))

    def score(idx_sent):
        idx, sent = idx_sent
        toks = [t for t in TOKEN_RE.findall(sent.lower())
                if len(t) >= 3 and t not in STOPWORDS]
        if not toks:
            return 0.0
        val = sum((1.0 / (1 + df[t])) for t in set(toks)) / len(set(toks))
        return val * (1.15 if idx == 0 else 1.0)

    ranked = sorted(enumerate(sents), key=lambda p: -score(p))
    chosen = sorted(idx for idx, _s in ranked[:n])
    return " ".join(sents[i] for i in chosen)


def build_tree(pages: list[str], outline: list[dict]) -> list[dict]:
    """Segment the document into a hierarchical node tree."""
    segments = []  # {title, depth, start}  (start = 0-based page)
    if outline:
        for entry in outline:
            segments.append({"title": entry["title"],
                             "depth": entry["level"] + 1,
                             "start": max(0, entry["page"] - 1)})
    else:
        # Running furniture first: a heading-shaped line that
        # repeats on a large share of pages is a page header or
        # footer ("THE PLAN" on every page of a filed plan), not
        # a section. Count candidates across the document and drop
        # the furniture before segmenting.
        per_page = []
        title_pages: Counter = Counter()
        for text in pages:
            cands = []
            for line in text.splitlines():
                h = _heading(line)
                if h:
                    cands.append(h)
            per_page.append(cands)
            for title in {t for t, _d in cands}:
                title_pages[title] += 1
        furniture_limit = max(3, int(0.3 * len(pages)) + 1)
        furniture = {t for t, n in title_pages.items()
                     if n >= furniture_limit}
        for i, cands in enumerate(per_page):
            for title, depth in cands:
                if title in furniture:
                    continue
                if segments and segments[-1]["start"] == i \
                        and segments[-1]["title"] == title:
                    break
                segments.append({"title": title, "depth": depth,
                                 "start": i})
                break  # first real heading on a page opens the segment
    if not segments or segments[0]["start"] > 0:
        segments.insert(0, {"title": "Opening", "depth": 1, "start": 0})
    # Deduplicate consecutive segments starting on the same page.
    deduped = []
    for seg in segments:
        if deduped and deduped[-1]["start"] == seg["start"]:
            continue
        deduped.append(seg)
    segments = deduped
    if len(segments) == 1 and len(pages) > CHUNK_PAGES:
        segments = [{"title": f"Pages {i + 1}–{min(i + CHUNK_PAGES, len(pages))}",
                     "depth": 1, "start": i}
                    for i in range(0, len(pages), CHUNK_PAGES)]

    nodes = []
    for idx, seg in enumerate(segments):
        end = (segments[idx + 1]["start"] - 1) if idx + 1 < len(segments) \
            else len(pages) - 1
        if end < seg["start"]:
            continue
        text = "\n".join(pages[seg["start"]:end + 1])
        nodes.append({"id": f"n{len(nodes) + 1}", "title": seg["title"],
                      "depth": seg["depth"],
                      "pages": [seg["start"] + 1, end + 1],
                      "text": text, "children": []})
    # Nest by depth: a node becomes a child of the nearest previous
    # node of strictly smaller depth.
    roots: list[dict] = []
    stack: list[dict] = []
    for node in nodes:
        while stack and stack[-1]["depth"] >= node["depth"]:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)
    all_texts = [n["text"] for n in nodes]

    def finish(node):
        node["summary"] = _extractive_summary(node["text"], all_texts)
        node["chars"] = len(node["text"])
        del node["text"]
        del node["depth"]
        for c in node["children"]:
            finish(c)

    for r in roots:
        finish(r)
    return roots


def count_nodes(nodes) -> int:
    return sum(1 + count_nodes(n["children"]) for n in nodes)


# ------------------------------------------------------------ build / CLI

def slug_for(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")


def build_index(path: Path, min_pages: int = DEFAULT_MIN_PAGES,
                force: bool = False, out_dir: Path = OUT_DIR) -> dict:
    pages, outline, extractor = extract(path)
    result = {"source": str(path.relative_to(ROOT))
              if path.is_relative_to(ROOT) else str(path),
              "pages": len(pages), "extractor": extractor}
    if len(pages) < min_pages and not force:
        return {**result, "built": False,
                "reason": f"{len(pages)} pages < threshold {min_pages}"}
    tree = build_tree(pages, outline)
    artefact = {
        "kind": "pageindex",
        "version": 1,
        "source": result["source"],
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "pages": len(pages),
        "extractor": extractor,
        "min_pages": min_pages,
        "built": str(date.today()),
        "node_count": count_nodes(tree),
        "tree": tree,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = slug_for(path)
    (out_dir / f"{slug}.json").write_text(
        json.dumps(artefact, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    (out_dir / f"{slug}.md").write_text(render_md(artefact), encoding="utf-8")
    return {**result, "built": True, "slug": slug,
            "nodes": artefact["node_count"]}


def render_md(artefact: dict) -> str:
    lines = [f"# PageIndex — {artefact['source']}",
             "",
             f"{artefact['pages']} pages · {artefact['node_count']} nodes · "
             f"extracted with {artefact['extractor']} · "
             f"built {artefact['built']}. Summaries are EXTRACTIVE "
             "(verbatim sentences), never paraphrase.",
             ""]

    def walk(nodes, depth):
        for n in nodes:
            lines.append(f"{'#' * (depth + 1)} {n['title']} "
                         f"(pp. {n['pages'][0]}–{n['pages'][1]})")
            lines.append("")
            if n["summary"]:
                lines.append(n["summary"])
                lines.append("")
            walk(n["children"], depth + 1)

    walk(artefact["tree"], 1)
    return "\n".join(lines)


def load_indexes(out_dir: Path = OUT_DIR) -> list[dict]:
    if not out_dir.exists():
        return []
    out = []
    for p in sorted(out_dir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def flatten(nodes, trail=None):
    trail = trail or []
    for n in nodes:
        path = trail + [n["title"]]
        yield n, path
        yield from flatten(n["children"], path)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("pdf")
    b.add_argument("--min-pages", type=int, default=DEFAULT_MIN_PAGES)
    b.add_argument("--force", action="store_true")
    sub.add_parser("build-all")
    s = sub.add_parser("show")
    s.add_argument("slug")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        res = build_index(Path(args.pdf), args.min_pages, args.force)
        print(json.dumps(res, indent=2))
        return 0
    if args.cmd == "build-all":
        pdfs = sorted((ROOT / "raw").rglob("*.pdf"))
        for pdf in pdfs:
            res = build_index(pdf)
            state = (f"built {res['nodes']} nodes" if res.get("built")
                     else f"skipped ({res['reason']})")
            print(f"{res['source']}: {res['pages']} pages, {state}")
        return 0
    if args.cmd == "show":
        p = OUT_DIR / f"{args.slug}.json"
        if not p.exists():
            print(f"no pageindex for {args.slug!r}", file=sys.stderr)
            return 2
        art = json.loads(p.read_text(encoding="utf-8"))
        for node, trail in flatten(art["tree"]):
            print(f"{'  ' * (len(trail) - 1)}{node['title']} "
                  f"(pp. {node['pages'][0]}–{node['pages'][1]})")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
