#!/usr/bin/env python3
"""The zenn-cli shape for this wiki (Marathon Round 4, lane B).

Pattern: zenn-dev/zenn-editor (the Zenn CLI, MIT) -- write
Markdown locally, preview locally, publish by git push. A thin
CLI convention over what this wiki already does; re-implemented
in our own code, no code copied. The three acts:

  check    validate a page (or a set of pages, or the whole
           wiki/ layer when none are named) BEFORE pushing:
           frontmatter complete, type/dates sane, sources
           resolve, wikilinks resolve, claim citations in range.
           All of the machinery is REUSED from
           scripts/wiki_validate.py by import -- its frontmatter
           parser, its Resolvers, its required-field and type
           vocabularies, its claim-citation checker. Nothing is
           duplicated here; this command is the validator's
           per-page front door, scoped to the pages about to be
           published instead of the whole corpus + coverage +
           secrets sweep the full validator runs.
  preview  render one page to a standalone HTML file in an
           output directory, using the Lens renderer
           (tools/lens/lenslib.py render_markdown) when present,
           with a small built-in fallback renderer when it is
           not (fixture trees, partial copies).
  push     a GUARDED wrapper: runs check first; on failure it
           reports and exits 1 without printing a plan. On
           success it prints the EXACT git commands that would
           publish the checked pages -- and does NOT run them.
           Publishing stays the coordinator's act; this tool
           never pushes, commits, or stages anything.

Usage:
  python3 scripts/wiki_publish.py [--root DIR] check [PAGE ...]
  python3 scripts/wiki_publish.py [--root DIR] preview PAGE
          [--out DIR]
  python3 scripts/wiki_publish.py [--root DIR] push [PAGE ...]

PAGE arguments are repo-relative paths (wiki/...) or paths on
disk. Exit codes: 0 clean / rendered / plan printed, 1 when
check finds errors (or the page cannot be rendered), 2 on
usage error. Stdlib only (the Lens renderer itself imports
PyYAML, as the Lens already does; the fallback needs nothing).
"""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------ validator

def load_validator(root: Path):
    """Import scripts/wiki_validate.py from *root* and re-point
    its module globals at *root*, so fixture trees validate
    against themselves. Returns the module."""
    path = root / "scripts" / "wiki_validate.py"
    if not path.is_file():
        raise FileNotFoundError(f"validator not found: {path}")
    spec = importlib.util.spec_from_file_location(
        "wiki_validate_for_publish", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    mod.WIKI = root / "wiki"
    mod.RAW = root / "raw"
    mod.RAW_SOURCES = root / "raw" / "sources"
    mod._line_counts = {}
    return mod


def page_rel(root: Path, page) -> str:
    p = Path(page)
    if not p.is_absolute():
        p = root / p
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def check_page(root: Path, rel: str, wv, resolvers):
    """Validate one page with the validator's own machinery.
    Returns (errors, warnings): lists of (kind, detail)."""
    errors, warnings = [], []
    if rel in wv.STRUCTURAL:
        return errors, warnings  # structural: catalog/log, exempt
    path = root / rel
    if not path.is_file():
        return [("missing page", f"{rel} is not on disk")], warnings
    text = path.read_text(encoding="utf-8", errors="ignore")
    fields, body = wv.parse_frontmatter(text)
    if fields is None:
        return [("missing frontmatter", "no --- frontmatter block")], \
            warnings
    missing = [n for n in wv.REQUIRED_FIELDS
               if n not in fields or fields[n] is None
               or fields[n] == ""]
    for name in missing:
        errors.append(("missing field",
                       f"required field '{name}' is absent or empty"))
    if missing:
        return errors, warnings
    ptype = fields["type"]
    if isinstance(ptype, list) or ptype not in wv.ALLOWED_TYPES:
        errors.append(("bad type",
                       f"type {ptype!r} not in {sorted(wv.ALLOWED_TYPES)}"))
    created = wv.parse_date(fields["created"])
    updated = wv.parse_date(fields["updated"])
    for name, val, parsed in (("created", fields["created"], created),
                              ("updated", fields["updated"], updated)):
        if parsed is None:
            errors.append(("bad date", f"{name} {val!r} is not an ISO date"))
    if created and updated and updated < created:
        warnings.append(("date order",
                         f"updated {updated} is before created {created}"))
    for entry in wv.as_list(fields.get("sources")):
        st, _resolved, detail = resolvers.resolve_source(entry)
        if st == "missing":
            errors.append(("source not on disk", f"{entry} ({detail})"))
        elif st == "unresolvable":
            errors.append(("unresolvable source slug",
                           f"{entry} ({detail})"))
        elif st == "ambiguous":
            warnings.append(("ambiguous source slug",
                             f"{entry} -> {detail}"))
        elif st == "ok" and detail:
            warnings.append(("source outside raw/", f"{entry} ({detail})"))
    for target in wv.LINK_RE.findall(wv.strip_code(body)):
        target = target.strip()
        if not target:
            continue
        st, detail = resolvers.resolve_link(target)
        if st == "broken":
            errors.append(("broken wikilink", f"[[{target}]]"))
        elif st == "ambiguous":
            warnings.append(("ambiguous wikilink",
                             f"[[{target}]] ({detail})"))
    cite_errors = []
    wv.check_claim_citations(rel, body, cite_errors)
    errors.extend((kind, detail) for _p, kind, detail in cite_errors)
    return errors, warnings


def run_check(root: Path, pages):
    """Check *pages* (repo-relative list; empty = whole wiki/).
    Returns (report, exit_code). report: {page: {errors, warnings}}
    with errors/warnings as [kind, detail] pairs."""
    wv = load_validator(root)
    resolvers = wv.Resolvers()
    if not pages:
        pages = sorted(p.relative_to(root).as_posix()
                       for p in (root / "wiki").rglob("*.md")
                       if p.is_file())
    report = {}
    n_errors = 0
    for rel in pages:
        errors, warnings = check_page(root, rel, wv, resolvers)
        report[rel] = {"errors": [list(e) for e in errors],
                       "warnings": [list(w) for w in warnings]}
        n_errors += len(errors)
    return report, (1 if n_errors else 0)


def print_check_report(report):
    n_err = n_warn = 0
    for rel, res in report.items():
        for kind, detail in res["errors"]:
            print(f"  ERROR   [{kind}] {rel}: {detail}")
            n_err += 1
        for kind, detail in res["warnings"]:
            print(f"  warning [{kind}] {rel}: {detail}")
            n_warn += 1
    print(f"check: {len(report)} page(s), {n_err} error(s), "
          f"{n_warn} warning(s)")
    print("Result:", "FAIL" if n_err else "PASS")


# -------------------------------------------------------------- preview

def load_lenslib(root: Path):
    path = root / "tools" / "lens" / "lenslib.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "lenslib_for_publish", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def fallback_render(body: str) -> str:
    """A small standalone renderer used only when the Lens
    renderer is unavailable: headings, paragraphs, lists, code
    fences, wikilinks shown as bracketed spans. Everything is
    HTML-escaped first; this is a preview, not a publisher."""
    out, para, in_fence = [], [], False

    def flush():
        if para:
            out.append("<p>" + " ".join(para) + "</p>")
            para.clear()

    for line in body.splitlines():
        if line.strip().startswith("```"):
            flush()
            out.append("</code></pre>" if in_fence else "<pre><code>")
            in_fence = not in_fence
            continue
        if in_fence:
            out.append(html.escape(line))
            continue
        esc = html.escape(line)
        esc = re.sub(r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]",
                     lambda m: f"<span class=\"wikilink\">"
                               f"{m.group(2) or m.group(1)}</span>", esc)
        m = re.match(r"^(#{1,6})\s+(.*)$", esc)
        if m:
            flush()
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{m.group(2)}</h{lvl}>")
        elif re.match(r"^\s*[-*]\s+", esc):
            flush()
            out.append("<ul><li>" + re.sub(r"^\s*[-*]\s+", "", esc)
                       + "</li></ul>")
        elif not esc.strip():
            flush()
        else:
            para.append(esc)
    flush()
    if in_fence:
        out.append("</code></pre>")
    return "\n".join(out)


def render_preview(root: Path, rel: str, out_dir: Path) -> Path:
    """Render one page to a standalone HTML file in *out_dir*.
    Returns the written path."""
    path = root / rel
    if not path.is_file():
        raise FileNotFoundError(f"page not on disk: {rel}")
    wv = load_validator(root)
    fields, body = wv.parse_frontmatter(
        path.read_text(encoding="utf-8", errors="ignore"))
    if fields is None:
        fields, body = {}, path.read_text(encoding="utf-8",
                                         errors="ignore")
    title = fields.get("title") or path.stem
    lens = load_lenslib(root)
    if lens is not None:
        rendered = lens.render_markdown(body)
        # lenslib.render_markdown returns (html, wikilinks):
        # the preview embeds the HTML fragment; the wikilink
        # route map is the Lens build's job, not a local
        # preview's.
        fragment = rendered[0] if isinstance(rendered, tuple) \
            else rendered
    else:
        fragment = fallback_render(body)
    doc = ("<!doctype html>\n<html lang=\"en\">\n<head>\n"
           "<meta charset=\"utf-8\">\n"
           f"<title>{html.escape(str(title))} — wiki preview</title>\n"
           "</head>\n<body>\n"
           f"<!-- local preview of {html.escape(rel)}; "
           "not published -->\n"
           + fragment + "\n</body>\n</html>\n")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (path.stem + ".html")
    out_path.write_text(doc, encoding="utf-8")
    return out_path


# ----------------------------------------------------------------- push

def push_plan(root: Path, pages):
    """The exact git commands that would publish *pages*.
    Returned, never executed."""
    rels = pages or ["wiki/"]
    add_targets = " ".join(rels)
    return [
        f"git -C {root} add -- {add_targets}",
        f"git -C {root} commit -m \"wiki: publish "
        f"{len(rels)} page(s)\"",
        f"git -C {root} push",
    ]


# ------------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="zenn-cli shape for this wiki: check / preview "
                    "/ push (guarded; never pushes itself).")
    ap.add_argument("--root", default=str(DEFAULT_ROOT),
                    help="repo root (default: the tree this script "
                         "lives in)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate pages pre-push")
    c.add_argument("pages", nargs="*", help="pages (default: all "
                                            "of wiki/)")
    c.add_argument("--json", action="store_true")
    pv = sub.add_parser("preview", help="render one page to HTML")
    pv.add_argument("page")
    pv.add_argument("--out", default=None,
                    help="output dir (default: a fresh temp dir)")
    pu = sub.add_parser("push", help="check, then print the git "
                                     "commands (never runs them)")
    pu.add_argument("pages", nargs="*")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if args.cmd == "check":
        pages = [page_rel(root, p) for p in args.pages]
        report, code = run_check(root, pages)
        if args.json:
            print(json.dumps(report, indent=1, ensure_ascii=False))
        else:
            print_check_report(report)
        return code
    if args.cmd == "preview":
        rel = page_rel(root, args.page)
        out_dir = Path(args.out) if args.out else Path(
            tempfile.mkdtemp(prefix="wiki-preview-"))
        try:
            out_path = render_preview(root, rel, out_dir)
        except FileNotFoundError as e:
            print(f"preview: {e}", file=sys.stderr)
            return 1
        print(f"preview: {rel} -> {out_path}")
        return 0
    if args.cmd == "push":
        pages = [page_rel(root, p) for p in args.pages]
        report, code = run_check(root, pages)
        print_check_report(report)
        if code:
            print("push: ABORTED — check failed; nothing staged, "
                  "nothing pushed.")
            return 1
        print("push: check passed. The exact commands to publish "
              "(NOT executed — publishing is the coordinator's "
              "act):")
        for cmd in push_plan(root, pages):
            print(f"  {cmd}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
