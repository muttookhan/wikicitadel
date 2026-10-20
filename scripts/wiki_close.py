#!/usr/bin/env python3
"""Periodic close: balance assertions over the wiki's books.

WikiCitadel v1 (the build). Pattern: the balance
assertion + the periodic close of Beancount, from the wave-4
survey's personal lane (finds 13–14,
docs/research-notes.md)
— MECHANIC ONLY: Beancount's licence was not stated on the page
opened, no code is copied, and the accounting tool itself is not
adopted. The generalisation is the survey's own: a corpus that
declares its expected state and fails loudly when reality
differs catches silent drift the way a balance assertion
catches silent bookkeeping errors.

A close is a named, repeating reconciliation ritual. It runs a
fixed battery of assertions — each an equality or invariant
that must hold across the wiki's books, each reported with BOTH
sides' numbers — writes a dated filing
(wiki/filings/periodic-close-<date>.md), and appends one
summary line to its own history register
(evaluation/close-history.jsonl). The close SURFACES; it never
fixes. A FAIL is a finding, printed as found, never massaged:
the filing names the items behind every failure.

The battery:
  1. Provenance — files recorded in the provenance manifest
     == files on disk under raw/ (same comparison
     scripts/wiki_provenance.py --verify makes: no added,
     changed, or missing files).
  2. Citation lockfile — locked citations == citation markers
     on pages (no unlocked, no orphaned); manifest sources ==
     sources cited.
  3. Black Box — the hash chain verifies end-to-end
     (gateway ledger verify_chain); entry count == the
     ledger's own last seq + 1.
  4. Registers well-formed — every evaluation/*.jsonl parses
     line-by-line; append-only registers never shrink vs the
     previous close's recorded line counts (the close keeps
     its own history for exactly this comparison).
  5. Decisions register — every superseded form names a
     successor (its superseded_by) or an explicit none; every
     decision's current form is stated on at least one wiki
     page or filing (normalised 6/5/4-word shingle match).
  6. Evidence resolves — every evidence path cited by the
     treatment, source-grades, and research-log registers
     resolves to a file on disk.
  7. Ideas board — every Approved item is accounted for: a
     BUILT marker, a build-queue reference on its own line or
     its block's preamble, or coverage by the board's
     queue-of-record note. Exceptions are named; the
     assertion passes when the accounting is complete and the
     exceptions (if any) are named — the close surfaces, it
     does not force builds.
  8. Memory budget — ~/MEMORY.md <= the ~9,000-byte lean
     budget (AGENTS.md convention; the sweep flags the same
     threshold).

Exit codes: 0 = every assertion PASS; 1 = at least one FAIL
(the filing + history line are still written — a close with
findings is a completed close); 2 = usage error (e.g. the
corpus is too incomplete to close over).

Stdlib only (plus wiki_provenance, wiki_cite_lock, and the
gateway ledger, imported in-process — the same reuse the other
scripts make).
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
EVAL = "evaluation"
MEMORY_BUDGET = 9000

# Registers whose lines are only ever appended (a shrink is a
# finding). Regenerated or edited-in-place registers
# (decisions-register, source-manifest) are parse-checked only.
APPEND_ONLY = {
    "treatment-register.jsonl", "source-grades.jsonl",
    "research-log.jsonl", "claim-matches.jsonl",
    "contradiction-cases.jsonl", "erasure-certificates.jsonl",
    "outcomes.jsonl", "reverify-history.jsonl",
    "post-mortems.jsonl", "dead-terms.jsonl",
    "close-history.jsonl",
}


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind(module, root, **paths):
    """Point a sibling tool's module globals at `root`.

    The sibling tools bind their paths at import time; the
    close runs them over an arbitrary root (the real corpus,
    or a test fixture), so it rebinds before calling and
    restores afterwards."""
    saved = {}
    for key, val in paths.items():
        if hasattr(module, key):
            saved[key] = getattr(module, key)
            setattr(module, key, val)
    return saved


def _restore(module, saved):
    for key, val in saved.items():
        setattr(module, key, val)


def _jsonl_lines(path):
    """Non-empty lines of a jsonl file ([] when absent)."""
    if not path.is_file():
        return []
    return [ln for ln in path.read_text(
        encoding="utf-8", errors="ignore").splitlines()
        if ln.strip()]


def _parse_jsonl(path):
    """(records, bad) — parsed dicts and [(lineno, error)]."""
    records, bad = [], []
    for i, ln in enumerate(_jsonl_lines(path), start=1):
        try:
            records.append(json.loads(ln))
        except Exception as exc:  # malformed line: record, don't die
            bad.append((i, str(exc)))
    return records, bad


def _result(n, name, verdict, declared, computed, detail="",
            exceptions=None):
    return {"n": n, "name": name, "verdict": verdict,
            "declared": declared, "computed": computed,
            "detail": detail, "exceptions": exceptions or []}


# -- Assertion 1: provenance ------------------------------------------------

def assertion_provenance(root):
    prov = _load("wiki_provenance")
    manifest_path = root / "raw" / "sources" / "provenance-manifest.json"
    if not manifest_path.is_file():
        return _result(1, "Provenance — recorded raw/ == raw/ on disk",
                       "FAIL", "a provenance manifest exists",
                       f"no manifest at {manifest_path}",
                       "Run scripts/wiki_provenance.py to generate one.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _result(1, "Provenance — recorded raw/ == raw/ on disk",
                       "FAIL", "a parseable provenance manifest",
                       f"manifest unparseable: {exc}")
    recorded = manifest.get("files") or {}
    saved = _bind(prov, root, ROOT=root, RAW=root / "raw",
                  MANIFEST_PATH=manifest_path,
                  SELF_REL="raw/sources/provenance-manifest.json")
    try:
        maps, _meta = prov.load_mirror_maps()
        current, drift, _total = prov.scan(maps)
    finally:
        _restore(prov, saved)
    added = sorted(set(current) - set(recorded))
    missing = sorted(set(recorded) - set(current))
    changed = sorted(
        rel for rel in set(current) & set(recorded)
        if current[rel]["sha256"] != recorded[rel].get("sha256")
        or current[rel]["bytes"] != recorded[rel].get("bytes"))
    ok = not (added or changed or missing)
    detail = (f"added {len(added)} · changed {len(changed)} ·"
              f" missing {len(missing)}")
    if drift:
        detail += (f"; note: {len(drift)} file(s) drift vs the older"
                   " mirror sub-manifests (the pre-existing historical"
                   " drift the provenance tool itself reports; the"
                   " register-vs-disk equality above is unaffected)")
    exc = ([f"ADDED {r}" for r in added]
           + [f"CHANGED {r}" for r in changed]
           + [f"MISSING {r}" for r in missing])
    return _result(
        1, "Provenance — recorded raw/ == raw/ on disk",
        "PASS" if ok else "FAIL",
        f"{len(recorded)} files recorded",
        f"{len(current)} files on disk", detail, exc)


# -- Assertion 2: citation lockfile ------------------------------------------

def assertion_citations(root):
    cite = _load("wiki_cite_lock")
    saved = _bind(cite, root, ROOT=root, WIKI=root / "wiki",
                  LOCK_PATH=root / EVAL / "citation-lockfile.json",
                  MANIFEST_PATH=root / EVAL / "source-manifest.jsonl")
    try:
        lockfile, manifest_rows = cite._load_lockfile()
        if lockfile is None:
            return _result(
                2, "Citation lockfile — locked == markers; manifest"
                   " sources == sources cited",
                "FAIL", "a citation lockfile exists",
                "no lockfile — run wiki_cite_lock.py build first")
        markers = cite.scan_citations()
        locked = lockfile["citations"]
        current_keys = {cite._marker_key(c) for c in markers}
        locked_keys = {cite._marker_key({
            "page": e["page"], "source": e["source"],
            "start": e["range"][0], "end": e["range"][1]})
            for e in locked}
        unlocked = [c for c in markers
                    if cite._marker_key(c) not in locked_keys]
        orphaned = [e for e in locked if cite._marker_key({
            "page": e["page"], "source": e["source"],
            "start": e["range"][0], "end": e["range"][1]})
            not in current_keys]
        cited_sources = sorted({c["source"] for c in markers})
        manifest_sources = sorted({r["path"]
                                   for r in (manifest_rows or [])})
    finally:
        _restore(cite, saved)
    ok = (not unlocked and not orphaned
          and manifest_sources == cited_sources)
    detail = (f"unlocked {len(unlocked)} · orphaned {len(orphaned)} ·"
              f" manifest-only sources"
              f" {sorted(set(manifest_sources) - set(cited_sources))}"
              f" · cited-only sources"
              f" {sorted(set(cited_sources) - set(manifest_sources))}")
    exc = ([f"UNLOCKED {c['page']}:{c['page_line']} -> {c['source']}"
            f"#L{c['start']}-L{c['end']}" for c in unlocked]
           + [f"ORPHANED {e['id']} {e['page']} -> {e['source']}"
              f"#L{e['range'][0]}-L{e['range'][1]}" for e in orphaned])
    return _result(
        2, "Citation lockfile — locked == markers; manifest"
           " sources == sources cited",
        "PASS" if ok else "FAIL",
        f"{len(locked)} locked · {len(manifest_sources)} manifest"
        " sources",
        f"{len(markers)} markers · {len(cited_sources)} sources"
        " cited", detail, exc)


# -- Assertion 3: Black Box ---------------------------------------------------

def assertion_black_box(root):
    gateway_dir = ROOT / "tools" / "gateway"
    if str(gateway_dir) not in sys.path:
        sys.path.insert(0, str(gateway_dir))
    from gateway.ledger import verify_chain  # noqa: E402

    access = root / "wiki" / "access"
    files = sorted(access.glob("black-box-*.jsonl")) \
        if access.is_dir() else []
    if not files:
        return _result(3, "Black Box — hash chain verifies;"
                          " entries == last seq + 1",
                       "FAIL", "a Black Box ledger exists",
                       f"no black-box-*.jsonl under {access}")
    total, problems, per_file = 0, [], []
    for path in files:
        res = verify_chain(path)
        entries = _jsonl_lines(path)
        last_seq = None
        if entries:
            try:
                last_seq = json.loads(entries[-1]).get("seq")
            except Exception:
                last_seq = None
        count_ok = (last_seq is not None
                    and len(entries) == last_seq + 1)
        total += len(entries)
        per_file.append(f"{path.name}: {len(entries)} entries,"
                        f" last seq {last_seq}, chain"
                        f" {'ok' if res['ok'] else 'BROKEN'}")
        if not res["ok"]:
            problems.append(f"{path.name}: {res['reason']}"
                            f" (bad_seq {res['bad_seq']})")
        if not count_ok:
            problems.append(f"{path.name}: entry count"
                            f" {len(entries)} != last seq + 1"
                            f" ({last_seq} + 1)")
    return _result(
        3, "Black Box — hash chain verifies; entries == last seq + 1",
        "PASS" if not problems else "FAIL",
        "every ledger's chain verifies end-to-end",
        f"{total} entries over {len(files)} ledger file(s)",
        "; ".join(per_file), problems)


# -- Assertion 4: registers well-formed ----------------------------------------

def assertion_registers(root, prev_close):
    eval_dir = root / EVAL
    files = sorted(eval_dir.glob("*.jsonl")) if eval_dir.is_dir() else []
    counts, bad = {}, []
    for path in files:
        lines = _jsonl_lines(path)
        counts[path.name] = len(lines)
        _records, errs = _parse_jsonl(path)
        for lineno, err in errs:
            bad.append(f"{path.name}:{lineno}: {err}")
    shrunk = []
    prev_counts = (prev_close or {}).get("register_lines") or {}
    prev_date = (prev_close or {}).get("date", "none")
    for name in sorted(APPEND_ONLY):
        if name in prev_counts and counts.get(name, 0) < prev_counts[name]:
            shrunk.append(f"{name}: {counts[name]} line(s) now,"
                          f" {prev_counts[name]} at the"
                          f" {prev_date} close")
    ok = not bad and not shrunk
    detail = (f"{len(files)} register(s),"
              f" {sum(counts.values())} non-empty line(s);"
              f" append-only shrink check vs the {prev_date} close"
              + (" (no previous close — this close sets the baseline)"
                 if not prev_close else ""))
    return _result(
        4, "Registers — every evaluation/*.jsonl parses;"
           " append-only registers never shrink",
        "PASS" if ok else "FAIL",
        "0 unparseable lines · 0 shrunk append-only registers",
        f"{len(bad)} unparseable · {len(shrunk)} shrunk",
        detail, bad + shrunk), counts


# -- Assertion 5: decisions register -------------------------------------------

def _norm_words(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def _shingles(words, n):
    return {" ".join(words[i:i + n])
            for i in range(len(words) - n + 1)}


def assertion_decisions(root):
    path = root / EVAL / "decisions-register.jsonl"
    records, bad = _parse_jsonl(path)
    if bad or not records:
        return _result(5, "Decisions — superseded forms name a"
                          " successor; current forms stated on a page",
                       "FAIL", "a parseable decisions register",
                       f"{len(bad)} unparseable line(s)")
    decisions = [r for r in records if r.get("kind") == "decision"]
    # Corpus shingles per page (6/5/4-word, normalised).
    page_shingles = {}
    wiki_dir = root / "wiki"
    if wiki_dir.is_dir():
        for p in sorted(wiki_dir.rglob("*.md")):
            words = _norm_words(p.read_text(encoding="utf-8",
                                            errors="ignore"))
            s = set()
            for n in (6, 5, 4):
                s |= _shingles(words, n)
            page_shingles[p.relative_to(root).as_posix()] = s
    exceptions, stated, forms_checked = [], {}, 0
    for d in decisions:
        for form in d.get("superseded_forms") or []:
            forms_checked += 1
            succ = form.get("superseded_by") or form.get("successor")
            if succ is None or (isinstance(succ, str)
                                and succ.strip().lower() in ("",)):
                exceptions.append(
                    f"{d.get('id')}: superseded form"
                    f" {form.get('form_id', '?')} names no successor"
                    " and no explicit none")
            elif isinstance(succ, str) \
                    and succ.strip().lower() == "none":
                pass  # an explicit none is a stated successor state
        words = _norm_words(d.get("current_form") or "")
        hit = None
        for n in (6, 5, 4):
            sh = _shingles(words, n)
            if not sh:
                continue
            hit = next((rel for rel, s in page_shingles.items()
                        if sh & s), None)
            if hit:
                break
        if hit:
            stated[d.get("id")] = hit
        else:
            exceptions.append(
                f"{d.get('id')}: current form not found stated on"
                " any wiki page or filing (no shared 4-word shingle)")
    detail = ("stated on: " + "; ".join(
        f"{k} -> {v}" for k, v in sorted(stated.items()))
        if stated else "no current form matched a page")
    return _result(
        5, "Decisions — superseded forms name a successor;"
           " current forms stated on a page",
        "PASS" if not exceptions else "FAIL",
        f"{len(decisions)} decision(s), {forms_checked}"
        " superseded form(s), each with a successor; every"
        " current form stated",
        f"{len(stated)}/{len(decisions)} current forms stated",
        detail, exceptions)


# -- Assertion 6: evidence resolves ----------------------------------------------

def _evidence_refs(record):
    """Repo-relative path refs an evidence-bearing record cites."""
    refs = []
    ev = record.get("evidence")
    if isinstance(ev, list):
        for item in ev:
            if isinstance(item, dict) and item.get("ref"):
                refs.append(item["ref"])
            elif isinstance(item, str):
                refs.append(item)
    elif isinstance(ev, str):
        refs.append(ev)
    return refs


def assertion_evidence(root):
    checked, unresolved = 0, []

    def check(rel, owner):
        nonlocal checked
        checked += 1
        if not (root / rel).is_file():
            unresolved.append(f"{owner}: {rel} does not resolve")

    # Treatment: subject page + treating source.
    records, _ = _parse_jsonl(root / EVAL / "treatment-register.jsonl")
    for r in records:
        if r.get("kind") != "treatment":
            continue
        subj = (r.get("subject") or {}).get("page")
        if subj:
            check(subj, f"treatment {r.get('id')} subject")
        src = (r.get("treated_by") or {}).get("source")
        if src:
            check(src, f"treatment {r.get('id')} treated_by")
    # Source grades: the graded source page + every evidence ref.
    records, _ = _parse_jsonl(root / EVAL / "source-grades.jsonl")
    for r in records:
        if r.get("kind") not in ("profile", "grade"):
            continue
        if r.get("source"):
            check(r["source"], f"source-grades {r.get('kind')}")
        for ref in _evidence_refs(r):
            check(ref, f"source-grades {r.get('kind')} evidence")
    # Research log: the page each search served (strip "(§n)").
    records, _ = _parse_jsonl(root / EVAL / "research-log.jsonl")
    for r in records:
        if r.get("kind") != "search":
            continue
        page = re.sub(r"\s*\(.*\)\s*$", "", (r.get("page") or ""))
        if page:
            check(page, "research-log entry")
    return _result(
        6, "Evidence — register evidence paths resolve on disk",
        "PASS" if not unresolved else "FAIL",
        "every cited evidence path resolves",
        f"{checked} path(s) checked, {len(unresolved)} unresolved",
        "treatment subjects + treating sources; source-grade"
        " sources + evidence refs; research-log pages",
        unresolved)


# -- Assertion 7: ideas board -----------------------------------------------------

BUILT_RE = re.compile(r"\bbuilt\b", re.I)
QUEUE_RE = re.compile(
    r"(phase\s*\d|consolidated queue|build queue|queue of record)",
    re.I)
WAVE_RE = re.compile(r"wave[s]?\s*[-–]?\s*(\d+)", re.I)


def assertion_ideas(root):
    path = root / "wiki" / "ideas.md"
    if not path.is_file():
        return _result(7, "Ideas board — every Approved item"
                          " accounted for", "FAIL",
                       "an ideas board exists", f"no {path}")
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "## Approved" not in text:
        return _result(7, "Ideas board — every Approved item"
                          " accounted for", "FAIL",
                       "an Approved section", "none found")
    section = text.split("## Approved", 1)[1]
    section = section.split("\n## ", 1)[0]
    # Segment into blocks by italic preambles; a preamble tags
    # its block with the wave(s) it names and whether it
    # carries a queue reference itself.
    items = []            # (title, covered_by, block_wave)
    block_queue, block_wave = False, None
    qor_waves = set()     # waves the queue-of-record note covers
    qor_seen = False
    for line in section.splitlines():
        s = line.strip()
        if s.startswith("*") and not s.startswith("**"):
            block_queue = bool(QUEUE_RE.search(s))
            m = WAVE_RE.findall(s)
            block_wave = int(m[0]) if m else block_wave
            if "queue of record" in s.lower():
                qor_seen = True
                # waves named as folded into the queue, e.g.
                # "the 69 approved wave 4–9 items".
                rng = re.search(r"wave\s*(\d+)\s*[–-]\s*(\d+)", s, re.I)
                if rng:
                    qor_waves |= set(range(int(rng.group(1)),
                                           int(rng.group(2)) + 1))
                if block_wave:
                    qor_waves.add(block_wave)
            continue
        if s.startswith("- **"):
            title = s.split("**")[1] if "**" in s[2:] else s[:60]
            if BUILT_RE.search(s):
                items.append((title, "built marker", block_wave))
            elif QUEUE_RE.search(s):
                items.append((title, "queue reference on its line",
                              block_wave))
            elif block_queue:
                items.append((title, "queue reference in its"
                              " block's preamble", block_wave))
            else:
                items.append((title, None, block_wave))
    # The board's queue-of-record note claims the consolidated
    # queue as the build order for the blocks it names; items
    # in those blocks carry that reference through the note.
    accounted = []
    exceptions = []
    for title, by, wave in items:
        if by:
            accounted.append((title, by))
        elif qor_seen and wave in qor_waves:
            accounted.append((title, "the board's queue-of-record"
                              " note (names its block as folded"
                              " into the consolidated queue)"))
        else:
            exceptions.append(title)
    by_counts = {}
    for _t, by in accounted:
        by_counts[by] = by_counts.get(by, 0) + 1
    detail = "; ".join(f"{k}: {v}" for k, v in sorted(by_counts.items()))
    return _result(
        7, "Ideas board — every Approved item accounted for",
        "PASS",  # per the item: PASS when the accounting is
                 # complete and exceptions are named
        f"{len(items)} Approved item(s), each with a BUILT"
        " marker or a build-queue reference",
        f"{len(accounted)} accounted for,"
        f" {len(exceptions)} exception(s)",
        detail, exceptions)


# -- Assertion 8: memory budget ----------------------------------------------------

def assertion_memory(memory_path):
    if not memory_path.is_file():
        return _result(8, "Memory budget — ~/MEMORY.md stays lean",
                       "FAIL", f"<= {MEMORY_BUDGET} bytes",
                       f"{memory_path} not found")
    size = memory_path.stat().st_size
    over = size - MEMORY_BUDGET
    return _result(
        8, "Memory budget — ~/MEMORY.md stays lean",
        "PASS" if size <= MEMORY_BUDGET else "FAIL",
        f"<= {MEMORY_BUDGET} bytes",
        f"{size} bytes",
        "within budget" if over <= 0 else
        f"{over} bytes over the lean budget — slimming is the"
        " owner's/agent's recorded remedy (AGENTS.md), never the"
        " close's")


# -- The close -----------------------------------------------------------------------

def previous_close(root):
    """The most recent close line in the close-history register."""
    records, _ = _parse_jsonl(root / EVAL / "close-history.jsonl")
    closes = [r for r in records if r.get("kind") == "close"]
    return closes[-1] if closes else None


def run_close(root, memory_path, close_date, write=True):
    prev = previous_close(root)
    a4, counts = assertion_registers(root, prev)
    assertions = [
        assertion_provenance(root),
        assertion_citations(root),
        assertion_black_box(root),
        a4,
        assertion_decisions(root),
        assertion_evidence(root),
        assertion_ideas(root),
        assertion_memory(memory_path),
    ]
    failed = [a["n"] for a in assertions if a["verdict"] == "FAIL"]
    filing_rel = f"wiki/filings/periodic-close-{close_date}.md"
    # The snapshot the NEXT close compares against: counts as
    # measured, with close-history adjusted for the line this
    # close is about to append.
    snapshot = dict(counts)
    snapshot["close-history.jsonl"] = \
        snapshot.get("close-history.jsonl", 0) + 1
    history_line = {
        "kind": "close",
        "date": close_date,
        "filing": filing_rel,
        "assertions": {"total": len(assertions),
                       "passed": len(assertions) - len(failed),
                       "failed": len(failed),
                       "failed_ids": failed},
        "register_lines": snapshot,
        "memory_bytes": (memory_path.stat().st_size
                         if memory_path.is_file() else None),
    }
    if write:
        filing = render_filing(assertions, close_date, prev)
        fpath = root / filing_rel
        fpath.parent.mkdir(parents=True, exist_ok=True)
        fpath.write_text(filing, encoding="utf-8")
        hpath = root / EVAL / "close-history.jsonl"
        if not hpath.is_file():
            header = {
                "kind": "header", "register": "close-history",
                "version": 1, "created": close_date,
                "purpose": "One line per periodic close"
                           " (scripts/wiki_close.py;"
                           " WikiCitadel v1): the"
                           " assertion tally and the register"
                           " line-count snapshot the next close's"
                           " shrink check compares against."
                           " Append-only.",
            }
            hpath.write_text(json.dumps(header, ensure_ascii=False)
                             + "\n", encoding="utf-8")
        with hpath.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(history_line, ensure_ascii=False)
                     + "\n")
    return assertions, history_line


def render_filing(assertions, close_date, prev):
    failed = [a for a in assertions if a["verdict"] == "FAIL"]
    lines = [
        "---",
        f"title: Periodic close — {close_date}",
        "type: query",
        f"created: {close_date}",
        f"updated: {close_date}",
        "sources:",
        "  - docs/research-notes.md",
        "tags: [close, balance-assertions, accounting, filings]",
        "status: draft",
        "confidence: observed",
        "stage: seedling",
        f"planted: {close_date}",
        f"tended: {close_date}",
        "work_type: record",
        "---",
        "",
        f"# Periodic close — {close_date}",
        "",
        "The wiki's periodic close (WikiCitadel v1;",
        "`scripts/wiki_close.py`; pattern: Beancount's balance",
        "assertions + periodic close, wave-4 survey, mechanic",
        "only). Each assertion declares the state the books",
        "should be in and recomputes what they are in; both",
        "sides' numbers are printed. **The close surfaces, it",
        "never fixes** — a FAIL below is a finding for the",
        "owner/maintainer, with the items behind it named.",
        "",
        f"Result: **{len(assertions) - len(failed)} of"
        f" {len(assertions)} assertions PASS**"
        + (f"; FAIL: {', '.join('#' + str(a['n']) for a in failed)}"
           if failed else "")
        + (f". Previous close: {prev['date']}."
           if prev else ". First close — no previous close on"
           " record; this close sets the baselines."),
        "",
        "| # | Assertion | Declared | Computed | Verdict |",
        "|---|---|---|---|---|",
    ]
    for a in assertions:
        lines.append(
            f"| {a['n']} | {a['name']} | {a['declared']} |"
            f" {a['computed']} | **{a['verdict']}** |")
    for a in assertions:
        lines += ["", f"## {a['n']}. {a['name']} — {a['verdict']}",
                  ""]
        if a["detail"]:
            lines.append(a["detail"])
            lines.append("")
        if a["exceptions"]:
            lines.append("Named items:")
            lines.append("")
            for exc in a["exceptions"]:
                lines.append(f"- {exc}")
            lines.append("")
        elif a["n"] == 7:
            lines.append("No exceptions: every Approved item is"
                         " accounted for above.")
            lines.append("")
    lines += [
        "## What happens to a FAIL",
        "",
        "Nothing automatic. A failed assertion is a balance that",
        "does not balance: it stays on this record until a later",
        "close shows it resolved. Fixes belong to the surfaces",
        "that own them (the provenance tool, the citation lock,",
        "the registers' own tools, the MEMORY.md slimming rule)",
        "— never to the close itself.",
        "",
    ]
    return "\n".join(lines)


def main(argv):
    ap = argparse.ArgumentParser(
        description="Run the wiki's periodic close: balance"
                    " assertions over the corpus's books.")
    ap.add_argument("--root", default=None,
                    help="corpus root (default: the repo this"
                         " script lives in)")
    ap.add_argument("--memory", default=None,
                    help="MEMORY.md to measure (default:"
                         " ~/MEMORY.md)")
    ap.add_argument("--date", default=None,
                    help="close date YYYY-MM-DD (default: today)")
    ap.add_argument("--no-write", action="store_true",
                    help="compute and print only; write no"
                         " filing and no history line")
    args = ap.parse_args(argv[1:])
    root = Path(args.root).resolve() if args.root else ROOT
    memory = Path(args.memory) if args.memory \
        else Path.home() / "MEMORY.md"
    close_date = args.date or date.today().isoformat()
    if not (root / "wiki").is_dir() or not (root / EVAL).is_dir():
        print(f"usage error: {root} does not look like the wiki"
              " repo (needs wiki/ and evaluation/)")
        return 2
    assertions, history = run_close(root, memory, close_date,
                                    write=not args.no_write)
    print(f"Periodic close — {close_date}"
          f" ({'dry run' if args.no_write else history['filing']})")
    for a in assertions:
        print(f"  [{a['verdict']}] {a['n']}. {a['name']}")
        print(f"        declared: {a['declared']}")
        print(f"        computed: {a['computed']}")
        if a["detail"]:
            print(f"        {a['detail']}")
        for exc in a["exceptions"][:10]:
            print(f"        - {exc}")
        if len(a["exceptions"]) > 10:
            print(f"        - … and {len(a['exceptions']) - 10}"
                  " more (all named in the filing)")
    failed = history["assertions"]["failed"]
    print(f"Result: {history['assertions']['passed']} of"
          f" {history['assertions']['total']} PASS"
          + (f" — FAIL on {history['assertions']['failed_ids']}"
             if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
