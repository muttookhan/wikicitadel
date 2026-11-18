#!/usr/bin/env python3
"""wiki_indic_nlp_trial.py — Indic NLP Library normalisation trial.

Marathon R11 lane BB (ideas board line 157, Tier A; Indic NLP
Library, MIT — external-tool trial). Runs Indic normalisation +
sentence splitting on a held sample via a Python that has
indic-nlp-library installed (a venv OUTSIDE the trees). The
library is never vendored and no dependency is added to either
tree. If the interpreter or library cannot be obtained, the
wrapper records the exact door failure in the evidence JSON and
exits 2 — an honest door failure is a complete deliverable; an
unrun trial is never claimed as run.

Usage:
  run --sample FILE --python VENV_PYTHON --result FILE
      --evidence FILE
Exit 0 trial ran; 2 door failure. Stdlib only (this wrapper).
"""
import argparse, hashlib, json, subprocess, sys, tempfile
from pathlib import Path

RUNNER = r'''
import json, sys
from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
from indicnlp.tokenize import sentence_tokenize
text = open(sys.argv[1], encoding="utf-8").read()
factory = IndicNormalizerFactory()
# indic-nlp-library 0.92 renamed create_normalizer -> get_normalizer;
# accept either so the trial is not pinned to one release's spelling.
make = getattr(factory, "get_normalizer", None) or factory.create_normalizer
normalizer = make("hi")
normalized = normalizer.normalize(text)
sentences = sentence_tokenize.sentence_split(normalized, lang="hi")
import indicnlp
print(json.dumps({"tool_version": getattr(indicnlp, "__version__", "unknown"),
                  "normalized": normalized,
                  "sentences": sentences}, ensure_ascii=False))
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
    ev = {"tool": "indic-nlp-trial", "library": "indic-nlp-library",
          "licence": "MIT", "ran": False,
          "sample": str(a.sample), "sample_sha256": sha256(a.sample)}
    py = Path(a.python)
    if not py.is_file():
        ev["door_failure"] = {
            "stage": "obtain",
            "command": f"{a.python} -c <indic runner>",
            "error": f"interpreter not found: {a.python} "
                     "(venv with indic-nlp-library not present)"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2,
            ensure_ascii=False) + "\n", encoding="utf-8")
        return 2
    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "indic_runner.py"
        runner.write_text(RUNNER, encoding="utf-8")
        proc = subprocess.run([str(py), str(runner), str(a.sample)],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        ev["door_failure"] = {
            "stage": "run",
            "command": f"{a.python} indic_runner.py {a.sample}",
            "error": (proc.stderr or proc.stdout)[-800:]}
        Path(a.evidence).write_text(json.dumps(ev, indent=2,
            ensure_ascii=False) + "\n", encoding="utf-8")
        return 2
    result = json.loads(proc.stdout)
    Path(a.result).write_text(json.dumps(result, indent=2,
        ensure_ascii=False) + "\n", encoding="utf-8")
    ev.update({"ran": True, "tool_version": result.get("tool_version"),
               "result": str(a.result),
               "result_sha256": sha256(a.result),
               "sentences": len(result.get("sentences", [])),
               "wrapper": "scripts/wiki_indic_nlp_trial.py run"})
    Path(a.evidence).write_text(json.dumps(ev, indent=2,
        ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
