#!/usr/bin/env python3
"""Preregistration prediction lines (WikiCitadel v1).

Pattern: preregistration / Registered Reports (OSF; SSR
Replication Centre workbook), via the science lane
(find C1). The mechanic this wiki lacked: we run evals and
make changes, then judge the results after the fact — the
exact posture preregistration exists to defeat. Before an
eval run (or a significant change), the expected outcome is
written down, dated, in a register; afterwards the result is
read against the prediction, not against hindsight. The eval
gate (WikiCitadel v1) enforces thresholds; this register records
what we BELIEVED before measuring, which is what keeps the
thresholds honest over time.

The register is evaluation/predictions.jsonl, append-only
and hash-chained exactly like evaluation/checkpoints.jsonl:
a header line first (kind: header, excluded from chaining),
then lines carrying prev_hash and
line_hash = sha256(prev_hash || canonical(line)), canonical
being sorted-keys compact JSON. Two line kinds:

  prediction  {id, date, subject, subject_key, prediction,
               basis, results_hint}
  score       {prediction_id, date, results_file, outcome,
               verdict: confirmed|refuted|mixed}

A prediction's state is the fold of its lines: open until a
score line names it. Scoring APPENDS — a chained line is
never edited, so an outcome can never quietly rewrite what
was predicted.

The one refusal that matters: `add` refuses a prediction
whose subject run already has results on disk — either a
results file carrying the exact label the prediction names
as its run (--results-hint; that run has already run,
whatever its date), or any results file for the subject
dated AFTER the prediction's date (a "prediction" filed
against a measurement dated later than the belief is
hindsight wearing a costume). Earlier results for the same
subject are the baseline the prediction is read against —
expected, and named in the prediction's basis.

The eval runner (scripts/wiki_eval_extended.py --predict)
reads this register through open_predictions() below: it
warns when a run has no open prediction registered for it,
and stamps the matching open prediction ids into the run's
report. It never blocks a run.

Usage:
  python3 scripts/wiki_predict.py add --subject TEXT
      --prediction TEXT --basis TEXT [--subject-key KEY]
      [--results-hint LABEL] [--date YYYY-MM-DD]
  python3 scripts/wiki_predict.py score PRED-ID
      --results-file evaluation/results/<label>.json
      --verdict confirmed|refuted|mixed --outcome TEXT
      [--date YYYY-MM-DD]
  python3 scripts/wiki_predict.py list [--status open|scored]
  python3 scripts/wiki_predict.py verify

Stdlib only. Also importable: open_predictions(path, key).
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "evaluation" / "predictions.jsonl"
RESULTS_DIR = ROOT / "evaluation" / "results"

GENESIS_PREV = "0" * 64
VERDICTS = ("confirmed", "refuted", "mixed")

HEADER = {
    "kind": "header",
    "register": "predictions",
    "version": 1,
    "purpose": ("Preregistered predictions for eval runs and "
                "significant changes: the expected outcome, "
                "stated before the measurement, scored against "
                "it afterwards. Maintained by "
                "scripts/wiki_predict.py (WikiCitadel v1; "
                "preregistration pattern, "
                "survey find C1)."),
    "maintenance": ("Append-only and hash-chained. A prediction "
                    "line is never edited; scoring appends a "
                    "score line naming the prediction, the "
                    "results file it was read against, the "
                    "outcome and the verdict. Where this "
                    "register and a run's own report disagree, "
                    "the run's report governs the numbers and "
                    "this register governs what was believed "
                    "before them."),
}


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def line_digest(prev_hash: str, line_without_hash: dict) -> str:
    return sha256_hex(prev_hash.encode("utf-8")
                      + canonical(line_without_hash))


# -- register io --------------------------------------------------------------

def load_register(path=REGISTER):
    """(header, lines): header excluded from chaining."""
    if not Path(path).exists():
        return None, []
    header, lines = None, []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        obj = json.loads(raw)
        if obj.get("kind") == "header":
            header = obj
        else:
            lines.append(obj)
    return header, lines


def ensure_header(path=REGISTER):
    if Path(path).exists():
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    header = dict(HEADER)
    header["created"] = date.today().isoformat()
    Path(path).write_text(canonical(header).decode("utf-8") + "\n",
                          encoding="utf-8")


def append_line(body: dict, path=REGISTER) -> dict:
    ensure_header(path)
    _header, lines = load_register(path)
    prev = lines[-1]["line_hash"] if lines else GENESIS_PREV
    line = dict(body)
    line["prev_hash"] = prev
    line["line_hash"] = line_digest(prev, line)
    with Path(path).open("a", encoding="utf-8") as fh:
        fh.write(canonical(line).decode("utf-8") + "\n")
    return line


def verify_chain(path=REGISTER):
    """(ok, index, problem) over the chained lines."""
    _header, lines = load_register(path)
    prev = GENESIS_PREV
    for i, line in enumerate(lines):
        if line.get("prev_hash") != prev:
            return False, i, "prev_hash mismatch"
        body = {k: v for k, v in line.items() if k != "line_hash"}
        if line_digest(prev, body) != line.get("line_hash"):
            return False, i, "line_hash mismatch (line altered)"
        prev = line["line_hash"]
    return True, None, None


def fold(lines):
    """Fold register lines into prediction states, in order."""
    preds = {}
    order = []
    for line in lines:
        if line.get("kind") == "prediction":
            state = dict(line)
            state["status"] = "open"
            state["score"] = None
            preds[line["id"]] = state
            order.append(line["id"])
        elif line.get("kind") == "score":
            state = preds.get(line.get("prediction_id"))
            if state is not None:
                state["status"] = "scored"
                state["score"] = line
    return [preds[i] for i in order]


def open_predictions(path=REGISTER, subject_key=None):
    """Open (unscored) prediction states, optionally filtered
    to one subject key. Defensive: any read problem yields []
    so callers (the eval runner) never break on the register."""
    try:
        _header, lines = load_register(path)
    except (OSError, ValueError):
        return []
    out = [s for s in fold(lines) if s["status"] == "open"]
    if subject_key is not None:
        out = [s for s in out if s.get("subject_key") == subject_key]
    return out


# -- the refuse-after-results rule ---------------------------------------------

def subject_key_of(subject: str, given: str | None) -> str:
    if given:
        return given
    slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")
    return slug[:48] or "run"


def results_dates(results_dir, subject_key):
    """[(path, date)] for results files matching the subject
    key (stem contains the key's first token, e.g. 'extended'
    for 'extended-eval'). Date = the file's recorded
    generated_at when present, else its mtime."""
    results_dir = Path(results_dir)
    if not results_dir.is_dir():
        return []
    token = subject_key.split("-")[0]
    found = []
    for path in sorted(results_dir.glob("*.json")):
        if token not in path.stem:
            continue
        when = None
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            gen = doc.get("generated_at")
            if gen:
                when = datetime.fromisoformat(
                    str(gen).replace("Z", "+00:00")).date()
        except (OSError, ValueError):
            when = None
        if when is None:
            when = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc).date()
        found.append((path, when))
    return found


def add_prediction(subject, prediction, basis, subject_key=None,
                   results_hint=None, on=None, path=REGISTER,
                   results_dir=RESULTS_DIR):
    """Append an open prediction. Raises ValueError with the
    refusal reason when the subject run already has results
    on disk: a file under the exact label the prediction
    names as its run, or any subject results dated after
    the prediction date."""
    on = on or date.today()
    key = subject_key_of(subject, subject_key)
    if results_hint:
        named = Path(results_dir) / f"{results_hint}.json"
        if named.is_file():
            raise ValueError(
                f"refused: results for the run this prediction "
                f"names ({results_hint}) already exist on disk "
                f"({named.name}) — a prediction filed now "
                f"would be hindsight, not preregistration")
    for rpath, when in results_dates(results_dir, key):
        if when > on:
            raise ValueError(
                f"refused: results for this subject exist on "
                f"disk dated {when.isoformat()}, after the "
                f"prediction date {on.isoformat()} "
                f"({rpath.name}) — a prediction filed now "
                f"would be hindsight, not preregistration")
    _header, lines = load_register(path)
    n = sum(1 for l in lines if l.get("kind") == "prediction") + 1
    body = {
        "kind": "prediction",
        "id": f"pred-{n:04d}",
        "date": on.isoformat(),
        "subject": subject,
        "subject_key": key,
        "prediction": prediction,
        "basis": basis,
    }
    if results_hint:
        body["results_hint"] = results_hint
    return append_line(body, path)


def score_prediction(pred_id, results_file, verdict, outcome,
                     on=None, path=REGISTER):
    """Append the score line for an open prediction. Raises
    ValueError for an unknown id, an already-scored id, a bad
    verdict, or a results file that does not exist."""
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    if not Path(results_file).is_file():
        raise ValueError(f"results file not found: {results_file}")
    _header, lines = load_register(path)
    states = {s["id"]: s for s in fold(lines)}
    state = states.get(pred_id)
    if state is None:
        raise ValueError(f"unknown prediction id: {pred_id}")
    if state["status"] == "scored":
        raise ValueError(f"{pred_id} is already scored "
                         f"({state['score'].get('date')})")
    on = on or date.today()
    metrics = {}
    try:
        doc = json.loads(Path(results_file).read_text(encoding="utf-8"))
        agg = doc.get("aggregates") or {}
        cov = agg.get("citation_coverage") or {}
        if cov.get("@10") is not None:
            metrics["citation_coverage@10"] = cov["@10"]
        if agg.get("hit_rate_topk") is not None:
            metrics["hit_rate_topk"] = agg["hit_rate_topk"]
        if agg.get("mrr_must_cite") is not None:
            metrics["mrr_must_cite"] = agg["mrr_must_cite"]
        abst = doc.get("abstention") or {}
        if abst.get("abstention_rate") is not None:
            metrics["abstention_rate"] = abst["abstention_rate"]
    except (OSError, ValueError):
        metrics = {}
    return append_line({
        "kind": "score",
        "prediction_id": pred_id,
        "date": on.isoformat(),
        "results_file": str(results_file),
        "metrics": metrics,
        "outcome": outcome,
        "verdict": verdict,
    }, path)


# -- CLI ------------------------------------------------------------------------

def main(argv):
    ap = argparse.ArgumentParser(
        description="Preregistration predictions register "
                    "(evaluation/predictions.jsonl).")
    ap.add_argument("--register", default=str(REGISTER),
                    help="register path (tests use a fixture)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="file an open prediction")
    a.add_argument("--subject", required=True)
    a.add_argument("--prediction", required=True)
    a.add_argument("--basis", required=True)
    a.add_argument("--subject-key", default=None)
    a.add_argument("--results-hint", default=None,
                   help="label of the run being predicted "
                        "(its results file must not exist yet)")
    a.add_argument("--date", default=None,
                   help="prediction date (default: today)")

    s = sub.add_parser("score", help="score a prediction "
                                     "against a results file")
    s.add_argument("prediction_id")
    s.add_argument("--results-file", required=True)
    s.add_argument("--verdict", required=True, choices=VERDICTS)
    s.add_argument("--outcome", required=True)
    s.add_argument("--date", default=None)

    li = sub.add_parser("list", help="list predictions")
    li.add_argument("--status", choices=("open", "scored"),
                    default=None)

    sub.add_parser("verify", help="verify the hash chain")

    args = ap.parse_args(argv[1:])
    path = Path(args.register)
    on = date.fromisoformat(args.date) if getattr(args, "date", None) else None

    if args.cmd == "add":
        try:
            line = add_prediction(args.subject, args.prediction,
                                  args.basis, args.subject_key,
                                  results_hint=args.results_hint,
                                  on=on, path=path)
        except ValueError as exc:
            print(f"wiki_predict: {exc}", file=sys.stderr)
            return 2
        print(f"filed {line['id']} ({line['date']}, open) — "
              f"subject key: {line['subject_key']}")
        print(f"  prediction: {line['prediction']}")
        return 0

    if args.cmd == "score":
        try:
            line = score_prediction(args.prediction_id,
                                    args.results_file, args.verdict,
                                    args.outcome, on=on, path=path)
        except ValueError as exc:
            print(f"wiki_predict: {exc}", file=sys.stderr)
            return 2
        print(f"scored {line['prediction_id']} on {line['date']}: "
              f"{line['verdict']} — {line['outcome']}")
        if line["metrics"]:
            print("  metrics read from the results file: "
                  + json.dumps(line["metrics"], sort_keys=True))
        return 0

    if args.cmd == "list":
        _header, lines = load_register(path)
        states = fold(lines)
        if args.status:
            states = [s for s in states if s["status"] == args.status]
        if not states:
            print("no predictions"
                  + (f" with status {args.status}" if args.status else ""))
            return 0
        for s in states:
            print(f"{s['id']}  {s['date']}  [{s['status']}]  "
                  f"{s['subject']}")
            print(f"  prediction: {s['prediction']}")
            print(f"  basis: {s['basis']}")
            if s["score"]:
                sc = s["score"]
                print(f"  scored {sc['date']} vs {sc['results_file']}: "
                      f"{sc['verdict']} — {sc['outcome']}")
        return 0

    if args.cmd == "verify":
        ok, idx, problem = verify_chain(path)
        if ok:
            _header, lines = load_register(path)
            print(f"chain OK ({len(lines)} chained line(s))")
            return 0
        print(f"chain BROKEN at line {idx}: {problem}",
              file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
