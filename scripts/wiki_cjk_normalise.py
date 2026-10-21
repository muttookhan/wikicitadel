#!/usr/bin/env python3
"""wiki_cjk_normalise.py - Vditor CJK normalisation rule set checker.

Marathon R13 lane BB (ideas board line 199, Round 11 RB, Tier A):
adopt the RULE SET only (not the editor) from Vditor / Lute
(MIT) for CJK text handling in clip/ingest-adjacent paths. The
rules live AS DATA in evaluation/cjk-normalisation-rules.json
with attribution; this module re-implements the four applied
rules in stdlib Python and never touches code spans or fenced
code blocks. `normalise` prints corrected text to stdout and
writes nothing; `check` reports findings and writes nothing.
Commands: rules / check FILE / normalise FILE.
Exit: check 0 clean, 1 findings; other commands 0; 2 usage.
Stdlib only, no network.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "evaluation" / "cjk-normalisation-rules.json"
CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af"
FW_PUNCT = "\uff0c\u3002\uff01\uff1f\uff1b\uff1a\u3001\uff08\uff09\u300c\u300d\u300e\u300f"
HALF2FULL = {",": "\uff0c", ".": "\u3002", "!": "\uff01",
             "?": "\uff1f", ";": "\uff1b", ":": "\uff1a"}


def is_cjk(ch):
    return bool(ch) and re.match("[" + CJK + "]", ch) is not None


def load_rules(path=None):
    return json.loads(Path(path or RULES).read_text(encoding="utf-8"))


def segments(text):
    parts = []
    buf = ""
    fence = False
    for line in text.splitlines(True):
        if line.lstrip().startswith("```"):
            if buf:
                parts.append((fence, buf))
                buf = ""
            fence = not fence
            parts.append((True, line))
            continue
        buf += line
    if buf:
        parts.append((fence, buf))
    out = []
    for code, chunk in parts:
        if code:
            out.append((True, chunk))
            continue
        for j, seg in enumerate(re.split(r"(`[^`\n]*`)", chunk)):
            out.append((j % 2 == 1, seg))
    return out


def normalise_segment(seg):
    findings = []

    def fw_alnum(m):
        findings.append(("cjk-fullwidth-alnum-to-halfwidth", m.group(0)))
        return chr(ord(m.group(0)) - 0xFEE0)

    seg = re.sub(r"[\uff10-\uff19\uff21-\uff3a\uff41-\uff5a]",
                 fw_alnum, seg)
    chars = list(seg)
    out = []
    for i, ch in enumerate(chars):
        prev = chars[i - 1] if i else ""
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if ch in HALF2FULL and (is_cjk(prev) or is_cjk(nxt)):
            findings.append(("cjk-halfwidth-punct-to-fullwidth", ch))
            out.append(HALF2FULL[ch])
        else:
            out.append(ch)
    seg = "".join(out)
    chars = list(seg)
    out = []
    for i, ch in enumerate(chars):
        prev = out[-1] if out else ""
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if ch == " " and (prev in FW_PUNCT or nxt in FW_PUNCT):
            findings.append(("cjk-no-space-fullwidth-punct", " "))
            continue
        latin_prev = bool(re.match(r"[A-Za-z0-9]", prev or " "))
        latin_ch = bool(re.match(r"[A-Za-z0-9]", ch or " "))
        if (is_cjk(prev) and latin_ch) or (latin_prev and is_cjk(ch)):
            findings.append(("cjk-autospace", prev + ch))
            out.append(" ")
        out.append(ch)
    return "".join(out), findings


def process(text):
    findings = []
    out = []
    for code, chunk in segments(text):
        if code:
            out.append(chunk)
            continue
        new, found = normalise_segment(chunk)
        out.append(new)
        findings.extend(found)
    return "".join(out), findings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rules")
    for name in ("check", "normalise"):
        p = sub.add_parser(name)
        p.add_argument("file")
    a = ap.parse_args(argv)
    if a.cmd == "rules":
        print(json.dumps(load_rules(), ensure_ascii=False, indent=2))
        return 0
    text = Path(a.file).read_text(encoding="utf-8")
    new, findings = process(text)
    if a.cmd == "normalise":
        sys.stdout.write(new)
        return 0
    for rule, frag in findings:
        print(f"FINDING {rule}: {frag!r}")
    print(f"{len(findings)} finding(s) in {a.file}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
