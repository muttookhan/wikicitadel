#!/usr/bin/env python3
"""wiki_slice_export.py — single-file wiki-slice export.

Wave 6 build item "Single-file wiki-slice export (quine
pattern)" (owner directive 2026-10-22: implement the research
ideas in both wikis). Idea sources: Alamantus/FeatherWiki and
the TiddlyWiki single-file pattern — app plus content in ONE
portable HTML file that opens anywhere with no server. Clean
re-implementation: no code from either project; the pattern
(one file, everything inline) is the idea taken.

A SLICE is a declared subset of the compiled layer, chosen
exactly one way per export:

  --tag TAG            pages carrying the frontmatter tag
  --folder SECTION     pages under wiki/<SECTION>/ (a deeper
                       prefix such as sources/deep works too)
  --seed PAGE --hops N the seed page plus every page within
                       N hops of it in the page graph
                       (undirected: outbound links and inbound
                       citations both count as one hop)
  --pages a,b,c        an explicit page list (ids, paths or
                       stems, resolved like the other doors)
  --all                the whole compiled layer

The compiled layer is the house set (scripts/wiki_export.py's
page_paths, reused by import): wiki/**/*.md minus wiki/access/
and wiki/talk/ minus the structural index.md / log.md at the
wiki root. Page loading, link resolution and the page graph
are likewise wiki_export.py's, and page bodies are rendered by
the Lens's own renderer (tools/lens/lenslib.py render_markdown,
imported in-process the same way), so a slice can never
disagree with the other doors about what a page says or links
to. Where the Lens build adds live evaluation on top of that
renderer (wiki-query blocks, Mermaid figures), the slice shows
the block's source text — a slice is a snapshot of the pages
as written, not a Lens rebuild.

The output is ONE self-contained HTML file:

  * every slice page rendered as an <article>, in path order;
  * a wikilink whose target is IN the slice becomes an in-file
    anchor (#page-...); a wikilink whose target is a corpus
    page OUTSIDE the slice becomes a visibly marked boundary
    reference (dashed chip, never a dead anchor); a wikilink
    that resolves to no page at all becomes a missing-page
    chip, exactly as the Lens marks it;
  * external Markdown links stay links (they fetch nothing);
  * images: a local image file at or under --max-image-bytes
    is inlined as a data URI; an external image, an oversized
    local image, or a missing local file is replaced in place
    by an "image omitted" note and listed in the manifest —
    the file never triggers a fetch at view time;
  * a manifest header (visible, plus the same data as an
    embedded JSON block) stating the slice spec, the corpus
    commit the export was taken from, exactly which pages are
    included, every boundary reference (target page + the
    slice pages that link to it), every unresolved link
    target, every asset disposition, and how many compiled
    pages the spec left out;
  * all CSS and the one small filter script are inline. There
    is no timestamp anywhere in the output: the same corpus
    state and the same spec produce byte-identical bytes (the
    corpus commit id is data, and is the only state marker).

The export is a derived artefact: it reads the corpus and
writes only the --out file. Exit codes: 0 exported · 2 usage
or selection error (unknown page, empty slice, bad spec).

    python3 scripts/wiki_slice_export.py --tag knowledge-base
    python3 scripts/wiki_slice_export.py --seed llm-wiki --hops 1 \
        --out exports/slice-llm-wiki.html
"""
from __future__ import annotations

import argparse
import base64
import html
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

DEFAULT_MAX_IMAGE_BYTES = 262144  # 256 KiB per inlined image

IMAGE_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".bmp": "image/bmp",
    ".ico": "image/x-icon",
}


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WX = _load_module("wiki_export", SCRIPTS / "wiki_export.py")
LENSLIB = _WX.LENSLIB
if LENSLIB is None:
    raise SystemExit(
        "wiki_slice_export: tools/lens/lenslib.py could not be "
        "loaded (it needs PyYAML, the repo's declared tooling "
        "dependency); the slice renderer is the Lens's own, so "
        "there is no fallback renderer to ship instead.")


# ------------------------------------------------------------ corpus state

def corpus_state(root: Path) -> dict:
    """{commit, dirty} from git at the root, or commit None
    with the reason recorded when git cannot answer — never
    a guessed state."""
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, timeout=30)
    try:
        head = git("rev-parse", "HEAD")
        if head.returncode != 0:
            return {"commit": None, "dirty": None,
                    "note": "not a git checkout (git rev-parse "
                            "failed); corpus state unrecorded"}
        status = git("status", "--porcelain")
        dirty = bool(status.stdout.strip()) \
            if status.returncode == 0 else None
        return {"commit": head.stdout.strip(), "dirty": dirty,
                "note": None}
    except Exception as exc:  # git missing, timeout, ...
        return {"commit": None, "dirty": None,
                "note": f"git unavailable ({exc}); corpus state "
                        "unrecorded"}


# ------------------------------------------------------------ slice choice

def select_slice(root: Path, spec: dict):
    """(pages, keys, edges, chosen) — chosen is the sorted list
    of repo-relative page ids the spec selects. Raises
    ValueError with a human message on a bad spec."""
    pages, keys, edges = _WX.build_graph(root)
    mode = spec["mode"]
    if mode == "all":
        chosen = sorted(pages)
    elif mode == "tag":
        tag = spec["tag"].lower()
        chosen = sorted(
            rel for rel, rec in pages.items()
            if tag in [str(t).lower()
                       for t in _WX.as_list(rec["fields"].get("tags"))])
    elif mode == "folder":
        folder = spec["folder"].strip("/")
        chosen = sorted(
            rel for rel in pages
            if (rel[len("wiki/"):-3].rsplit("/", 1)[0]
                if "/" in rel[len("wiki/"):-3] else "") == folder
            or rel[len("wiki/"):].startswith(folder + "/"))
    elif mode == "pages":
        chosen, bad = [], []
        for name in spec["pages"]:
            hit = _WX.resolve_page(keys, name)
            if hit is None:
                bad.append(name)
            elif hit not in chosen:
                chosen.append(hit)
        if bad:
            raise ValueError(
                "page(s) not found in the compiled layer: "
                + ", ".join(bad))
        chosen.sort()
    elif mode == "seed":
        seed = _WX.resolve_page(keys, spec["seed"])
        if seed is None:
            raise ValueError(
                f"seed page not found in the compiled layer: "
                f"{spec['seed']}")
        hops = spec["hops"]
        adj = {}
        for e in edges:
            adj.setdefault(e["source"], set()).add(e["target"])
            adj.setdefault(e["target"], set()).add(e["source"])
        seen, frontier = {seed}, {seed}
        for _ in range(hops):
            nxt = set()
            for node in frontier:
                nxt |= adj.get(node, set())
            nxt -= seen
            seen |= nxt
            frontier = nxt
            if not frontier:
                break
        chosen = sorted(seen)
    else:  # pragma: no cover - argparse constrains the modes
        raise ValueError(f"unknown slice mode: {mode}")
    if not chosen:
        raise ValueError(
            f"the slice is empty under this spec ({spec}); "
            "refusing to export an empty file")
    return pages, keys, edges, chosen


# ------------------------------------------------------------ anchors

def page_anchor(rel: str, taken: set) -> str:
    """Deterministic in-file anchor for a page id:
    wiki/concepts/llm-wiki.md -> page-concepts-llm-wiki.
    Collisions (names differing only by punctuation) take a
    numeric suffix in sorted page order."""
    stem = rel[len("wiki/"):-3] if rel.startswith("wiki/") \
        and rel.endswith(".md") else rel
    base = "page-" + re.sub(r"[^a-z0-9]+", "-",
                            stem.lower()).strip("-")
    anchor, n = base, 2
    while anchor in taken:
        anchor = f"{base}-{n}"
        n += 1
    taken.add(anchor)
    return anchor


# ------------------------------------------------------------ rendering

_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc=\"([^\"]*)\"[^>]*?>")
_HEADING_ID_RE = re.compile(r"(<h[1-6] id=\")([^\"]+)(\")")
_WL_PH_RE = re.compile("\x00WL(\\d+)\x00")


def _resolve_image(root: Path, page_rel: str, src: str,
                   max_bytes: int):
    """(kind, payload) for one rendered <img src>:
    ("inline", (data-uri, file-bytes)) · ("omit", reason)."""
    if re.match(r"^(https?:)?//", src) or src.startswith("data:"):
        return "omit", "external image — not fetched, not inlined"
    raw = src.split("#", 1)[0].split("?", 1)[0]
    cands = []
    if raw.startswith("/"):
        cands.append(root / raw.lstrip("/"))
    else:
        cands.append((root / page_rel).parent / raw)
        cands.append(root / raw)
    path = next((c for c in cands if c.is_file()), None)
    if path is None:
        return "omit", f"local image file not found ({src})"
    mime = IMAGE_MIME.get(path.suffix.lower())
    if mime is None:
        return "omit", f"not an inlinable image type ({path.suffix})"
    size = path.stat().st_size
    if size > max_bytes:
        return "omit", (f"local image over the inline cap "
                        f"({size} bytes > {max_bytes})")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return "inline", (f"data:{mime};base64,{data}", size)


def render_page(root: Path, rel: str, rec: dict, keys: dict,
                anchors: dict, max_image_bytes: int,
                census: dict):
    """Render one page to article HTML, resolving its wikilink
    placeholders against the slice, and fold its link/image
    outcomes into the census (boundary / unresolved / assets)
    the manifest is built from."""
    anchor = anchors[rel]
    body_html, wikilinks = LENSLIB.render_markdown(rec["body"])

    # Namespace this page's heading ids so in-file anchors
    # cannot collide across pages.
    body_html = _HEADING_ID_RE.sub(
        lambda m: f"{m.group(1)}{anchor}--{m.group(2)}{m.group(3)}",
        body_html)

    def sub(m):
        target, link_anchor, label = wikilinks[int(m.group(1))]
        label_e = html.escape(label)
        hit = _WX._resolve_link(keys, target)
        if hit is not None and hit in anchors:
            href = f"#{anchors[hit]}"
            if link_anchor:
                href += f"--{LENSLIB.slugify(link_anchor)}"
            return f'<a class="wl" href="{href}">{label_e}</a>'
        if hit is not None:
            census["boundary"].setdefault(hit, {}).setdefault(
                rel, 0)
            census["boundary"][hit][rel] += 1
            title = html.escape(
                census["titles"].get(hit, hit), quote=True)
            return (f'<span class="wl-boundary" title="Links to '
                    f'&ldquo;{title}&rdquo; ({html.escape(hit, quote=True)})'
                    f' — outside this slice">{label_e}</span>')
        census["unresolved"].setdefault(target, set()).add(rel)
        return (f'<span class="wl-missing" title="No page exists '
                f'for this link yet">{label_e}</span>')

    body_html = _WL_PH_RE.sub(sub, body_html)

    def img_sub(m):
        whole, src = m.group(0), m.group(1)
        kind, payload = _resolve_image(
            root, rel, src, max_image_bytes)
        if kind == "inline":
            uri, nbytes = payload
            census["assets_inlined"].append(
                {"page": rel, "src": src, "bytes": nbytes})
            return whole.replace(
                f'src="{src}"', f'src="{uri}"', 1)
        census["assets_omitted"].append(
            {"page": rel, "src": src, "reason": payload})
        alt = re.search(r'alt="([^"]*)"', whole)
        alt_t = alt.group(1) if alt else ""
        return (f'<span class="img-omitted">[image omitted from '
                f'slice export: {html.escape(alt_t)} — '
                f'{html.escape(payload)}]</span>')

    body_html = _IMG_RE.sub(img_sub, body_html)
    return body_html


# ------------------------------------------------------------ document

_CSS = """
body{font-family:Georgia,'Times New Roman',serif;margin:0 auto;
max-width:52rem;padding:1.5rem 1rem 4rem;line-height:1.55;color:#1a1a1a}
header.manifest{border:2px solid #444;padding:1rem 1.25rem;
background:#faf7f0;margin-bottom:2rem}
header.manifest h1{font-size:1.4rem;margin:.2rem 0 .6rem}
header.manifest h2{font-size:1.05rem;margin:1rem 0 .3rem}
header.manifest ul{margin:.2rem 0 .6rem;padding-left:1.4rem}
header.manifest code,article code{background:#eee;padding:0 .25em}
.spec{font-family:ui-monospace,Menlo,monospace;font-size:.9em}
nav.slice-index{columns:2;column-gap:2rem;font-size:.95rem}
nav.slice-index li{break-inside:avoid}
article{border-top:1px solid #bbb;padding-top:1rem;margin-top:2.5rem}
article>header h2{margin-bottom:.15rem}
.pagemeta{color:#555;font-size:.9rem;margin-top:0}
a.wl{color:#0b5394}
.wl-boundary{border-bottom:2px dashed #b8860b;background:#fdf6e0;
padding:0 .15em;cursor:help}
.wl-boundary::after{content:" ⧉";color:#b8860b;font-size:.85em}
.wl-missing{color:#a00;border-bottom:1px dotted #a00;cursor:help}
.img-omitted{display:inline-block;border:1px dashed #999;color:#555;
padding:.4rem .6rem;font-size:.9rem;background:#f4f4f4}
figure.page-figure img{max-width:100%}
table{border-collapse:collapse}
th,td{border:1px solid #bbb;padding:.25rem .5rem}
pre{background:#f4f4f4;padding:.6rem;overflow-x:auto}
#filter{width:100%;padding:.5rem;font-size:1rem;margin:.5rem 0 1rem}
.hidden{display:none}
""".strip()

_JS = """
document.getElementById('filter').addEventListener('input',function(){
var q=this.value.toLowerCase();
document.querySelectorAll('article.page').forEach(function(a){
a.classList.toggle('hidden',q&&a.textContent.toLowerCase().indexOf(q)<0);
});});
""".strip()


def build_slice_html(root: Path, spec: dict, name: str,
                     max_image_bytes: int):
    """(html_text, manifest dict) for one slice export."""
    pages, keys, edges, chosen = select_slice(root, spec)
    chosen_set = set(chosen)
    state = corpus_state(root)

    anchors, taken = {}, set()
    for rel in chosen:
        anchors[rel] = page_anchor(rel, taken)

    census = {"boundary": {}, "unresolved": {},
              "assets_inlined": [], "assets_omitted": [],
              "titles": {rel: rec["title"]
                         for rel, rec in pages.items()}}

    # Boundary references also arrive through the graph's
    # declared edges (frontmatter links:/relation fields), not
    # only body wikilinks; the census counts an edge once,
    # under its target, whichever door found it.
    edge_boundary = {}
    for e in edges:
        if e["source"] in chosen_set and e["target"] not in chosen_set:
            edge_boundary.setdefault(e["target"], set()).add(
                e["source"])

    articles = []
    for rel in chosen:
        rec = pages[rel]
        body_html = render_page(
            root, rel, rec, keys, anchors, max_image_bytes, census)
        fields = rec["fields"]
        meta_bits = [f"<code>{html.escape(rel)}</code>"]
        for key in ("type", "stage", "status"):
            if fields.get(key):
                meta_bits.append(
                    f"{key}: {html.escape(str(fields[key]))}")
        tags = [str(t) for t in _WX.as_list(fields.get("tags"))]
        if tags:
            meta_bits.append("tags: " + ", ".join(
                html.escape(t) for t in tags))
        articles.append(
            f'<article class="page" id="{anchors[rel]}">\n'
            f"<header><h2>{html.escape(rec['title'])}</h2>\n"
            f'<p class="pagemeta">{" · ".join(meta_bits)}</p>'
            f"</header>\n{body_html}\n</article>")

    # Merge the two boundary censuses: body occurrences keep
    # their counts; declared-edge-only sources join with a 0
    # body count (the manifest records sources, not tallies,
    # per target — counts are in the per-source map).
    boundary = []
    for target in sorted(set(census["boundary"]) | set(edge_boundary)):
        sources = {}
        for src in sorted(edge_boundary.get(target, set())):
            sources[src] = census["boundary"].get(
                target, {}).get(src, 0)
        for src, n in sorted(census["boundary"].get(target, {}).items()):
            sources[src] = n
        boundary.append({
            "target": target,
            "title": census["titles"].get(target, target),
            "linked_from": sources,
        })
    unresolved = [
        {"target": t, "linked_from": sorted(srcs)}
        for t, srcs in sorted(census["unresolved"].items())]
    assets_inlined = sorted(
        census["assets_inlined"],
        key=lambda a: (a["page"], a["src"]))
    assets_omitted = sorted(
        census["assets_omitted"],
        key=lambda a: (a["page"], a["src"]))

    manifest = {
        "tool": "scripts/wiki_slice_export.py",
        "kind": "wiki-slice-export",
        "slice": {"name": name, "spec": spec},
        "corpus": {
            "commit": state["commit"],
            "dirty_working_tree": state["dirty"],
            "state_note": state["note"],
            "compiled_pages_total": len(pages),
            "compiled_layer": "wiki/**/*.md minus wiki/access/, "
                              "wiki/talk/, wiki/index.md, "
                              "wiki/log.md",
        },
        "pages": [{"id": rel, "title": pages[rel]["title"],
                   "anchor": anchors[rel]} for rel in chosen],
        "pages_included": len(chosen),
        "pages_left_out_by_spec": len(pages) - len(chosen),
        "boundary_references": boundary,
        "unresolved_targets": unresolved,
        "assets": {"inlined": assets_inlined,
                   "omitted": assets_omitted},
    }

    spec_text = html.escape(json.dumps(spec, sort_keys=True))
    commit = state["commit"] or "unrecorded"
    dirty_note = ""
    if state["dirty"]:
        dirty_note = (" — the working tree had uncommitted "
                      "changes when this export was taken")
    elif state["note"]:
        dirty_note = f" — {html.escape(state['note'])}"
    index_items = "\n".join(
        f'<li><a href="#{anchors[rel]}">'
        f'{html.escape(pages[rel]["title"])}</a> '
        f'<code>{html.escape(rel)}</code></li>' for rel in chosen)
    boundary_items = "\n".join(
        f"<li><strong>{html.escape(b['title'])}</strong> "
        f"<code>{html.escape(b['target'])}</code> — linked from "
        + ", ".join(f"<code>{html.escape(s)}</code>"
                    for s in b["linked_from"])
        + "</li>" for b in boundary) or "<li>none</li>"
    unresolved_items = "\n".join(
        f"<li><code>{html.escape(u['target'])}</code> — linked "
        f"from " + ", ".join(
            f"<code>{html.escape(s)}</code>"
            for s in u["linked_from"]) + "</li>"
        for u in unresolved) or "<li>none</li>"
    omitted_items = "\n".join(
        f"<li><code>{html.escape(a['src'])}</code> on "
        f"<code>{html.escape(a['page'])}</code> — "
        f"{html.escape(a['reason'])}</li>"
        for a in assets_omitted) or "<li>none</li>"
    manifest_json = html.escape(
        json.dumps(manifest, indent=2, sort_keys=True))
    # The <script type="application/json"> copy must stay
    # parseable JSON: no HTML escaping there, only the
    # standard \u003c guard against a literal "</script>"
    # appearing inside a string value.
    manifest_json_raw = json.dumps(
        manifest, indent=2, sort_keys=True).replace(
            "<", "\\u003c")

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wiki slice: {html.escape(name)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<header class="manifest">
<h1>Wiki slice: {html.escape(name)}</h1>
<p>A single-file, read-only export of a declared slice of the
wiki. It opens offline; nothing in it is fetched at view time.
Links marked <span class="wl-boundary">like this</span> point
to pages that exist in the wiki but are outside this slice —
they are listed under Boundary references below instead of
pretending to work.</p>
<p class="spec">Slice spec: {spec_text}<br>
Corpus commit: <code>{html.escape(commit)}</code>{dirty_note}<br>
Pages included: {len(chosen)} of {len(pages)} compiled pages
({len(pages) - len(chosen)} left out by the spec; the compiled
layer itself excludes wiki/access/, wiki/talk/, wiki/index.md
and wiki/log.md).</p>
<h2>Pages in this slice</h2>
<nav class="slice-index"><ul>
{index_items}
</ul></nav>
<h2>Boundary references (in the wiki, outside this slice)</h2>
<ul>
{boundary_items}
</ul>
<h2>Unresolved link targets (no page exists)</h2>
<ul>
{unresolved_items}
</ul>
<h2>Images omitted (not inlined)</h2>
<ul>
{omitted_items}
</ul>
<details><summary>Machine-readable manifest (JSON)</summary>
<pre id="slice-manifest-json">{manifest_json}</pre>
</details>
</header>
<input id="filter" type="search" placeholder="Filter pages by text…" aria-label="Filter pages by text">
<main>
{chr(10).join(articles)}
</main>
<script type="application/json" id="slice-manifest">{manifest_json_raw}</script>
<script>
{_JS}
</script>
</body>
</html>
"""
    return doc, manifest


# ------------------------------------------------------------ CLI

def _default_name(spec: dict) -> str:
    mode = spec["mode"]
    if mode == "tag":
        raw = f"tag-{spec['tag']}"
    elif mode == "folder":
        raw = f"folder-{spec['folder']}"
    elif mode == "seed":
        raw = f"seed-{Path(spec['seed']).stem}-h{spec['hops']}"
    elif mode == "pages":
        raw = f"pages-{len(spec['pages'])}"
    else:
        raw = "all"
    return re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Export a declared slice of the wiki as "
                    "one self-contained HTML file.")
    parser.add_argument("--root", default=None,
                        help="repo root (default: the repo this "
                             "script lives in)")
    parser.add_argument("--out", default=None,
                        help="output HTML path (default: "
                             "exports/slice-<name>.html)")
    parser.add_argument("--name", default=None,
                        help="slice name (default: derived from "
                             "the spec)")
    parser.add_argument("--max-image-bytes", type=int,
                        default=DEFAULT_MAX_IMAGE_BYTES,
                        help="inline cap per local image "
                             "(default %(default)s)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tag", default=None)
    group.add_argument("--folder", default=None,
                       help="wiki section, e.g. concepts")
    group.add_argument("--seed", default=None,
                       help="seed page (id, path or stem)")
    group.add_argument("--pages", default=None,
                       help="comma-separated page list")
    group.add_argument("--all", action="store_true")
    parser.add_argument("--hops", type=int, default=1,
                        help="hop radius for --seed (default 1)")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if args.root \
        else SCRIPTS.parent
    if args.tag is not None:
        spec = {"mode": "tag", "tag": args.tag}
    elif args.folder is not None:
        spec = {"mode": "folder", "folder": args.folder}
    elif args.seed is not None:
        if args.hops < 0:
            print("wiki_slice_export: --hops must be >= 0",
                  file=sys.stderr)
            return 2
        spec = {"mode": "seed", "seed": args.seed,
                "hops": args.hops}
    elif args.pages is not None:
        spec = {"mode": "pages",
                "pages": [p.strip() for p in args.pages.split(",")
                          if p.strip()]}
    else:
        spec = {"mode": "all"}
    name = args.name or _default_name(spec)
    try:
        doc, manifest = build_slice_html(
            root, spec, name, args.max_image_bytes)
    except ValueError as exc:
        print(f"wiki_slice_export: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out) if args.out else \
        root / "exports" / f"slice-{name}.html"
    if not out.is_absolute():
        out = (Path.cwd() / out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"slice '{name}': {manifest['pages_included']} page(s), "
          f"{len(manifest['boundary_references'])} boundary "
          f"reference(s), {len(manifest['unresolved_targets'])} "
          f"unresolved target(s), "
          f"{len(manifest['assets']['inlined'])} image(s) inlined, "
          f"{len(manifest['assets']['omitted'])} omitted "
          f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
