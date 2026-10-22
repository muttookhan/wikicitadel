#!/usr/bin/env python3
"""wiki_bookbuilder.py — Bookbuilder editions + presentation
export for a declared, ordered set of wiki pages.

Wave 6 build item "Bookbuilder editions + presentation and
print-CSS exports" (owner directive 2026-10-22: implement the
research ideas in both wikis). Idea sources, restated as
patterns and re-implemented cleanly — no code from any of
them: AmuseWiki's bookbuilder (assemble selected texts into a
print-quality edition from an explicit selection), Slidev's
deck model (one source, slide frames split on section
boundaries), and Paged.js's paged-media print layer (@page
rules, margin boxes, running headers via string-set, named
pages). The house's own beautiful-PDF delivery preference is
the consumer: this tool emits the print-ready HTML + CSS;
PDF conversion happens elsewhere by the house route.

An EDITION SPEC is a JSON input file:

    {"title": "The Edition",            (required)
     "subtitle": "...",                  (optional)
     "author": "...",                    (optional)
     "pages": ["wiki/entities/x.md",
               "some-stem", ...],       (required, ordered,
                                         resolved like the
                                         other doors resolve)
     "options": {"max_image_bytes": N}} (optional)

Two artefacts, one spec:

  build    ONE print-ready HTML document: a cover/title page
           from the spec, a table of contents built from the
           page order + each page's headings, then the pages
           in spec order as chapters — full content, nothing
           summarised or reworded — with cross-page wikilinks
           resolved to edition-internal anchors, and a print
           stylesheet (paged-media layer) so chapters start
           on fresh pages and the running footer counts them.
  present  the same edition as a slide-style deck: ONE HTML
           file whose frames are the cover, then per page a
           chapter divider frame plus one frame per top-level
           section of that page, then a manifest frame.
           Frames paginate on screen (arrow keys / click)
           and one-per-page in print.

Link and asset honesty, shared by both artefacts (the slice
export's discipline, reused): a wikilink whose target is IN
the edition becomes an internal reference; a wikilink to a
corpus page OUTSIDE the edition becomes a visibly marked
boundary reference and is listed in the manifest with its
linking pages; a wikilink resolving to no page becomes a
missing-page mark and an unresolved-targets entry; a local
image at or under the byte cap is inlined as a data URI,
anything else is replaced in place by an "image omitted"
note and listed with its reason. The manifest (a visible
closing section AND the same data embedded as JSON) records
the spec, the corpus commit the edition was taken from, the
ordered page list, every boundary reference, every
unresolved target and every asset disposition.

Determinism: no timestamp appears anywhere in the output;
the corpus commit id is the only state marker, so the same
spec over the same corpus state yields byte-identical
bytes. The export is a derived artefact: it reads the
corpus and writes only the --out file.

Page loading, link resolution and the page graph are
wiki_export.py's (imported); bodies are rendered by the
Lens's own renderer (tools/lens/lenslib.py render_markdown,
via wiki_export); image resolution and corpus state are
wiki_slice_export.py's (imported) — an edition can never
disagree with the other doors about what a page says.

Usage:
  build   --spec FILE --out FILE [--root DIR]
          [--max-image-bytes N]
  present --spec FILE --out FILE [--root DIR]
          [--max-image-bytes N]
Exit 0 artefact built · 1 a declared page is missing ·
2 usage or spec error (bad spec, duplicate page). Stdlib
only.
"""
import argparse
import html
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent

DEFAULT_MAX_IMAGE_BYTES = 262144


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_WX = _load_module("wiki_export", SCRIPTS / "wiki_export.py")
_SL = _load_module("wiki_slice_export",
                   SCRIPTS / "wiki_slice_export.py")
LENSLIB = _WX.LENSLIB
if LENSLIB is None:
    raise SystemExit(
        "wiki_bookbuilder: tools/lens/lenslib.py could not be "
        "loaded (it needs PyYAML, the repo's declared tooling "
        "dependency); the edition renderer is the Lens's own, "
        "so there is no fallback renderer to ship instead.")

_IMG_RE = re.compile(r"<img\b[^>]*?\bsrc=\"([^\"]*)\"[^>]*?>")
_HEADING_ID_RE = re.compile(r"(<h[1-6] id=\")([^\"]+)(\")")
_WL_PH_RE = re.compile("\x00WL(\\d+)\x00")
_HEADING_TAG_RE = re.compile(
    r"<h([1-6]) id=\"([^\"]+)\">(.*?)</h\1>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


# ------------------------------------------------------------ spec

class SpecError(Exception):
    pass


def load_spec(path):
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecError(f"spec file unreadable: {exc}")
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SpecError(f"spec is not valid JSON: {exc}")
    if not isinstance(spec, dict):
        raise SpecError("spec must be a JSON object")
    title = str(spec.get("title") or "").strip()
    if not title:
        raise SpecError("spec.title is required and must be "
                        "non-empty")
    pages = spec.get("pages")
    if not isinstance(pages, list) or not pages:
        raise SpecError("spec.pages must be a non-empty list")
    opts = spec.get("options") or {}
    if not isinstance(opts, dict):
        raise SpecError("spec.options must be an object")
    mib = opts.get("max_image_bytes", DEFAULT_MAX_IMAGE_BYTES)
    if not isinstance(mib, int) or mib < 0:
        raise SpecError("spec.options.max_image_bytes must be "
                        "a non-negative integer")
    return {
        "title": title,
        "subtitle": str(spec.get("subtitle") or "").strip(),
        "author": str(spec.get("author") or "").strip(),
        "pages": [str(p) for p in pages],
        "max_image_bytes": mib,
    }


def resolve_edition(root, spec):
    """(records, keys, pages_all) — records are the edition's
    page records in SPEC ORDER, each annotated with its
    chapter number and anchor. Raises LookupError for a
    declared page that resolves to nothing, SpecError for a
    duplicate."""
    pages_all, keys = _WX.load_pages(root)
    records = []
    seen = {}
    for i, name in enumerate(spec["pages"], start=1):
        rel = _WX.resolve_page(keys, name)
        if rel is None:
            raise LookupError(name)
        if rel in seen:
            raise SpecError(
                f"spec.pages lists {rel} twice (entries "
                f"{seen[rel]} and {i}); an edition is an "
                f"ordered set")
        seen[rel] = i
        rec = dict(pages_all[rel])
        rec["chapter"] = i
        rec["anchor"] = "ch-%02d-%s" % (
            i, LENSLIB.slugify(rec["title"] or rel))
        records.append(rec)
    return records, keys, pages_all


# ------------------------------------------------------------ census

def new_census(pages_all):
    return {
        "boundary": {},      # target rel -> {from rel: count}
        "unresolved": {},    # target text -> {from rel}
        "titles": {rel: r["title"]
                   for rel, r in pages_all.items()},
        "assets_inlined": [],
        "assets_omitted": [],
    }


def census_manifest(census, all_titles):
    boundary = []
    for target in sorted(census["boundary"]):
        linked_from = census["boundary"][target]
        boundary.append({
            "target": target,
            "title": all_titles.get(target, target),
            "linked_from": sorted(linked_from),
            "count": sum(linked_from.values()),
        })
    unresolved = [{
        "target": t,
        "linked_from": sorted(census["unresolved"][t]),
    } for t in sorted(census["unresolved"])]
    return boundary, unresolved


# ------------------------------------------------------------ rendering

def render_body(root, rec, keys, in_edition, link_for, census,
                id_prefix):
    """Render one page body (or one section of it) to HTML
    with heading ids namespaced under id_prefix, wikilinks
    resolved through link_for(target_rel, fragment) -> href
    or None (None = not linkable here), and images inlined
    or omitted — every outcome folded into the census."""
    body_html, wikilinks = LENSLIB.render_markdown(rec["_text"])
    body_html = _HEADING_ID_RE.sub(
        lambda m: f"{m.group(1)}{id_prefix}--{m.group(2)}"
                  f"{m.group(3)}",
        body_html)

    def sub(m):
        target, link_anchor, label = wikilinks[int(m.group(1))]
        label_e = html.escape(label)
        hit = _WX._resolve_link(keys, target)
        if hit is not None and hit in in_edition:
            href = link_for(hit, link_anchor)
            return f'<a class="wl" href="{href}">{label_e}</a>'
        if hit is not None:
            census["boundary"].setdefault(hit, {}).setdefault(
                rec["id"], 0)
            census["boundary"][hit][rec["id"]] += 1
            title = html.escape(
                census["titles"].get(hit, hit), quote=True)
            return (f'<span class="wl-boundary" title="Links to '
                    f'&ldquo;{title}&rdquo; '
                    f'({html.escape(hit, quote=True)}) — outside '
                    f'this edition">{label_e}</span>')
        census["unresolved"].setdefault(target, set()).add(
            rec["id"])
        return (f'<span class="wl-missing" title="No page '
                f'exists for this link yet">{label_e}</span>')

    body_html = _WL_PH_RE.sub(sub, body_html)

    def img_sub(m):
        whole, src = m.group(0), m.group(1)
        kind, payload = _SL._resolve_image(
            root, rec["id"], src, rec["_max_image_bytes"])
        if kind == "inline":
            uri, nbytes = payload
            census["assets_inlined"].append(
                {"page": rec["id"], "src": src,
                 "bytes": nbytes})
            return whole.replace(f'src="{src}"',
                                 f'src="{uri}"', 1)
        census["assets_omitted"].append(
            {"page": rec["id"], "src": src, "reason": payload})
        alt = re.search(r'alt="([^"]*)"', whole)
        alt_t = alt.group(1) if alt else ""
        return (f'<span class="img-omitted">[image omitted '
                f'from edition: {html.escape(alt_t)} — '
                f'{html.escape(payload)}]</span>')

    return _IMG_RE.sub(img_sub, body_html)


def headings_of(body_html, max_level=3):
    """[(level, id, text)] from rendered, namespaced HTML —
    the table-of-contents source."""
    out = []
    for m in _HEADING_TAG_RE.finditer(body_html):
        level = int(m.group(1))
        if level > max_level:
            continue
        text = html.unescape(_TAG_RE.sub("", m.group(3)))
        out.append((level, m.group(2), text.strip()))
    return out


# ------------------------------------------------------------ styles

_BOOK_CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{font-family:Georgia,'Times New Roman',serif;font-size:16px;
line-height:1.62;color:#1a1a1a;background:#fdfdfb;margin:0}
#canvas{max-width:46rem;margin:0 auto;padding:1.5rem 1.25rem 4rem}
.screen-chrome{max-width:46rem;margin:0 auto;padding:.8rem 1.25rem 0;
font-size:.92rem;color:#555}
.screen-chrome a{color:#0b5394}
.cover{text-align:center;padding:5.5rem 1rem 3.5rem;
border-bottom:3px double #444}
.cover .kicker{letter-spacing:.18em;text-transform:uppercase;
font-size:.8rem;color:#666}
.cover h1{font-size:2.6rem;line-height:1.2;margin:.6rem 0 .4rem}
.cover .subtitle{font-size:1.25rem;color:#444;margin:.2rem 0}
.cover .author{font-size:1.05rem;color:#444;margin-top:1.2rem}
.cover .colophon{margin-top:2.5rem;font-size:.92rem;color:#666}
.toc{margin:2.5rem 0}
.toc h2{font-size:1.4rem;border-bottom:2px solid #444;
padding-bottom:.3rem}
.toc ol{margin:.4rem 0;padding-left:1.6rem}
.toc .toc-chapter{font-weight:700;margin-top:.7rem}
.toc .toc-head{font-weight:400;font-size:.95rem;margin-left:1.2rem}
.toc a{color:#0b5394;text-decoration:none}
.chapter{margin-top:3rem}
.chapter-head{border-bottom:2px solid #444;padding-bottom:.4rem;
margin-bottom:1.2rem}
.chapter-kicker{letter-spacing:.14em;text-transform:uppercase;
font-size:.78rem;color:#666;margin:0}
.chapter-title{font-size:1.9rem;line-height:1.25;margin:.25rem 0}
.pagemeta{color:#555;font-size:.88rem;margin:.2rem 0 0}
.pagemeta code{background:#eee;padding:0 .25em}
.reading-body h2{margin-top:1.8rem}
.reading-body img,figure img{max-width:100%}
.reading-body table{border-collapse:collapse}
.reading-body th,.reading-body td{border:1px solid #bbb;
padding:.3rem .55rem}
.reading-body pre{background:#f4f4f4;padding:.7rem;
overflow-x:auto;font-size:.86rem;line-height:1.45}
.reading-body code{background:#eee;padding:0 .2em}
.reading-body pre code{background:none;padding:0}
.reading-body blockquote{border-left:3px solid #999;
margin-left:0;padding-left:1rem;color:#333}
a.wl{color:#0b5394}
.wl-boundary{border-bottom:2px dashed #b8860b;background:#fdf6e0;
padding:0 .15em;cursor:help}
.wl-boundary::after{content:" \\29C9";color:#b8860b;
font-size:.85em}
.wl-missing{color:#a00;border-bottom:1px dotted #a00;cursor:help}
.img-omitted{display:inline-block;border:1px dashed #999;
color:#555;padding:.4rem .6rem;font-size:.9rem;background:#f4f4f4}
.tombstone-note{border:1px solid #a00;color:#a00;padding:.5rem .8rem;
font-size:.95rem}
.manifest{margin-top:3.5rem;border-top:3px double #444;
padding-top:1rem;font-size:.94rem}
.manifest h2{font-size:1.35rem}
.manifest h3{margin-bottom:.3rem}
.manifest ul{margin:.3rem 0 .8rem;padding-left:1.4rem}
.manifest code{background:#eee;padding:0 .25em}
@media print{
  body { background: #fff; color: #111; }
  .screen-chrome { display: none !important; }
  #canvas { max-width: none; max-height: none;
  overflow: visible; padding: 0; }
  a { color: #111; text-decoration: none; }
  .wl-boundary { background: none;
  border-bottom: 1.5px dashed #666; }
}
@page{
  size:A4;margin:22mm 18mm 20mm;
  @bottom-center{content:counter(page);font-size:9pt;color:#666}
  @top-left{content:string(chapter-title);font-size:9pt;
  color:#666}
}
@page cover{margin:12mm;
  @bottom-center{content:none}
  @top-left{content:none}
}
.cover{page:cover;break-after:page}
.chapter{break-before:page}
.chapter h1.chapter-title{string-set:chapter-title content(text)}
.toc{break-after:page}
.manifest{break-before:page}
h2,h3,h4{break-after:avoid}
table,figure,blockquote{break-inside:avoid}
""".strip()

_DECK_CSS = """
:root{color-scheme:light}
*{box-sizing:border-box}
body{font-family:Georgia,'Times New Roman',serif;font-size:16px;
line-height:1.55;color:#1a1a1a;background:#26262a;margin:0}
.screen-chrome{max-width:62rem;margin:0 auto;padding:.7rem 1rem 0;
color:#ccc;font-size:.92rem;display:flex;gap:1.2rem;
align-items:baseline}
.screen-chrome a{color:#9fc3ec}
#canvas{max-width:62rem;margin:0 auto;padding:1rem 1rem 3rem}
.frame{display:none;background:#fdfdfb;border-radius:6px;
padding:2.2rem 2.6rem;min-height:70vh;overflow:visible}
.frame.current{display:block}
.frame-cover{text-align:center;padding-top:12vh}
.frame-cover .kicker{letter-spacing:.18em;text-transform:uppercase;
font-size:.8rem;color:#666}
.frame-cover h1{font-size:2.5rem;line-height:1.2;margin:.6rem 0}
.frame-cover .subtitle{font-size:1.2rem;color:#444}
.frame-cover .author{margin-top:1.2rem;color:#444}
.frame-cover .colophon{margin-top:2.2rem;font-size:.92rem;
color:#666}
.frame-cover ol{text-align:left;max-width:34rem;
margin:2rem auto 0}
.frame-divider{padding-top:16vh}
.frame-kicker{letter-spacing:.14em;text-transform:uppercase;
font-size:.78rem;color:#666;margin:0}
.frame h1{font-size:2rem;line-height:1.25}
.frame h2{font-size:1.55rem}
.frame img{max-width:100%}
.frame table{border-collapse:collapse}
.frame th,.frame td{border:1px solid #bbb;padding:.3rem .55rem}
.frame pre{background:#f4f4f4;padding:.7rem;overflow-x:auto;
font-size:.86rem;line-height:1.45}
.frame code{background:#eee;padding:0 .2em}
.frame pre code{background:none;padding:0}
.frame blockquote{border-left:3px solid #999;margin-left:0;
padding-left:1rem;color:#333}
a.wl{color:#0b5394}
.wl-boundary{border-bottom:2px dashed #b8860b;background:#fdf6e0;
padding:0 .15em;cursor:help}
.wl-boundary::after{content:" \\29C9";color:#b8860b;
font-size:.85em}
.wl-missing{color:#a00;border-bottom:1px dotted #a00;cursor:help}
.img-omitted{display:inline-block;border:1px dashed #999;
color:#555;padding:.4rem .6rem;font-size:.9rem;background:#f4f4f4}
.tombstone-note{border:1px solid #a00;color:#a00;padding:.5rem .8rem;
font-size:.95rem}
.pagemeta{color:#555;font-size:.88rem}
.pagemeta code{background:#eee;padding:0 .25em}
.frame-manifest{font-size:.92rem}
.frame-manifest ul{margin:.3rem 0 .8rem;padding-left:1.4rem}
.frame-manifest code{background:#eee;padding:0 .25em}
@media print{
  body { background: #fff; color: #111; }
  .screen-chrome { display: none !important; }
  #canvas { max-width: none; max-height: none;
  overflow: visible; padding: 0; }
  .frame { display: block; min-height: 0; border-radius: 0;
  break-after: page; }
  .frame:last-child { break-after: auto; }
  a { color: #111; text-decoration: none; }
}
""".strip()

_DECK_JS = """
var frames=[].slice.call(document.querySelectorAll('.frame'));
var cur=0;
function show(n){
  cur=Math.max(0,Math.min(frames.length-1,n));
  frames.forEach(function(f,i){
    f.classList.toggle('current',i===cur);});
  var c=document.getElementById('frame-counter');
  if(c){c.textContent=(cur+1)+' / '+frames.length;}
  if(window.history&&history.replaceState){
    history.replaceState(null,'','#'+frames[cur].id);}
}
function fromHash(){
  var id=window.location.hash.slice(1);
  for(var i=0;i<frames.length;i++){
    if(frames[i].id===id){return i;}}
  return 0;
}
document.addEventListener('keydown',function(e){
  if(e.key==='ArrowRight'||e.key===' '){show(cur+1);}
  else if(e.key==='ArrowLeft'){show(cur-1);}
});
document.addEventListener('click',function(e){
  var a=e.target.closest?e.target.closest('a[href^="#frame-"]')
    :null;
  if(a){
    e.preventDefault();
    var id=a.getAttribute('href').slice(1);
    for(var i=0;i<frames.length;i++){
      if(frames[i].id===id){show(i);break;}}
    return;
  }
  if(e.target.closest&&e.target.closest('a')){return;}
  show(cur+1);
});
show(fromHash());
""".strip()


# ------------------------------------------------------------ manifest

def build_manifest(fmt, spec, records, census, pages_all, state):
    boundary, unresolved = census_manifest(
        census, {rel: r["title"] for rel, r in pages_all.items()})
    return {
        "tool": "wiki_bookbuilder",
        "format": fmt,
        "title": spec["title"],
        "spec": {
            "title": spec["title"],
            "subtitle": spec["subtitle"],
            "author": spec["author"],
            "pages": spec["pages"],
            "max_image_bytes": spec["max_image_bytes"],
        },
        "corpus": state,
        "pages": [{
            "order": r["chapter"],
            "page": r["id"],
            "title": r["title"],
            "anchor": r["anchor"],
            "tombstoned": bool(r["tombstoned"]),
        } for r in records],
        "boundary_references": boundary,
        "unresolved_targets": unresolved,
        "assets_inlined": census["assets_inlined"],
        "assets_omitted": census["assets_omitted"],
        "compiled_pages_total": len(pages_all),
        "pages_not_in_edition":
            len(pages_all) - len(records),
    }


def manifest_html(manifest):
    esc = html.escape
    out = ['<h2>Edition manifest</h2>']
    out.append(
        f'<p>Assembled by <code>scripts/wiki_bookbuilder.py</code> '
        f'({esc(manifest["format"])} format) from corpus commit '
        f'<code>{esc(str(manifest["corpus"].get("commit")))}'
        f'</code>.</p>')
    out.append('<h3>Pages, in edition order</h3><ul>')
    for p in manifest["pages"]:
        out.append(
            f'<li>{p["order"]}. {esc(p["title"])} — '
            f'<code>{esc(p["page"])}</code></li>')
    out.append('</ul>')
    out.append('<h3>Boundary references '
               '(linked pages outside this edition)</h3>')
    if manifest["boundary_references"]:
        out.append('<ul>')
        for b in manifest["boundary_references"]:
            out.append(
                f'<li>{esc(b["title"])} — '
                f'<code>{esc(b["target"])}</code> '
                f'({b["count"]} link(s) from '
                f'{len(b["linked_from"])} edition page(s))</li>')
        out.append('</ul>')
    else:
        out.append('<p>None.</p>')
    out.append('<h3>Unresolved link targets</h3>')
    if manifest["unresolved_targets"]:
        out.append('<ul>')
        for u in manifest["unresolved_targets"]:
            out.append(
                f'<li><code>{esc(u["target"])}</code> — linked '
                f'from {len(u["linked_from"])} edition '
                f'page(s)</li>')
        out.append('</ul>')
    else:
        out.append('<p>None.</p>')
    out.append('<h3>Assets</h3><ul>')
    out.append(f'<li>{len(manifest["assets_inlined"])} image(s) '
               f'inlined as data URIs.</li>')
    for a in manifest["assets_omitted"]:
        out.append(
            f'<li>omitted: <code>{esc(a["src"])}</code> on '
            f'<code>{esc(a["page"])}</code> — '
            f'{esc(a["reason"])}</li>')
    out.append('</ul>')
    out.append(
        f'<p>{manifest["pages_not_in_edition"]} compiled '
        f'page(s) are not in this edition.</p>')
    return "\n".join(out)


def manifest_json(manifest):
    text = json.dumps(manifest, indent=1, sort_keys=True,
                      ensure_ascii=False)
    return text.replace("</", "<\\/")


# ------------------------------------------------------------ book

def cover_html(spec, records, state, extra_class="cover",
               attrs=""):
    esc = html.escape
    lines = [f'<section class="{extra_class}"{attrs}>',
             '<p class="kicker">An edition of the LLM Wiki</p>',
             f'<h1>{esc(spec["title"])}</h1>']
    if spec["subtitle"]:
        lines.append(
            f'<p class="subtitle">{esc(spec["subtitle"])}</p>')
    if spec["author"]:
        lines.append(
            f'<p class="author">{esc(spec["author"])}</p>')
    commit = state.get("commit")
    lines.append(
        f'<p class="colophon">{len(records)} pages, in the '
        f'order given by the edition spec.<br>Corpus commit: '
        f'<code>{esc(str(commit))}</code></p>')
    lines.append('</section>')
    return "\n".join(lines)


def build_book(root, spec, records, keys, pages_all):
    state = _SL.corpus_state(root)
    census = new_census(pages_all)
    in_edition = {r["id"] for r in records}
    anchors = {r["id"]: r["anchor"] for r in records}

    def link_for(hit, fragment):
        href = f"#{anchors[hit]}"
        if fragment:
            href = (f"#{anchors[hit]}--"
                    f"{LENSLIB.slugify(fragment)}")
        return href

    chapters = []
    toc = []
    for rec in records:
        rec["_text"] = rec["body"]
        rec["_max_image_bytes"] = spec["max_image_bytes"]
        body_html = render_body(
            root, rec, keys, in_edition, link_for, census,
            rec["anchor"])
        toc.append((rec, headings_of(body_html)))
        tomb = ('<p class="tombstone-note">This page is '
                'tombstoned in the wiki; it is included as '
                'recorded.</p>' if rec["tombstoned"] else "")
        chapters.append(
            f'<section class="chapter" id="{rec["anchor"]}" '
            f'data-page="{html.escape(rec["id"], quote=True)}">\n'
            f'<header class="chapter-head">'
            f'<p class="chapter-kicker">Chapter '
            f'{rec["chapter"]}</p>'
            f'<h1 class="chapter-title">'
            f'{html.escape(rec["title"])}</h1>'
            f'<p class="pagemeta"><code>'
            f'{html.escape(rec["id"])}</code></p></header>\n'
            f'{tomb}\n<div class="reading-body">\n{body_html}\n'
            f'</div>\n</section>')

    toc_lines = ['<nav class="toc" id="toc">',
                 '<h2>Contents</h2>', '<ol>']
    for rec, heads in toc:
        toc_lines.append(
            f'<li class="toc-chapter"><a href="#{rec["anchor"]}">'
            f'{rec["chapter"]}. '
            f'{html.escape(rec["title"])}</a></li>')
        for level, hid, text in heads:
            toc_lines.append(
                f'<li class="toc-head"><a href="#{hid}">'
                f'{html.escape(text)}</a></li>')
    toc_lines.append('</ol>')
    toc_lines.append('</nav>')

    manifest = build_manifest(
        "edition", spec, records, census, pages_all, state)
    manifest["notes"] = [
        "The table of contents lists headings to level 3; "
        "deeper headings appear in the chapter body only.",
    ]
    doc = "\n".join([
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f'<title>{html.escape(spec["title"])}</title>',
        "<style>", _BOOK_CSS, "</style>",
        '<script type="application/json" id="edition-manifest">',
        manifest_json(manifest), "</script>",
        "</head>",
        "<body>",
        '<div class="screen-chrome">Print-ready edition — '
        'use the browser&rsquo;s Print / Save as PDF for the '
        'paged form. <a href="#toc">Contents</a> · '
        '<a href="#manifest">Manifest</a></div>',
        '<main id="canvas">',
        cover_html(spec, records, state),
        "\n".join(toc_lines),
        "\n".join(chapters),
        '<section class="manifest" id="manifest">',
        manifest_html(manifest),
        "</section>",
        "</main>",
        "</body>",
        "</html>",
        "",
    ])
    return doc, manifest


# ------------------------------------------------------------ deck

def split_sections(body):
    """Split a page body into (heading_text, markdown) segments
    at its top-level headings (the shallowest heading level the
    body uses), honouring fenced code. The first segment is
    the lead (heading_text ""); when the body has no headings
    it is one segment."""
    lines = body.splitlines()
    heads = []
    in_fence = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _HEADING_LINE_RE.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    if not heads:
        return [("", body)]
    top = min(level for _i, level, _t in heads)
    cuts = [i for i, level, _t in heads if level == top]
    title_at = {i: t for i, _l, t in heads}
    segments = [("", "\n".join(lines[:cuts[0]]))]
    for j, start in enumerate(cuts):
        end = cuts[j + 1] if j + 1 < len(cuts) else len(lines)
        segments.append(
            (title_at[start], "\n".join(lines[start:end])))
    return segments


def build_deck(root, spec, records, keys, pages_all):
    state = _SL.corpus_state(root)
    census = new_census(pages_all)
    in_edition = {r["id"] for r in records}

    # Frame plan first (links need target frame ids before
    # any body is rendered): cover, then per chapter a
    # divider + one frame per top-level section, then the
    # manifest frame.
    per_chapter = []
    total = 1
    for rec in records:
        segments = split_sections(rec["body"])
        per_chapter.append(segments)
        total += 1 + (len(segments) - 1)
    total += 1  # manifest frame
    frame_no = {}
    n = 1  # frame 0 is the cover
    for rec, segments in zip(records, per_chapter):
        frame_no[rec["id"]] = n
        n += 1 + (len(segments) - 1)
    manifest_frame = n

    def fid(i):
        return f"frame-{i:04d}"

    def link_for(hit, fragment):
        # A deck frame is the unit of navigation: page links
        # land on the target chapter's divider frame; heading
        # fragments are not carried (recorded in the manifest
        # notes below, never silently upgraded).
        return f"#{fid(frame_no[hit])}"

    frames = []
    cover = cover_html(spec, records, state,
                       extra_class="frame frame-cover current",
                       attrs=f' id="{fid(0)}"')
    toc_items = []
    for rec in records:
        toc_items.append(
            f'<li><a href="#{fid(frame_no[rec["id"]])}">'
            f'{rec["chapter"]}. '
            f'{html.escape(rec["title"])}</a></li>')
    cover = cover.replace(
        "</section>",
        '<ol>' + "".join(toc_items) + '</ol></section>')
    frames.append(cover)

    counter = 1
    for rec, segments in zip(records, per_chapter):
        rec["_max_image_bytes"] = spec["max_image_bytes"]
        for j, (heading, text) in enumerate(segments):
            rec["_text"] = text
            body_html = render_body(
                root, rec, keys, in_edition, link_for, census,
                f"{rec['anchor']}-s{j}")
            if j == 0:
                tomb = (
                    '<p class="tombstone-note">This page is '
                    'tombstoned in the wiki; it is included as '
                    'recorded.</p>' if rec["tombstoned"]
                    else "")
                frames.append(
                    f'<section class="frame frame-divider" '
                    f'id="{fid(counter)}" '
                    f'data-page="'
                    f'{html.escape(rec["id"], quote=True)}">'
                    f'<p class="frame-kicker">Chapter '
                    f'{rec["chapter"]}</p>'
                    f'<h1>{html.escape(rec["title"])}</h1>'
                    f'<p class="pagemeta"><code>'
                    f'{html.escape(rec["id"])}</code></p>'
                    f'{tomb}{body_html}</section>')
            else:
                frames.append(
                    f'<section class="frame" '
                    f'id="{fid(counter)}" '
                    f'data-page="'
                    f'{html.escape(rec["id"], quote=True)}">'
                    f'<p class="frame-kicker">'
                    f'{html.escape(rec["title"])}</p>'
                    f'{body_html}</section>')
            counter += 1

    manifest = build_manifest(
        "presentation", spec, records, census, pages_all, state)
    manifest["notes"] = [
        "In the presentation format a page link lands on the "
        "target chapter's divider frame; heading fragments "
        "are not carried.",
    ]
    frames.append(
        f'<section class="frame frame-manifest" '
        f'id="{fid(manifest_frame)}">'
        f'{manifest_html(manifest)}</section>')

    doc = "\n".join([
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f'<title>{html.escape(spec["title"])} — presentation'
        f'</title>',
        "<style>", _DECK_CSS, "</style>",
        '<script type="application/json" id="edition-manifest">',
        manifest_json(manifest), "</script>",
        "</head>",
        '<body class="deck">',
        '<div class="screen-chrome"><span id="frame-counter">'
        '</span><span>Arrow keys, space or click advance; '
        'links jump to a chapter&rsquo;s first frame.</span>'
        '</div>',
        '<main id="canvas">',
        "\n".join(frames),
        "</main>",
        "<script>", _DECK_JS, "</script>",
        "</body>",
        "</html>",
        "",
    ])
    return doc, manifest


# ------------------------------------------------------------ CLI

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Bookbuilder editions + presentation "
                    "export for a declared page set")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("build", "present"):
        p = sub.add_parser(name)
        p.add_argument("--spec", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--root", default=str(ROOT))
        p.add_argument("--max-image-bytes", type=int,
                       default=None)
    a = ap.parse_args(argv)
    try:
        spec = load_spec(a.spec)
    except SpecError as exc:
        print(f"wiki_bookbuilder: {exc}", file=sys.stderr)
        return 2
    if a.max_image_bytes is not None:
        if a.max_image_bytes < 0:
            print("wiki_bookbuilder: --max-image-bytes must be "
                  "non-negative", file=sys.stderr)
            return 2
        spec["max_image_bytes"] = a.max_image_bytes
    root = Path(a.root)
    try:
        records, keys, pages_all = resolve_edition(root, spec)
    except LookupError as exc:
        print(f"wiki_bookbuilder: declared page not found: "
              f"{exc}", file=sys.stderr)
        return 1
    except SpecError as exc:
        print(f"wiki_bookbuilder: {exc}", file=sys.stderr)
        return 2
    if a.cmd == "build":
        doc, manifest = build_book(root, spec, records, keys,
                                   pages_all)
    else:
        doc, manifest = build_deck(root, spec, records, keys,
                                   pages_all)
    out = Path(a.out)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"wiki_bookbuilder: {manifest['format']} "
          f"'{spec['title']}' — {len(records)} page(s), "
          f"{len(manifest['boundary_references'])} boundary "
          f"reference(s), "
          f"{len(manifest['unresolved_targets'])} unresolved "
          f"target(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
