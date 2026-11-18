#!/usr/bin/env python3
"""wiki_bolognese_trial.py — Bolognese conversion trial recorder.

Marathon R10 lane BB (ideas board R8 research, Tier A): bolognese
(DataCite, MIT; Ruby gem) as a reversible CLI trial converting a
bounded set of held bibliographic records (BibTeX <-> CSL JSON)
with before/after diffs as the acceptance check. The gem lives
OUTSIDE the trees; no Ruby dependency is added to either tree.
If Ruby/gem installation fails, this wrapper records the exact
door failure in the evidence JSON and exits 2 — an honest door
failure is a complete deliverable; an unrun trial is never
claimed as run.

Usage:
  run --records FILE [FILE...] --out-dir DIR --evidence FILE
      [--bolognese PATH] [--from FORMAT] [--to FORMAT]
Exit 0 every record converted and diffed; 2 door failure.
Stdlib only.
"""
import argparse, difflib, hashlib, json, shutil, subprocess, sys
from pathlib import Path


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--records", nargs="+", required=True)
    r.add_argument("--out-dir", required=True)
    r.add_argument("--evidence", required=True)
    r.add_argument("--bolognese", default=None)
    r.add_argument("--from", dest="frm", default="bibtex")
    r.add_argument("--to", dest="to", default="citeproc")
    a = ap.parse_args(argv)
    exe = a.bolognese or shutil.which("bolognese")
    ev = {"tool": "bolognese-trial", "ran": False, "records": []}
    if exe and not Path(exe).is_file() and not shutil.which(exe):
        exe = None
    if not exe:
        ev["door_failure"] = {
            "stage": "obtain",
            "error": "bolognese executable not found on PATH and "
                     "no --bolognese path given (Ruby/gem not "
                     "installed in this environment)"}
        Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n",
                                    encoding="utf-8")
        return 2
    out_dir = Path(a.out_dir); out_dir.mkdir(parents=True,
                                             exist_ok=True)
    ok = True
    for rec in a.records:
        rec = Path(rec)
        entry = {"input": str(rec), "input_sha256": sha256(rec)}
        proc = subprocess.run(
            [exe, str(rec), "--from", a.frm, "--to", a.to],
            capture_output=True, text=True)
        entry["exit"] = proc.returncode
        if proc.returncode != 0:
            entry["stderr_tail"] = proc.stderr[-500:]
            ok = False
        else:
            out = out_dir / (rec.stem + ".converted.json")
            out.write_text(proc.stdout, encoding="utf-8")
            entry["output"] = str(out)
            entry["output_sha256"] = sha256(out)
            entry["diff"] = "".join(difflib.unified_diff(
                rec.read_text(encoding="utf-8").splitlines(True),
                proc.stdout.splitlines(True),
                fromfile=rec.name, tofile=out.name))
            (out_dir / (rec.stem + ".diff")).write_text(
                entry.pop("diff"), encoding="utf-8")
        ev["records"].append(entry)
    ev["ran"] = ok
    if not ok:
        ev["door_failure"] = {"stage": "convert",
            "error": "one or more conversions exited non-zero; "
                     "see per-record stderr_tail"}
    Path(a.evidence).write_text(json.dumps(ev, indent=2) + "\n",
                                encoding="utf-8")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
