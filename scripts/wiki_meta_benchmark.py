#!/usr/bin/env python3
"""Meta-benchmark + preregistered criteria (W3, 2026-10-22).

The bakeoff harness (scripts/wiki_bakeoff.py) measures
configurations and publishes figures a verifier can recompute.
This layer sits ON TOP of it — it never re-measures and never
edits a bakeoff row. It answers the next question: judged
against criteria fixed in a register, which configurations may
be ADOPTED, and is the judging itself sound?

Three registers, all append-only JSONL in the harness's
hash-chained style (prev_entry_sha256 -> entry_sha256 over the
canonical entry):

  evaluation/bakeoff-ledger.jsonl    (the harness's — READ-ONLY
                                      here; figures + row
                                      identities judged against)
  evaluation/bakeoff-criteria.jsonl  (this tool's: criteria
                                      sets + freeze markers)
  evaluation/bakeoff-verdicts.jsonl  (this tool's: one verdict
                                      entry per judged row)

Preregistration discipline, enforced by the tool, not by
convention:

  - A criteria set is a named, VERSIONED record: each criterion
    names the instrument, the metric (a path into a bakeoff
    ledger entry's summaries), the operator + threshold, the
    configuration class it binds, a rationale, and the standing
    rule it codifies, cited where that rule already lives.
  - A set must be FROZEN before it may judge: freezing appends
    a marker binding the sha256 of the criteria exactly as
    recorded. Judging an unfrozen set is refused.
  - A frozen version is immutable: re-registering the same
    set+version is refused, and any amendment mints a NEW
    version (with `amends` naming the old). Old versions and
    their verdicts never change.
  - Registration is a recorded act: `registered_on` /
    `registered_by` / `registration_timing` are caller-supplied
    and stored on the set's face. A set registered AFTER the
    runs it first judges says so — tonight's v1 does (below).

Judging:

  - Before judging, the judge runs the harness's own verifier
    (wiki_bakeoff.verify_ledger) over the bakeoff ledger. A
    verdict records, per row, whether that row still
    recomputes from its run file; a row implicated by any
    verifier finding is judged with row_recomputes = false and
    can never be adoptable. A verdict is a claim about a
    recomputable row, never about a number taken on trust.
  - Every criterion result carries the MEASURED value beside
    the operator + threshold — no bare verdicts. Criteria
    whose configuration class does not cover a row record
    `not-applicable` with the reason (never a silent pass).
  - adoptable = (row recomputes) AND (at least one criterion
    applied) AND (every applied criterion passed).
  - Judging is deterministic: same ledger + same criteria
    version + same judged_on -> byte-identical verdict
    entries (chain fields aside). Re-judging a row already
    judged under the same frozen criteria is a no-op.

The meta view (`meta`) judges the judges: per criterion, how
many judged rows passed / failed / were not applicable, and
whether the criterion DISCRIMINATES — a criterion every
applicable row passes, or every applicable row fails, carries
no information and is named as such; and coverage — which
ledger rows no criteria version has judged.

Tonight's first set, `house-adoption` v1, codifies standing
rules that PREDATE the eight bakeoff rows it first judges —
each criterion cites its rule — and its registration_timing
states plainly that the criteria TEXT was registered after
those runs (2026-10-22, the runs recorded 06:09-06:48 UTC).
That is the honest form of preregistration available tonight;
future sets for future runs can be registered before the runs.

Patterns: preregistered, independent judging of benchmark
claims (build-list sources: chunxiaoxx/nautilus-compass,
wontopos/glasshouse, techtheist/knowledgedrift — ideas only;
this is a clean re-implementation in the house register
style, no upstream code taken).

Usage:
  python3 scripts/wiki_meta_benchmark.py register-v1 \
      --registered-on YYYY-MM-DD [--registered-by WHO]
  python3 scripts/wiki_meta_benchmark.py register \
      --set NAME --version N --registered-on DATE \
      --criteria FILE [--registered-by WHO] \
      [--timing TEXT] [--amends N]
  python3 scripts/wiki_meta_benchmark.py freeze \
      --set NAME --version N --frozen-on DATE
  python3 scripts/wiki_meta_benchmark.py judge \
      --set NAME --version N --judged-on DATE
  python3 scripts/wiki_meta_benchmark.py meta \
      [--set NAME --version N]
  python3 scripts/wiki_meta_benchmark.py verify
  python3 scripts/wiki_meta_benchmark.py list
  (all take [--ledger FILE] [--criteria FILE]
   [--verdicts FILE] as applicable)

Exit codes: 0 ok · 1 verify failed · 2 usage / refusal.
Stdlib only, no network.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL = ROOT / "evaluation"
LEDGER = EVAL / "bakeoff-ledger.jsonl"
CRITERIA = EVAL / "bakeoff-criteria.jsonl"
VERDICTS = EVAL / "bakeoff-verdicts.jsonl"

OPS = (">=", ">", "<=", "<", "==", "not-null")
CLASSES = ("all-configurations", "hybrid-family")


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bakeoff = _load("wiki_bakeoff", "wiki_bakeoff.py")
canonical = bakeoff.canonical
sha256_text = bakeoff.sha256_text


class Refusal(Exception):
    """A named refusal: the tool will not do this, on the
    record (exit 2), never a silent pass."""


# ---------------------------------------------------------------------------
# JSONL registers — append-only, hash-chained (the harness style)
# ---------------------------------------------------------------------------

def load_jsonl(path):
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def _append(path, entry):
    path = Path(path)
    entries = load_jsonl(path)
    entry["prev_entry_sha256"] = (
        entries[-1].get("entry_sha256") if entries else None)
    entry["entry_sha256"] = sha256_text(canonical(
        {k: v for k, v in entry.items() if k != "entry_sha256"}))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def _chain_findings(entries, label):
    findings = []
    prev = None
    for i, entry in enumerate(entries):
        expect = sha256_text(canonical(
            {k: v for k, v in entry.items()
             if k != "entry_sha256"}))
        if entry.get("entry_sha256") != expect:
            findings.append(
                f"{label} line {i + 1}: entry_sha256 mismatch — "
                "the line was altered")
        if entry.get("prev_entry_sha256") != prev:
            findings.append(
                f"{label} line {i + 1}: prev_entry_sha256 does "
                "not chain to the previous entry")
        prev = entry.get("entry_sha256")
    return findings


def criteria_sha256(criteria):
    return sha256_text(canonical(criteria))


# ---------------------------------------------------------------------------
# Criteria register
# ---------------------------------------------------------------------------

def validate_criteria(criteria):
    if not isinstance(criteria, list) or not criteria:
        raise Refusal("criteria must be a non-empty list")
    seen = set()
    for c in criteria:
        for key in ("id", "instrument", "metric", "op",
                    "applies_to", "rationale", "rule_source"):
            if key not in c:
                raise Refusal(f"criterion missing {key!r}: {c}")
        if c["id"] in seen:
            raise Refusal(f"duplicate criterion id {c['id']!r}")
        seen.add(c["id"])
        if c["op"] not in OPS:
            raise Refusal(
                f"criterion {c['id']}: op {c['op']!r} not in "
                f"{OPS}")
        if c["applies_to"] not in CLASSES:
            raise Refusal(
                f"criterion {c['id']}: applies_to "
                f"{c['applies_to']!r} not in {CLASSES}")
        if c["op"] != "not-null" and not isinstance(
                c.get("threshold"), (int, float)):
            raise Refusal(
                f"criterion {c['id']}: op {c['op']} needs a "
                "numeric threshold")
    return criteria


def find_set(entries, name, version):
    for e in entries:
        if (e.get("kind") == "criteria-set"
                and e.get("set") == name
                and e.get("version") == version):
            return e
    return None


def find_freeze(entries, name, version):
    for e in entries:
        if (e.get("kind") == "criteria-freeze"
                and e.get("set") == name
                and e.get("version") == version):
            return e
    return None


def register_set(criteria_path, name, version, criteria,
                 registered_on, registered_by,
                 registration_timing, amends=None):
    validate_criteria(criteria)
    entries = load_jsonl(criteria_path)
    if find_set(entries, name, version) is not None:
        raise Refusal(
            f"criteria set {name} v{version} is already "
            "registered — versions are immutable; an amendment "
            "mints a new version")
    if amends is not None and find_set(
            entries, name, amends) is None:
        raise Refusal(
            f"cannot amend {name} v{amends}: no such version "
            "is registered")
    entry = {
        "kind": "criteria-set",
        "set": name,
        "version": version,
        "status": "registered",
        "registered_on": registered_on,
        "registered_by": registered_by,
        "registration_timing": registration_timing,
        "amends": amends,
        "criteria": criteria,
        "criteria_sha256": criteria_sha256(criteria),
    }
    return _append(criteria_path, entry)


def freeze_set(criteria_path, name, version, frozen_on):
    entries = load_jsonl(criteria_path)
    s = find_set(entries, name, version)
    if s is None:
        raise Refusal(
            f"no criteria set {name} v{version} is registered")
    if find_freeze(entries, name, version) is not None:
        raise Refusal(
            f"criteria set {name} v{version} is already frozen")
    entry = {
        "kind": "criteria-freeze",
        "set": name,
        "version": version,
        "frozen_on": frozen_on,
        "criteria_entry_sha256": s["entry_sha256"],
        "criteria_sha256": s["criteria_sha256"],
        "note": "frozen on the landing of this version's first "
                "judged run; from here the set is immutable — "
                "any change mints a new version",
    }
    return _append(criteria_path, entry)


# ---------------------------------------------------------------------------
# Metrics — paths into a bakeoff ledger entry's summaries
# ---------------------------------------------------------------------------

def resolve_metric(entry, metric):
    """(present, value). Most metrics are dot-paths over the
    ledger entry; `summaries.battery.passed_fraction` is the
    one derived metric (passed / cases), defined here so
    criteria can state the battery as a fraction of its own
    cases. A path that exists with value None returns
    (True, None) — present-but-null is a measurement (CQ-001
    not retrievable), not a missing path."""
    if metric == "summaries.battery.passed_fraction":
        bat = entry.get("summaries", {}).get("battery")
        if bat is None:
            return False, None
        if not bat.get("applicable") or not bat.get("cases"):
            return True, None
        return True, round(bat["passed"] / bat["cases"], 4)
    node = entry
    for part in metric.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def config_classes(entry):
    classes = {"all-configurations"}
    spec = entry.get("config", {}).get("spec", {})
    if spec.get("engine") == "hybrid":
        classes.add("hybrid-family")
    return classes


def judge_criterion(entry, criterion, classes):
    cid = criterion["id"]
    base = {"criterion": cid, "op": criterion["op"],
            "threshold": criterion.get("threshold")}
    if criterion["applies_to"] not in classes:
        return {**base, "status": "not-applicable",
                "measured": None,
                "detail": f"criterion binds class "
                          f"{criterion['applies_to']!r}; this "
                          f"configuration's classes: "
                          f"{', '.join(sorted(classes))}"}
    present, value = resolve_metric(entry, criterion["metric"])
    if not present:
        return {**base, "status": "error", "measured": None,
                "detail": f"metric path {criterion['metric']} "
                          "did not resolve on this ledger row"}
    if criterion["op"] == "not-null":
        ok = value is not None
        return {**base, "status": "pass" if ok else "fail",
                "measured": value,
                "detail": ("must-cite rank present "
                           f"({value})" if ok else
                           "value is null — not retrievable")}
    if value is None or not isinstance(value, (int, float)):
        return {**base, "status": "error", "measured": value,
                "detail": f"metric {criterion['metric']} "
                          f"resolved to {value!r}, not a number"}
    t = criterion["threshold"]
    ok = {">=": value >= t, ">": value > t, "<=": value <= t,
          "<": value < t, "==": value == t}[criterion["op"]]
    return {**base, "status": "pass" if ok else "fail",
            "measured": value,
            "detail": f"measured {value} vs "
                      f"{criterion['op']} {t}"}


# ---------------------------------------------------------------------------
# Judging
# ---------------------------------------------------------------------------

def _implicated_rows(findings, entries):
    """Map harness-verifier findings to the ledger rows they
    implicate (by config name or by line). A row no finding
    implicates still recomputes."""
    bad = set()
    for f in findings:
        for i, e in enumerate(entries):
            name = e.get("config", {}).get("name")
            if (f"({name})" in f or f.startswith(f"{name}:")
                    or f"{name}/" in f
                    or f.startswith(f"line {i + 1}:")):
                bad.add(i)
    return bad


def judge(ledger_path, criteria_path, verdicts_path, set_name,
          version, judged_on):
    register = load_jsonl(criteria_path)
    s = find_set(register, set_name, version)
    if s is None:
        raise Refusal(
            f"no criteria set {set_name} v{version} is "
            "registered")
    freeze = find_freeze(register, set_name, version)
    if freeze is None:
        raise Refusal(
            f"criteria set {set_name} v{version} is not "
            "frozen — an unfrozen set may not judge (freeze "
            "it first; freezing is what makes the criteria "
            "preregistered for the runs they judge)")
    if freeze["criteria_sha256"] != criteria_sha256(s["criteria"]):
        raise Refusal(
            f"criteria set {set_name} v{version}: the frozen "
            "criteria hash does not match the recorded "
            "criteria — the register line was altered; "
            "refusing to judge")
    if freeze["criteria_entry_sha256"] != s["entry_sha256"]:
        raise Refusal(
            f"criteria set {set_name} v{version}: the freeze "
            "marker does not bind this set entry")
    ledger_entries = load_jsonl(ledger_path)
    if not ledger_entries:
        raise Refusal(f"bakeoff ledger missing or empty: "
                      f"{ledger_path}")
    _ok, findings = bakeoff.verify_ledger(ledger_path)
    bad = _implicated_rows(findings, ledger_entries)
    implicated = {i: [f for f in findings
                      if i in _implicated_rows([f],
                                               ledger_entries)]
                  for i in bad}
    existing = load_jsonl(verdicts_path)
    judged_keys = {
        (v["row"]["row_identity"],
         v["criteria"]["entry_sha256"])
        for v in existing if v.get("kind") == "config-verdict"}
    appended, skipped = [], []
    for i, entry in enumerate(ledger_entries):
        name = entry.get("config", {}).get("name")
        key = (entry.get("row_identity"), s["entry_sha256"])
        if key in judged_keys:
            skipped.append(name)
            continue
        classes = config_classes(entry)
        results = [judge_criterion(entry, c, classes)
                   for c in s["criteria"]]
        applied = [r for r in results
                   if r["status"] in ("pass", "fail", "error")]
        recomputes = i not in bad
        adoptable = bool(
            recomputes and applied
            and all(r["status"] == "pass" for r in applied))
        verdict = {
            "kind": "config-verdict",
            "version": 1,
            "judged_on": judged_on,
            "criteria": {
                "set": set_name, "version": version,
                "entry_sha256": s["entry_sha256"],
                "freeze_entry_sha256": freeze["entry_sha256"],
                "criteria_sha256": s["criteria_sha256"],
            },
            "row": {
                "config": name,
                "row_identity": entry.get("row_identity"),
                "bakeoff_entry_sha256": entry.get(
                    "entry_sha256"),
                "bakeoff_line": i + 1,
            },
            "row_recomputes": recomputes,
            "recompute_findings": implicated.get(i, []),
            "results": results,
            "adoptable": adoptable,
        }
        appended.append(_append(verdicts_path, verdict))
    return {"judged": [v["row"]["config"] for v in appended],
            "skipped_already_judged": skipped,
            "verdicts": appended}


# ---------------------------------------------------------------------------
# Meta view — judging the judges
# ---------------------------------------------------------------------------

def meta_view(ledger_path, criteria_path, verdicts_path,
              set_name=None, version=None):
    register = load_jsonl(criteria_path)
    ledger_entries = load_jsonl(ledger_path)
    verdicts = [v for v in load_jsonl(verdicts_path)
                if v.get("kind") == "config-verdict"]
    groups = {}
    for v in verdicts:
        key = (v["criteria"]["set"], v["criteria"]["version"])
        if set_name is not None and key != (set_name, version):
            continue
        groups.setdefault(key, []).append(v)
    out_groups = []
    for (name, ver), vs in sorted(groups.items()):
        s = find_set(register, name, ver)
        crit_stats = {}
        if s is not None:
            for c in s["criteria"]:
                rs = [r for v in vs for r in v["results"]
                      if r["criterion"] == c["id"]]
                n_pass = sum(1 for r in rs
                             if r["status"] == "pass")
                n_fail = sum(1 for r in rs
                             if r["status"] == "fail")
                n_na = sum(1 for r in rs
                           if r["status"] == "not-applicable")
                n_err = sum(1 for r in rs
                            if r["status"] == "error")
                if n_pass + n_fail == 0:
                    verdict_disc = (
                        "no applicable rows judged — carries "
                        "no information here")
                elif n_fail == 0:
                    verdict_disc = (
                        "NON-DISCRIMINATING — every applicable "
                        "row passes; the criterion currently "
                        "carries no information")
                elif n_pass == 0:
                    verdict_disc = (
                        "NON-DISCRIMINATING — every applicable "
                        "row fails; the criterion currently "
                        "carries no information")
                else:
                    verdict_disc = "discriminates"
                crit_stats[c["id"]] = {
                    "pass": n_pass, "fail": n_fail,
                    "not_applicable": n_na, "error": n_err,
                    "discrimination": verdict_disc}
        out_groups.append({
            "criteria": {"set": name, "version": ver},
            "rows_judged": len(vs),
            "adoptable": [v["row"]["config"] for v in vs
                          if v["adoptable"]],
            "not_adoptable": [v["row"]["config"] for v in vs
                              if not v["adoptable"]],
            "criteria_stats": crit_stats})
    judged_any = {v["row"]["row_identity"] for v in verdicts}
    unjudged = [{"config": e.get("config", {}).get("name"),
                 "row_identity": e.get("row_identity")}
                for e in ledger_entries
                if e.get("row_identity") not in judged_any]
    return {"groups": out_groups,
            "ledger_rows": len(ledger_entries),
            "rows_judged_any_version": len(
                judged_any & {e.get("row_identity")
                              for e in ledger_entries}),
            "unjudged_rows": unjudged}


# ---------------------------------------------------------------------------
# Verify — both registers, verdicts re-derived from the ledger
# ---------------------------------------------------------------------------

def verify_registers(criteria_path, verdicts_path, ledger_path):
    findings = []
    register = load_jsonl(criteria_path)
    verdicts = load_jsonl(verdicts_path)
    ledger_entries = load_jsonl(ledger_path)
    findings += _chain_findings(register, "criteria")
    findings += _chain_findings(verdicts, "verdicts")
    seen = set()
    for e in register:
        if e.get("kind") == "criteria-set":
            key = (e["set"], e["version"])
            if key in seen:
                findings.append(
                    f"criteria: set {e['set']} v{e['version']} "
                    "registered twice — versions are immutable")
            seen.add(key)
            if e.get("criteria_sha256") != criteria_sha256(
                    e.get("criteria", [])):
                findings.append(
                    f"criteria: set {e['set']} v{e['version']} "
                    "criteria_sha256 does not match its criteria")
        elif e.get("kind") == "criteria-freeze":
            s = find_set(register, e["set"], e["version"])
            if s is None:
                findings.append(
                    f"criteria: freeze of unknown set "
                    f"{e['set']} v{e['version']}")
            elif (e.get("criteria_sha256")
                    != s.get("criteria_sha256")
                    or e.get("criteria_entry_sha256")
                    != s.get("entry_sha256")):
                findings.append(
                    f"criteria: freeze of {e['set']} "
                    f"v{e['version']} does not bind the set "
                    "entry it names")
    by_identity = {e.get("row_identity"): e
                   for e in ledger_entries}
    by_sha = {e.get("entry_sha256"): e for e in ledger_entries}
    for v in verdicts:
        if v.get("kind") != "config-verdict":
            continue
        name = v.get("row", {}).get("config")
        s = None
        for e in register:
            if e.get("entry_sha256") == v.get(
                    "criteria", {}).get("entry_sha256"):
                s = e
        if s is None:
            findings.append(
                f"verdicts: {name}: criteria entry_sha256 "
                "resolves to no registered set")
            continue
        row = by_identity.get(v["row"].get("row_identity"))
        if row is None:
            findings.append(
                f"verdicts: {name}: row_identity not in the "
                "bakeoff ledger")
            continue
        if by_sha.get(v["row"].get(
                "bakeoff_entry_sha256")) is not row:
            findings.append(
                f"verdicts: {name}: bakeoff_entry_sha256 "
                "does not name this ledger row — the row the "
                "verdict judged is not the row on record")
            continue
        classes = config_classes(row)
        expect = [judge_criterion(row, c, classes)
                  for c in s["criteria"]]
        if expect != v.get("results"):
            findings.append(
                f"verdicts: {name}: recorded results do not "
                "re-derive from the ledger row + criteria")
        applied = [r for r in expect
                   if r["status"] in ("pass", "fail", "error")]
        expect_adoptable = bool(
            v.get("row_recomputes") and applied
            and all(r["status"] == "pass" for r in applied))
        if expect_adoptable != v.get("adoptable"):
            findings.append(
                f"verdicts: {name}: adoptable does not "
                "re-derive from the recorded results")
    return not findings, findings


# ---------------------------------------------------------------------------
# House-adoption v1 — the standing rules, codified
# ---------------------------------------------------------------------------

HOUSE_ADOPTION_V1 = [
    {
        "id": "golden-full-coverage",
        "instrument": "golden — wiki_benchmark.score_question "
                      "over evaluation/golden-questions.jsonl, "
                      "as summarised in the bakeoff ledger",
        "metric": "summaries.golden.aggregates."
                  "citation_coverage.@10",
        "op": ">=",
        "threshold": 1.0,
        "applies_to": "all-configurations",
        "rationale": "An adoption candidate must place the "
                     "must-cite page of every golden question "
                     "in its top 10. The golden set is the "
                     "owner's fixed acceptance set — fifteen "
                     "questions, never grown to fit a result.",
        "rule_source": "Owner decision 2026-10-14: the golden "
                       "set stays 15 (evaluation/"
                       "extended-baseline-report-2026-10-20.md; "
                       "wiki/log.md). The serving "
                       "configuration's standing figure is full "
                       "coverage — the harness's MemScore "
                       "accuracy IS golden coverage@10 "
                       "(scripts/wiki_bakeoff.py).",
    },
    {
        "id": "battery-full-pass",
        "instrument": "abstention battery — "
                      "wiki_abstention_check case runners over "
                      "evaluation/abstention-battery.jsonl at "
                      "the tau recorded in the ledger row",
        "metric": "summaries.battery.passed_fraction",
        "op": ">=",
        "threshold": 1.0,
        "applies_to": "hybrid-family",
        "rationale": "The abstention battery is a pinned "
                     "regression property: a configuration "
                     "that answers when it must abstain, or "
                     "abstains when it must answer, is not "
                     "adoptable whatever its ranking scores. "
                     "The battery pins the hybrid pipeline "
                     "(scripts/wiki_bakeoff.py), so the "
                     "criterion binds the hybrid family; "
                     "other families record it not-applicable "
                     "— never as a pass.",
        "rule_source": "AGENTS.md, 'Abstention and conflict "
                       "regression gate (est. 2026-10-20)': a "
                       "red battery blocks the change, and the "
                       "abstention threshold is never re-tuned "
                       "in the same change that fails it. "
                       "tau = 1.23 stands in evaluation/"
                       "extended-baseline.json "
                       "(abstain_threshold) and is read into "
                       "every battery row.",
    },
    {
        "id": "supersession-floor",
        "instrument": "supersession (directional) slice — "
                      "wiki_eval_extended.score_answerable "
                      "over the directional slice of "
                      "evaluation/extended-questions.jsonl",
        "metric": "summaries.supersession.aggregates."
                  "citation_coverage.@10",
        "op": ">=",
        "threshold": 0.75,
        "applies_to": "all-configurations",
        "rationale": "Truth-aware retrieval is the wiki's "
                     "sharpest measured gap turned gain: the "
                     "directional slice sat at 0.50 before the "
                     "governance layer and stands at 0.75 "
                     "governed. No configuration may be "
                     "adopted that hands that gain back.",
        "rule_source": "Pre-governance figure 0.50: the "
                       "Round 2 directional-slice measurement "
                       "(wiki/syntheses/"
                       "marathon-round-2-2026-10-20.md). "
                       "Governed figure 0.75: W1.5 truth-aware "
                       "retrieval, confirmed by the bakeoff "
                       "harness — governance-off returns the "
                       "slice to exactly 0.50 (build note "
                       "benchmark-harness-bakeoff.md).",
    },
    {
        "id": "cq001-must-cite-retrievable",
        "instrument": "conflict slice — wiki_benchmark over "
                      "evaluation/conflict-questions.jsonl "
                      "(case CQ-001)",
        "metric": "summaries.conflict.cq001_must_cite_rank",
        "op": "not-null",
        "threshold": None,
        "applies_to": "all-configurations",
        "rationale": "CQ-001 is the pinned conflict case "
                     "(Identify 1 / Solve 0): its must-cite "
                     "page — the record that corrects the "
                     "claim — must at least be retrievable. A "
                     "configuration under which the "
                     "correcting record vanishes from the "
                     "ranking fails the conflict discipline "
                     "even when its coverage averages look "
                     "fine. Rank quality beyond retrievability "
                     "is reported by the instruments, not "
                     "gated here.",
        "rule_source": "AGENTS.md, 'Abstention and conflict "
                       "regression gate (est. 2026-10-20)': "
                       "the conflict slice is scored Identify "
                       "/ Solve / Escalate and a slice "
                       "regression not explained on the record "
                       "blocks the change. CQ-001's must-cite "
                       "was not retrievable pre-governance and "
                       "stands at rank 2 governed (W1.5; "
                       "bakeoff ledger).",
    },
]

V1_TIMING = (
    "Registered 2026-10-22, AFTER the eight bakeoff ledger "
    "rows it first judges (recorded 2026-10-22T06:09-06:48Z). "
    "This set codifies standing rules that predate those runs "
    "— each criterion cites the rule it codifies — and does "
    "not pretend the criteria text was written before the "
    "harness existed. Future sets for future runs can and "
    "should be registered before the runs they judge; "
    "amendments to this set mint new versions.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Meta-benchmark: preregistered criteria "
                    "+ judging over the bakeoff ledger.")
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--criteria", default=str(CRITERIA))
    ap.add_argument("--verdicts", default=str(VERDICTS))
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("register-v1", help="seed house-"
                       "adoption v1 (the standing rules)")
    p.add_argument("--registered-on", required=True)
    p.add_argument("--registered-by",
                   default="mehmed (W3 meta-benchmark lane, "
                           "2026-10-22)")

    p = sub.add_parser("register", help="register a criteria "
                       "set version from a criteria JSON file")
    p.add_argument("--set", required=True)
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--registered-on", required=True)
    p.add_argument("--registered-by", default="mehmed")
    p.add_argument("--timing", default="")
    p.add_argument("--amends", type=int)
    p.add_argument("--criteria", dest="criteria_file",
                   required=True)

    p = sub.add_parser("freeze", help="freeze a registered "
                       "criteria set version")
    p.add_argument("--set", required=True)
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--frozen-on", required=True)

    p = sub.add_parser("judge", help="judge every unjudged "
                       "ledger row under a frozen set")
    p.add_argument("--set", required=True)
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--judged-on", required=True)

    p = sub.add_parser("meta", help="discrimination + "
                       "coverage over the verdicts register")
    p.add_argument("--set")
    p.add_argument("--version", type=int)

    sub.add_parser("verify", help="verify both registers; "
                   "verdicts re-derive from the ledger")
    sub.add_parser("list", help="register state")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "register-v1":
            entry = register_set(
                args.criteria, "house-adoption", 1,
                HOUSE_ADOPTION_V1, args.registered_on,
                args.registered_by, V1_TIMING)
            print(f"registered house-adoption v1 "
                  f"({len(HOUSE_ADOPTION_V1)} criteria, "
                  f"entry {entry['entry_sha256'][:12]}…)")
            return 0
        if args.cmd == "register":
            criteria = json.loads(Path(
                args.criteria_file).read_text(encoding="utf-8"))
            entry = register_set(
                args.criteria, args.set, args.version,
                criteria, args.registered_on,
                args.registered_by, args.timing, args.amends)
            print(f"registered {args.set} v{args.version} "
                  f"(entry {entry['entry_sha256'][:12]}…)")
            return 0
        if args.cmd == "freeze":
            entry = freeze_set(args.criteria, args.set,
                               args.version, args.frozen_on)
            print(f"froze {args.set} v{args.version} "
                  f"(entry {entry['entry_sha256'][:12]}…)")
            return 0
        if args.cmd == "judge":
            out = judge(args.ledger, args.criteria,
                        args.verdicts, args.set, args.version,
                        args.judged_on)
            for v in out["verdicts"]:
                marks = " ".join(
                    f"{r['criterion']}="
                    f"{r['status']}"
                    f"({r['measured']})"
                    for r in v["results"])
                print(f"[{v['row']['config']}] "
                      f"adoptable={v['adoptable']} "
                      f"recomputes={v['row_recomputes']}  "
                      f"{marks}")
            if out["skipped_already_judged"]:
                print("already judged, skipped: "
                      + ", ".join(out["skipped_already_judged"]))
            print(f"judged {len(out['verdicts'])} row(s) "
                  f"under {args.set} v{args.version}")
            return 0
        if args.cmd == "meta":
            view = meta_view(args.ledger, args.criteria,
                             args.verdicts, args.set,
                             args.version)
            print(json.dumps(view, indent=2,
                             ensure_ascii=False))
            return 0
        if args.cmd == "verify":
            ok, findings = verify_registers(
                args.criteria, args.verdicts, args.ledger)
            if ok:
                print("verify: OK — criteria + verdicts "
                      "chains intact; every verdict re-derives "
                      "from the ledger row it judged under "
                      "its frozen criteria")
                return 0
            print("verify: FAILED")
            for f in findings:
                print(f"  - {f}")
            return 1
        if args.cmd == "list":
            register = load_jsonl(args.criteria)
            for e in register:
                if e.get("kind") == "criteria-set":
                    frozen = find_freeze(
                        register, e["set"], e["version"])
                    print(f"{e['set']} v{e['version']} — "
                          f"{len(e['criteria'])} criteria, "
                          f"registered {e['registered_on']} "
                          f"by {e['registered_by']}, "
                          f"{'FROZEN ' + frozen['frozen_on'] if frozen else 'not frozen'}")
            verdicts = [v for v in load_jsonl(args.verdicts)
                        if v.get("kind") == "config-verdict"]
            print(f"verdicts: {len(verdicts)}")
            for v in verdicts:
                print(f"  {v['row']['config']:14s} under "
                      f"{v['criteria']['set']} "
                      f"v{v['criteria']['version']} — "
                      f"adoptable={v['adoptable']}")
            return 0
    except Refusal as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
