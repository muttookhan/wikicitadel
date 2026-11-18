#!/usr/bin/env python3
"""wiki_compile_decompose.py - DocETL decomposition + gleaning pass
for ingest compile (Marathon R7, lane BA; Shankar et al., PVLDB 2025,
CC BY 4.0 pattern, re-implemented as deterministic machinery).

WHAT IS MACHINERY HERE (this module, no model calls):
  * the decomposition rule - a source whose measured complexity
    exceeds the stated threshold in evaluation/compile-decompose.json
    is split before compilation, by section and then by paragraph,
    and every chunk carries a GATHER block (title, class, position,
    neighbouring sections, shared terms, and the first sentence of
    every earlier chunk) so context crosses the split;
  * the gleaning REPORT scaffold - a second, checklist-shaped pass
    over a compiled output whose only job is to report what the
    first pass missed (sections, citations, links, dated/numbered
    facts, caveats), each check keyed to the validation prompt
    recorded for the source's class in the same data file.

WHAT REMAINS AN OPERATOR / MODEL ACT (stated plainly):
  * the compilation itself between decomposition and gleaning -
    an operator or model reads each chunk WITH its gather block
    and writes the compiled page;
  * acting on the gleaning report - the prompts in the data file
    are the exact validation prompts an operator/model runs for
    the model-driven gleaning step; this module records them and
    runs the deterministic subset of their checks, it does not
    pretend the deterministic subset is the whole prompt.

Usage:
  python3 scripts/wiki_compile_decompose.py plan SOURCE [--class C]
  python3 scripts/wiki_compile_decompose.py glean SOURCE COMPILED [--class C]
Exit codes: 0 ok, 1 glean found misses (report still printed),
2 usage error. Stdlib only; JSON on stdout.
"""
from __future__ import annotations
import argparse, json, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_REL = "evaluation/compile-decompose.json"
STOP = set("the a an and or of to in on for with by from as is are was were be been it its this that these those at into about over under between".split())

def load_data(root):
    p = Path(root) / DATA_REL
    return json.loads(p.read_text(encoding="utf-8"))

def source_class_of(text, given=None):
    if given:
        return given
    m = re.search(r"(?m)^type:\s*(\S+)", text or "")
    fm_type = m.group(1) if m else None
    return {"paper": "paper", "repo": "repo"}.get(fm_type, "generic")

def metrics(text):
    sections = re.findall(r"(?m)^##\s+.+$", text)
    return {
        "lines": text.count("\n") + 1,
        "chars": len(text),
        "sections": len(sections),
        "cite_markers": len(re.findall(r"\^\[cite:", text)),
        "sentences": len(re.findall(r"[.!?](?:\s|$)", text)),
    }

def needs_split(m, threshold):
    return any(m.get(k, 0) > v for k, v in threshold.items())

def _sections(text):
    parts, cur_title, cur = [], "preamble", []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            parts.append((cur_title, "\n".join(cur)))
            cur_title, cur = m.group(1).strip(), [line]
        else:
            cur.append(line)
    parts.append((cur_title, "\n".join(cur)))
    return [(t, b) for t, b in parts if b.strip()]

def _first_sentence(text):
    body = re.sub(r"(?m)^#+.*$", "", text).strip()
    m = re.search(r"[^.!?]*[.!?]", body, re.S)
    return " ".join((m.group(0) if m else body[:160]).split())[:200]

def _shared_terms(text, n=12):
    words = [w for w in re.findall(r"[a-z][a-z0-9-]{3,}", text.lower())
             if w not in STOP]
    return [w for w, _ in Counter(words).most_common(n)]

def decompose(text, threshold, source_class="generic", title=""):
    m = metrics(text)
    secs = _sections(text)
    shared = _shared_terms(text)
    chunks_raw = []
    if needs_split(m, threshold):
        max_chars = int(threshold.get("chars", 20000))
        for sec_title, body in secs:
            if len(body) <= max_chars:
                chunks_raw.append((sec_title, body))
            else:
                paras, buf = body.split("\n\n"), ""
                for para in paras:
                    if buf and len(buf) + len(para) > max_chars:
                        chunks_raw.append((sec_title, buf)); buf = para
                    else:
                        buf = (buf + "\n\n" + para) if buf else para
                if buf.strip():
                    chunks_raw.append((sec_title, buf))
    else:
        chunks_raw = [("whole-source", text)]
    chunks = []
    for i, (sec_title, body) in enumerate(chunks_raw):
        chunks.append({
            "index": i, "section": sec_title, "chars": len(body),
            "text": body,
            "gather": {
                "source_title": title, "source_class": source_class,
                "chunk": i + 1, "chunks": len(chunks_raw),
                "previous_section": chunks_raw[i-1][0] if i else None,
                "next_section": chunks_raw[i+1][0] if i+1 < len(chunks_raw) else None,
                "shared_terms": shared,
                "prior_first_sentences": [_first_sentence(b) for _, b in chunks_raw[:i]],
            }})
    return {"metrics": m, "threshold": threshold,
            "split": len(chunks) > 1, "chunks": chunks}

_CAVEAT = re.compile(r"\b(unless|except|provided that|only if|subject to)\b", re.I)
_FACT = re.compile(r"\b\d[\d,./:%-]*\b|\b\d{4}-\d{2}-\d{2}\b")

def _norm(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())

def glean(source_text, compiled_text, prompts):
    comp_norm = _norm(compiled_text)
    missed_sections = [t for t, _ in _sections(source_text)
                       if t != "preamble" and _norm(t) not in comp_norm]
    missed_cites = sorted(set(re.findall(r"\^\[cite:\s*([^\]]+)\]", source_text))
                          - set(re.findall(r"\^\[cite:\s*([^\]]+)\]", compiled_text)))
    missed_links = sorted(set(re.findall(r"\[\[([^\]|]+)", source_text))
                          - set(re.findall(r"\[\[([^\]|]+)", compiled_text)))
    missed_facts, missed_caveats = [], []
    for sent in re.split(r"(?<=[.!?])\s+", re.sub(r"(?m)^#+.*$", "", source_text)):
        s = " ".join(sent.split())
        if not s:
            continue
        present = _norm(s)[:60] in comp_norm
        if _FACT.search(s) and not present and not any(
                tok in compiled_text for tok in _FACT.findall(s)):
            missed_facts.append(s[:200])
        if _CAVEAT.search(s) and _norm(s)[:60] not in comp_norm:
            missed_caveats.append(s[:200])
    checks = [
        {"check": "sections", "missed": missed_sections},
        {"check": "citations", "missed": missed_cites},
        {"check": "links", "missed": missed_links},
        {"check": "dated-or-numbered-facts", "missed": missed_facts},
        {"check": "caveats", "missed": missed_caveats},
    ]
    for i, chk in enumerate(checks):
        chk["validation_prompt"] = prompts[i] if i < len(prompts) else None
    total = sum(len(c["missed"]) for c in checks)
    return {"checks": checks, "missed_total": total,
            "machinery_note": "Deterministic subset only: the recorded "
            "validation prompts are the operator/model gleaning step; "
            "this report scaffolds it and never marks a page verified."}

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("plan"); p1.add_argument("source"); p1.add_argument("--class", dest="cls", default=None)
    p2 = sub.add_parser("glean"); p2.add_argument("source"); p2.add_argument("compiled"); p2.add_argument("--class", dest="cls", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT
    data = load_data(root)
    src_path = Path(args.source)
    if not src_path.is_file():
        print(f"no such source: {src_path}", file=sys.stderr); return 2
    text = src_path.read_text(encoding="utf-8")
    cls = source_class_of(text, args.cls)
    prompts = (data.get("validation_prompts") or {}).get(cls) or         (data.get("validation_prompts") or {}).get("generic", [])
    if args.cmd == "plan":
        title_m = re.search(r"(?m)^title:\s*(.+)$", text)
        plan = decompose(text, data["complexity_threshold"], cls,
                         (title_m.group(1).strip().strip('"') if title_m else src_path.stem))
        plan["source"] = str(src_path); plan["source_class"] = cls
        plan["operator_step"] = "Compile each chunk WITH its gather block; then run the glean pass."
        print(json.dumps(plan, indent=2, sort_keys=True)); return 0
    comp_path = Path(args.compiled)
    if not comp_path.is_file():
        print(f"no such compiled page: {comp_path}", file=sys.stderr); return 2
    report = glean(text, comp_path.read_text(encoding="utf-8"), prompts)
    report.update({"source": str(src_path), "compiled": str(comp_path),
                   "source_class": cls, "validation_prompts": prompts})
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["missed_total"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
