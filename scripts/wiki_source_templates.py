#!/usr/bin/env python3
"""wiki_source_templates.py — per-source-type clip templates
(implementation wave W4, 2026-10-22).

WHERE THIS SITS. scripts/wiki_clip_templates.py (Round 3)
selects an EXTRACTION profile by URL pattern — which part of
a page is content, which parts are chrome. This module is the
other half of the template idea: a COMPOSITION template
chosen by the source's TYPE (article / paper / video / forum
thread / documentation / generic). The type template decides
how the staged capture draft is composed from the converted
body — what leads it, which source metadata is lifted into
the draft's frontmatter and the sidecar record, and which
fidelity notes are recorded about what the composition did
(dropped / reordered / could not find). Idea sources:
Obsidian Web Clipper's per-type templates and wallabag's
per-site article handling, via the wave-4 survey —
re-implemented here against this pipeline's own shapes; no
code carried.

SELECTION. detect_type() reads the fetched bytes (meta tags,
JSON-LD @types, markup signals) and the URL, and returns the
detected type with its EVIDENCE — every detection carries the
signals that fired, and the sidecar records them. An explicit
--template at the clip door overrides detection (the record
says so, and names what detection would have chosen). When
nothing is detected, the type is "generic" with selection
"fallback", stated in the record — never silent.

THE GENERIC TEMPLATE IS THE CURRENT BEHAVIOUR. It shapes
nothing: the body passes through exactly as the converter
produced it and no frontmatter lines are added, so a generic
clip's staged draft is byte-identical to the clip path
without this layer (proved on fixtures in
scripts/tests/test_wiki_source_templates.py). The one record
the layer adds in every case is the sidecar's
clip.source_template block — the item's own bookkeeping: a
capture always says which template composed it and how that
template was chosen.

SAFETY. Templates shape presentation only; they never
bypass the pipeline's machinery. The converted body has
already passed the converter's injection gate before any
shaping runs. The one place a template LIFTS text out of the
source (the video template's description lead), the lifted
text goes back through the converter's own sanitiser
(clean_text, handed in by the caller as `gate_clean`): a
"blocked" verdict withholds the lead entirely, with the
withholding recorded as a fidelity note; when the gate is
unavailable the lead is withheld too — lifted text is never
carried past an absent gate. Metadata lifted to frontmatter
is plain-text cleaned here (tags stripped, entities
unescaped, invisible codepoints removed, whitespace
collapsed) and its provenance is the page's own metadata.

FIDELITY, NOT SILENCE. Every template returns fidelity
notes: what was moved, what was kept, what was looked for
and not found. A template that silently dropped or
reordered content would fail the item; absence is recorded
as absence.

    python3 scripts/wiki_source_templates.py list
    python3 scripts/wiki_source_templates.py match
        [--url URL] [--file PATH]

Exit codes: 0 ok · 1 refusal · 2 usage error. `match` reads
a local file's bytes (never fetches) and prints the
resolution record as JSON.
"""
import argparse
import html as _html
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent

# Detection precedence: the most specific scholarly / media
# shapes win over the generic "article" shape (a paper page
# usually also declares og:type=article).
TEMPLATE_NAMES = ("paper", "video", "forum", "docs",
                  "article", "generic")

TEMPLATES = {
    "paper": {
        "note": "scholarly paper: the abstract leads the "
                "body (moved there if the conversion put it "
                "elsewhere); authors / venue / DOI / date "
                "lifted from citation_* metadata to "
                "frontmatter; section structure preserved "
                "in source order and listed in the record",
    },
    "video": {
        "note": "video page: the body leads with the page's "
                "own description record (metadata, passed "
                "through the sanitiser); a transcript is "
                "claimed only when the page actually carries "
                "one — otherwise the record says none was "
                "embedded",
    },
    "forum": {
        "note": "forum thread: posts stay in the fetched "
                "page's document order — thread order IS the "
                "content; per-post authors recorded in "
                "order of first appearance where the markup "
                "attributes them",
    },
    "docs": {
        "note": "documentation: body kept as converted "
                "(navigation handling belongs to the "
                "extraction profile); the record names the "
                "documentation signals that fired",
    },
    "article": {
        "note": "article / post: body kept as converted in "
                "document order; byline, publication date "
                "and section lifted from page metadata to "
                "frontmatter where present",
    },
    "generic": {
        "note": "THE STATED FALLBACK: no source type was "
                "detected (or generic was chosen explicitly) "
                "— the converted body is staged exactly as "
                "the converter produced it, the behaviour "
                "the clip path always had",
    },
}


class SourceTemplateError(Exception):
    """An unknown template name or an unreadable input."""


# ----------------------------------------------------------------
# Small text helpers (self-contained on purpose: this module
# must stay importable without the converter or the gateway)
# ----------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_value(text):
    """One metadata value as plain text: tags stripped,
    entities unescaped, invisible codepoints (Unicode
    category Cf plus the zero-width set) removed, whitespace
    collapsed. Metadata is lifted from untrusted pages; it
    lands in frontmatter, so it is kept to one clean line."""
    if text is None:
        return ""
    text = _TAG_RE.sub(" ", str(text))
    text = _html.unescape(text)
    text = "".join(ch for ch in text
                   if unicodedata.category(ch) != "Cf")
    return _WS_RE.sub(" ", text).strip()


_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I | re.S)
_ATTR_RE = re.compile(
    r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'>]+))")


def _attrs(tag):
    out = {}
    for m in _ATTR_RE.finditer(tag):
        val = next(g for g in m.groups()[1:] if g is not None)
        out[m.group(1).lower()] = _html.unescape(val)
    return out


def _meta_map(text):
    """{key: [values in document order]} over the page's
    <meta> tags, keyed by name= or property= (lowercased)."""
    out = {}
    for m in _META_TAG_RE.finditer(text or ""):
        attrs = _attrs(m.group(0))
        key = (attrs.get("name") or attrs.get("property")
               or "").strip().lower()
        content = attrs.get("content")
        if key and content is not None:
            out.setdefault(key, []).append(content)
    return out


_JSONLD_RE = re.compile(
    r"<script\b[^>]*type\s*=\s*[\"']application/ld\+json"
    r"[\"'][^>]*>(.*?)</script>", re.I | re.S)


def _jsonld_objects(text):
    """Parsed JSON-LD blocks (unparseable blocks skipped —
    a broken block is no evidence either way)."""
    objs = []
    for m in _JSONLD_RE.finditer(text or ""):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        if isinstance(data, dict) and "@graph" in data \
                and isinstance(data["@graph"], list):
            objs.extend(o for o in data["@graph"]
                        if isinstance(o, dict))
        elif isinstance(data, dict):
            objs.append(data)
        elif isinstance(data, list):
            objs.extend(o for o in data if isinstance(o, dict))
    return objs


def _jsonld_types(objs):
    types = []
    for obj in objs:
        t = obj.get("@type")
        if isinstance(t, str):
            types.append(t)
        elif isinstance(t, list):
            types.extend(x for x in t if isinstance(x, str))
    return types


def _decode(data):
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data or ""


# ----------------------------------------------------------------
# Detection — every hit names its evidence
# ----------------------------------------------------------------

_VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")


def detect_type(data, url=None, content_type=None):
    """Detect the source type of fetched bytes. Returns
    {"type": name or None, "evidence": [{kind, detail}]} —
    the evidence lists ONLY the signals behind the returned
    type. content_type is accepted for the record's sake;
    the detectors key on bytes + URL, which a fetcher cannot
    mislabel."""
    text = _decode(data)
    meta = _meta_map(text)
    objs = _jsonld_objects(text)
    types = _jsonld_types(objs)
    host = (urlparse(url).hostname or "").lower() if url else ""
    path = (urlparse(url).path or "") if url else ""
    found = {}  # type -> evidence list

    def add(t, kind, detail):
        found.setdefault(t, []).append(
            {"kind": kind, "detail": detail})

    # paper
    for key in sorted(meta):
        if key.startswith("citation_"):
            add("paper", "meta:citation",
                "meta name=%r present" % key)
            break
    if "ScholarlyArticle" in types:
        add("paper", "jsonld:@type", "ScholarlyArticle")
    if host in ("arxiv.org", "www.arxiv.org") \
            and path.startswith("/abs/"):
        add("paper", "url", "arXiv abstract page")
    if host in ("doi.org", "dx.doi.org"):
        add("paper", "url", "DOI resolver")

    # video
    og_type = (meta.get("og:type") or [""])[0].strip().lower()
    if og_type.startswith("video"):
        add("video", "meta:og:type", og_type)
    if meta.get("og:video") or meta.get("og:video:url"):
        add("video", "meta:og:video", "og:video present")
    if "VideoObject" in types:
        add("video", "jsonld:@type", "VideoObject")
    if host in _VIDEO_HOSTS or host.endswith(".youtube.com"):
        add("video", "url", "video host %s" % host)

    # forum
    for t in ("DiscussionForumPosting", "QAPage"):
        if t in types:
            add("forum", "jsonld:@type", t)
    comments = len(re.findall(r"itemprop\s*=\s*[\"']comment[\"']",
                              text, re.I))
    if comments >= 3:
        add("forum", "markup:itemprop-comment",
            "%d comment items in the markup" % comments)
    posts = len(re.findall(r"data-post-number\s*=", text, re.I))
    if posts >= 3:
        add("forum", "markup:discourse",
            "%d data-post-number elements" % posts)
    if re.search(r"/(forum|forums|threads?|topic|t)/", path):
        add("forum", "url", "forum-shaped path %s" % path)

    # docs
    if "TechArticle" in types:
        add("docs", "jsonld:@type", "TechArticle")
    generator = (meta.get("generator") or [""])[0].lower()
    if any(g in generator for g in
           ("mkdocs", "readthedocs", "docusaurus", "sphinx")):
        add("docs", "meta:generator", generator)
    if host.startswith("docs.") or "/docs/" in path \
            or host.endswith("readthedocs.io") \
            or host == "readthedocs.io":
        add("docs", "url", "documentation-shaped address")

    # article
    if og_type == "article":
        add("article", "meta:og:type", "article")
    if meta.get("article:published_time"):
        add("article", "meta:article",
            "article:published_time present")
    for t in ("Article", "NewsArticle", "BlogPosting"):
        if t in types:
            add("article", "jsonld:@type", t)

    for name in TEMPLATE_NAMES:
        if name != "generic" and found.get(name):
            return {"type": name, "evidence": found[name]}
    return {"type": None, "evidence": []}


# ----------------------------------------------------------------
# Metadata extraction (per type; values plain-text cleaned)
# ----------------------------------------------------------------

_AUTHOR_ITEMPROP_RE = re.compile(
    r"itemprop\s*=\s*[\"']author[\"'][^>]*>.*?"
    r"itemprop\s*=\s*[\"']name[\"'][^>]*>([^<]+)",
    re.I | re.S)


def _jsonld_authors(objs):
    names = []
    for obj in objs:
        author = obj.get("author")
        if isinstance(author, dict):
            author = [author]
        if isinstance(author, list):
            for a in author:
                if isinstance(a, dict) and a.get("name"):
                    names.append(str(a["name"]))
                elif isinstance(a, str):
                    names.append(a)
        for key in ("comment", "suggestedAnswer",
                    "acceptedAnswer"):
            sub = obj.get(key)
            if isinstance(sub, dict):
                sub = [sub]
            if isinstance(sub, list):
                names.extend(_jsonld_authors(
                    [s for s in sub if isinstance(s, dict)]))
    return names


def _dedup_ordered(values):
    seen, out = set(), []
    for v in values:
        v = _clean_value(v)
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def extract_metadata(data, type_name):
    """The source metadata a type template lifts, as an
    ordered dict of the fields actually found (absent fields
    are absent — never present-but-empty)."""
    text = _decode(data)
    meta = _meta_map(text)
    objs = _jsonld_objects(text)

    def first(*keys):
        for key in keys:
            vals = meta.get(key) or []
            if vals and _clean_value(vals[0]):
                return _clean_value(vals[0])
        return None

    def all_of(key):
        return _dedup_ordered(meta.get(key) or [])

    out = {}
    if type_name == "paper":
        authors = all_of("citation_author") \
            or _dedup_ordered(_jsonld_authors(objs))
        if authors:
            out["authors"] = authors
        venue = first("citation_journal_title",
                      "citation_conference_title")
        if venue:
            out["venue"] = venue
        doi = first("citation_doi")
        if doi:
            out["doi"] = doi
        published = first("citation_publication_date",
                          "citation_date", "citation_year")
        if published:
            out["published"] = published
        abstract = first("citation_abstract")
        if abstract:
            out["abstract"] = abstract
            out["abstract_from"] = "citation_abstract meta"
    elif type_name == "article":
        authors = all_of("author") or all_of("article:author") \
            or _dedup_ordered(_jsonld_authors(objs))
        if authors:
            out["authors"] = authors
        published = first("article:published_time")
        if published:
            out["published"] = published
        section = first("article:section")
        if section:
            out["section"] = section
    elif type_name == "video":
        desc = first("og:description", "description")
        if not desc:
            for obj in objs:
                if obj.get("description"):
                    desc = _clean_value(obj["description"])
                    break
        if desc:
            out["description"] = desc
        duration = first("video:duration", "og:video:duration")
        if duration:
            out["duration"] = duration
        uploader = first("og:video:actor")
        if uploader:
            out["uploader"] = uploader
    elif type_name == "forum":
        authors = _dedup_ordered(
            _AUTHOR_ITEMPROP_RE.findall(text)) \
            or _dedup_ordered(_jsonld_authors(objs))
        if authors:
            out["authors"] = authors
        posts = max(
            len(re.findall(r"itemprop\s*=\s*[\"']comment[\"']",
                           text, re.I)),
            len(re.findall(r"data-post-number\s*=", text, re.I)))
        if posts:
            out["posts_detected"] = posts
    return out


# ----------------------------------------------------------------
# Body shaping + fidelity notes
# ----------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$", re.M)


def _sections(md):
    """Split markdown into (heading_line, level, title,
    start, end) spans; the preamble before the first heading
    is span 0 with heading None."""
    spans = []
    matches = list(_HEADING_RE.finditer(md))
    if not matches:
        return [{"heading": None, "level": 0, "title": "",
                 "start": 0, "end": len(md)}]
    if matches[0].start() > 0:
        spans.append({"heading": None, "level": 0, "title": "",
                      "start": 0, "end": matches[0].start()})
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) \
            else len(md)
        spans.append({"heading": m.group(0),
                      "level": len(m.group(1)),
                      "title": m.group(2),
                      "start": m.start(), "end": end})
    return spans


def _shape_paper(md, metadata):
    notes = []
    spans = _sections(md)
    headed = [s for s in spans if s["heading"]]
    if headed:
        titles = [s["title"] for s in headed]
        notes.append(
            "section structure preserved in source order: %s"
            % "; ".join(titles))
    abstract_idx = None
    for i, s in enumerate(spans):
        if s["heading"] and s["title"].strip().lower() \
                .startswith("abstract"):
            abstract_idx = i
            break
    if abstract_idx is not None:
        before = [s for s in spans[:abstract_idx]
                  if s["heading"]]
        preamble = spans[0] if spans and not spans[0]["heading"] \
            else None
        if not before and (preamble is None
                           or not preamble["end"]):
            notes.append("abstract already leads the "
                         "converted body; left in place")
        else:
            s = spans[abstract_idx]
            chunk = md[s["start"]:s["end"]]
            rest = (md[:s["start"]] + md[s["end"]:]).strip("\n")
            md = chunk.rstrip("\n") + "\n\n" + rest + "\n"
            notes.append(
                "abstract section moved to the lead (it "
                "followed %d headed section(s))"
                % len(before))
    elif metadata.get("abstract"):
        notes.append(
            "abstract present in the page's metadata only "
            "(%s) — recorded in the sidecar, NOT injected "
            "into the body: lifted text does not enter the "
            "draft outside the converted body"
            % metadata.get("abstract_from", "meta"))
    else:
        notes.append("no abstract found in the source "
                     "(neither a body section nor metadata)")
    if not metadata.get("authors"):
        notes.append("no authors in the page's citation "
                     "metadata — none recorded")
    if not metadata.get("doi"):
        notes.append("no DOI in the page's citation "
                     "metadata — none recorded")
    return md, notes


def _shape_video(md, metadata, data, gate_clean):
    notes = []
    text = _decode(data)
    has_track = bool(re.search(
        r"<track\b[^>]*(kind\s*=\s*[\"'](captions|subtitles)"
        r"|itemprop\s*=\s*[\"']transcript[\"'])", text, re.I))
    desc = metadata.get("description")
    if not desc:
        notes.append("no description in the page's metadata "
                     "— the body is the converted page as-is")
    elif gate_clean is None:
        notes.append(
            "description lead withheld: the converter's "
            "sanitiser is unavailable in this run — lifted "
            "text is never carried past an absent gate")
    else:
        cleaned, scan = gate_clean(desc)
        verdict = (scan or {}).get("verdict")
        if verdict == "blocked":
            kinds = sorted({f.get("kind", "?")
                            for f in (scan or {})
                            .get("findings") or []})
            notes.append(
                "description lead withheld: the sanitiser "
                "verdict on the lifted description was "
                "'blocked' (finding kinds: %s) — the text "
                "stays out of the draft body"
                % (", ".join(kinds) or "none named"))
        elif cleaned and md.lstrip().startswith(cleaned[:80]):
            notes.append("the page description already opens "
                         "the converted body; no lead added")
        elif cleaned:
            lead = ("## Description (from the page's own "
                    "metadata)\n\n%s\n\n" % cleaned.strip())
            md = lead + md
            notes.append(
                "body leads with the page description "
                "lifted from its own metadata, passed "
                "through the converter's sanitiser "
                "(verdict: %s)" % verdict)
        else:
            notes.append("the lifted description sanitised "
                         "to nothing; no lead added")
    if has_track:
        notes.append(
            "the page advertises a caption/transcript "
            "track; the clip path does not fetch caption "
            "tracks, so no transcript text is in this "
            "capture")
    else:
        notes.append(
            "no embedded transcript was present in the "
            "fetched page; the description record is the "
            "page's own metadata, not a transcript")
    return md, notes


def _shape_forum(md, metadata):
    notes = ["thread order preserved: posts kept in the "
             "fetched page's document order; nothing "
             "reordered, nothing dropped"]
    if metadata.get("posts_detected"):
        notes.append("%d posts detected in the source "
                     "markup" % metadata["posts_detected"])
    if metadata.get("authors"):
        notes.append(
            "thread authors recorded in frontmatter in "
            "order of first appearance (%d)"
            % len(metadata["authors"]))
    else:
        notes.append(
            "no per-post authorship could be attributed "
            "from the fetched markup — none recorded")
    return md, notes


def shape_body(md, type_name, metadata, data=None,
               gate_clean=None):
    """Compose the staged body for a type. Returns
    (md, fidelity_notes). generic is the identity: the body
    and an empty note list — the current clip behaviour,
    factored. Every other template's notes name what it
    moved, kept, or could not find."""
    metadata = metadata or {}
    if type_name == "generic":
        return md, []
    if type_name == "paper":
        return _shape_paper(md, metadata)
    if type_name == "video":
        return _shape_video(md, metadata, data, gate_clean)
    if type_name == "forum":
        return _shape_forum(md, metadata)
    if type_name == "article":
        notes = ["article body kept exactly as converted, "
                 "in document order"]
        if metadata.get("authors"):
            notes.append("byline lifted to frontmatter "
                         "from page metadata")
        else:
            notes.append("no byline in the page's "
                         "metadata — none recorded")
        if not metadata.get("published"):
            notes.append("no publication date in the "
                         "page's metadata — none recorded")
        return md, notes
    if type_name == "docs":
        return md, [
            "documentation body kept exactly as converted; "
            "navigation handling belongs to the extraction "
            "profile (see the sidecar's clip_template "
            "block), not to this composition"]
    raise SourceTemplateError("unknown source template %r"
                              % type_name)


# ----------------------------------------------------------------
# Frontmatter + resolution
# ----------------------------------------------------------------

def _q(value):
    return '"%s"' % str(value).replace('"', "'")


def frontmatter_lines(type_name, metadata):
    """Draft frontmatter lines a template adds (non-generic
    templates only, fields actually found only). generic
    adds none — one half of its byte-identity with the
    pre-template clip path."""
    metadata = metadata or {}
    lines = []
    if type_name in ("paper", "article") \
            and metadata.get("authors"):
        lines.append("source_authors: [%s]"
                     % ", ".join(_q(a)
                                 for a in metadata["authors"]))
    if type_name == "paper":
        if metadata.get("venue"):
            lines.append("source_venue: %s"
                         % _q(metadata["venue"]))
        if metadata.get("doi"):
            lines.append("source_doi: %s" % _q(metadata["doi"]))
        if metadata.get("published"):
            lines.append("source_published: %s"
                         % _q(metadata["published"]))
    if type_name == "article":
        if metadata.get("published"):
            lines.append("source_published: %s"
                         % _q(metadata["published"]))
        if metadata.get("section"):
            lines.append("source_section: %s"
                         % _q(metadata["section"]))
    if type_name == "video" and metadata.get("duration"):
        lines.append("source_duration: %s"
                     % _q(metadata["duration"]))
    if type_name == "forum" and metadata.get("authors"):
        lines.append("thread_authors: [%s]"
                     % ", ".join(_q(a)
                                 for a in metadata["authors"]))
    return lines


def validate_name(name):
    if name is not None and name not in TEMPLATE_NAMES:
        raise SourceTemplateError(
            "unknown source template %r (one of: %s)"
            % (name, ", ".join(TEMPLATE_NAMES)))


def resolve(explicit, data, url=None, content_type=None):
    """The resolution record a clip carries: the template
    applied, how it was chosen, and the evidence. An
    explicit choice wins; detection runs anyway so the
    record names what it overrode."""
    validate_name(explicit)
    detected = detect_type(data, url=url,
                           content_type=content_type)
    if explicit:
        return {"name": explicit, "selection": "explicit",
                "evidence": [],
                "detected_type": detected["type"]}
    if detected["type"]:
        return {"name": detected["type"],
                "selection": "detected",
                "evidence": detected["evidence"],
                "detected_type": detected["type"]}
    return {"name": "generic", "selection": "fallback",
            "evidence": [], "detected_type": None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("match")
    p.add_argument("--url", default=None)
    p.add_argument("--file", type=Path, default=None,
                   help="read these bytes (never fetched)")
    p.add_argument("--template", default=None,
                   help="an explicit choice, to show the "
                        "override record")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "list":
            for name in TEMPLATE_NAMES:
                print("%s: %s" % (name, TEMPLATES[name]["note"]))
            return 0
        if args.file is None:
            print("wiki_source_templates: match needs "
                  "--file PATH (bytes are read, never "
                  "fetched)", file=sys.stderr)
            return 2
        if not args.file.is_file():
            raise SourceTemplateError(
                "no such file: %s" % args.file)
        record = resolve(args.template,
                         args.file.read_bytes(), url=args.url)
        print(json.dumps(record, indent=2, sort_keys=True))
    except SourceTemplateError as exc:
        print("wiki_source_templates: %s" % exc,
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
