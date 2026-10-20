#!/usr/bin/env python3
"""Wiki presets (gap 12, scoped form): named starter shapes for a wiki.

A preset is a directory under templates/presets/<name>/ holding:
  preset.json   {name, title, description, best_for}
  files/...     the starter tree copied verbatim on install

Subcommands:
  list                      every preset with its one-line description
  show <name>               the preset's metadata + file list
  install <name> --target D copy files/ into D; NEVER overwrites —
                            existing files are skipped and reported;
                            --dry-run reports without writing

Install writes <target>/preset-<name>.receipt.json recording what was
installed and what was skipped, so an install is auditable afterwards.
Stdlib only.
"""
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESETS_DIR = ROOT / "templates" / "presets"


def load_preset(presets_dir, name):
    pdir = presets_dir / name
    meta_file = pdir / "preset.json"
    if not meta_file.is_file():
        raise KeyError(f"no such preset: {name}")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    files = sorted(
        str(p.relative_to(pdir / "files"))
        for p in (pdir / "files").rglob("*") if p.is_file()
    ) if (pdir / "files").is_dir() else []
    return meta, files, pdir


def list_presets(presets_dir=PRESETS_DIR):
    out = []
    if presets_dir.is_dir():
        for pdir in sorted(presets_dir.iterdir()):
            if (pdir / "preset.json").is_file():
                meta, _, _ = load_preset(presets_dir, pdir.name)
                out.append(meta)
    return out


def install(presets_dir, name, target, dry_run=False):
    meta, files, pdir = load_preset(presets_dir, name)
    target = Path(target)
    installed, skipped = [], []
    for rel in files:
        src = pdir / "files" / rel
        dst = target / rel
        if dst.exists():
            skipped.append(rel)
            continue
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        installed.append(rel)
    receipt = {"preset": meta["name"], "installed": installed,
               "skipped_existing": skipped, "dry_run": dry_run,
               "date": date.today().isoformat()}
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        (target / f"preset-{name}.receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("show")
    s.add_argument("name")
    i = sub.add_parser("install")
    i.add_argument("name")
    i.add_argument("--target", required=True)
    i.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            for m in list_presets():
                print(f"{m['name']:<20} {m['description']}")
            return 0
        if args.cmd == "show":
            meta, files, _ = load_preset(PRESETS_DIR, args.name)
            print(json.dumps(meta, indent=2))
            print("files:")
            for f in files:
                print(f"  {f}")
            return 0
        receipt = install(PRESETS_DIR, args.name, args.target, args.dry_run)
        print(json.dumps(receipt, indent=2))
        return 0
    except KeyError as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
