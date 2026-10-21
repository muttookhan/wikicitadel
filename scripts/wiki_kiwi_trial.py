#!/usr/bin/env python3
"""wiki_kiwi_trial.py - Kiwi morphological-analysis trial recorder.

Marathon R13 lane BB (ideas board line 200, Round 11 RB, Tier A):
Kiwi (bab2min/Kiwi, Apache-2.0; Python binding kiwipiepy) as a
bounded trial of Korean morphological analysis on a held Korean
sample. The venv lives OUTSIDE the trees; this wrapper runs a
fixed analysis script there and records tokens (form/tag/span),
sentence count and hashes in the evidence JSON. If the venv or
the package cannot be obtained, the exact door failure is
recorded and the exit code is 2 - an honest door failure is a
complete deliverable; an unrun trial is never claimed as run.
Usage: run --sample FILE --evidence FILE [--python PATH]
       [--work-dir DIR]
Exit 0 trial ran; 2 door failure. Stdlib only (in-tree side).
"""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path

RUNNER = '''import json, sys
from kiwipiepy import Kiwi
text = open(sys.argv[1], encoding="utf-8").read()
kiwi = Kiwi()
toks = kiwi.tokenize(text)
res = {"tokens": [{"form": t.form, "tag": t.tag,
                   "start": t.start, "len": t.len} for t in toks],
       "token_count": len(toks),
       "sentences": len(kiwi.split_into_sents(text))}
open(sys.argv[2], "w", encoding="utf-8").write(
    json.dumps(res, ensure_ascii=False, indent=2) + "\\n")
'''


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--sample", required=True)
    r.add_argument("--evidence", required=True)
    r.add_argument("--python", default=None)
    r.add_argument("--work-dir", default=None)
    a = ap.parse_args(argv)
    ev = {"tool": "kiwi-trial", "library": "kiwipiepy (Kiwi)",
          "licence": "Apache-2.0", "ran": False}
    sample = Path(a.sample)
    ev["sample"] = str(sample)
    if sample.is_file():
        ev["sample_sha256"] = sha256(sample)
    py = a.python
    if not py or not Path(py).is_file():
        ev["door_failure"] = {
            "stage": "obtain",
            "error": f"venv python not found: {py!r} (pass --python "
                     "pointing at the OUT-OF-TREE venv python)"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n",
                                    encoding="utf-8")
        return 2
    work = Path(a.work_dir) if a.work_dir else sample.parent
    work.mkdir(parents=True, exist_ok=True)
    runner = work / "kiwi_runner.py"
    runner.write_text(RUNNER, encoding="utf-8")
    result = work / "kiwi-result.json"
    proc = subprocess.run([py, str(runner), str(sample), str(result)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        ev["door_failure"] = {
            "stage": "analyse", "command": f"{py} {runner} {sample}",
            "error": proc.stderr.strip()[-800:]}
        Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n",
                                    encoding="utf-8")
        return 2
    data = json.loads(result.read_text(encoding="utf-8"))
    ver = subprocess.run([py, "-c", "import kiwipiepy;"
                                "print(kiwipiepy.__version__)"],
                         capture_output=True, text=True)
    ev.update({"ran": True, "tool_version": ver.stdout.strip(),
               "token_count": data["token_count"],
               "sentences": data["sentences"],
               "result": str(result), "result_sha256": sha256(result)})
    Path(a.evidence).write_text(
        json.dumps(ev, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
