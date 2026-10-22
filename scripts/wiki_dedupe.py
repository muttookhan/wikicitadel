#!/usr/bin/env python3
"""wiki_dedupe.py — capture-time dedupe, vocabulary-constrained
filing, and the consolidation-exclusion registry (build-list
W1.9, 2026-10-22).

Idea sources (IDEAS ONLY, clean re-implementation in our own
code from the described mechanisms): the Clippings Dedupe
rules (Round 5 deep-dive), Bookmarker, @dhague/wiki-knowledge
— all three recorded in the completion masters; nothing here
is copied from any of them.

ONE DEDUPE DESIGN ACROSS ALL APPEND DOORS. The doors that
append or re-admit content — the filings pickup's capture
path (scripts/wiki_mailcapture.py), the capture templates
(scripts/wiki_capture.py), the staging inbox
(scripts/wiki_staging_inbox.py) — share this module's rules:

  text-as-identity
      A capture's identity is its TEXT, not its filename,
      message id or timestamp. Identity is a semantic
      fingerprint: SHA-256 over the normalised payload —
      frontmatter stripped, datamark wrappers removed,
      date/time tokens replaced by a placeholder, HTML
      comments removed (commentary is the tiebreak, not
      identity), case folded, whitespace collapsed. Two
      copies of the same text have the same fingerprint
      however they arrived.

  comment-bearing copy wins
      When two copies share a fingerprint and one carries
      commentary the other lacks — an HTML comment beyond
      the harness furniture, an owner annotation mark
      (^[mark: ...]) — the comment-bearing copy is the
      survivor: it is strictly richer, and the bare copy's
      only extra fact (its provenance) is preserved by the
      door's own raw record and by the dedupe log. When both
      or neither carry commentary and the normalised texts
      still differ, that is a COLLISION: both copies are
      kept — nothing is ever merged away on a fingerprint
      alone.

  backup-before-rewrite (literal)
      No rewrite path runs without a backup artefact first:
      backup_before_rewrite() copies the current file under
      the door's backup dir and returns its path; only then
      may the caller write. The dedupe log names the backup
      beside the decision it belongs to.

  never silently dropped
      Every dedupe decision is appended to the door's dedupe
      log (JSONL) with the surviving copy NAMED. A skipped
      write is a logged act with a named survivor, never a
      disappearance; where a door keeps its own immutable
      raw record (mail capture), that record is written
      before dedupe is even consulted.

VOCABULARY-CONSTRAINED FILING. The filing router's proposals
(scripts/wiki_filing_router.py) carry a `vocabulary` block
from vocabulary_check(): every tag on the item must resolve
in the tag registry (evaluation/tag-registry.jsonl —
prefLabel or altLabel; a deprecated concept is a violation),
and every declared relation field must be one of the adopted
frontmatter spellings of the closed relation vocabulary
(wiki/rules/relation-vocabulary.md, incl. the grounds
extension). A frontmatter key that carries a relation stem
but is not an adopted spelling is a violation: the
vocabulary is closed, and a proposal may not smuggle a new
relation in by naming it almost-right. The check REPORTS;
it never edits, registers or moves anything — registering a
tag or amending the vocabulary stays the recorded act it
already is.

CONSOLIDATION-EXCLUSION REGISTRY. evaluation/
consolidation-exclusions.jsonl — append-only. When a
merge/consolidation of two records is DECLINED (by the owner
or a recorded review act), record_decline() appends the
pair keyed by BOTH records' git blob OIDs and semantic
fingerprints. check_pair() then reports the pair as
`excluded` while both sides are byte- and fingerprint-
identical to the declined state — a proposer (consolidation,
entity-merge, dedupe) must not re-propose it — and as
`changed` (re-proposal allowed, the changed side named)
once either side's content moves. The checker reports; it
never deletes, blocks a write, or acts on its own.

CLI:
    python3 scripts/wiki_dedupe.py fingerprint <file>
    python3 scripts/wiki_dedupe.py check <fileA> <fileB>
    python3 scripts/wiki_dedupe.py vocab <file>... [--root R]
    python3 scripts/wiki_dedupe.py exclusions list [--root R]
    python3 scripts/wiki_dedupe.py exclusions check <A> <B>
                                             [--root R]
    python3 scripts/wiki_dedupe.py exclusions decline <A> <B>
        --by WHO --reason "..." [--root R]

Exit codes: 0 ok · 1 a check found its flagged state
(excluded pair / vocabulary violations) · 2 usage/input.
Stdlib only.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

LOG_REL = "evaluation/dedupe-log.jsonl"
EXCLUSIONS_REL = "evaluation/consolidation-exclusions.jsonl"

DATA_MARK_OPEN = "<<<DATA"
DATA_MARK_CLOSE = "<<</DATA>>>"

# ---------------------------------------------------------------
# Identity: blob OID + semantic fingerprint
# ---------------------------------------------------------------


def blob_oid(data: bytes) -> str:
    """The git blob OID of a byte string: SHA-1 of
    'blob <len>\\0' + data — computed, never shelled out, so
    it is identical inside and outside a checkout."""
    head = b"blob %d\x00" % len(data)
    return hashlib.sha1(head + data).hexdigest()


def strip_frontmatter(text):
    """The payload of a markdown file: everything after a
    leading --- ... --- block. Text without one is its own
    payload."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end >= 0:
            nl = text.find("\n", end + 1)
            return text[nl + 1:] if nl >= 0 else ""
    return text


_DATAMARK_LINE = re.compile(r"^.*<<< ?/?DATA.*$", re.M)
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_ZONE = r"(?:UTC|EST|EDT|CST|CDT|MST|MDT|PST|PDT)"
_WHEN = re.compile(
    r"\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2}|" + _ZONE + r")?"
    r"|\d{2}:\d{2}(:\d{2})?\s*" + _ZONE + r"?")
_WS = re.compile(r"\s+")


def normalise(text):
    """Identity normalisation (documented in the module
    docstring): datamark wrappers out, date/time tokens
    replaced, HTML comments out, case folded, whitespace
    collapsed. Punctuation and wording are identity —
    normalisation never rewrites what a text SAYS."""
    t = _DATAMARK_LINE.sub("", text)
    t = _COMMENT.sub("", t)
    t = _WHEN.sub("<when>", t)
    t = t.casefold()
    return _WS.sub(" ", t).strip()


def fingerprint(text):
    """Semantic fingerprint of a payload: SHA-256 of its
    normalisation. Callers pass payloads (bodies), or full
    markdown — payload_of() is applied first either way for
    full files; see fingerprint_body for raw bodies."""
    return hashlib.sha256(
        normalise(text).encode("utf-8")).hexdigest()


def fingerprint_body(body):
    """Fingerprint of a raw captured body (no frontmatter to
    strip — the body IS the payload)."""
    return fingerprint(body)


def fingerprint_file_text(text):
    """Fingerprint of a whole markdown file: fingerprint of
    its payload (frontmatter stripped)."""
    return fingerprint(strip_frontmatter(text))


def datamark_payloads(text):
    """The bodies carried inside a file's datamark sections
    (the mail-capture draft shape), in order."""
    out = []
    for m in re.finditer(
            r"<<<DATA[^>]*>>>\n?(.*?)\n?<<</DATA>>>", text, re.S):
        out.append(m.group(1))
    return out


# ---------------------------------------------------------------
# Commentary + the decision algebra
# ---------------------------------------------------------------

_HARNESS_COMMENT_PREFIXES = ("<!-- write from here -->",
                             "<!-- CAPTURE TEMPLATE")


def _commentary_signature(text):
    """The commentary a payload carries, as a comparable
    signature: the sorted non-harness HTML comments plus a
    flag for owner annotation marks. Two copies whose
    signatures differ are NOT the same capture, however
    equal their bare text — the difference is exactly what
    the wins rule and the collision rule adjudicate."""
    comments = sorted(
        m.group(0) for m in _COMMENT.finditer(text)
        if not any(m.group(0).startswith(p)
                   for p in _HARNESS_COMMENT_PREFIXES))
    return (tuple(comments), "^[mark:" in text)


def has_commentary(text):
    """True when a payload carries commentary beyond the bare
    text: an HTML comment that is not harness furniture, or
    an owner annotation mark (^[mark: ...])."""
    comments, marked = _commentary_signature(text)
    return bool(comments) or marked


def decide(existing, incoming):
    """The dedupe decision between two payloads. Returns a
    dict: outcome, fingerprint, both commentary flags,
    normalised_equal, survivor ('existing' / 'incoming' /
    'both' / None when the texts are simply distinct).

    Outcomes:
      distinct            fingerprints differ — not the
                          same capture at all.
      exact-duplicate     same fingerprint, same normalised
                          text, same commentary profile —
                          the existing copy stands.
      existing-wins       same fingerprint; the existing
                          copy carries commentary the
                          incoming lacks.
      incoming-wins       same fingerprint; the incoming
                          copy carries commentary the
                          existing lacks — it supersedes.
      collision-keep-both same fingerprint, but the copies
                          differ beyond a commentary gap
                          (both annotated differently): a
                          fingerprint is not proof enough
                          to destroy either — both kept.
    """
    fp_e, fp_i = fingerprint(existing), fingerprint(incoming)
    base = {"fingerprint": fp_i,
            "existing_commentary": has_commentary(existing),
            "incoming_commentary": has_commentary(incoming),
            "normalised_equal":
                normalise(existing) == normalise(incoming)}
    if fp_e != fp_i:
        return {**base, "outcome": "distinct", "survivor": None}
    # Same fingerprint from here: the bare texts agree. What
    # remains is the commentary — compared by SIGNATURE, not
    # by presence, so two differently-annotated copies are a
    # collision (both kept), never a silent exact-duplicate.
    sig_e = _commentary_signature(existing)
    sig_i = _commentary_signature(incoming)
    if sig_e == sig_i:
        return {**base, "outcome": "exact-duplicate",
                "survivor": "existing"}
    if sig_i != ((), False) and sig_e == ((), False):
        return {**base, "outcome": "incoming-wins",
                "survivor": "incoming"}
    if sig_e != ((), False) and sig_i == ((), False):
        return {**base, "outcome": "existing-wins",
                "survivor": "existing"}
    return {**base, "outcome": "collision-keep-both",
            "survivor": "both"}


# ---------------------------------------------------------------
# Backup-before-rewrite + the dedupe log
# ---------------------------------------------------------------


def backup_before_rewrite(root, path, door, backup_dir=None,
                          stamp=None):
    """Copy `path` (repo-relative or absolute under root) to
    the door's backup dir BEFORE any rewrite. Returns the
    backup's repo-relative path. Refuses to proceed when the
    source does not exist — a rewrite with no backup is not
    a state this design admits."""
    src = Path(path)
    if not src.is_absolute():
        src = Path(root) / src
    if not src.is_file():
        raise FileNotFoundError(
            "backup-before-rewrite: no such file: %s" % src)
    bdir = Path(backup_dir) if backup_dir else \
        Path(root) / "staging" / "dedupe-backups"
    if not bdir.is_absolute():
        bdir = Path(root) / bdir
    day = stamp or _date.today().isoformat()
    dest_dir = bdir / day
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (src.name + ".bak")
    n = 2
    while dest.exists():
        dest = dest_dir / ("%s.%d.bak" % (src.name, n))
        n += 1
    dest.write_bytes(src.read_bytes())
    try:
        return str(dest.relative_to(Path(root)))
    except ValueError:
        return str(dest)


def log_decision(root, record, log_path=None):
    """Append one dedupe decision (a dict) to the dedupe log
    as a JSONL line. The record is stamped kind/at here when
    the caller did not supply them."""
    record = {k: v for k, v in record.items()
              if not (k == "at" and not v)}
    rec = {"kind": "dedupe-decision",
           "at": _date.today().isoformat(), **record}
    root_p = Path(root)
    dest = Path(log_path) if log_path else root_p / LOG_REL
    if not dest.is_absolute():
        # A caller that already joined the root onto the log
        # path (the voice-capture / media-ingest call shape)
        # must not be joined twice (tree/tree/...). A plain
        # root-relative path still joins, as before.
        # (Coordinator repair, 2026-10-22.)
        joined = str(root_p) + "/"
        if not (str(dest) == str(root_p)
                or str(dest).startswith(joined)):
            dest = root_p / dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


# ---------------------------------------------------------------
# Vocabulary-constrained filing
# ---------------------------------------------------------------

# Adopted frontmatter spellings (wiki/rules/
# relation-vocabulary.md + the grounds extension recorded in
# the schema): the closed list a declared relation may use.
RELATION_FIELDS = {
    "supersedes", "superseded_by", "cites", "cited_by",
    "corrects", "corrected_by", "extends", "contradicts",
    "derives_from", "replaces_part_of", "grounds",
    "grounded_by",
}

# Stems that make a frontmatter key LOOK like a relation
# assertion. A key carrying one that is not an adopted
# spelling is an undeclared relation — a violation, because
# the vocabulary is closed.
_RELATION_STEMS = ("supersede", "cite", "cited", "correct",
                   "extend", "contradict", "derive", "replace",
                   "ground", "based_on", "obsolete", "precede",
                   "follows", "part_of", "succeed")


def _parse_tags(raw):
    if raw is None:
        return []
    s = str(raw).strip().strip("[]")
    out = []
    for piece in s.split(","):
        piece = piece.strip().strip('"').strip("'")
        if piece:
            out.append(piece)
    return out


def vocabulary_check(frontmatter, root):
    """Constrain a filing proposal's declared vocabulary.

    frontmatter: a {key: raw-value} dict (the router's
    parser shape). Returns {"ok", "violations", "tags",
    "relations"} — reporting only, nothing is edited or
    registered here.
    """
    import wiki_tags  # sibling tool; loaded lazily (it pulls
    # the validator) and only on this path.
    root = Path(root)
    violations = []
    _header, concepts = wiki_tags.load_registry(root)
    tags = _parse_tags(frontmatter.get("tags"))
    for tag in tags:
        concept, _form = wiki_tags.resolve_concept(concepts, tag)
        if concept is None:
            violations.append(
                "unregistered tag %r — not in the tag registry "
                "(evaluation/tag-registry.jsonl); registering "
                "it is a separate recorded act" % tag)
        elif str(concept.get("status", "")).lower() == "deprecated":
            violations.append(
                "deprecated tag %r — the registry supersedes "
                "it (replacedBy: %s); a new filing may not "
                "declare it" % (tag,
                                concept.get("replacedBy") or "?"))
    relations = []
    for key in sorted(frontmatter):
        lk = key.lower()
        if lk in RELATION_FIELDS:
            relations.append(lk)
        elif any(stem in lk for stem in _RELATION_STEMS):
            violations.append(
                "undeclared relation field %r — the relation "
                "vocabulary is closed (wiki/rules/"
                "relation-vocabulary.md); adopted spellings: "
                "%s" % (key, ", ".join(sorted(RELATION_FIELDS))))
    return {"ok": not violations, "violations": violations,
            "tags": tags, "relations": relations}


# ---------------------------------------------------------------
# Consolidation-exclusion registry
# ---------------------------------------------------------------


def _pair_key(a, b):
    return tuple(sorted([str(a), str(b)]))


def _state_of(root, rel):
    p = Path(root) / rel
    data = p.read_bytes()
    return {"oid": blob_oid(data),
            "fingerprint": fingerprint_file_text(
                data.decode("utf-8", errors="replace"))}


def load_exclusions(root):
    path = Path(root) / EXCLUSIONS_REL
    out = []
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("kind") == "consolidation-exclusion":
            out.append(obj)
    return out


def record_decline(root, a, b, by, reason, at=None):
    """Append a declined-merge record for the pair (a, b),
    keyed by both sides' CURRENT blob OID + fingerprint.
    Append-only: the file is opened for append, never
    rewritten. Returns the record written."""
    a, b = _pair_key(a, b)
    rec = {"kind": "consolidation-exclusion",
           "pair": [a, b],
           "states": {a: _state_of(root, a),
                      b: _state_of(root, b)},
           "decision": "declined",
           "decided_at": at or _date.today().isoformat(),
           "decided_by": by,
           "reason": reason}
    path = Path(root) / EXCLUSIONS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        header = {"kind": "header",
                  "registry": "consolidation-exclusions",
                  "format": "one JSON object per line; a pair "
                            "is excluded while BOTH sides' "
                            "git blob OID and semantic "
                            "fingerprint equal the recorded "
                            "states; any change re-opens "
                            "the pair. Append-only."}
        path.write_text(json.dumps(header) + "\n",
                        encoding="utf-8")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def check_pair(root, a, b):
    """Report the pair's exclusion state:
      excluded — a decline stands and both sides are
                 unchanged (OID + fingerprint): do not
                 re-propose this merge/consolidation.
      changed  — a decline stands but content moved on a
                 named side: re-proposal is allowed.
      clear    — no decline on record for this pair.
    Reports only; never acts."""
    a, b = _pair_key(a, b)
    records = [r for r in load_exclusions(root)
               if _pair_key(*r["pair"]) == (a, b)]
    if not records:
        return {"pair": [a, b], "state": "clear",
                "records": 0}
    current = {a: _state_of(root, a), b: _state_of(root, b)}
    latest = records[-1]
    changed = [side for side in (a, b)
               if latest["states"][side] != current[side]]
    if changed:
        return {"pair": [a, b], "state": "changed",
                "changed_sides": changed, "records": len(records),
                "declined_at": latest["decided_at"],
                "note": "content changed since the decline — "
                        "re-proposal is allowed"}
    return {"pair": [a, b], "state": "excluded",
            "records": len(records),
            "declined_at": latest["decided_at"],
            "decided_by": latest["decided_by"],
            "note": "declined and unchanged — do not "
                    "re-propose this merge/consolidation"}


# ---------------------------------------------------------------
# CLI
# ---------------------------------------------------------------


def _read(path):
    return Path(path).read_text(encoding="utf-8",
                                errors="replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    fp = sub.add_parser("fingerprint")
    fp.add_argument("file")
    ck = sub.add_parser("check")
    ck.add_argument("a")
    ck.add_argument("b")
    vc = sub.add_parser("vocab")
    vc.add_argument("files", nargs="+")
    ex = sub.add_parser("exclusions")
    exsub = ex.add_subparsers(dest="excmd", required=True)
    exsub.add_parser("list")
    exc = exsub.add_parser("check")
    exc.add_argument("a")
    exc.add_argument("b")
    exd = exsub.add_parser("decline")
    exd.add_argument("a")
    exd.add_argument("b")
    exd.add_argument("--by", required=True)
    exd.add_argument("--reason", required=True)
    args = ap.parse_args(argv)
    root = args.root
    if args.cmd == "fingerprint":
        text = _read(args.file)
        data = Path(args.file).read_bytes()
        print("blob_oid:    %s" % blob_oid(data))
        print("fingerprint: %s" % fingerprint_file_text(text))
        print("commentary:  %s" % has_commentary(
            strip_frontmatter(text)))
        return 0
    if args.cmd == "check":
        va = strip_frontmatter(_read(args.a))
        vb = strip_frontmatter(_read(args.b))
        print(json.dumps(decide(va, vb), indent=2))
        return 0
    if args.cmd == "vocab":
        import wiki_filing_router as wfr
        bad = 0
        for f in args.files:
            fm, _body = wfr.parse_frontmatter(_read(f))
            res = vocabulary_check(fm, root)
            print("%s: %s" % (f, "ok" if res["ok"] else
                              "VIOLATIONS"))
            for v in res["violations"]:
                print("  - %s" % v)
                bad += 1
        return 1 if bad else 0
    # exclusions
    if args.excmd == "list":
        recs = load_exclusions(root)
        for r in recs:
            print("%s + %s — declined %s by %s: %s"
                  % (r["pair"][0], r["pair"][1],
                     r["decided_at"], r["decided_by"],
                     r["reason"]))
        print("%d exclusion record(s)" % len(recs))
        return 0
    if args.excmd == "check":
        rep = check_pair(root, args.a, args.b)
        print(json.dumps(rep, indent=2))
        return 1 if rep["state"] == "excluded" else 0
    rec = record_decline(root, args.a, args.b, args.by,
                         args.reason)
    print("recorded decline: %s + %s (oids %s, %s)"
          % (rec["pair"][0], rec["pair"][1],
             rec["states"][rec["pair"][0]]["oid"][:12],
             rec["states"][rec["pair"][1]]["oid"][:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
