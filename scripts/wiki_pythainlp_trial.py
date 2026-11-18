#!/usr/bin/env python3
"""wiki_pythainlp_trial.py — PyThaiNLP tokenisation trial.

Marathon R11 lane BB (ideas board line 158, Tier A; PyThaiNLP,
Apache-2.0 — external-tool trial). Runs Thai word tokenisation
(newmm engine) + sentence segmentation on a held sample via a
Python that has pythainlp installed (a venv OUTSIDE the trees).
Nothing is vendored; no dependency is added to either tree. If
the interpreter or library cannot be obtained, the wrapper
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
import pythainlp
from pythainlp import word_tokenize, sent_tokenize
text = open(sys.argv[1], encoding="utf-8").read().strip()
sentences = sent_tokenize(text)
tokens = word_tokenize(text, engine="newmm")
print(json.dumps({"tool_version": pythainlp.__version__,
                  "sentences": sentences,
                  "tokens": tokens,
                  "token_count": len(tokens)}, ensure_ascii=False))
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
    ev = {"tool": "pythainlp-trial", "library": "pythainlp",
          "licence": "Apache-2.0", "ran": False,
          "sample": str(a.sample), "sample_sha256": sha256(a.sample)}
    py = Path(a.python)
    if not py.is_file():
        ev["door_failure"] = {
            "stage": "obtain",
            "command": f"{a.python} -c <pythainlp runner>",
            "error": f"interpreter not found: {a.python} "
                     "(venv with pythainlp not present)"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2,
            ensure_ascii=False) + "\n", encoding="utf-8")
        return 2
    with tempfile.TemporaryDirectory() as td:
        runner = Path(td) / "thai_runner.py"
        runner.write_text(RUNNER, encoding="utf-8")
        proc = subprocess.run([str(py), str(runner), str(a.sample)],
                              capture_output=True, text=True)
    if proc.returncode != 0:
        ev["door_failure"] = {
            "stage": "run",
            "command": f"{a.python} thai_runner.py {a.sample}",
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
               "token_count": result.get("token_count"),
               "wrapper": "scripts/wiki_pythainlp_trial.py run"})
    Path(a.evidence).write_text(json.dumps(ev, indent=2,
        ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
