#!/usr/bin/env python3
"""wiki_pysastrawi_trial.py — PySastrawi stemming trial.

Marathon R11 lane BB (ideas board line 159, Tier A; PySastrawi,
Indonesia). Runs Indonesian stemming on a held sample via a
Python that has PySastrawi installed (a venv OUTSIDE the trees).

LICENCE TRAP (board line, verbatim duty): PySastrawi's CODE is
MIT, but its bundled dictionary is CC-BY-NC-SA 3.0 and must NOT
be redistributed with either tree — above all not the public
tree. The dictionary therefore stays inside the lane-workspace
venv; only trial OUTPUTS (stemmed text, per-word map) and this
evidence record enter the trees. This wrapper copies nothing
from the installed package.

If the interpreter or library cannot be obtained, the wrapper
records the exact door failure in the evidence JSON and exits
2 — an honest door failure is a complete deliverable.

Usage:
  run --sample FILE --python VENV_PYTHON --result FILE
      --evidence FILE
Exit 0 trial ran; 2 door failure. Stdlib only (this wrapper).
"""
import argparse, hashlib, json, subprocess, sys, tempfile
from pathlib import Path

RUNNER = r'''
import json, sys
from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
text = open(sys.argv[1], encoding="utf-8").read().strip()
stemmer = StemmerFactory().create_stemmer()
stemmed = stemmer.stem(text)
words = text.replace(".", " ").replace(",", " ").split()
word_map = {w: stemmer.stem(w) for w in words}
print(json.dumps({"stemmed": stemmed, "word_map": word_map},
                  ensure_ascii=False))
'''


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--sample", required=True)
    r.add_argument("--python", required=True)
    r.add_argument("--result", required=True)
    r.add_argument("--evidence", required=True)
    a = ap.parse_args(argv)
    ev = {"tool": "pysastrawi-trial", "library": "PySastrawi",
          "licence_code": "MIT",
          "licence_dictionary": "CC-BY-NC-SA 3.0 — dictionary NOT "
              "copied into either tree; it remains in the "
              "lane-workspace venv only",
          "ran": False,
          "sample": str(a.sample), "sample_sha256": sha256(a.sample)}
    py = Path(a.python)
    if not py.is_file():
        ev["door_failure"] = {
            "stage": "obtain",
            "command": f"{a.python} -c <pysastrawi runner>",
            "error": f"interpreter not found: {a.python} "
                     "(venv with PySastrawi not present)"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2,
            ensure_ascii=False) + "\n", encoding="utf-8")
        return 2
    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "sastrawi_runner.py"
        runner.write_text(RUNNER, encoding="utf-8")
        proc = subprocess.run([str(py), str(runner), str(a.sample)],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        ev["door_failure"] = {
            "stage": "run",
            "command": f"{a.python} sastrawi_runner.py {a.sample}",
            "error": (proc.stderr or proc.stdout)[-800:]}
        Path(a.evidence).write_text(json.dumps(ev, indent=2,
            ensure_ascii=False) + "\n", encoding="utf-8")
        return 2
    result = json.loads(proc.stdout)
    Path(a.result).write_text(json.dumps(result, indent=2,
        ensure_ascii=False) + "\n", encoding="utf-8")
    ev.update({"ran": True,
               "result": str(a.result),
               "result_sha256": sha256(a.result),
               "words": len(result.get("word_map", {})),
               "wrapper": "scripts/wiki_pysastrawi_trial.py run"})
    Path(a.evidence).write_text(json.dumps(ev, indent=2,
        ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
