#!/usr/bin/env python3
"""Memory-operations slice: does the store know WHICH operation
it performed? (FEB-30 pattern; ideas board item from the
2026-10-27 landscape weekly.)

Pattern: Toma et al., "Beyond Downstream QA" (arXiv:2610.22209,
2026-10-15) — FEB-30 evaluates a memory store intrinsically:
over fact-evolution trajectories, each incoming item's correct
operation class (create / update / reinforce / supersede) is
known by construction, and the store is scored on classifying
its own operations. The tested system classified correctly
only 20% of the time — a failure invisible to downstream-QA
evaluation, which is all most stores (this one included) had.
Re-implemented from the paper's design in this wiki's own
terms; no code copied.

WHAT THE STORE'S MACHINERY ACTUALLY IS, and what is scored:

  Free-text claims arrive at ingest and meet ONE deterministic
  classifier: scripts/wiki_claim_match.py — token containment
  against the settled corpus (claim pages, beliefs, decision
  current + superseded forms), noise floor 0.35. Below the
  floor the claim is genuinely new (CREATE). Above it, the
  store treats the text as a restatement of the settled claim
  it matched: the material is linked to the existing record
  and inherits its status — no second record (REINFORCE). A
  top match on a SUPERSEDED form (or a retired claim) is a
  zombie repeat: the store flags the form's standing instead
  of resurrecting it (scored as a probe outcome,
  "superseded-repeat", outside the four classes).

  Rulings arrive as maintainer-recorded writes to the
  decisions register. The store's machinery downstream of the
  write is the severance derivation (scripts/wiki_severance.py
  decision-form + treatment entries): if the form that stood
  before the ruling now appears in the derived severance list,
  the store SEVERED it (SUPERSEDE); if the register line
  changed and nothing was severed, the record was revised in
  place (UPDATE — the refinement path: the register's own
  header distinguishes a refined form from a reversed one);
  if nothing changed, the store performed no operation at all
  ("none").

  Stated limits, plainly: claim-match PROPOSES and a human
  picks — this slice scores the deterministic core's
  classification, not the pick. The severance derivation's
  page-level signals (frontmatter supersession scan) are out
  of scope: the slice exercises the register paths only. And
  UPDATE in free text — a restatement whose VALUE changed —
  is the blind spot FEB-30 predicts: the text classifier has
  no value-comparison step, so such steps are expected to
  misclassify as REINFORCE here; the battery carries them
  labelled, and the score reports them as disagreements,
  never as cases to weaken.

Replay: each trajectory runs against a fresh temporary store
(claim pages + a decisions register, in the real formats), so
the battery never touches this tree's registers. The
classifier reads only store state and the incoming item; the
expected class lives in the battery data and is read only by
the scorer. Live probes additionally run the classifier,
read-only, against THIS tree's real settled corpus.

Exit codes: 0 = every scored step agrees and every probe
passes, 1 = a disagreement or probe failure (a finding —
reported, never repaired by this tool), 2 = usage error.
Stdlib only; no model calls; no network.

Usage:
  python3 scripts/wiki_memory_ops_check.py [--json]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
BATTERY_REL = "evaluation/memory-ops-battery.jsonl"
CLASSES = ("create", "update", "reinforce", "supersede")

REGISTER_HEADER = {
    "kind": "header", "register": "decisions-register",
    "version": 1,
    "purpose": "Replay-store register for the memory-operations "
               "slice (scripts/wiki_memory_ops_check.py); "
               "temporary, synthetic, never the real register.",
}


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- the store

class Store:
    """A miniature store in a temp dir, in the real formats:
    claim pages under wiki/ (claim: frontmatter) and a
    decisions register at evaluation/decisions-register.jsonl.
    `form_titles` tracks each decision's standing form title —
    the maintainer's knowledge of what the standing form says,
    used when a later ruling records it as superseded."""

    def __init__(self, root: Path):
        self.root = root
        (root / "wiki" / "facts").mkdir(parents=True)
        (root / "evaluation").mkdir(parents=True)
        self.decisions: dict[str, dict] = {}
        self.form_titles: dict[str, str] = {}
        self._supersede_count: dict[str, int] = {}
        self._write_register()

    # -- files

    def write_claim_page(self, page: str, claim: str):
        path = self.root / page
        path.parent.mkdir(parents=True, exist_ok=True)
        title = claim if len(claim) <= 72 else claim[:69] + "..."
        path.write_text(
            f"---\ntitle: {title}\nclaim: {claim}\n"
            f"status: draft\n---\n\n{claim}\n",
            encoding="utf-8")

    def _write_register(self):
        lines = [json.dumps(REGISTER_HEADER, ensure_ascii=False)]
        for line in self.decisions.values():
            lines.append(json.dumps(line, ensure_ascii=False))
        (self.root / "evaluation" / "decisions-register.jsonl"
         ).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def read_register_line(self, decision_id: str):
        path = self.root / "evaluation" / "decisions-register.jsonl"
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            obj = json.loads(raw)
            if obj.get("kind") == "decision" \
                    and obj.get("id") == decision_id:
                return obj
        return None

    # -- seeding and step application (the world's script;
    #    the classifier never sees these fields)

    def seed_claim(self, page: str, claim: str):
        self.write_claim_page(page, claim)

    def seed_decision(self, spec: dict):
        line = {
            "kind": "decision", "id": spec["id"],
            "title": spec["title"], "status": "active",
            "decided": "2026-01-01", "decided_by": "committee",
            "source": {"page": spec["source_page"]},
            "current_form": spec["current_form"],
            "superseded_forms": [],
        }
        self.decisions[spec["id"]] = line
        self.form_titles[spec["id"]] = spec["form_title"]
        self._write_register()

    def apply_claim_step(self, step: dict):
        """Advance the world after a claim step, per the
        trajectory's construction: a created fact gets its
        page; an updated fact's page is revised in place; a
        reinforcement or a zombie repeat changes nothing."""
        expect = step.get("expect")
        if expect in ("create", "update") and step.get("page"):
            self.write_claim_page(step["page"], step["text"])

    def apply_rule_step(self, step: dict):
        """Advance the world after a ruling step: the
        maintainer's recorded register write, or — when the
        ruling was never recorded — nothing at all."""
        if not step.get("recorded"):
            return
        line = self.decisions[step["decision"]]
        if step.get("supersede"):
            n = self._supersede_count.get(step["decision"], 0) + 1
            self._supersede_count[step["decision"]] = n
            form = {
                "form_id": f"{step['decision']}-old-{n}",
                "title": step.get(
                    "record_title",
                    self.form_titles[step["decision"]]),
                "status": "superseded",
                "superseded_on": "2026-01-02",
                "superseded_by": "trajectory ruling",
                "match_phrases": step.get("match_phrases", []),
            }
            line["superseded_forms"].append(form)
        line["current_form"] = step["new_current_form"]
        self.form_titles[step["decision"]] = step["new_form_title"]
        self._write_register()


# ---------------------------------------------------------------- classifier

def classify_claim(cm, root: Path, text: str) -> tuple[str, str]:
    """The store's text classification, from its real core
    (scripts/wiki_claim_match.py): corpus build, ranking, the
    0.35 noise floor, and the standing of the top hit."""
    corpus = cm.build_corpus(root)
    ranked = cm.match(text, corpus, top=1)
    if not ranked or ranked[0][0] < cm.NOISE_FLOOR:
        return "create", "no settled claim at or above the " \
                         "noise floor — genuinely new"
    score, entry = ranked[0]
    status = str(entry.get("status", ""))
    if entry.get("kind") == "decision-superseded-form" \
            or status.startswith("superseded") \
            or status == "retired":
        return "superseded-repeat", \
            f"top hit is a dead form [{score:.2f}] {entry['id']}"
    return "reinforce", \
        f"restatement of a standing claim [{score:.2f}] {entry['id']}"


def _severed_claims(sev, root: Path) -> dict[str, dict]:
    """claim title -> severance entry, from the register paths
    of the real derivation (decision forms + treatment)."""
    out = {}
    for entry in sev.decision_form_entries(root) \
            + sev.treatment_entries(root):
        if entry.get("claim"):
            out[entry["claim"]] = entry
    return out


def classify_rule(sev, store: Store, step: dict,
                  apply_fn) -> tuple[str, str]:
    """The store's ruling classification, observed from state,
    not from the step's labels: snapshot the register line and
    the derived severance list, apply the recorded write, and
    read what the machinery did to the form that stood before.
    """
    decision_id = step["decision"]
    before_line = store.read_register_line(decision_id)
    before_form = before_line["current_form"] if before_line \
        else None
    old_title = store.form_titles.get(decision_id)
    before_severed = _severed_claims(sev, store.root)
    apply_fn()
    after_line = store.read_register_line(decision_id)
    after_severed = _severed_claims(sev, store.root)
    if old_title and old_title in after_severed \
            and old_title not in before_severed:
        entry = after_severed[old_title]
        cues = entry.get("cues") or {}
        if cues.get("phrases") or cues.get("terms"):
            return "supersede", \
                f"the standing form is severed by the derivation: " \
                f"{old_title!r}"
        return "superseded-unsevered", \
            f"a severance entry exists for {old_title!r} but " \
            f"carries no usable cues"
    if after_line and before_form is not None \
            and after_line["current_form"] != before_form:
        return "update", "the register line was revised and the " \
                         "old form was not severed"
    return "none", "no register change the machinery can see"


# ---------------------------------------------------------------- the run

def load_battery(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def run(root: Path, battery_path: Path | None = None) -> dict:
    cm = _load("wiki_claim_match_for_memory_ops", "wiki_claim_match.py")
    sev = _load("wiki_severance_for_memory_ops", "wiki_severance.py")
    rows = load_battery(battery_path or (root / BATTERY_REL))
    report = {
        "trajectories": 0, "steps": 0, "agreements": 0,
        "accuracy": None,
        "per_class": {c: {"steps": 0, "agreements": 0}
                      for c in CLASSES},
        "disagreements": [],
        "probes": {"total": 0, "passed": 0, "failures": []},
        "live_probes": {"total": 0, "passed": 0, "failures": []},
    }

    def score(bucket: str, subject: str, expect: str,
              classified: str, detail: str):
        report[bucket]["total"] += 1
        if classified == expect:
            report[bucket]["passed"] += 1
        else:
            report[bucket]["failures"].append({
                "subject": subject, "expect": expect,
                "classified": classified, "detail": detail})

    for row in rows:
        if row.get("kind") == "live-probe":
            classified, detail = classify_claim(cm, root, row["text"])
            score("live_probes", row["id"], row["expect"],
                  classified, detail)
            continue
        if row.get("kind") != "trajectory":
            continue
        report["trajectories"] += 1
        with tempfile.TemporaryDirectory() as td:
            store = Store(Path(td))
            seed = row.get("seed") or {}
            for claim in seed.get("claims") or []:
                store.seed_claim(claim["page"], claim["claim"])
            for spec in seed.get("decisions") or []:
                store.seed_decision(spec)
            for i, step in enumerate(row.get("steps") or [], 1):
                subject = f"{row['id']} step {i}"
                if step.get("op") == "rule":
                    classified, detail = classify_rule(
                        sev, store, step,
                        lambda s=step: store.apply_rule_step(s))
                else:
                    classified, detail = classify_claim(
                        cm, store.root, step["text"])
                    store.apply_claim_step(step)
                if step.get("probe"):
                    score("probes", subject, step["expect"],
                          classified, detail)
                    continue
                report["steps"] += 1
                expect = step["expect"]
                if expect in report["per_class"]:
                    report["per_class"][expect]["steps"] += 1
                if classified == expect:
                    report["agreements"] += 1
                    if expect in report["per_class"]:
                        report["per_class"][expect]["agreements"] += 1
                else:
                    report["disagreements"].append({
                        "subject": subject, "expect": expect,
                        "classified": classified, "detail": detail,
                        "note": step.get("note", "")})
    if report["steps"]:
        report["accuracy"] = round(
            report["agreements"] / report["steps"], 4)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true",
                    help="emit the report as JSON")
    ap.add_argument("--battery", default=None,
                    help="battery file (default: this tree's "
                         "evaluation/memory-ops-battery.jsonl)")
    args = ap.parse_args(argv)
    battery = Path(args.battery) if args.battery else None
    report = run(ROOT, battery)
    bad = bool(report["disagreements"]
               or report["probes"]["failures"]
               or report["live_probes"]["failures"])
    if args.json:
        print(json.dumps(report, indent=1, sort_keys=True))
    else:
        acc = report["accuracy"]
        print(f"memory-ops slice: {report['trajectories']} "
              f"trajectories, {report['steps']} scored steps, "
              f"{report['agreements']} agreements, accuracy "
              f"{acc if acc is not None else 'n/a'}")
        for cls in CLASSES:
            pc = report["per_class"][cls]
            print(f"  {cls}: {pc['agreements']}/{pc['steps']}")
        for d in report["disagreements"]:
            print(f"  DISAGREE {d['subject']}: expect "
                  f"{d['expect']}, store classified "
                  f"{d['classified']} — {d['detail']}")
        for bucket in ("probes", "live_probes"):
            b = report[bucket]
            print(f"  {bucket}: {b['passed']}/{b['total']} passed")
            for f in b["failures"]:
                print(f"  FAIL {f['subject']}: expect "
                      f"{f['expect']}, store classified "
                      f"{f['classified']} — {f['detail']}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
