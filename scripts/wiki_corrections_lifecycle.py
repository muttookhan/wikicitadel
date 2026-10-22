#!/usr/bin/env python3
"""Corrections-ledger lifecycle, trends and promotion ladder
(build-list wave 5, 2026-10-22).

Patterns, re-implemented in this wiki's own code (no code
copied): the warning-to-blocking hardening of DomDemetz/
claude-soul and the evidence ladder of IgorGanapolsky/
mcp-memory-gateway and Ikalus1988/MisakaNet (survey rows;
see the wave-5 build-list item). The base it extends is the
house machinery: scripts/wiki_corrections.py (classification
+ repetition counter, item 19) and scripts/wiki_heed_rate.py
(Round 9 heed-rate over evaluation/correction-outcomes.jsonl).

This tool derives, for every ledger entry, three things the
older tools do not state — always from evidence in the
record, never by rewriting the ledger (the ledger is
append-only law: entries are never deleted or rewritten, and
this tool opens it read-only):

LIFECYCLE STATE — one of a closed set, per entry:
  superseded-by-later-entry
      a later record NAMES this entry (or its rule) as
      superseded, in its own text or in an entry whose body
      declares the supersession. A generic mention of
      supersession naming no entry changes nothing.
  promoted-to-rule
      the entry's standing rule is carried as standing text
      outside the entry itself, by any of three grounded
      routes: (a) a later entry invokes the entry/rule as
      governing ("recurrence of ..." in its title, a
      classification row naming the recurrence OF THIS
      ENTRY — matched on the entry's title, never on a bare
      date, which several entries can share — or a body
      applying the rule); (b) a standing-rule surface (the
      schema AGENTS.md or another wiki/rules/ page) carries
      the rule slug or a verbatim five-word window of the
      rule's first sentence (the window must carry at least
      two content tokens, so function-word runs never
      promote); (c) an extra surface passed with --surface.
      The standard is verbatim: a surface carrying the rule
      in paraphrase does not count, and the report says so
      by omission — the derivation under-claims rather than
      over-claims.
  acted-on
      the entry's Recorded line cites concrete landing
      places (wikilinks, file paths, commits) — the
      correction demonstrably landed in the world.
  open
      the entry parses (standing rule and/or classification)
      but no landing, promotion or supersession evidence is
      in the record yet.
  unstated
      the entry cannot be grounded in any state: neither a
      Standing rule bullet nor a classification row. The
      reason is reported, never guessed over.
  Precedence: superseded > promoted > acted-on > open.

GATE POSTURE — a recorded failure starts as a WARNING and
hardens into a BLOCKING gate only after it recurs
(rule-level recurrence: a later entry under the same
standing-rule slug, an explicit recurrence of this entry,
or an outcome line recording recurred=true). The blocking
rule carries its originating feedback — the first entry
that set it and the recurrence that hardened it — so a
check that fires on it can cite both. Kind-level recurrence
(the repetition counter's ground) is reported in trends
as the repeat-offence signal; it does not by itself harden
an entry's gate.

EVIDENCE GRADE — per entry, five rungs, each present only
with cited evidence (absence is stated, never smoothed):
  landed          Recorded line cites landing places.
  reproduced      the entry's own record names a tool/check
                  run (a backticked scripts/*.py path) whose
                  stated result re-derives the correction.
  ci-verified     a script in scripts/ carries the rule slug
                  or a verbatim five-word window of the rule
                  text — a standing machine check embodies it.
  reuse-observed  a later entry invokes the rule, or the
                  outcomes register records retrieved=true.
  measured-heeded the outcomes register records heeded=true.
The summary grade is the highest rung reached, in the order
recorded < landed < reproduced < ci-verified < reuse-
observed < measured-heeded < field-proven. FIELD-PROVEN —
the top grade — requires ALL five rungs: it cannot be
earned by writing (a ledger entry alone reaches only
"recorded") or by voting (no vote exists in this system).

TRENDS — entries by month and ISO week, cumulative counts
by error kind, and the repeat-offence patterns: standing
rules with two or more entries (the same ground corrected
twice is a named signal), kinds repeated since first ruled
(from wiki_corrections' own accounting), and entry
velocity against --today.

PROMOTION LADDER — promotion CANDIDATES: entries whose
correction landed, whose rule has not recurred since, and
which are neither already promoted nor superseded. A
candidate is a report line only: promoting a correction
into the schema or a rules page is Mehmed's/owner's act,
never this tool's.

Determinism: same ledger + same register + same surfaces +
same --today give byte-identical output; the artefact
carries the ledger's sha256 so a stale artefact is visible.

Usage:
  python3 scripts/wiki_corrections_lifecycle.py report
      [--json] [--today YYYY-MM-DD] [--ledger PATH]
      [--register PATH] [--root DIR] [--surface PATH ...]
      [--out PATH]
Exit 0: report produced (this is a report, not a gate —
the wiki_corrections convention). Exit 2: usage error.
Stdlib only, no network.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_REL = "wiki/rules/corrections-ledger.md"
REGISTER_REL = "evaluation/correction-outcomes.jsonl"

STATES = ("superseded-by-later-entry", "promoted-to-rule",
          "acted-on", "open", "unstated")
GRADE_ORDER = ("recorded", "landed", "reproduced", "ci-verified",
               "reuse-observed", "measured-heeded", "field-proven")
RUNGS = ("landed", "reproduced", "ci-verified",
         "reuse-observed", "measured-heeded")

HEADING_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) — (.+?)\s*$")
SECTION_RE = re.compile(r"^#{2,3}\s")
BULLET_RE = re.compile(r"^- \*\*(.+?):\*\*\s*(.*)$")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
BACKTICK_RE = re.compile(r"`([^`]+)`")
COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$")
RESULT_WORD_RE = re.compile(
    r"\b(verdict|caught|checked|verified|lookup returns|"
    r"resolves|recomputed|re-run|rerun)\b", re.I)
SUPERSEDE_RE = re.compile(r"superseded|supersedes", re.I)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _norm(text):
    """Case/punctuation-insensitive normal form for matching."""
    t = text.lower().replace("“", '"').replace("”", '"')
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def base_slug(rule_cell):
    """The standing-rule slug of a classification row: the
    first token of the cell ('artifact-governs (RECURRENCE
    of ...)' -> 'artifact-governs')."""
    if not rule_cell:
        return None
    return rule_cell.split()[0].strip("`").lower() or None


def parse_bodies(text):
    """{entry key: {bullets: {label: text}, lines: [str]}}
    for every `### DATE — Title` entry, where the body runs
    to the next ##/### heading. Bullet text is unwrapped."""
    bodies = {}
    current = None
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            current = {"bullets": {}, "lines": [], "_label": None}
            bodies[f"{m.group(1)} — {m.group(2)}"] = current
            continue
        if SECTION_RE.match(line):
            current = None
            continue
        if current is None:
            continue
        current["lines"].append(line)
        b = BULLET_RE.match(line)
        if b:
            current["_label"] = b.group(1).strip()
            current["bullets"][current["_label"]] = b.group(2)
        elif current["_label"] and line.strip():
            current["bullets"][current["_label"]] += " " + line.strip()
    for body in bodies.values():
        body.pop("_label", None)
        for k, v in body["bullets"].items():
            body["bullets"][k] = " ".join(v.split())
    return bodies


def recorded_refs(recorded_text):
    """Concrete landing references in a Recorded line:
    wikilinks, backticked paths, backticked commit hashes."""
    refs = []
    for w in WIKILINK_RE.findall(recorded_text or ""):
        refs.append({"kind": "wikilink", "ref": w.strip()})
    for span in BACKTICK_RE.findall(recorded_text or ""):
        span = span.strip()
        if COMMIT_RE.match(span):
            refs.append({"kind": "commit", "ref": span})
        elif "/" in span or span.endswith((".md", ".jsonl", ".json")):
            refs.append({"kind": "path", "ref": span})
    return refs


def rule_windows(rule_text, n=5):
    """Normalised verbatim n-word windows of the rule's
    first sentence."""
    first = re.split(r"(?<=[.!?])\s", rule_text or "", maxsplit=1)[0]
    toks = _norm(first).split()
    return {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def load_outcomes(path):
    """All outcome lines per entry (the lifecycle reads the
    whole register history, not latest-wins)."""
    out = {}
    p = Path(path)
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("entry"):
            out.setdefault(obj["entry"], []).append(obj)
    return out


def surface_lines(surface_paths):
    """[(path, lineno, raw line, normalised line)] for every
    surface file that exists."""
    rows = []
    for sp in surface_paths:
        p = Path(sp)
        if not p.is_file():
            continue
        for i, line in enumerate(
                p.read_text(encoding="utf-8").splitlines(), 1):
            rows.append((str(p), i, line, _norm(line)))
    return rows


def find_on_surface(rows, slug, windows):
    """First surface line carrying the rule slug verbatim or
    a content-bearing window of the rule text; evidence or
    None. A window counts only with at least two tokens of
    length >= 4, so a run of function words never promotes."""
    strong = {w for w in windows
              if sum(1 for t in w.split() if len(t) >= 4) >= 2}
    for path, lineno, raw, norm in rows:
        if slug and slug in raw:
            return {"surface": path, "line": lineno,
                    "matched": "rule slug", "quote": raw.strip()[:200]}
        for w in strong:
            if w in norm:
                return {"surface": path, "line": lineno,
                        "matched": "rule text window",
                        "quote": raw.strip()[:200]}
    return None


def _title_window_in(fragment_norm, title):
    """True when a 2-token window of the title (normalised,
    digit tokens excluded) appears in the fragment — the
    strict naming test for recurrence references: a bare
    date never names an entry, since entries share dates."""
    toks = [t for t in _norm(title).split() if not t.isdigit()]
    frag = " " + fragment_norm + " "
    return any(f" {toks[i]} {toks[i + 1]} " in frag
               for i in range(len(toks) - 1))


def build_report(ledger_text, outcomes, today, root,
                 extra_surfaces=(), script_texts=None):
    corr = _load("wiki_corrections",
                 Path(__file__).resolve().parent / "wiki_corrections.py")
    entries, classifications = corr.parse_ledger(ledger_text)
    bodies = parse_bodies(ledger_text)
    rep_counter = corr.build_report(ledger_text)
    root = Path(root)

    # Standing-rule surfaces: schema + other rules pages.
    default_surfaces = [root / "AGENTS.md"]
    rules_dir = root / "wiki" / "rules"
    if rules_dir.is_dir():
        default_surfaces += sorted(
            p for p in rules_dir.glob("*.md")
            if p.name != "corrections-ledger.md")
    surface_paths = default_surfaces + [Path(s) for s in extra_surfaces]
    surf_rows = surface_lines(surface_paths)

    # CI-verification surface: the scripts themselves.
    if script_texts is None:
        script_texts = {}
        sdir = root / "scripts"
        if sdir.is_dir():
            for p in sorted(sdir.glob("*.py")):
                if p.name == Path(__file__).name:
                    continue
                try:
                    script_texts[str(p)] = p.read_text(encoding="utf-8")
                except OSError:
                    pass

    keys = [f"{e['date']} — {e['title']}" for e in entries]
    info = {}
    for e, key in zip(entries, keys):
        cls = classifications.get(
            e["date"] + " " + corr._norm_title(e["title"]))
        body = bodies.get(key, {"bullets": {}, "lines": []})
        bullets = body["bullets"]
        rule_text = bullets.get("Standing rule", "")
        recorded = bullets.get("Recorded", "")
        refs = recorded_refs(recorded)
        info[key] = {
            "date": e["date"], "title": e["title"],
            "class": cls["class"] if cls else None,
            "kind": cls["kind"] if cls else None,
            "rule_raw": cls["rule"] if cls else None,
            "rule": base_slug(cls["rule"]) if cls else None,
            "rule_text": rule_text, "recorded": recorded,
            "refs": refs, "lines": body["lines"],
            "outcomes": outcomes.get(key, []),
        }

    # --- supersession: a record NAMES an entry as superseded
    superseded = {}   # key -> evidence
    for key in keys:
        src = info[key]
        for line in src["lines"]:
            if not SUPERSEDE_RE.search(line):
                continue
            nline = _norm(line)
            for other in keys:
                if other == key:
                    continue
                o = info[other]
                if o["date"] in line or _norm(o["title"])[:40] in nline:
                    superseded[other] = {
                        "basis": "supersession statement",
                        "ref": key, "quote": line.strip()[:200]}
    # a verdict-change entry overturning a named earlier rule
    for key in keys:
        src = info[key]
        if src["class"] != "verdict-change":
            continue
        text = " ".join(src["lines"])
        for other in keys:
            if other == key:
                continue
            o = info[other]
            if (o["rule"] and o["rule"] in text) or o["date"] in text:
                superseded.setdefault(other, {
                    "basis": "verdict-change entry",
                    "ref": key, "quote": f"verdict-change: {key}"})

    # --- later-entry invocation of an entry/rule (promotion
    # route a + reuse evidence + recurrence evidence)
    invokes = {k: [] for k in keys}      # key -> evidence list
    recurrence_of = {k: [] for k in keys}
    for i, key in enumerate(keys):
        src = info[key]
        for later in keys[i + 1:]:
            dst = info[later]
            ev = None
            frag = re.search(r"recurrence of\s+\"?([^)\"]+)\"?",
                             dst["title"], re.I)
            if frag and _norm(frag.group(1)) in _norm(src["title"]):
                ev = {"basis": "later entry title",
                      "ref": later,
                      "quote": dst["title"]}
            if ev is None and dst["rule_raw"] and \
                    "RECURRENCE of" in dst["rule_raw"]:
                frag = dst["rule_raw"].split("RECURRENCE of", 1)[1]
                if _title_window_in(_norm(frag), src["title"]):
                    ev = {"basis": "classification row recurrence",
                          "ref": later, "quote": dst["rule_raw"]}
            if ev is None and src["rule"]:
                for line in dst["lines"]:
                    if src["rule"] in line and re.search(
                            r"recurr|under that rule|recurrence",
                            line, re.I):
                        ev = {"basis": "later entry body",
                              "ref": later, "quote": line.strip()[:200]}
                        break
            if ev:
                invokes[key].append(ev)
                recurrence_of[key].append(ev)
            elif src["rule"] and dst["rule"] == src["rule"] \
                    and dst["date"] > src["date"]:
                recurrence_of[key].append({
                    "basis": "later entry under the same rule",
                    "ref": later, "quote": dst["rule_raw"] or dst["title"]})

    # --- gate recurrences per entry (rule-level): a later
    # entry explicitly recurring this one, a later entry
    # under the same rule, or an outcome line recurred=true.
    gate_recs = {}
    for key in keys:
        d = info[key]
        recs = list(recurrence_of[key])
        if any(o.get("recurred") is True for o in d["outcomes"]):
            recs.append({"basis": "outcome register", "ref": key,
                         "quote": "recurred=true"})
        gate_recs[key] = recs
    # Rules harden as a whole: a rule is blocking once any
    # recurrence of it is on record; originating feedback is
    # the first entry that set the rule + the recurrence
    # that hardened it.
    rules_gate = {}
    for key in keys:
        rule = info[key]["rule"]
        if not rule:
            continue
        g = rules_gate.setdefault(
            rule, {"posture": "warning", "entries": [],
                   "originating_feedback": None})
        g["entries"].append(key)
        if gate_recs[key] and g["posture"] != "blocking":
            g["posture"] = "blocking"
            g["originating_feedback"] = {
                "first_ruled": g["entries"][0],
                "hardened_by": gate_recs[key][0]["ref"]}

    rows = []
    for key in keys:
        d = info[key]
        windows = rule_windows(d["rule_text"])
        promotion = list(invokes[key])
        hit = find_on_surface(surf_rows, d["rule"], windows)
        if hit:
            promotion.append({"basis": "standing-rule surface",
                              **hit})
        landed = bool(d["refs"])
        # reproduced: the entry's own record names a tool run
        # (a backticked scripts/*.py path) with a stated result
        body_text = " ".join(d["lines"])
        tool_named = any(
            span.strip().startswith("scripts/")
            and span.strip().endswith(".py")
            for span in BACKTICK_RE.findall(body_text))
        reproduced = bool(tool_named
                          and RESULT_WORD_RE.search(body_text))
        # ci-verified: a script carries the slug / rule window
        ci_hit = None
        for path, text in script_texts.items():
            ntext = _norm(text)
            if (d["rule"] and d["rule"] in text) or \
                    any(w in ntext for w in windows):
                ci_hit = path
                break
        oc = d["outcomes"]
        retrieved = any(o.get("retrieved") is True for o in oc)
        heeded = any(o.get("heeded") is True for o in oc)
        recurred_oc = any(o.get("recurred") is True for o in oc)
        rungs = {
            "landed": landed,
            "reproduced": reproduced,
            "ci-verified": bool(ci_hit),
            "reuse-observed": bool(invokes[key]) or retrieved,
            "measured-heeded": heeded,
        }
        if all(rungs.values()):
            grade = "field-proven"
        else:
            grade = "recorded"
            for rung in RUNGS:
                if rungs[rung]:
                    grade = rung
        # state by precedence
        if key in superseded:
            state, state_ev = "superseded-by-later-entry", [superseded[key]]
        elif promotion:
            state, state_ev = "promoted-to-rule", promotion
        elif landed:
            state = "acted-on"
            state_ev = [{"basis": "Recorded line landing references",
                         "ref": r["ref"]} for r in d["refs"]]
        elif d["rule_text"] or d["class"]:
            state, state_ev = "open", []
        else:
            state = "unstated"
            state_ev = [{"basis": "no Standing rule bullet and no "
                                  "classification row — state not "
                                  "grounded in the record"}]
        # gate posture: the posture of this entry's rule as
        # of today (warning unless the rule has recurred)
        recs = gate_recs[key]
        if d["rule"] and d["rule"] in rules_gate:
            posture = rules_gate[d["rule"]]["posture"]
        else:
            posture = "blocking" if recs else "warning"
        if recs:
            basis = "this entry's rule recurred after it"
        elif posture == "blocking":
            basis = "rule hardened by a recurrence on record"
        else:
            basis = "first ruling; no recurrence on record"
        rows.append({
            "entry": key, "date": d["date"], "title": d["title"],
            "class": d["class"], "kind": d["kind"],
            "rule": d["rule"], "rule_raw": d["rule_raw"],
            "state": state, "state_evidence": state_ev,
            "gate": {"posture": posture,
                     "basis": ("rule recurred after this entry"
                               if recs else "first ruling; no "
                               "recurrence on record"),
                     "recurrence_evidence": recs},
            "evidence_rungs": rungs,
            "grade": grade,
            "grade_evidence": {
                "landed_refs": [r["ref"] for r in d["refs"]],
                "ci_verified_in": ci_hit,
                "outcome_lines": len(oc)},
            "recorded_refs": d["refs"],
        })

    # --- trends
    by_month = {}
    for r in rows:
        month = r["date"][:7]
        slot = by_month.setdefault(month, {"entries": 0, "by_kind": {}})
        slot["entries"] += 1
        if r["kind"]:
            slot["by_kind"][r["kind"]] = slot["by_kind"].get(r["kind"], 0) + 1
    by_week = Counter()
    for r in rows:
        y, w, _ = date.fromisoformat(r["date"]).isocalendar()
        by_week[f"{y}-W{w:02d}"] += 1
    cumulative = {}
    running = Counter()
    for r in rows:
        if r["kind"]:
            running[r["kind"]] += 1
            cumulative.setdefault(r["kind"], []).append(
                [r["date"], running[r["kind"]]])
    by_rule_entries = {}
    for r in rows:
        if r["rule"]:
            by_rule_entries.setdefault(r["rule"], []).append(r["entry"])
    repeat_rules = {k: v for k, v in by_rule_entries.items()
                    if len(v) >= 2}
    dates = [r["date"] for r in rows]
    last7 = sum(1 for dt in dates
                if 0 <= (today - date.fromisoformat(dt)).days < 7)
    trends = {
        "span": {"first": min(dates) if dates else None,
                 "last": max(dates) if dates else None,
                 "days_since_latest":
                     (today - date.fromisoformat(max(dates))).days
                     if dates else None},
        "by_month": dict(sorted(by_month.items())),
        "by_week": dict(sorted(by_week.items())),
        "cumulative_by_kind": cumulative,
        "repeat_offence_rules": repeat_rules,
        "repeated_since_ruled": rep_counter["repeated_since_ruled"],
        "velocity": {"entries_last_7_days_as_of_today": last7,
                     "entries_total": len(rows)},
    }

    # --- promotion candidates: landed, not promoted (and
    # its rule not promoted via any entry), not superseded,
    # and the rule has not recurred since it was set.
    promoted_rules = {r["rule"] for r in rows
                      if r["state"] == "promoted-to-rule" and r["rule"]}
    candidates = []
    for r in rows:
        if r["state"] != "acted-on":
            continue
        if r["rule"] and r["rule"] in promoted_rules:
            continue
        if r["gate"]["recurrence_evidence"]:
            continue
        if not info[r["entry"]]["rule_text"]:
            continue
        candidates.append({
            "entry": r["entry"], "rule": r["rule"],
            "grade": r["grade"],
            "held_since": r["date"],
            "landed_refs": [x["ref"] for x in r["recorded_refs"]],
            "note": "candidate only — promotion into the schema "
                    "or a rules page is Mehmed's/owner's act"})

    return {
        "tool": "scripts/wiki_corrections_lifecycle.py",
        "kind": "corrections-lifecycle-report",
        "as_of": today.isoformat(),
        "ledger": LEDGER_REL,
        "ledger_sha256": hashlib.sha256(
            ledger_text.encode("utf-8")).hexdigest(),
        "surfaces_searched": [str(p) for p in surface_paths],
        "entries_total": len(rows),
        "by_state": {s: sum(1 for r in rows if r["state"] == s)
                     for s in STATES},
        "by_grade": {g: sum(1 for r in rows if r["grade"] == g)
                     for g in GRADE_ORDER},
        "entries": rows,
        "rules_gate": rules_gate,
        "trends": trends,
        "promotion_candidates": candidates,
        "unclassified": [r["entry"] for r in rows if not r["class"]],
        "orphan_classification_rows":
            rep_counter["orphan_classification_rows"],
    }


def render_text(rep):
    lines = ["Corrections ledger — lifecycle, trends, promotion ladder",
             f"As of {rep['as_of']} · entries: {rep['entries_total']} · "
             f"ledger sha256 {rep['ledger_sha256'][:12]}…", "",
             "Lifecycle states:"]
    for s in STATES:
        lines.append(f"  {s:<28} {rep['by_state'][s]}")
    lines += ["", "Evidence grades:"]
    for g in GRADE_ORDER:
        lines.append(f"  {g:<18} {rep['by_grade'][g]}")
    lines += ["", "Entries:"]
    for r in rep["entries"]:
        lines.append(f"  - {r['entry']}")
        lines.append(f"      state {r['state']} · grade {r['grade']} · "
                     f"gate {r['gate']['posture']} · "
                     f"rule {r['rule'] or '(unclassified)'}")
        for ev in r["state_evidence"]:
            lines.append(f"      evidence: {ev.get('basis')} — "
                         f"{ev.get('ref') or ev.get('surface') or ''}")
    lines += ["", "Rules at blocking gate (warning hardened by "
                  "recurrence):"]
    blocking = {k: v for k, v in rep["rules_gate"].items()
                if v["posture"] == "blocking"}
    if blocking:
        for rule, g in blocking.items():
            of = g["originating_feedback"] or {}
            lines.append(f"  - {rule}: first ruled {of.get('first_ruled')}"
                         f"; hardened by {of.get('hardened_by')}")
    else:
        lines.append("  (none — every rule still at warning)")
    lines += ["", "Repeat-offence patterns:"]
    if rep["trends"]["repeat_offence_rules"]:
        for rule, es in rep["trends"]["repeat_offence_rules"].items():
            lines.append(f"  - rule {rule}: {len(es)} entries")
            for e in es:
                lines.append(f"      {e}")
    else:
        lines.append("  (no standing rule carries two entries)")
    for r in rep["trends"]["repeated_since_ruled"]:
        lines.append(f"  - kind {r['kind']} recurred: {r['date']} — "
                     f"{r['title']} (first ruled {r['first_ruled']['date']})")
    lines += ["", "Promotion candidates (report only):"]
    if rep["promotion_candidates"]:
        for c in rep["promotion_candidates"]:
            lines.append(f"  - {c['entry']} (rule {c['rule']}, "
                         f"grade {c['grade']}, held since {c['held_since']})")
    else:
        lines.append("  (none)")
    if rep["unclassified"]:
        lines += ["", "UNCLASSIFIED entries (no classification row):"]
        for e in rep["unclassified"]:
            lines.append(f"  - {e}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Corrections-ledger lifecycle, trends and "
                    "promotion ladder (wave 5).")
    sub = ap.add_subparsers(dest="command")
    pr = sub.add_parser("report")
    pr.add_argument("--json", action="store_true")
    pr.add_argument("--today", default=None,
                    help="date treated as today (default: the real "
                         "today); trends are computed as of it")
    pr.add_argument("--ledger", default=None)
    pr.add_argument("--register", default=None)
    pr.add_argument("--root", default=None)
    pr.add_argument("--surface", action="append", default=[],
                    help="extra standing-rule surface file "
                         "(repeatable)")
    pr.add_argument("--out", default=None,
                    help="also write the JSON artefact here")
    args = ap.parse_args(argv)
    if (args.command or "report") != "report":
        return 2
    root = Path(args.root).resolve() if args.root else ROOT
    ledger_path = Path(args.ledger) if args.ledger else root / LEDGER_REL
    register_path = (Path(args.register) if args.register
                     else root / REGISTER_REL)
    if not ledger_path.is_file():
        print(f"wiki_corrections_lifecycle: no ledger at {ledger_path}",
              file=sys.stderr)
        return 2
    today = (date.fromisoformat(args.today) if args.today
             else date.today())
    ledger_text = ledger_path.read_text(encoding="utf-8")
    rep = build_report(ledger_text, load_outcomes(register_path),
                       today, root, extra_surfaces=args.surface)
    if args.out:
        Path(args.out).write_text(
            json.dumps(rep, indent=2, ensure_ascii=False,
                       sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False,
                         sort_keys=True))
    else:
        print(render_text(rep), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
