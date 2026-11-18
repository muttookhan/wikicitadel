#!/usr/bin/env python3
"""wiki_citeproof_ledger.py — checker-accuracy ledger.

Marathon R10 lane BB (ideas board R8 deep-dive, Tier A; CiteProof
pattern). A held-out seeded-bad fixture set for the citation
lockfile checker (scripts/wiki_cite_lock.py verify_quote + range
check), in its OWN new file evaluation/citeproof-fixtures.json:
a fabricated locator, a swapped source, a one-word-altered
quote, plus clean controls. The runner copies the fixture
sources into a TEMPORARY directory and points the checker's
ROOT there — the real lockfile is never modified by the seeded
fixtures, and the golden sets / pinned battery are never
touched. Results (catches / false-cleans) are written beside
the lockfile check summary in the derived ledger
evaluation/citeproof-ledger.json.

Usage: run [--fixtures FILE] [--out FILE] | check [...]
  run   — execute fixtures, (re)write the ledger.
  check — re-execute and verify the ledger matches + every
          seeded-bad fixture was caught and every control passed.
Exit 0 ok; 1 a fixture outcome differs / a bad fixture was not
caught; 2 usage error. Stdlib only.
"""
import argparse, importlib.util, json, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "evaluation" / "citeproof-fixtures.json"
OUT = ROOT / "evaluation" / "citeproof-ledger.json"
LOCK = ROOT / "evaluation" / "citation-lockfile.json"


def _load_cite_lock():
    spec = importlib.util.spec_from_file_location(
        "wiki_cite_lock", ROOT / "scripts" / "wiki_cite_lock.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_fixtures(fixtures, cite_lock):
    results = []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for name, lines in fixtures["sources"].items():
            p = td / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        old_root = cite_lock.ROOT
        cite_lock.ROOT = td
        try:
            for fx in fixtures["fixtures"]:
                lines = (cite_lock._read_lines(fx["source"])
                         or [])
                if fx["start"] > len(lines):
                    observed = "caught"
                    detail = (f"locator out of range: source has "
                              f"{len(lines)} lines")
                else:
                    ok, div = cite_lock.verify_quote(
                        fx["quote"], fx["source"], fx["start"],
                        fx["end"])
                    observed = ("passed" if ok else "caught")
                    detail = div
                expected = fx["expected"]
                results.append({
                    "id": fx["id"], "kind": fx["kind"],
                    "expected": expected, "observed": observed,
                    "match": expected == observed,
                    "false_clean": (expected == "caught"
                                    and observed == "passed"),
                    "detail": detail})
        finally:
            cite_lock.ROOT = old_root
    return results


def build_ledger(fixtures_path=None):
    import hashlib
    fp = Path(fixtures_path) if fixtures_path else FIXTURES
    fixtures = json.loads(fp.read_text(encoding="utf-8"))
    results = run_fixtures(fixtures, _load_cite_lock())
    lock_summary = {"path": "evaluation/citation-lockfile.json",
                    "present": LOCK.is_file()}
    if LOCK.is_file():
        data = LOCK.read_bytes()
        lock_summary["sha256"] = hashlib.sha256(data).hexdigest()
        lock_summary["citations"] = len(json.loads(
            data).get("citations", []))
    return {"tool": "wiki_citeproof_ledger",
            "fixtures_file": "evaluation/citeproof-fixtures.json",
            "lockfile_check_beside": lock_summary,
            "results": results,
            "catches": sum(1 for r in results
                           if r["kind"] != "clean-control"
                           and r["observed"] == "caught"),
            "seeded_bad": sum(1 for r in results
                              if r["kind"] != "clean-control"),
            "false_cleans": sum(1 for r in results
                                if r["false_clean"]),
            "controls_passed": sum(
                1 for r in results if r["kind"] == "clean-control"
                and r["observed"] == "passed"),
            "controls": sum(1 for r in results
                            if r["kind"] == "clean-control")}


def render(ledger):
    return json.dumps(ledger, indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "check"):
        p = sub.add_parser(name)
        p.add_argument("--fixtures", default=str(FIXTURES))
        p.add_argument("--out", default=str(OUT))
    a = ap.parse_args(argv)
    ledger = build_ledger(a.fixtures)
    text = render(ledger)
    bad = (ledger["false_cleans"] > 0
           or ledger["controls_passed"] != ledger["controls"]
           or not all(r["match"] for r in ledger["results"]))
    if a.cmd == "run":
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}: catches "
              f"{ledger['catches']}/{ledger['seeded_bad']}, "
              f"false-cleans {ledger['false_cleans']}, controls "
              f"{ledger['controls_passed']}/{ledger['controls']}")
        return 1 if bad else 0
    cur = Path(a.out)
    if not cur.is_file() or cur.read_text(encoding="utf-8") != text:
        print("ledger does not match a fresh fixture run")
        return 1
    if bad:
        print("a seeded-bad fixture was not caught, or a control "
              "failed")
        return 1
    print("ledger matches; all seeded-bad fixtures caught, all "
          "controls passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
