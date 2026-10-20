#!/usr/bin/env python3
"""Claim matching + verdict inheritance (WikiCitadel v1;
Squash / Meedan Check via the survey).

Before new checking or compiling work starts, incoming text
is matched against the claims this wiki has ALREADY settled,
and a human (the owner, or the agent acting for him) picks
which proposed match is real. The expensive work is reserved
for genuinely new claims. A reworded repeat of a settled
claim, once picked, INHERITS the settled claim's status
instead of spawning a second, divergent record — one settled
verdict, many surface forms (Meedan's answer to "zombie"
claims that keep travelling in new words).

The settled corpus is assembled from three places:

  claim pages   — any wiki page carrying `claim:` frontmatter;
                  the status offered for inheritance is its
                  `outcome_status` (candidate / rule / retired)
                  when present, else its page `status`.
  beliefs       — the bullet lines of wiki/syntheses/beliefs.md;
                  each is an owner position currently held.
  decisions     — evaluation/decisions-register.jsonl: each
                  decision's current form (status: the
                  register's), AND each superseded form (status:
                  superseded) — a repeat of a superseded form
                  must surface as such, not pass as new.

Scoring is deliberately simple and inspectable: token
containment over content words (how much of the shorter text
the longer one covers) plus the Jaccard overlap of citation
tokens (raw/ paths and [[wikilinks]] both sides cite). No
embeddings, no model, nothing to drift silently.

THIS TOOL NEVER EDITS ANYTHING. `match` only prints ranked
candidates. A pick is a human act; `record` appends it to
evaluation/claim-matches.jsonl (picker, date, chosen claim,
verdict inherited) and changes nothing else — the ingest
rule that follows from a pick lives in the schema: the
incoming material is linked to the
existing claim record and inherits its status; it never
opens a second record for the same claim.

Usage:
  python3 scripts/wiki_claim_match.py match --file incoming.md
  python3 scripts/wiki_claim_match.py match --text "a claim restated"
  cat draft.md | python3 scripts/wiki_claim_match.py match -
  python3 scripts/wiki_claim_match.py record \
      --picker agent --claim wiki/overview.md \
      --verdict "rule" [--incoming-text "..." | --incoming-file F]

Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCHES_REL = Path("evaluation/claim-matches.jsonl")
BELIEFS_REL = Path("wiki/syntheses/beliefs.md")
REGISTER_REL = Path("evaluation/decisions-register.jsonl")

NOISE_FLOOR = 0.35

STOPWORDS = set("""
a an the and or of to in on for with by at from as is are was were be
been being it its this that these those there here not no yes if then
than so such into over under between about against when while who
whom whose what which how all any both each few more most other some
only own same too very can will just should now
""".split())

TOKEN_RE = re.compile(r"[a-z0-9]+")
CITE_RE = re.compile(r"(raw/[^\s\]\)\"']+|\[\[[^\]]+\]\])")

HEADER = {
    "kind": "header",
    "register": "claim-matches",
    "version": 1,
    "purpose": ("Picks made under claim matching (scripts/"
                "wiki_claim_match.py; WikiCitadel v1): "
                "when incoming text restates an already-settled "
                "claim, the picker records the chosen claim here and "
                "the incoming material inherits its settled status "
                "instead of spawning a divergent record. One line "
                "per pick: date, picker, chosen claim, verdict "
                "inherited. The tool never merges or edits anything; "
                "this register is the record of the human picks."),
}


# ---------------------------------------------------------------- corpus

def _split_frontmatter(text):
    m = re.match(r"\A---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def _fm_scalar(fm_text, key):
    m = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm_text, re.M)
    if not m:
        return None
    return m.group(1).strip().strip("\"'")


def build_corpus(root: Path):
    """The settled corpus: claim pages, beliefs lines, decisions
    (current + superseded forms). Each entry: id, kind, text,
    status (the verdict a pick would inherit)."""
    corpus = []
    wiki = root / "wiki"
    if wiki.is_dir():
        for p in sorted(wiki.rglob("*.md")):
            if "access" in p.relative_to(wiki).parts:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            fm, _ = _split_frontmatter(text)
            if fm is None:
                continue
            claim = _fm_scalar(fm, "claim")
            if not claim:
                continue
            status = (_fm_scalar(fm, "outcome_status")
                      or _fm_scalar(fm, "status") or "unstated")
            corpus.append({
                "id": p.relative_to(root).as_posix(),
                "kind": "claim-page",
                "text": claim,
                "status": status,
            })
    beliefs = root / BELIEFS_REL
    if beliefs.exists():
        for line in beliefs.read_text(
                encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("- "):
                corpus.append({
                    "id": BELIEFS_REL.as_posix(),
                    "kind": "belief",
                    "text": line[2:].strip(),
                    "status": "held — owner position (beliefs page)",
                })
    register = root / REGISTER_REL
    if register.exists():
        for line in register.read_text(
                encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("kind") != "decision":
                continue
            corpus.append({
                "id": f"decision {obj['id']} ({obj.get('title', '')})",
                "kind": "decision",
                "text": obj.get("current_form", ""),
                "status": obj.get("status", "active"),
            })
            for form in obj.get("superseded_forms", []):
                corpus.append({
                    "id": f"decision {obj['id']} superseded form "
                          f"{form.get('form_id', '')}",
                    "kind": "decision-superseded-form",
                    "text": form.get("title", ""),
                    "status": f"superseded on "
                              f"{form.get('superseded_on', '?')}",
                })
    return corpus


# ---------------------------------------------------------------- scoring

def tokenize(text: str):
    return {t for t in TOKEN_RE.findall(text.lower())
            if t not in STOPWORDS and len(t) > 1}


def citation_tokens(text: str):
    out = set()
    for raw in CITE_RE.findall(text):
        out.add(raw.strip("[]").split("|")[0].split("#")[0].lower())
    return out


def score_pair(incoming: str, candidate: str) -> float:
    """0..1 — token containment blended with citation overlap."""
    a, b = tokenize(incoming), tokenize(candidate)
    if not a or not b:
        return 0.0
    containment = len(a & b) / min(len(a), len(b))
    ca, cb = citation_tokens(incoming), citation_tokens(candidate)
    if ca and cb:
        cite_j = len(ca & cb) / len(ca | cb)
        return round(min(1.0, 0.8 * containment + 0.2 * cite_j), 4)
    return round(containment, 4)


def match(incoming: str, corpus, top=5):
    scored = []
    for entry in corpus:
        s = score_pair(incoming, entry["text"])
        if s > 0:
            scored.append((s, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return scored[:top]


# ---------------------------------------------------------------- picks

def record_pick(root: Path, picker: str, claim_id: str, verdict: str,
                incoming_text=None, when=None) -> dict:
    record = {
        "kind": "pick",
        "date": when or date.today().isoformat(),
        "picker": picker,
        "chosen_claim": claim_id,
        "verdict_inherited": verdict,
    }
    if incoming_text:
        record["incoming_sha256"] = hashlib.sha256(
            incoming_text.encode("utf-8")).hexdigest()
        record["incoming_preview"] = " ".join(incoming_text.split())[:120]
    p = root / MATCHES_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not p.exists() or p.stat().st_size == 0
    with p.open("a", encoding="utf-8") as fh:
        if needs_header:
            header = dict(HEADER, created=date.today().isoformat())
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


# ---------------------------------------------------------------- main

def _read_incoming(args) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.text:
        return args.text
    return sys.stdin.read()


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None,
                    help="repo root (default: this script's repo)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("match", help="rank settled-claim candidates "
                                     "for incoming text (read-only)")
    m.add_argument("source", nargs="?", default=None,
                   help="'-' or omitted: read the text from stdin")
    m.add_argument("--file", default=None)
    m.add_argument("--text", default=None)
    m.add_argument("--top", type=int, default=5)

    r = sub.add_parser("record", help="record a human pick in "
                                      "evaluation/claim-matches.jsonl")
    r.add_argument("--picker", required=True)
    r.add_argument("--claim", required=True,
                   help="the chosen corpus entry id, exactly as "
                        "printed by `match`")
    r.add_argument("--verdict", required=True,
                   help="the settled status the incoming text "
                        "inherits")
    r.add_argument("--incoming-text", default=None)
    r.add_argument("--incoming-file", default=None)
    r.add_argument("--date", default=None)

    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else ROOT

    if args.cmd == "match":
        incoming = _read_incoming(args).strip()
        if not incoming:
            print("no incoming text", file=sys.stderr)
            return 2
        corpus = build_corpus(root)
        results = match(incoming, corpus, top=args.top)
        print(f"settled corpus: {len(corpus)} entries "
              f"(claim pages, beliefs, decisions)")
        if not results:
            print("no candidates share any content tokens — "
                  "treat as genuinely new.")
            return 0
        for i, (score, entry) in enumerate(results, 1):
            snippet = " ".join(entry["text"].split())[:140]
            print(f"{i}. [{score:.2f}] {entry['kind']} · "
                  f"{entry['id']}")
            print(f"    would inherit: {entry['status']}")
            print(f"    claim: {snippet}")
        if results[0][0] < NOISE_FLOOR:
            print(f"\nTop score {results[0][0]:.2f} is below the "
                  f"{NOISE_FLOOR} noise floor — no confident match; "
                  "treat as genuinely new unless a human sees the "
                  "kinship the tokens miss.")
        return 0

    incoming_text = args.incoming_text
    if args.incoming_file:
        incoming_text = Path(args.incoming_file).read_text(
            encoding="utf-8")
    record = record_pick(root, args.picker, args.claim, args.verdict,
                         incoming_text=incoming_text, when=args.date)
    print(f"pick recorded: {record['date']} · {record['picker']} · "
          f"{record['chosen_claim']} · inherits "
          f"{record['verdict_inherited']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
