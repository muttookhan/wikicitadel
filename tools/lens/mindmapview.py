"""Build-time page-outline mindmaps for the Lens (Wave-2 item W2).

A wiki page's own headings — nothing else — become an expandable
mindmap in the Lens reader: headings nest by level, and the
wikilinks written under each heading hang off it as leaf
references. The tree is computed at Lens build time and shipped as
a static artefact (data/mindmaps.json / data/mindmaps.js,
window.LENS_MINDMAPS); expand/collapse is client-side over that
shipped data. No new store, no new format: the input is just the
page's Markdown, exactly as the build-list row specifies.

Pattern credit: the view adapts the Markmap idea — render a
Markdown document's heading outline as an interactive mindmap
with foldable branches and per-branch colours — from the markmap
family (markmap.js.org; MIT, (c) the markmap contributors).
Adapt-with-credit per the item's licence route: the *idea* and
interaction pattern are Markmap's; this generator and the client
renderer are our own code, written against lenslib's parsing so
the Lens keeps exactly one Markdown dialect.

Parsing parity (the honesty contract):
  * Headings come from lenslib.page_headings — the same list the
    build already ships per page (same HEADING_RE, same fence
    rule, same anchor de-duplication). The tree's heading
    sequence is that list, nested; nothing is re-outlined,
    summarised, re-ordered, or invented.
  * Wikilinks are extracted with lenslib's WIKILINK_RE under the
    same fence/inline-code rules as lenslib.extract_wikilinks,
    and each link is attributed to the deepest heading whose
    section contains it (links before the first heading belong
    to the root). A link repeated under one heading collapses to
    one leaf carrying its occurrence count.
  * Link resolution is the build's own two-step route_by_stem
    lookup, identical to lenslib.resolve_wikilinks: a resolved
    leaf carries the target page id; an unresolved one carries
    page=None and missing=True — a boundary reference, marked,
    never a pretend link.

Root rule: the page's first level-1 heading, when it has one, is
the root (kind "h1", consumed — not repeated as a child); any
later level-1 headings are ordinary top-level children. Without
a level-1 heading the root is the page title (kind "title"),
which is what the reader shows anyway. A page with no headings
at all gets empty=True and a root with no heading children — an
explicit empty state, not an error.

Interface (what build_lens consumes):

  page_mindmap(title, body, resolve) -> record dict
      resolve: target string -> page id or None.
  build_mindmaps(pages, resolve) -> {"pages": {id: record},
      "note": ..., "credit": ...}
      pages: page dicts with id / title / body (pages_raw rows).
"""

import re
from pathlib import Path

import lenslib as L

NOTE = ("Each tree is the page's own heading outline (lenslib "
        "page_headings, nested by level) with the wikilinks "
        "written under each heading as leaf references; an "
        "unresolved leaf is a boundary reference — no page "
        "exists for it in this build.")
CREDIT = ("Mindmap view pattern adapted from Markmap "
          "(markmap.js.org, MIT, (c) the markmap contributors) "
          "— idea and interaction pattern credited; generator "
          "and renderer are this tree's own code.")


def _events(body):
    """Document-order stream of ("heading", heading_dict) and
    ("link", (target, anchor, label)) events, walked with
    lenslib's own rules: fenced code toggles on lines starting
    with ``` (page_headings / extract_wikilinks rule), headings
    match lenslib.HEADING_RE outside fences, wikilinks match
    lenslib.WIKILINK_RE on lines with inline code spans stripped.
    Heading dicts are consumed in order from the canonical
    page_headings list, so anchors (including -2/-3 de-dup
    suffixes) are the build's own."""
    canonical = L.page_headings(body)
    out = []
    hi = 0
    in_code = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = L.HEADING_RE.match(line)
        if m:
            out.append(("heading", canonical[hi]))
            hi += 1
            # fall through: a wikilink inside the heading text is
            # still a link on this line (extract_wikilinks finds
            # it); emitting it after the heading event attributes
            # it to the section this heading opens.
        stripped = re.sub(r"`[^`\n]*`", "", line)
        for wm in L.WIKILINK_RE.finditer(stripped):
            target = wm.group(1).strip()
            anchor = wm.group(2)
            label = (wm.group(3) or wm.group(1)).strip()
            out.append(("link", (target, anchor, label)))
    assert hi == len(canonical), "heading walk diverged from page_headings"
    return out


def _attach_link(parent, target, anchor, label, resolve):
    """Hang a wikilink leaf off `parent`, collapsing repeats of
    the same target under one heading into one counted leaf."""
    for child in parent["children"]:
        if child["kind"] == "link" and child["target"] == target:
            child["count"] += 1
            return child
    pid = resolve(target)
    leaf = {"kind": "link", "text": label, "target": target,
            "page": pid, "missing": pid is None,
            "anchor": L.slugify(anchor) if (pid and anchor) else None,
            "count": 1, "children": []}
    parent["children"].append(leaf)
    return leaf


def page_mindmap(title, body, resolve):
    """One page's mindmap record: {id-less root tree, empty,
    counts}. `resolve` is the build's route lookup
    (target -> page id or None)."""
    events = _events(body)
    root = {"kind": "root", "text": title, "root_kind": "title",
            "level": 0, "anchor": None, "children": []}
    stack = [root]  # open heading nodes, shallow -> deep
    n_headings = 0
    n_refs = 0
    root_pending = True  # a first level-1 heading becomes the root
    for kind, payload in events:
        if kind == "heading":
            if root_pending and payload["level"] == 1:
                root["text"] = payload["text"]
                root["root_kind"] = "h1"
                root["level"] = 1
                root_pending = False
                continue
            root_pending = False
            node = {"kind": "heading", "text": payload["text"],
                    "level": payload["level"],
                    "anchor": payload["anchor"], "children": []}
            n_headings += 1
            while len(stack) > 1 and stack[-1]["level"] >= payload["level"]:
                stack.pop()
            stack[-1]["children"].append(node)
            stack.append(node)
        else:
            target, anchor, label = payload
            n_refs += 1
            _attach_link(stack[-1], target, anchor, label, resolve)
    leaves = []

    def collect(node):
        for c in node["children"]:
            if c["kind"] == "link":
                leaves.append(c)
            collect(c)
    collect(root)
    return {
        "root": root,
        "empty": n_headings == 0,
        "counts": {"headings": n_headings,
                   "links": len(leaves),
                   "link_refs": n_refs,
                   "resolved": sum(1 for lf in leaves if not lf["missing"]),
                   "missing": sum(1 for lf in leaves if lf["missing"])},
    }


def build_mindmaps(pages, resolve):
    """The full artefact: one record per page, keyed by page id.
    Pure function of the page bodies + route table — same corpus
    in, identical artefact out (the build's dump_json/dump_js
    sort keys on top of that)."""
    out = {}
    for pg in pages:
        rec = page_mindmap(pg["title"], pg["body"], resolve)
        rec["id"] = pg["id"]
        rec["title"] = pg["title"]
        out[pg["id"]] = rec
    return {"pages": out, "note": NOTE, "credit": CREDIT}


def route_resolver(route_by_stem):
    """The build's wikilink resolution as a callable — the same
    two-step lookup lenslib.resolve_wikilinks performs (exact
    target, then bare file name)."""
    def resolve(target):
        return route_by_stem.get(target) or route_by_stem.get(Path(target).name)
    return resolve
