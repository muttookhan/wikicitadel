#!/usr/bin/env python3
"""Citation integrity pack: lockfile, source manifest, quote check.

WikiCitadel v1. Until
now this wiki's ^[cite: <path>#L<a>-L<b>] markers were only checked
for *resolution* (scripts/wiki_validate.py: the file exists and the
range is in bounds). Nothing verified that the words at the cited
lines are still the words the claim rests on. This script adds the
verification layer, in four parts:

  1. Citation lockfile (evaluation/citation-lockfile.json) —
     every inline marker in wiki/, locked with: the citing page
     and line, a hash of the claim sentence, the source path and
     line range, a per-line hash of the cited lines, and a
     content hash of the cited block as it is NOW. `check`
     re-reads each source and reports per citation:
       OK       — the cited lines hash exactly as locked;
       MOVED    — the same lines (same per-line hash sequence)
                  found at a different range; new range reported;
       CHANGED  — the cited content differs and is not found
                  elsewhere in the file; the claim needs
                  re-verification by a human/agent;
       MISSING  — the source file, or the cited lines, are gone.
     Pattern: the per-claim citation lockfile + zero-LLM `ground`
     check of @thenewguard/tng-wiki (MIT) — re-implemented here;
     no code copied.
  2. Source manifest (evaluation/source-manifest.jsonl) — every
     raw/ file cited by any marker, registered with its whole-file
     sha256 and size. Check mode verifies the registered bytes
     still match; a changed registered source flags every
     citation pointing into it (a change outside the cited ranges
     is caught here even when every citation still reads OK).
     Pattern: the manifest.jsonl source registry of
     pumblus/okf-harness (Apache-2.0) — re-implemented.
  3. Quote verification — direct quotations on wiki pages that
     carry a cite marker on the same or the adjacent line are
     checked verbatim against the cited range (normalising only
     whitespace and smart quotes); divergences are reported with
     the exact point of divergence. Pattern: the quote
     verification of MetamusicX/zissa-wiki (MIT) — re-implemented.
     Exposed as find_checkable_quotes()/verify_quote() and wired
     into scripts/wiki_lint_lanes.py as its fifth lane.
  4. Strong mode (`check --strong`) — the per-source audit
     fan-out: the same deterministic checks, grouped per
     registered source, each block carrying the source's current
     sha256 + size so a reviewer can adversarially re-verify any
     block independently. Pattern: the per-source parallel audit
     of kfchou/wiki-skills (MIT) — re-implemented as grouped
     deterministic output; this script calls no LLM.
  5. Converter identity (the survey, KNOX find) — the text a
     citation locks may have been *produced* by a converter
     (scripts/wiki_convert.py + the gateway sanitiser it
     delegates to). The manifest records, per source, the
     converter identity the record supports: an ingest sidecar
     (<source>.ingest.json, written by wiki_convert.py) names
     the converter and its script hash; anything the record
     cannot support is recorded as `unknown-legacy`, never
     guessed. `check` recomputes the converter identity in the
     tree and re-flags every citation over a converted source
     whose recorded identity no longer matches — a converter
     change must not silently pass the citations that ride on
     its output. Pattern: KNOX's parser-fingerprint cache
     identity (survey find 1) — re-implemented.
  6. Dual-anchored selectors (the survey, W3C Web
     Annotation) — every locked citation also carries a
     TextQuoteSelector second anchor: the cited passage
     verbatim (`exact`) plus up to 32 chars of `prefix`/`suffix`
     context, generated at build time. `check` verifies BOTH
     anchors: the line anchor (hashes, as before) and the quote
     anchor (the passage located in the source's normalised
     text, disambiguated by its context). The pair disagrees
     out loud: a passage the line anchor can no longer find but
     the quote anchor resolves at a new range is MOVED; a
     passage occurring more than once with context that cannot
     disambiguate it is AMBIGUOUS — reported, never resolved by
     fiat. Pattern: W3C Web Annotation selectors
     (find 20) — the vocabulary is the standard's.

Coverage honesty: claim-level citation in this wiki is young
(measured on the reference corpus: coverage is partial).
Every report this script generates states its actual coverage —
markers locked, sources registered, quotations checked. Nothing
here manufactures citations to inflate those numbers.

Marker scanning, the cite regex, and the sentence-extraction
helpers are reused from scripts/wiki_validate.py /
scripts/wiki_observe.py (imported in-process), the same reuse the
other scripts make. Stdlib only. Deterministic ordering
everywhere: the same corpus always produces the same lockfile
(apart from the generated date) and the same report.

Usage:
  python3 scripts/wiki_cite_lock.py build
      (Re)write evaluation/citation-lockfile.json and
      evaluation/source-manifest.jsonl from the current corpus.
  python3 scripts/wiki_cite_lock.py check [--strong]
      Verify the corpus against the lockfile + manifest.
      Exit 0 when everything verifies; 1 when any citation is
      MOVED / CHANGED / MISSING / AMBIGUOUS, any registered
      source changed, the converter identity over a converted
      source changed, or the lockfile is stale (unlocked or
      orphaned markers); 2 on usage error (e.g. no lockfile —
      run build first).
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
SCRIPTS = ROOT / "scripts"
LOCK_PATH = ROOT / "evaluation" / "citation-lockfile.json"
MANIFEST_PATH = ROOT / "evaluation" / "source-manifest.jsonl"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


observe = _load("wiki_observe")
CITE_RE = observe.CITE_RE
CITE_LOOSE_RE = observe.CITE_LOOSE_RE


# -- Hashing -----------------------------------------------------------------

def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _line_hash(line):
    return _sha_text(line)


def _content_hash(lines):
    return _sha_text("\n".join(lines))


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_lines(rel):
    """The cited file's lines (1-based access via [n-1]), or None
    when the file is not on disk. Split the same way the validator
    counts lines, so ranges mean the same thing in both tools."""
    path = ROOT / rel
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8",
                           errors="ignore").splitlines()


# -- Converter identity --------------------------------------------------------

CONVERT_PATH = SCRIPTS / "wiki_convert.py"
SANITIZER_PATH = (ROOT / "tools" / "gateway" / "gateway"
                  / "sanitize.py")


def current_converter_identity():
    """The converter set currently in the tree, identified by
    content hash: scripts/wiki_convert.py plus the gateway
    sanitiser it delegates text mutation to (the sanitiser is
    part of the set — it can change what a document converts
    into). Any edit to either file re-identifies the set."""
    return {
        "tool": "wiki_convert.py",
        "script_sha256": (_file_sha256(CONVERT_PATH)
                          if CONVERT_PATH.is_file() else None),
        "sanitizer_sha256": (_file_sha256(SANITIZER_PATH)
                             if SANITIZER_PATH.is_file() else None),
    }


def converter_identity_for(source_rel):
    """The converter identity the record supports for one
    registered source. Determinable only from the ingest sidecar
    (<source>.ingest.json) that wiki_convert.py writes beside a
    conversion: it names the original file and (since the
    converter-identity build) the converter's own identity.
    A sidecar written before that build names the original but
    not the script hash — the kind is determinable, the hash is
    recorded as unrecorded (None), not invented. Anything else
    is `unknown-legacy`: the text may be native or converted,
    and the record does not say. Never guessed."""
    sidecar = ROOT / (source_rel + ".ingest.json")
    if sidecar.is_file():
        try:
            data = json.loads(
                sidecar.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = None
        if isinstance(data, dict):
            conv = data.get("converter") or {}
            original = data.get("source") or ""
            return {
                "kind": "wiki_convert",
                "tool": conv.get("tool") or "wiki_convert.py",
                "script_sha256": conv.get("script_sha256"),
                "sanitizer_sha256": conv.get("sanitizer_sha256"),
                "format": (conv.get("format")
                           or Path(original).suffix.lstrip(".")
                           or None),
                "original_sha256": data.get("sha256"),
                "evidence": ("ingest sidecar "
                             + source_rel + ".ingest.json"),
            }
    return {"kind": "unknown-legacy"}


def verify_converters(manifest_rows):
    """Per registered source: OK / CHANGED / UNRECORDED.
    CHANGED when the source is recorded as produced by
    wiki_convert.py under one script identity and the tree now
    carries a different one — every citation over that source
    rides on the old converter's output and needs re-verifying
    against a re-conversion. UNRECORDED covers unknown-legacy
    sources and pre-recording sidecars: no comparison is
    possible, and none is faked."""
    current = current_converter_identity()
    out = {}
    for row in manifest_rows:
        conv = row.get("converter") or {"kind": "unknown-legacy"}
        if conv.get("kind") != "wiki_convert":
            out[row["path"]] = (
                "UNRECORDED",
                "converter identity not determinable from the"
                " record (unknown-legacy)")
            continue
        if not conv.get("script_sha256"):
            out[row["path"]] = (
                "UNRECORDED",
                "ingest sidecar predates converter recording —"
                " the script identity was not recorded")
            continue
        diffs = []
        if conv["script_sha256"] != current.get("script_sha256"):
            diffs.append("wiki_convert.py")
        rec_san = conv.get("sanitizer_sha256")
        if rec_san and current.get("sanitizer_sha256") \
                and rec_san != current["sanitizer_sha256"]:
            diffs.append("the gateway sanitiser")
        if diffs:
            out[row["path"]] = (
                "CHANGED",
                "converter changed since the lock ("
                + " and ".join(diffs) + ") — citations over"
                " this converted source need re-verification")
        else:
            out[row["path"]] = ("OK", "")
    return out


# -- Marker scan ---------------------------------------------------------------

def scan_citations():
    """Every inline ^[cite:] marker under wiki/, deterministic
    order. Fenced code blocks and frontmatter are skipped (the
    wiki_observe.body_paragraphs convention: a marker quoted in a
    fence is syntax, not a claim). Each entry: page, page_line
    (the file line the marker sits on), source, start, end, and
    claim (the sentence carrying the marker, marker stripped)."""
    out = []
    for path in sorted(WIKI.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for _pstart, para in observe.body_paragraphs(text):
            joined_parts, line_at = [], []
            pos = 0
            for line_no, line_text in para:
                line_at.append((pos, line_no))
                joined_parts.append(line_text.strip())
                pos += len(line_text.strip()) + 1
            joined = " ".join(joined_parts)
            for m in CITE_RE.finditer(joined):
                line_no = max(no for at, no in line_at
                              if at <= m.start())
                sentence = observe.sentence_around(
                    joined, m.start(), m.end())
                claim = observe.clean_text(
                    CITE_LOOSE_RE.sub("", sentence))
                if not claim:
                    claim = observe.clean_text(
                        CITE_LOOSE_RE.sub("", joined))
                start = int(m.group(2))
                end = int(m.group(3)) if m.group(3) else start
                out.append({
                    "page": rel,
                    "page_line": line_no,
                    "source": Path(m.group(1)).as_posix(),
                    "start": start,
                    "end": end,
                    "claim": claim,
                })
    out.sort(key=lambda c: (c["page"], c["page_line"], c["source"],
                            c["start"], c["end"]))
    return out


def _marker_key(c):
    return (c["page"], c["source"], c["start"], c["end"])


# -- Build ---------------------------------------------------------------------

def build_records():
    """(lockfile dict, manifest rows) for the current corpus."""
    citations = scan_citations()
    locked = []
    sources = {}
    for i, c in enumerate(citations, start=1):
        lines = _read_lines(c["source"])
        entry = {
            "id": f"c{i:04d}",
            "page": c["page"],
            "page_line": c["page_line"],
            "claim": c["claim"],
            "claim_hash": _sha_text(c["claim"]),
            "source": c["source"],
            "range": [c["start"], c["end"]],
        }
        if lines is None:
            entry["locked_missing"] = True
            entry["line_hashes"] = []
            entry["content_hash"] = None
        else:
            block = lines[c["start"] - 1:c["end"]]
            entry["line_hashes"] = [_line_hash(ln) for ln in block]
            entry["content_hash"] = _content_hash(block)
            selector = make_selector(lines, c["start"], c["end"])
            if selector is not None:
                entry["selector"] = selector
        locked.append(entry)
        agg = sources.setdefault(c["source"], {
            "citations": 0, "cited_by_pages": set()})
        agg["citations"] += 1
        agg["cited_by_pages"].add(c["page"])
    manifest = []
    for src in sorted(sources):
        path = ROOT / src
        row = {"path": src, "citations": sources[src]["citations"],
               "cited_by_pages": sorted(
                   sources[src]["cited_by_pages"]),
               "converter": converter_identity_for(src)}
        if path.is_file():
            row["sha256"] = _file_sha256(path)
            row["size"] = path.stat().st_size
        else:
            row["sha256"] = None
            row["size"] = None
            row["missing"] = True
        manifest.append(row)
    coverage = {
        "pages_scanned": len(list(WIKI.rglob("*.md"))),
        "pages_with_markers": len({c["page"] for c in citations}),
        "citations": len(citations),
        "sources_registered": len(manifest),
        "selectors": sum(1 for e in locked if e.get("selector")),
        "converter_recorded": sum(
            1 for r in manifest
            if r["converter"].get("kind") == "wiki_convert"),
        "converter_unknown_legacy": sum(
            1 for r in manifest
            if r["converter"].get("kind") == "unknown-legacy"),
    }
    lockfile = {
        "tool": "wiki_cite_lock citation lockfile",
        "lockfile_version": 2,
        "generated": date.today().isoformat(),
        "note": "Per-citation lock: claim hash + cited-line hashes "
                "as of the generated date, plus a TextQuoteSelector"
                " second anchor per citation (dual anchoring). "
                "CHANGED means the cited content differs — "
                "re-verify the claim by hand; MOVED means the "
                "same passage lives at a new range (re-run build "
                "to re-lock); AMBIGUOUS means the quoted passage "
                "occurs more than once and its context cannot "
                "disambiguate it. The manifest records each "
                "source's converter identity where the record "
                "supports one (unknown-legacy where it does not). "
                "Patterns: tng-wiki lockfile (MIT), okf-harness "
                "manifest (Apache-2.0), zissa-wiki quote check "
                "(MIT), wiki-skills audit (MIT), KNOX converter "
                "identity (MIT), W3C Web Annotation selectors"
                " — all re-implemented.",
        "converter": current_converter_identity(),
        "coverage": coverage,
        "citations": locked,
    }
    return lockfile, manifest


def cmd_build(_args):
    lockfile, manifest = build_records()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(
        json.dumps(lockfile, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    MANIFEST_PATH.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n"
                for row in manifest),
        encoding="utf-8")
    cov = lockfile["coverage"]
    print(f"wrote {LOCK_PATH.relative_to(ROOT).as_posix()}"
          f" and {MANIFEST_PATH.relative_to(ROOT).as_posix()}")
    print(f"coverage: {cov['citations']} citations on"
          f" {cov['pages_with_markers']} pages"
          f" ({cov['pages_scanned']} pages scanned),"
          f" {cov['sources_registered']} sources registered")
    print(f"dual anchors: {cov['selectors']} of"
          f" {cov['citations']} citations carry a"
          f" TextQuoteSelector")
    print(f"converter identity: {cov['converter_recorded']} of"
          f" {cov['sources_registered']} sources determinable"
          f" from the record,"
          f" {cov['converter_unknown_legacy']} unknown-legacy")
    missing = [e["id"] for e in lockfile["citations"]
               if e.get("locked_missing")]
    if missing:
        print(f"warning: {len(missing)} citation(s) point at"
              f" sources not on disk: {', '.join(missing)}")
    return 0


# -- Dual-anchored selectors (TextQuoteSelector) -------------------------------

CONTEXT_CHARS = 32


def make_selector(lines, start, end):
    """The second anchor for a citation: a W3C TextQuoteSelector
    over the cited block — `exact` is the passage verbatim,
    `prefix`/`suffix` up to CONTEXT_CHARS chars of the source
    text on either side, the context that disambiguates a
    repeated passage. None when the range holds no lines."""
    block = lines[start - 1:end]
    if not block:
        return None
    exact = "\n".join(block)
    full = "\n".join(lines)
    offset = sum(len(ln) + 1 for ln in lines[:start - 1])
    return {
        "type": "TextQuoteSelector",
        "exact": exact,
        "prefix": full[max(0, offset - CONTEXT_CHARS):offset],
        "suffix": full[offset + len(exact):
                      offset + len(exact) + CONTEXT_CHARS],
    }


def verify_selector(entry, lines):
    """The quote anchor against the current source. Returns
    (verdict, span): verdict in AT_RANGE (resolves at the
    locked range) / ELSEWHERE (resolves uniquely at another
    range; span is that (start, end)) / AMBIGUOUS (the passage
    occurs more than once and its prefix/suffix context cannot
    pick one) / ABSENT (the passage is not in the source) /
    NONE (the entry carries no selector — a pre-dual-anchor
    lock). Matching is on the quote lane's normalisation
    (whitespace runs and smart quotes), so the anchor survives
    line-break reflow that defeats the per-line hashes."""
    sel = entry.get("selector")
    if not sel or not sel.get("exact"):
        return "NONE", None
    start, end = entry["range"]
    needle = normalize_text(sel["exact"])
    if not needle:
        return "NONE", None
    norm = [normalize_text(ln) for ln in lines]
    line_starts = []
    pos = 0
    for nl in norm:
        line_starts.append(pos)
        pos += len(nl) + 1
    joined = " ".join(norm)

    def span_of(occ):
        occ_end = occ + len(needle)
        s_line = max(i for i, st in enumerate(line_starts)
                     if st <= occ)
        e_line = max(i for i, st in enumerate(line_starts)
                     if st <= occ_end - 1)
        return (s_line + 1, e_line + 1)

    occ = []
    at = joined.find(needle)
    while at != -1:
        occ.append(at)
        at = joined.find(needle, at + 1)
    if not occ:
        return "ABSENT", None
    spans = [span_of(o) for o in occ]
    if (start, end) in spans:
        return "AT_RANGE", (start, end)
    prefix = normalize_text(sel.get("prefix") or "")
    suffix = normalize_text(sel.get("suffix") or "")

    def context_ok(o):
        before = joined[:o].rstrip()
        after = joined[o + len(needle):].lstrip()
        return (not prefix or before.endswith(prefix)) \
            and (not suffix or after.startswith(suffix))

    ctx = [o for o in occ if context_ok(o)]
    if len(ctx) == 1:
        return "ELSEWHERE", span_of(ctx[0])
    if len(ctx) > 1:
        return "AMBIGUOUS", None
    if len(occ) == 1:
        # The passage is unique in the source; its recorded
        # context has itself drifted, but there is nothing else
        # it could be pointing at.
        return "ELSEWHERE", spans[0]
    return "AMBIGUOUS", None


# -- Check ---------------------------------------------------------------------

def _find_block(lines, line_hashes):
    """Start index (0-based) of the locked per-line hash sequence
    in `lines`, or None. When the sequence occurs more than once,
    the first occurrence wins (deterministic)."""
    if not line_hashes:
        return None
    current = [_line_hash(ln) for ln in lines]
    n = len(line_hashes)
    for i in range(0, len(current) - n + 1):
        if current[i:i + n] == line_hashes:
            return i
    return None


def verify_citation(entry):
    """One locked citation against the current source bytes,
    verified on BOTH anchors. Returns (status, detail): status
    in OK / MOVED / CHANGED / MISSING / AMBIGUOUS.

    The line anchor is authoritative when it verifies at the
    locked range. Otherwise the anchors are combined, and a
    disagreement is reported as itself, never smoothed over:
    the per-line hash sequence found at a new range is MOVED;
    a passage only the quote anchor can still locate (the
    lines were reflowed — the case dual anchoring exists for)
    is MOVED on the quote anchor's evidence; a passage the
    quote anchor still resolves at the locked range while the
    line hashes fail there has drifted *inside* the cited
    lines below word level and is CHANGED with that said; a
    passage occurring more than once, with context that
    cannot disambiguate it and no line anchor to pin it, is
    AMBIGUOUS."""
    src = entry["source"]
    start, end = entry["range"]
    lines = _read_lines(src)
    if lines is None:
        return "MISSING", f"source {src} not on disk"
    if entry.get("locked_missing"):
        return "MISSING", "source was already missing at lock time"
    if start > len(lines):
        return "MISSING", (f"cited lines L{start}-L{end} are gone:"
                           f" {src} now has {len(lines)} lines")
    block = lines[start - 1:end]
    if len(block) == end - start + 1 \
            and _content_hash(block) == entry["content_hash"]:
        return "OK", ""
    sel_status, sel_span = verify_selector(entry, lines)
    found = _find_block(lines, entry["line_hashes"])
    if found is not None:
        new_start = found + 1
        new_end = found + len(entry["line_hashes"])
        if (new_start, new_end) != (start, end):
            detail = (f"same content now at"
                      f" L{new_start}-L{new_end}")
            if sel_status == "AT_RANGE":
                detail += ("; note: the quote anchor also still"
                           " resolves at the locked range — the"
                           " passage may now occur twice")
            return "MOVED", detail
        return "CHANGED", "content differs at the locked range"
    if sel_status == "ELSEWHERE":
        new_start, new_end = sel_span
        return "MOVED", (f"the line anchor fails at"
                         f" L{start}-L{end}, but the quote anchor"
                         f" (TextQuoteSelector) resolves at"
                         f" L{new_start}-L{new_end}")
    if sel_status == "AMBIGUOUS":
        return "AMBIGUOUS", (f"the quoted passage occurs more"
                             f" than once in {src} and its"
                             f" prefix/suffix context cannot"
                             f" disambiguate it; the line anchor"
                             f" does not verify at the locked"
                             f" range — a human must pin this"
                             f" citation")
    if sel_status == "AT_RANGE":
        return "CHANGED", (f"content at L{start}-L{end} differs"
                           f" and the locked lines are not found"
                           f" elsewhere, but the quote anchor"
                           f" still resolves at the locked range"
                           f" — drift inside the cited lines at"
                           f" whitespace/line-break level;"
                           f" re-verify the claim or re-lock")
    return "CHANGED", (f"content at L{start}-L{end} differs and"
                       f" the locked lines are not found"
                       f" elsewhere in {src}")


def verify_manifest(manifest_rows):
    """Per registered source: OK / CHANGED / MISSING by bytes."""
    out = {}
    for row in manifest_rows:
        path = ROOT / row["path"]
        if not path.is_file():
            out[row["path"]] = ("MISSING", "registered source not"
                                " on disk")
        elif row.get("sha256") is None:
            out[row["path"]] = ("MISSING", "was missing when the"
                                " manifest was built")
        else:
            now = _file_sha256(path)
            if now == row["sha256"] \
                    and path.stat().st_size == row["size"]:
                out[row["path"]] = ("OK", "")
            else:
                out[row["path"]] = ("CHANGED",
                                    "registered bytes differ from"
                                    " the manifest (sha256/size)")
    return out


def _load_lockfile():
    if not LOCK_PATH.is_file():
        return None, None
    lockfile = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    rows = []
    if MANIFEST_PATH.is_file():
        for line in MANIFEST_PATH.read_text(
                encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return lockfile, rows


def cmd_check(args):
    lockfile, manifest_rows = _load_lockfile()
    if lockfile is None:
        print("no lockfile at"
              f" {LOCK_PATH.relative_to(ROOT).as_posix()} —"
              " run `wiki_cite_lock.py build` first")
        return 2
    locked = lockfile["citations"]
    cov = lockfile.get("coverage", {})
    results = []          # (entry, status, detail)
    for entry in locked:
        status, detail = verify_citation(entry)
        results.append((entry, status, detail))
    manifest_status = verify_manifest(manifest_rows or [])
    converter_status = verify_converters(manifest_rows or [])
    # Lockfile freshness: markers on pages now vs locked then.
    current = scan_citations()
    current_keys = {_marker_key(c) for c in current}
    locked_keys = {_marker_key({
        "page": e["page"], "source": e["source"],
        "start": e["range"][0], "end": e["range"][1]})
        for e in locked}
    unlocked = [c for c in current
                if _marker_key(c) not in locked_keys]
    orphaned = [e for e in locked if _marker_key({
        "page": e["page"], "source": e["source"],
        "start": e["range"][0], "end": e["range"][1]})
        not in current_keys]
    # Claim drift: same marker, different claim sentence.
    current_claims = {}
    for c in current:
        current_claims.setdefault(_marker_key(c), c["claim"])
    drift = []
    for e in locked:
        key = _marker_key({"page": e["page"], "source": e["source"],
                           "start": e["range"][0],
                           "end": e["range"][1]})
        now = current_claims.get(key)
        if now is not None and _sha_text(now) != e["claim_hash"]:
            drift.append(e)

    counts = {"OK": 0, "MOVED": 0, "CHANGED": 0, "MISSING": 0,
              "AMBIGUOUS": 0}
    for _e, status, _d in results:
        counts[status] += 1
    manifest_bad = {p: v for p, v in manifest_status.items()
                    if v[0] != "OK"}
    converter_bad = {p: v for p, v in converter_status.items()
                     if v[0] == "CHANGED"}
    problems = (counts["MOVED"] + counts["CHANGED"]
                + counts["MISSING"] + counts["AMBIGUOUS"]
                + len(manifest_bad) + len(converter_bad)
                + len(unlocked) + len(orphaned))

    if args.strong:
        _print_strong(results, manifest_rows or [],
                      manifest_status, converter_status, counts,
                      unlocked, orphaned, drift, cov, lockfile)
    else:
        print(f"Citation lock check — {len(locked)} locked"
              f" citations, {cov.get('sources_registered', '?')}"
              f" registered sources (locked"
              f" {lockfile.get('generated', '?')})")
        print(f"  OK {counts['OK']} · MOVED {counts['MOVED']} ·"
              f" CHANGED {counts['CHANGED']} ·"
              f" MISSING {counts['MISSING']} ·"
              f" AMBIGUOUS {counts['AMBIGUOUS']}")
        for entry, status, detail in results:
            if status != "OK":
                print(f"  [{status}] {entry['id']}"
                      f" {entry['page']}:{entry['page_line']}"
                      f" -> {entry['source']}"
                      f"#L{entry['range'][0]}-L{entry['range'][1]}"
                      f" — {detail}")
        for path in sorted(manifest_bad):
            status, detail = manifest_bad[path]
            affected = [e["id"] for e in locked
                        if e["source"] == path]
            print(f"  [MANIFEST {status}] {path} — {detail};"
                  f" flags citations: {', '.join(affected)}")
        for path in sorted(converter_bad):
            _status, detail = converter_bad[path]
            affected = [e["id"] for e in locked
                        if e["source"] == path]
            print(f"  [CONVERTER CHANGED] {path} — {detail};"
                  f" flags citations: {', '.join(affected)}")
        for c in unlocked:
            print(f"  [UNLOCKED] {c['page']}:{c['page_line']} ->"
                  f" {c['source']}#L{c['start']}-L{c['end']}"
                  " — marker not in the lockfile (re-run build)")
        for e in orphaned:
            print(f"  [ORPHANED] {e['id']} {e['page']}"
                  f":{e['page_line']} -> {e['source']}"
                  f"#L{e['range'][0]}-L{e['range'][1]}"
                  " — marker no longer on the page (re-run build)")
        for e in drift:
            print(f"  [CLAIM DRIFT] {e['id']} {e['page']}"
                  f":{e['page_line']} — the claim sentence changed"
                  " since the lock; its source still verifies"
                  " as above")
    verdict = "PASS" if problems == 0 else "FINDINGS"
    print(f"Result: {verdict} ({problems} problem(s))")
    return 0 if problems == 0 else 1


def _converter_line(row, converter_status):
    """One source's converter-identity line for the strong
    audit: the identity folded into the source's verification
    record, the identity in the tree now, and the verdict."""
    conv = (row or {}).get("converter") or {"kind": "unknown-legacy"}
    current = current_converter_identity()
    status, detail = converter_status.get(
        (row or {}).get("path"), ("?", ""))
    if conv.get("kind") == "wiki_convert":
        recorded = (f"wiki_convert.py script"
                    f" {(conv.get('script_sha256') or 'unrecorded')[:12]}…"
                    f" (format {conv.get('format')})")
    else:
        recorded = "unknown-legacy"
    cur = (f"wiki_convert.py script"
           f" {(current.get('script_sha256') or '?')[:12]}…")
    return (f"   converter: recorded {recorded} · current {cur}"
            f" → {status}" + (f" — {detail}" if detail else ""))


def _print_strong(results, manifest_rows, manifest_status,
                  converter_status, counts, unlocked, orphaned,
                  drift, cov, lockfile):
    """Strong mode: the audit fan-out, grouped per source. Each
    block is independently re-checkable: it carries the source's
    registered and current sha256 + size, its converter
    identity (recorded vs current), and every citation's
    verdict on both anchors."""
    by_source = {}
    for entry, status, detail in results:
        by_source.setdefault(entry["source"], []).append(
            (entry, status, detail))
    manifest_by_path = {r["path"]: r for r in manifest_rows}
    sources = sorted(set(by_source) | set(manifest_by_path))
    print(f"Citation lock check (strong) — per-source audit of"
          f" {len(sources)} registered sources,"
          f" {sum(counts.values())} locked citations (locked"
          f" {lockfile.get('generated', '?')}; coverage at lock:"
          f" {cov.get('citations', '?')} citations on"
          f" {cov.get('pages_with_markers', '?')} pages)")
    for src in sources:
        path = ROOT / src
        row = manifest_by_path.get(src)
        status, detail = manifest_status.get(src, ("?", ""))
        current_sha = _file_sha256(path) if path.is_file() else None
        current_size = path.stat().st_size if path.is_file() else None
        lines = _read_lines(src)
        print(f"\n== {src}")
        print(f"   manifest: {status}"
              + (f" — {detail}" if detail else "")
              + (f"; registered sha256 {row['sha256']}"
                 f" size {row['size']}" if row else
                 "; not in the manifest"))
        print(f"   current : sha256 {current_sha}"
              f" size {current_size}")
        print(_converter_line(row, converter_status))
        entries = sorted(by_source.get(src, []),
                         key=lambda t: t[0]["id"])
        if not entries:
            print("   (no citations point into this source)")
        for entry, st, det in entries:
            line = (f"   [{st}] {entry['id']}"
                    f" {entry['page']}:{entry['page_line']}"
                    f" range L{entry['range'][0]}-L{entry['range'][1]}"
                    f" content_hash {entry['content_hash']}")
            if lines is not None and entry.get("selector"):
                sel_status, sel_span = verify_selector(entry, lines)
                line += f" · quote anchor: {sel_status}"
                if sel_status == "ELSEWHERE" and sel_span:
                    line += (f" (L{sel_span[0]}-L{sel_span[1]})")
            if det:
                line += f" — {det}"
            print(line)
    print(f"\nSummary: OK {counts['OK']} · MOVED {counts['MOVED']}"
          f" · CHANGED {counts['CHANGED']} ·"
          f" MISSING {counts['MISSING']} · AMBIGUOUS"
          f" {counts['AMBIGUOUS']} · manifest problems"
          f" {sum(1 for v in manifest_status.values() if v[0] != 'OK')}"
          f" · converter changed"
          f" {sum(1 for v in converter_status.values() if v[0] == 'CHANGED')}"
          f" · unlocked {len(unlocked)} · orphaned"
          f" {len(orphaned)} · claim drift {len(drift)}")


# -- Quote verification (lane 5 machinery) -------------------------------------

QUOTE_RE = re.compile(
    r'"([^"\n]{3,})"|“([^”\n]{3,})”')
MIN_QUOTE_WORDS = 2


def normalize_text(text):
    """The quote lane's only normalisations: smart quotes to
    straight, all whitespace runs to single spaces."""
    text = (text.replace("‘", "'").replace("’", "'")
            .replace("“", '"').replace("”", '"'))
    return re.sub(r"\s+", " ", text).strip()


def _quoted_spans(text):
    spans = []
    for m in QUOTE_RE.finditer(text):
        span = m.group(1) if m.group(1) is not None else m.group(2)
        span = span.strip()
        if len(span.split()) >= MIN_QUOTE_WORDS or len(span) >= 6:
            spans.append(span)
    return spans


def _blockquote_text(lines):
    parts = []
    for ln in lines:
        s = ln.lstrip()
        if s.startswith(">"):
            s = s[1:].lstrip()
        parts.append(s.strip())
    return " ".join(p for p in parts if p)


def find_checkable_quotes():
    """Direct quotations carrying a cite marker on the same or
    the adjacent line. Returns dicts: page, page_line (the line
    the quote sits on), quote, source, start, end. Deterministic
    order. Fenced code blocks are skipped (quoted syntax is not a
    quotation). A blockquote block counts as one quotation; a
    marker on its last line, or on the line right after the
    block, attaches the block to that marker."""
    found = {}
    for path in sorted(WIKI.rglob("*.md")):
        rel = path.relative_to(ROOT).as_posix()
        raw_lines = path.read_text(
            encoding="utf-8", errors="ignore").split("\n")
        in_fence = False
        markers = {}   # line_no -> [(source, start, end)]
        for i, line in enumerate(raw_lines, start=1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for m in CITE_RE.finditer(line):
                start = int(m.group(2))
                end = int(m.group(3)) if m.group(3) else start
                markers.setdefault(i, []).append(
                    (Path(m.group(1)).as_posix(), start, end))
        if not markers:
            continue

        def add(quote, quote_line, target):
            quote = quote.strip()
            if not quote:
                return
            src, start, end = target
            key = (rel, quote_line, quote, src, start, end)
            found[key] = {"page": rel, "page_line": quote_line,
                          "quote": quote, "source": src,
                          "start": start, "end": end}

        for line_no in sorted(markers):
            targets = markers[line_no]
            # Quoted spans on the marker line and the line above.
            for qline in (line_no, line_no - 1):
                if qline < 1 or qline > len(raw_lines):
                    continue
                for span in _quoted_spans(raw_lines[qline - 1]):
                    for t in targets:
                        add(span, qline, t)
            # Blockquote block ending at or just above the marker
            # line: walk up over consecutive '>' lines.
            for anchor in (line_no, line_no - 1):
                if anchor < 1 or anchor > len(raw_lines):
                    continue
                if not raw_lines[anchor - 1].lstrip().startswith(">"):
                    continue
                block = []
                j = anchor
                while j >= 1 and raw_lines[j - 1].lstrip().startswith(">"):
                    block.append(raw_lines[j - 1])
                    j -= 1
                block.reverse()
                text = _blockquote_text(block)
                # An Obsidian callout (> [!warning] ...) is the
                # page's own prose in a box, not a quotation of
                # anything — never a checkable quote.
                if text.startswith("[!"):
                    continue
                # A blockquote that merely contains quoted spans
                # was already handled span by span; the whole
                # block is itself the quotation only when it has
                # no inner span of its own.
                if text and not _quoted_spans(text):
                    for t in targets:
                        add(text, j + 1, t)
    return [found[k] for k in sorted(found)]


def verify_quote(quote, source, start, end):
    """(verified, divergence) — the normalised quote must appear
    verbatim in the normalised cited range. On failure the
    divergence names the exact point: the longest prefix of the
    quote that does appear, and what the quote says next."""
    lines = _read_lines(source)
    if lines is None:
        return False, f"source {source} not on disk"
    haystack = normalize_text("\n".join(lines[start - 1:end]))
    needle = normalize_text(quote)
    if not needle:
        return False, "empty quotation"
    if needle in haystack:
        return True, ""
    # Longest prefix of the quote present in the range.
    lo = 0
    for cut in range(len(needle), 0, -1):
        if needle[:cut] in haystack:
            lo = cut
            break
    if lo == 0:
        return False, ("quotation not present in the cited range"
                       f" {source}#L{start}-L{end}")
    nxt = needle[lo:lo + 40]
    return False, (f"diverges after {lo} of {len(needle)} chars"
                   f" — the quotation continues {nxt!r}, which"
                   f" is not in {source}#L{start}-L{end}")


def quote_report():
    """The quote lane's data: coverage + per-quote verdicts."""
    quotes = find_checkable_quotes()
    results = []
    for q in quotes:
        ok, divergence = verify_quote(
            q["quote"], q["source"], q["start"], q["end"])
        results.append({**q, "verified": ok,
                        "divergence": divergence})
    pages = len({q["page"] for q in quotes})
    return {"checked": len(results), "pages": pages,
            "verified": sum(1 for r in results if r["verified"]),
            "divergences": [r for r in results
                            if not r["verified"]],
            "results": results}


# -- CLI -----------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(
        description="Citation integrity pack: lockfile, source"
                    " manifest, quote verification.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="(re)write the lockfile and the"
                                 " source manifest")
    p_check = sub.add_parser("check", help="verify the corpus"
                                           " against the lockfile")
    p_check.add_argument("--strong", action="store_true",
                         help="per-source audit fan-out: every"
                              " citation grouped under its source,"
                              " with the source's hashes printed"
                              " for independent re-verification")
    args = ap.parse_args(argv[1:])
    if args.cmd == "build":
        return cmd_build(args)
    return cmd_check(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
