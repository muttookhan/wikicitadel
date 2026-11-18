#!/usr/bin/env python3
"""wiki_mdbook_print.py — mdBook print artefact for a declared set.

Marathon R11 lane BB (ideas board line 160, Tier A; mdBook
pattern — mdBook, MPL-2.0, external prebuilt binary). Builds a
book-form print artefact from the DECLARED page set in
evaluation/mdbook-print-pages.json: the pages are staged as a
minimal mdBook (book.toml + src/SUMMARY.md + the pages' bodies,
frontmatter stripped, wikilinks left verbatim — mdBook does not
resolve them and the manifest says so), `mdbook build` renders
it, and mdBook's own print page (print.html — the single-page
print view mdBook generates for every book) is copied out as
THE print artefact beside its manifest. The binary lives
OUTSIDE the trees; the staged book source lives in the work
dir (outside the trees); in-tree deliverables are this script,
the declared set, the manifest, and the artefact.

If the binary cannot be obtained, the manifest records the
exact door failure and the command exits 2 — no artefact is
claimed. Regeneration: same command, same declared set.

Usage:
  build --pages-file FILE --mdbook PATH --work DIR
        --out-dir DIR --manifest FILE [--root DIR]
Exit 0 artefact built; 1 a declared page is missing; 2 door
failure (binary). Stdlib only (this wrapper).
"""
import argparse, hashlib, json, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FM_RE = re.compile(r"\A---\n.*?\n---\n", re.S)


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def body_of(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    m = FM_RE.match(text)
    return text[m.end():] if m else text


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--pages-file", required=True)
    b.add_argument("--mdbook", required=True)
    b.add_argument("--work", required=True)
    b.add_argument("--out-dir", required=True)
    b.add_argument("--manifest", required=True)
    b.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    root = Path(a.root)
    declared = json.loads(Path(a.pages_file).read_text(
        encoding="utf-8"))
    pages = declared["pages"]
    man = {"tool": "mdbook-print", "declared_set": pages,
           "built": False}
    exe = Path(a.mdbook)
    if not exe.is_file():
        man["door_failure"] = {
            "stage": "obtain",
            "command": f"{a.mdbook} build",
            "error": f"mdbook binary not found: {a.mdbook}"}
        Path(a.manifest).write_text(json.dumps(man, indent=2) +
                                    "\n", encoding="utf-8")
        return 2
    ver = subprocess.run([str(exe), "--version"], capture_output=True,
                         text=True)
    man["mdbook_version"] = ver.stdout.strip()
    work = Path(a.work)
    src = work / "src"
    if work.exists():
        shutil.rmtree(work)
    src.mkdir(parents=True)
    entries = []
    summary = ["# Summary", ""]
    for i, rel in enumerate(pages):
        page = root / rel
        if not page.is_file():
            man["door_failure"] = {"stage": "stage",
                "error": f"declared page missing: {rel}"}
            Path(a.manifest).write_text(json.dumps(man, indent=2) +
                                        "\n", encoding="utf-8")
            return 1
        name = f"ch{i+1:02d}-{page.stem}.md"
        (src / name).write_text(body_of(page), encoding="utf-8")
        title = page.stem.replace("-", " ")
        summary.append(f"- [{title}]({name})")
        entries.append({"page": rel, "chapter": name,
                        "source_sha256": sha256(page)})
    (src / "SUMMARY.md").write_text("\n".join(summary) + "\n",
                                    encoding="utf-8")
    (work / "book.toml").write_text(
        '[book]\ntitle = "Wiki print artefact — declared set"\n'
        'language = "en"\n\n[output.html]\n', encoding="utf-8")
    dest = work / "book"
    proc = subprocess.run([str(exe), "build", "--dest-dir",
                           str(dest), str(work)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        man["door_failure"] = {"stage": "build",
            "command": f"{a.mdbook} build --dest-dir {dest} {work}",
            "error": (proc.stderr or proc.stdout)[-800:]}
        Path(a.manifest).write_text(json.dumps(man, indent=2) +
                                    "\n", encoding="utf-8")
        return 2
    print_html = dest / "print.html"
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    artefact = out_dir / "print.html"
    shutil.copyfile(print_html, artefact)
    man.update({"built": True, "pages": entries,
                "artefact": str(artefact),
                "artefact_sha256": sha256(artefact),
                "artefact_bytes": artefact.stat().st_size,
                "known_loss": "wikilinks are carried verbatim; "
                    "mdBook does not resolve [[wikilinks]], "
                    "callouts or claim markers — see the export "
                    "loss inventory (scripts/wiki_export_loss.py)",
                "wrapper": "scripts/wiki_mdbook_print.py build"})
    Path(a.manifest).write_text(json.dumps(man, indent=2) + "\n",
                                encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
