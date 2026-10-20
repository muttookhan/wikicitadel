#!/usr/bin/env python3
"""Weeding-as-triage: CREW/MUSTIE translated into a nomination
queue over the compiled layer (WikiCitadel v1).

The pattern (LIS-practice survey,
docs/research-notes.md,
finds 14–16): CREW — Continuous Review, Evaluation, and
Weeding — scores candidates per class with an X/Y formula
(X = years since the item's date, Y = years since last use)
AND requires a MUSTIE defect; either gate alone is
insufficient, and the formula NOMINATES — the librarian
decides, item in hand. The ALA guardrails ride along:
exception classes named in advance, a held-elsewhere check
(inbound links are our "only loanable copy"), and the
method is never a content purge.

Translated to this wiki:

  - Classes are page kinds (the first directory under
    wiki/), each with a stated staleness window X in days —
    stated policy, below, not a measurement.
  - A nomination requires a DEFECT: a named signal with
    its measured value attached. A page matching its class
    formula but showing no defect is not nominated; a
    nomination attempted without a defect is REFUSED by
    the tool (exit 2), in code, not by convention.
  - The defect signals (each computed from the tree, the
    rot census, the reverify schedule, or the retrieval
    baseline — never copied from another tool's summary):
      orphan            rot census: no inbound wikilinks
                        from the compiled layer and no
                        outbound to it — an island.
      no-inbound-links  no compiled page links to it,
                        though it links out: findable only
                        via the index (find 18's
                        "mis-shelved = lost" in wiki form).
      never-retrieved   zero top-10 appearances across the
                        retrieval baseline's probes
                        (evaluation/retrieval-baseline.json);
                        asserted only for pages created
                        BEFORE the baseline date — a page
                        the baseline never saw is unmeasured,
                        not unretrieved.
      ghost-source      rot census: a source it cites is
                        not on disk; the referent is gone.
      fork              rot census: a live twin shares its
                        stem, title, or settled claim.
      expired-horizon   rot census: the page's own date
                        horizon (verified_until & kin) has
                        passed.
      reverify-overdue  the page is a claim page whose
                        FSRS re-verification is overdue.
      stale-beyond-class last content anchor (latest of
                        updated / tended / as_of / created)
                        is older than the class window X.
      oversized         body over the size threshold with
                        its section count attached (named
                        exception classes exempt).
  - Calibration, on the record: the first draft let
    no-inbound-links and never-retrieved nominate ALONE
    and produced 34 candidates — a third of the corpus.
    On an 8-day corpus read through a 93-probe baseline,
    zero appearances is the base rate for source records,
    and reference pages are legitimately reached via the
    index rather than prose links; a signal that fires on
    a third of the corpus is measuring the corpus, not
    the page. So the two usage signals are SUPPORTING
    defects, with one exception: a page carrying BOTH —
    no inbound links AND never retrieved — is lost to
    both reading paths at once, and that combination
    nominates. The structural defects (orphan, ghost,
    fork, expired horizon, overdue re-verification,
    class staleness, oversize) nominate on their own.
    This is CREW's own shape: the X/Y formula gates, a
    defect nominates.
  - Routing outcomes are a CLOSED vocabulary of six —
    keep / refresh / merge-into / split / demote-to-raw /
    owner-call — and the tool only PROPOSES a route:
    fork -> merge-into (target named), the staleness and
    horizon signals -> refresh, oversized -> split, the
    findability and ghost signals -> owner-call (the fix
    is editorial or a ruling). merge-into without a target
    is refused.
  - Named exceptions, decided in advance (find 16):
    EXEMPT_PAGES below are never nominated — historical
    records the owner has ruled stand as written, and the
    decisions of record. Retired pages (status superseded
    / deprecated, or superseded_by set) are already routed
    and are skipped, not re-nominated.

The register: evaluation/weeding-nominations.jsonl —
append-only, one JSON object per nomination:
  {"id": "weed-0001", "date": ..., "page": ...,
   "page_class": {"kind": ..., "work_type": ...},
   "defects": [{"signal": ..., "value": ...}, ...],
   "proposed_route": ..., "route_target": ... | null,
   "status": "open", "source": "auto-scan" | "manual"}
A page with an open nomination is not re-nominated for the
same scan. This tool NEVER deletes, demotes, merges, or
edits a page: routing is executed by the parent/owner only.

Commands:
  scan                 Print the candidate nominations
                       (defects verified against the tree
                       this run). --limit N caps the batch.
  nominate             Append the scan's candidates to the
                       register (up to --limit, default 8),
                       or file one manual nomination:
                       --page P --signal S --value V
                       --route R [--target T].
  list                 The register's open nominations.

Exit codes: 0 = ok; 2 = usage error or a REFUSED
nomination (no defect, route outside the vocabulary,
merge-into without a target, page not in the compiled
layer, page exempt or already nominated).
Stdlib only (sibling tools imported in-process).
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
REGISTER_REL = "evaluation/weeding-nominations.jsonl"
BASELINE_REL = "evaluation/retrieval-baseline.json"

ROUTES = ("keep", "refresh", "merge-into", "split",
          "demote-to-raw", "owner-call")
SIGNALS = ("orphan", "no-inbound-links", "never-retrieved",
           "ghost-source", "fork", "expired-horizon",
           "reverify-overdue", "stale-beyond-class",
           "oversized")

# CREW class windows X, in days since the last content
# anchor. Stated policy for an 8-day-old corpus: they bind
# as the corpus ages; today they correctly fire rarely.
CLASS_WINDOWS = {"queries": 60, "entities": 90,
                 "syntheses": 90, "concepts": 120,
                 "rules": 180, "sources": 365}
DEFAULT_WINDOW = 120
OVERSIZE_CHARS = 60000

# Named exceptions (find 16): records that stand as
# written by the owner's ruling, and the decisions of
# record. Never nominated, whatever signals they carry.
# EXAMPLE ENTRIES — deployments name their own exempt pages.
EXEMPT_PAGES = {
    "wiki/syntheses/design-record.md":
        "the design record, left as written by"
        " the owner's standing posture",
    "wiki/syntheses/decisions-of-record.md":
        "the decisions of record",
}
RETIRED_STATUSES = {"superseded", "deprecated"}

# Proposed route per lead defect, in priority order.
ROUTE_PRIORITY = ("fork", "expired-horizon", "reverify-overdue",
                  "stale-beyond-class", "oversized",
                  "ghost-source", "orphan", "no-inbound-links",
                  "never-retrieved")
ROUTE_FOR = {"fork": "merge-into",
             "expired-horizon": "refresh",
             "reverify-overdue": "refresh",
             "stale-beyond-class": "refresh",
             "oversized": "split",
             "ghost-source": "owner-call",
             "orphan": "owner-call",
             "no-inbound-links": "owner-call",
             "never-retrieved": "owner-call"}


def _load(name):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rot = _load("wiki_rot")
reverify = _load("wiki_reverify")
parse_frontmatter = rot.parse_frontmatter

DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
MD_PATH_RE = re.compile(r"wiki/[\w./-]+\.md")


def _parse_date(value):
    if not value:
        return None
    m = DATE_RE.search(str(value))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)),
                    int(m.group(3)))
    except ValueError:
        return None


# -- page facts -------------------------------------------------------------------

def page_facts(root, today):
    """{rel: facts} over the compiled layer, plus the rot
    census and the link graph, computed this run."""
    root = Path(root)
    census = rot.census(root, today)
    pages = rot.layer_pages(root)
    stem_map = {}
    for p in pages:
        stem_map.setdefault(p.stem, []).append(
            p.relative_to(root).as_posix())
    facts = {}
    bodies = {}
    for p in pages:
        rel = p.relative_to(root).as_posix()
        text = p.read_text(encoding="utf-8", errors="ignore")
        fields, _srcs = parse_frontmatter(text)
        body = rot.strip_fences(
            rot.body_without_frontmatter(text))
        bodies[rel] = body
        facts[rel] = {"fields": fields or {}, "chars": len(body),
                      "sections": body.count("\n## ")}
    inbound = {rel: 0 for rel in facts}
    outbound = {rel: set() for rel in facts}
    for rel, body in bodies.items():
        for m in rot.LINK_RE.finditer(body):
            tgt = m.group(1).strip()
            if tgt.endswith(".md"):
                tgt = tgt[:-3]
            stem = Path(tgt).stem if "/" in tgt else tgt
            for hit in stem_map.get(stem, []):
                if hit != rel:
                    outbound[rel].add(hit)
                    inbound[hit] += 1
    appearances = {}
    baseline_date = None
    baseline = root / BASELINE_REL
    if baseline.is_file():
        try:
            data = json.loads(baseline.read_text(
                encoding="utf-8"))
            baseline_date = _parse_date(data.get("created"))
            for q in data.get("per_query", {}).values():
                for path in q.get("top10", []):
                    if path.startswith("wiki/"):
                        appearances[path] = \
                            appearances.get(path, 0) + 1
        except (OSError, ValueError):
            baseline_date = None
    schedules = {}
    for row in reverify.due_claims(today):
        schedules[row["page"]] = row
    return {"facts": facts, "census": census, "inbound": inbound,
            "outbound": outbound, "appearances": appearances,
            "baseline_date": baseline_date,
            "schedules": schedules}


def kind_of(rel):
    parts = rel.split("/")
    return parts[1] if len(parts) > 2 else ""


def anchor_of(fields):
    best = None
    for key in ("updated", "tended", "as_of", "created"):
        day = _parse_date(fields.get(key))
        if day and (best is None or day > best):
            best = day
    return best


def defects_for(rel, ctx, today):
    """[(signal, value)] — every defect this page verifiably
    carries, computed from the tree this run."""
    f = ctx["facts"][rel]
    fields = f["fields"]
    defects = []
    census_pages = ctx["census"]["pages"].get(rel, {})
    for cls in ("ghost", "fork", "expired"):
        for signal_text in census_pages.get(cls, []):
            signal = {"ghost": "ghost-source", "fork": "fork",
                      "expired": "expired-horizon"}[cls]
            defects.append((signal, signal_text))
    if census_pages.get("orphan"):
        defects.append(("orphan", census_pages["orphan"][0]))
    elif ctx["inbound"][rel] == 0:
        defects.append((
            "no-inbound-links",
            "no inbound wikilinks from the compiled layer"
            f" (outbound: {len(ctx['outbound'][rel])}) —"
            " findable only via the index"))
    created = _parse_date(fields.get("created"))
    base_day = ctx["baseline_date"]
    if base_day and created and created < base_day \
            and ctx["appearances"].get(rel, 0) == 0:
        defects.append((
            "never-retrieved",
            "0 top-10 appearances across the retrieval"
            f" baseline's probes (baseline {base_day.isoformat()})"))
    sched = ctx["schedules"].get(rel)
    if sched and sched["status"] == "overdue":
        defects.append((
            "reverify-overdue",
            f"claim re-verification due"
            f" {sched['due'].isoformat()},"
            f" {sched['days_overdue']} day(s) overdue"))
    kind = kind_of(rel)
    window = CLASS_WINDOWS.get(kind, DEFAULT_WINDOW)
    anchor = anchor_of(fields)
    vu = _parse_date(fields.get("verified_until"))
    if anchor and not (vu and vu >= today):
        age = (today - anchor).days
        if age > window:
            defects.append((
                "stale-beyond-class",
                f"last content anchor {anchor.isoformat()} is"
                f" {age} days old; class window for"
                f" {kind or 'pages'} is {window} days"))
    if f["chars"] > OVERSIZE_CHARS:
        defects.append((
            "oversized",
            f"body is {f['chars']} chars with"
            f" {f['sections']} level-2 sections; threshold"
            f" is {OVERSIZE_CHARS}"))
    return defects


def propose_route(defects):
    """(route, target) from the lead defect; target only for
    merge-into, parsed from the fork defect's census value."""
    present = {s for s, _v in defects}
    for signal in ROUTE_PRIORITY:
        if signal in present:
            route = ROUTE_FOR[signal]
            target = None
            if route == "merge-into":
                value = next(v for s, v in defects
                             if s == signal)
                others = [p for p in MD_PATH_RE.findall(value)]
                target = others[0] if others else None
            return route, target
    return "owner-call", None


def retired(fields):
    return (str(fields.get("status") or "").strip().lower()
            in RETIRED_STATUSES) or bool(fields.get("superseded_by"))


# Defects that nominate on their own. no-inbound-links and
# never-retrieved are supporting defects: they attach to a
# nomination whenever true, and nominate only together
# (see the calibration note in the module docstring).
PRIMARY_SIGNALS = ("orphan", "ghost-source", "fork",
                   "expired-horizon", "reverify-overdue",
                   "stale-beyond-class", "oversized")


def nominates(defects):
    signals = {s for s, _v in defects}
    if signals & set(PRIMARY_SIGNALS):
        return True
    return {"no-inbound-links", "never-retrieved"} <= signals


def scan(root, today, limit=None):
    """Candidate nominations: pages carrying a nominating
    defect (see nominates()), not exempt, not retired, not
    already nominated."""
    ctx = page_facts(root, today)
    already = {n["page"] for n in load_register(root)
               if n.get("status") == "open"}
    out = []
    for rel in sorted(ctx["facts"]):
        if rel in EXEMPT_PAGES or rel in already:
            continue
        fields = ctx["facts"][rel]["fields"]
        if retired(fields):
            continue
        defects = defects_for(rel, ctx, today)
        if not nominates(defects):
            continue
        route, target = propose_route(defects)
        if route == "merge-into" and target is None:
            route = "owner-call"   # a fork with no named twin
        out.append({
            "page": rel,
            "page_class": {"kind": kind_of(rel),
                           "work_type":
                               str(fields.get("work_type") or "")},
            "defects": [{"signal": s, "value": v}
                        for s, v in defects],
            "proposed_route": route, "route_target": target})
    # Strongest first: most defects, then most severe lead.
    def strength(n):
        lead = min(ROUTE_PRIORITY.index(d["signal"])
                   for d in n["defects"])
        return (lead, -len(n["defects"]), n["page"])
    out.sort(key=strength)
    return out[:limit] if limit else out


# -- register -----------------------------------------------------------------------

def load_register(root):
    path = Path(root) / REGISTER_REL
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_register(root, entry):
    path = Path(root) / REGISTER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def next_id(root):
    nums = []
    for n in load_register(root):
        m = re.match(r"weed-(\d+)$", str(n.get("id", "")))
        if m:
            nums.append(int(m.group(1)))
    return f"weed-{(max(nums) + 1) if nums else 1:04d}"


# -- commands -------------------------------------------------------------------------

def _print_nomination(n):
    print(f"{n['page']}  [{n['page_class']['kind']}"
          f"{'/' + n['page_class']['work_type'] if n['page_class']['work_type'] else ''}]"
          f"  -> {n['proposed_route']}"
          f"{' into ' + n['route_target'] if n['route_target'] else ''}")
    for d in n["defects"]:
        print(f"    defect {d['signal']}: {d['value']}")


def cmd_scan(args, root, today):
    cands = scan(root, today, args.limit)
    if not cands:
        print("no candidates: no compiled page carries a"
              " verified defect this run")
        return 0
    print(f"{len(cands)} candidate nomination(s) — defects"
          f" verified against the tree {today.isoformat()}:")
    for n in cands:
        _print_nomination(n)
    return 0


def cmd_nominate(args, root, today):
    register = Path(root) / REGISTER_REL
    if args.page:
        # Manual nomination: every refusal rule applies.
        rel = args.page
        layer = {p.relative_to(root).as_posix()
                 for p in rot.layer_pages(root)}
        if rel not in layer:
            print(f"REFUSED: {rel} is not a page in the"
                  f" compiled layer")
            return 2
        if rel in EXEMPT_PAGES:
            print(f"REFUSED: {rel} is a named exception"
                  f" ({EXEMPT_PAGES[rel]})")
            return 2
        if not args.signal or not args.value:
            print("REFUSED: a nomination requires a defect —"
                  " a named signal (--signal) AND its measured"
                  " value (--value). A nomination without a"
                  " defect is not filed.")
            return 2
        if args.signal not in SIGNALS:
            print(f"REFUSED: signal {args.signal!r} is not in"
                  f" the closed signal vocabulary {SIGNALS}")
            return 2
        if args.route not in ROUTES:
            print(f"REFUSED: route {args.route!r} is not one"
                  f" of the six routing outcomes {ROUTES}")
            return 2
        if args.route == "merge-into" and not args.target:
            print("REFUSED: merge-into requires --target"
                  " (the page this one merges into)")
            return 2
        if any(n["page"] == rel and n.get("status") == "open"
               for n in load_register(root)):
            print(f"REFUSED: {rel} already has an open"
                  f" nomination")
            return 2
        text = (root / rel).read_text(encoding="utf-8",
                                      errors="ignore")
        fields, _s = parse_frontmatter(text)
        fields = fields or {}
        entry = {"id": next_id(root),
                 "date": today.isoformat(), "page": rel,
                 "page_class": {
                     "kind": kind_of(rel),
                     "work_type": str(fields.get("work_type")
                                      or "")},
                 "defects": [{"signal": args.signal,
                              "value": args.value}],
                 "proposed_route": args.route,
                 "route_target": args.target,
                 "status": "open", "source": "manual"}
        append_register(root, entry)
        print(f"filed {entry['id']}: {rel} -> {args.route}")
        return 0
    cands = scan(root, today, args.limit)
    if not cands:
        print("no candidates to file")
        return 0
    for n in cands:
        entry = {"id": next_id(root),
                 "date": today.isoformat(), **n,
                 "status": "open", "source": "auto-scan"}
        append_register(root, entry)
        print(f"filed {entry['id']}: {n['page']} ->"
              f" {n['proposed_route']}"
              f" ({len(n['defects'])} defect(s))")
    return 0


def cmd_list(args, root, today):
    rows = [n for n in load_register(root)
            if n.get("status") == "open"]
    if not rows:
        print("no open nominations")
        return 0
    print(f"{len(rows)} open nomination(s):")
    for n in rows:
        print(f"  {n['id']} ({n['date']}) {n['page']} ->"
              f" {n['proposed_route']}"
              f"{' into ' + n['route_target'] if n.get('route_target') else ''}"
              f" — defects:"
              f" {', '.join(d['signal'] for d in n['defects'])}")
    return 0


def main(argv):
    ap = argparse.ArgumentParser(
        description="Weeding-as-triage over the compiled"
                    " layer : CREW/MUSTIE nominations"
                    " with verified defects; never edits a"
                    " page.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_scan = sub.add_parser("scan", help="print candidates"
                                         " (no writes)")
    p_scan.add_argument("--limit", type=int, default=None)
    p_nom = sub.add_parser("nominate", help="file nominations"
                                            " to the register")
    p_nom.add_argument("--limit", type=int, default=8)
    p_nom.add_argument("--page", default=None)
    p_nom.add_argument("--signal", default=None)
    p_nom.add_argument("--value", default=None)
    p_nom.add_argument("--route", default=None)
    p_nom.add_argument("--target", default=None)
    sub.add_parser("list", help="open nominations")
    for p in (p_scan, p_nom):
        p.add_argument("--today", default=None)
        p.add_argument("--root", default=None)
    args = ap.parse_args(argv[1:])
    root = ROOT
    today = date.today()
    if args.cmd in ("scan", "nominate"):
        if args.root:
            root = Path(args.root).resolve()
        if args.today:
            today = _parse_date(args.today)
            if today is None:
                print(f"bad --today: {args.today!r}")
                return 2
    if args.cmd == "scan":
        return cmd_scan(args, root, today)
    if args.cmd == "nominate":
        return cmd_nominate(args, root, today)
    return cmd_list(args, root, today)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
