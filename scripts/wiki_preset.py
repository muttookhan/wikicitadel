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
  gallery --out FILE        write a single self-contained HTML
                            gallery of all presets + page templates
                            (name, purpose, file list). The output
                            is deterministic (sorted, no timestamps)
                            and offline (inline style, no external
                            references, no scripts).

Install writes <target>/preset-<name>.receipt.json recording what was
installed and what was skipped, so an install is auditable afterwards.
Stdlib only.
"""
import argparse
import html
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRESETS_DIR = ROOT / "templates" / "presets"
TEMPLATES_DIR = ROOT / "templates"


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


def _template_purpose(text):
    """First meaningful body line of a template, as its purpose."""
    body = text
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line and not line.startswith(("<!--", "%")):
            return line[:120]
    return ""


def list_templates(templates_dir=TEMPLATES_DIR):
    """Page templates on offer: templates/*.md + templates/capture/*.md.

    Preset trees under templates/presets/ are not page templates and
    are never listed here. Sorted by name; deterministic.
    """
    templates_dir = Path(templates_dir)
    out = []
    if not templates_dir.is_dir():
        return out
    for kind, folder in (("page", templates_dir),
                         ("capture", templates_dir / "capture")):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            title = path.stem
            if text.startswith("---"):
                for line in text.split("---", 2)[1].splitlines():
                    if line.startswith("title:"):
                        value = line.split(":", 1)[1].strip().strip('"')
                        if value:
                            title = value
                        break
            out.append({
                "name": path.relative_to(templates_dir).as_posix(),
                "kind": kind,
                "title": title,
                "purpose": _template_purpose(text),
            })
    out.sort(key=lambda t: t["name"])
    return out


def build_gallery_html(presets_dir=PRESETS_DIR, templates_dir=TEMPLATES_DIR):
    """The gallery page: one self-contained, deterministic HTML string."""
    preset_blocks = []
    for meta in list_presets(presets_dir):
        _, files, _ = load_preset(presets_dir, meta["name"])
        file_items = "".join(
            f"<li><code>{html.escape(f)}</code></li>" for f in files)
        preset_blocks.append(
            "<section class=\"preset\">\n"
            f"<h2>{html.escape(meta.get('title', meta['name']))}</h2>\n"
            f"<p class=\"name\"><code>{html.escape(meta['name'])}</code></p>\n"
            f"<p>{html.escape(meta.get('description', ''))}</p>\n"
            f"<p><em>Best for:</em> {html.escape(meta.get('best_for', ''))}</p>\n"
            f"<ul>{file_items}</ul>\n</section>"
        )
    template_rows = "".join(
        "<tr><td><code>{name}</code></td><td>{kind}</td>"
        "<td>{title}</td><td>{purpose}</td></tr>".format(
            name=html.escape(t["name"]), kind=html.escape(t["kind"]),
            title=html.escape(t["title"]),
            purpose=html.escape(t["purpose"]))
        for t in list_templates(templates_dir)
    )
    return (
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>Wiki presets and templates gallery</title>\n<style>\n"
        "body { font-family: sans-serif; margin: 2em; max-width: 60em; }\n"
        "table { border-collapse: collapse; }\n"
        "td, th { padding: 0.25em 0.75em; text-align: left; "
        "vertical-align: top; }\n</style>\n</head>\n<body>\n"
        "<h1>Wiki presets and templates gallery</h1>\n"
        "<p>Every preset and page template in this installation, "
        "generated offline from the files themselves.</p>\n"
        + "\n".join(preset_blocks)
        + "\n<h2>Page templates</h2>\n<table>\n"
        + "<tr><th>Template</th><th>Kind</th><th>Title</th>"
        + "<th>Purpose</th></tr>\n"
        + template_rows
        + "\n</table>\n</body>\n</html>\n"
    )


def write_gallery(out_path, presets_dir=PRESETS_DIR,
                  templates_dir=TEMPLATES_DIR):
    """Write the gallery to *out_path*; return a small summary dict."""
    page = build_gallery_html(presets_dir, templates_dir)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return {"out": str(out), "presets": len(list_presets(presets_dir)),
            "templates": len(list_templates(templates_dir))}


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
    g = sub.add_parser("gallery")
    g.add_argument("--out", required=True)
    g.add_argument("--templates-dir", default=None)
    args = ap.parse_args(argv)
    try:
        if args.cmd == "gallery":
            templates_dir = args.templates_dir or TEMPLATES_DIR
            summary = write_gallery(args.out, PRESETS_DIR, templates_dir)
            print(json.dumps(summary, indent=2))
            return 0
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
