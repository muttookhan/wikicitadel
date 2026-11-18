#!/usr/bin/env python3
"""wiki_scrape_profiles.py — scrape profiles for feedless sites
+ fit-Markdown extraction (implementation wave W4, 2026-10-22;
build-list row: "Scrape profiles for feedless sites +
fit-Markdown web front end").

Patterns, both CLEAN RE-IMPLEMENTATIONS — ideas only, no code
taken: (1) FreshRSS's XPath scraping for sites that publish no
feed (FreshRSS is AGPL — idea only, per the house licence
rule): a feedless listing page is turned into feed-shaped items
by a PROFILE held as data; (2) crawl4ai's fit-Markdown pruning
(Apache-2.0 — the idea re-implemented, not the code): blocks
are scored by text density / link density and low-value blocks
are pruned before conversion, with the pruning recorded.

A scrape profile lives as DATA in templates/scrape-profiles.json
(beside templates/site-rules.json, the TA4 per-site rules file —
the two layers are distinct: site rules are per-DOMAIN strip /
keep facts for the converter, scrape profiles are per-SHAPE
extraction + pruning + item schemas for the web-ingest front
end). A profile is a closed-vocabulary object:

    {"name": "listing-cards",
     "note": "why this profile exists",
     "url_patterns": ["regex", ...],          (selection)
     "shape": [{"selector": ".post-card",
                "min_count": 2}],             (selection)
     "keep": ".article-body",                 (selector|null)
     "strip": [".comments", ...],             (selectors)
     "fit": {"enabled": true,
             "min_text_chars": 25,
             "max_link_density": 0.6,
             "min_text_density": 0.2},
     "items": {"selector": ".post-card",
               "fields": {"title": {"selector": ".post-title",
                                    "required": true,
                                    "transform": "collapse_ws"},
                          "link": {"selector": "a.post-link",
                                   "attr": "href",
                                   "required": true},
                          "date": {"selector": "time",
                                   "attr": "datetime"}}}}

SELECTORS come in two dialects, both deliberately small and
both validated at load — anything outside the grammar is
refused BY NAME, never partially applied:

- CSS subset: compound selectors (`tag`, `*`, `.class`,
  `#id`, `tag.class`, `[attr]`, `[attr="value"]`, chained)
  joined by the descendant (space) and child (`>`)
  combinators. A bare "." selects the context element itself
  (field extraction from the item element).
- XPath subset: an expression starting `//` or `.//`, steps
  of `tag` / `*` with predicates `[@attr]`, `[@attr='v']`,
  `[contains(@attr,'v')]`, `[n]` (1-based, per parent), and a
  final step of `@attr` or `text()`.

SELECTION: an explicit name wins; else the first profile (file
order) with a matching url_pattern; else the first whose
shape selectors all meet their min_count in the page; else
the built-in GENERIC profile (no keep / strip, fit disabled,
no items) with the fallback STATED in the record — the same
fallback the clip path returns when the profiles file is
absent. The chosen profile and how it was chosen ride in the
clip sidecar's `scrape_profile` record (scripts/wiki_clip.py
wires this module in behind its fetch contract: this module
never fetches anything itself).

FIT-MARKDOWN: under a profile, the conversion copy of the page
is rewritten — profile strips removed, the keep root retained,
and (fit enabled) block elements pruned by density rules.
EVERY removal is recorded in a fidelity record (rule, element,
measured densities, counts) that lands in the sidecar: what
was dropped is never silent. The preserved source stays the
fetched bytes verbatim (the clip path's standing rule); only
the conversion copy is fitted. A profile cannot weaken the
injection gate: fitted HTML still runs through
wiki_convert.py's full sanitiser, and no profile field can
mark content trusted — the vocabulary has no such key, and an
unknown key refuses the whole file at load.

ITEM EXTRACTION (the feedless half): a profile with an `items`
schema extracts feed-shaped items {title, link, date, ...}
from a listing page; scripts/wiki_clip.py clip --scrape-items
stages each item as its own capture through the same converter
defences as a feed item. An extraction that finds no items is
a door failure there, never an empty capture.

    python3 scripts/wiki_scrape_profiles.py check [--root DIR]
    python3 scripts/wiki_scrape_profiles.py list [--root DIR]
    python3 scripts/wiki_scrape_profiles.py match <url>
        [--file page.html] [--root DIR]
    python3 scripts/wiki_scrape_profiles.py extract <page.html>
        --profile NAME [--base URL] [--root DIR]
    python3 scripts/wiki_scrape_profiles.py fit <page.html>
        --profile NAME [--root DIR]

Exit codes: 0 ok · 1 refusal / invalid profiles · 2 usage error.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from html import escape as _escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
PROFILES_FILE = Path("templates/scrape-profiles.json")

VOID = {"area", "base", "br", "col", "embed", "hr", "img",
        "input", "link", "meta", "param", "source", "track",
        "wbr"}

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form",
    "header", "li", "main", "nav", "ol", "section", "table",
    "td", "th", "tr", "ul",
}

TRANSFORMS = ("none", "strip", "collapse_ws", "iso_date")
_PROFILE_KEYS = {"name", "note", "url_patterns", "shape",
                 "keep", "strip", "fit", "items"}
_SHAPE_KEYS = {"selector", "min_count"}
_FIT_KEYS = {"enabled", "min_text_chars", "max_link_density",
             "min_text_density"}
_ITEMS_KEYS = {"selector", "fields"}
_FIELD_KEYS = {"selector", "attr", "required", "transform"}
_ATTR_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")

GENERIC_PROFILE = {
    "name": "generic",
    "note": "built-in fallback: whole page, no keep / strip, "
            "fit pruning disabled, no item schema",
    "url_patterns": [],
    "shape": [],
    "keep": None,
    "strip": [],
    "fit": {"enabled": False, "min_text_chars": 25,
            "max_link_density": 0.6, "min_text_density": 0.2},
    "items": None,
}


class ProfileError(Exception):
    """A refusal: invalid profile data, named. Nothing is
    partially applied when this is raised at load."""


# ----------------------------------------------------------------
# A tiny DOM (stdlib html.parser) — the tree both selector
# dialects run over, and the fit filter rewrites.
# ----------------------------------------------------------------

class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag = tag                    # None = document root
        self.attrs = attrs or []          # [(name, value|None)]
        self.children = []                # _Node | str | _Comment
        self.parent = parent

    def attr(self, name):
        for k, v in self.attrs:
            if k == name:
                return v
        return None

    def classes(self):
        return (self.attr("class") or "").split()

    def descriptor(self):
        out = self.tag or "?"
        if self.attr("id"):
            out += "#" + self.attr("id")
        for cls in self.classes():
            out += "." + cls
        return out


class _Comment:
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node(None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, list(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = _Node(tag, list(attrs), self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)

    def handle_comment(self, data):
        self.stack[-1].children.append(_Comment(data))


def parse_html(text):
    builder = _TreeBuilder()
    builder.feed(text or "")
    builder.close()
    return builder.root


def _iter_elements(node):
    """Every element descendant of `node`, document order."""
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _iter_elements(child)


def node_text(node):
    parts = []

    def walk(n):
        for c in n.children:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, _Node):
                walk(c)

    walk(node)
    return "".join(parts)


def _collapse(text):
    return " ".join((text or "").split())


def serialise(node):
    """Deterministic HTML for a DOM subtree: attributes in
    source order, void elements unclosed, text escaped.
    Comments are preserved verbatim."""
    out = []

    def walk(n):
        if isinstance(n, str):
            out.append(_escape(n, quote=False))
            return
        if isinstance(n, _Comment):
            out.append("<!--%s-->" % n.text)
            return
        if n.tag is None:
            for c in n.children:
                walk(c)
            return
        attrs = "".join(
            ' %s="%s"' % (k, _escape(v, quote=True))
            if v is not None else " %s" % k
            for k, v in n.attrs)
        out.append("<%s%s>" % (n.tag, attrs))
        if n.tag not in VOID:
            for c in n.children:
                walk(c)
            out.append("</%s>" % n.tag)

    walk(node)
    return "".join(out)


def _inner_html(node):
    holder = _Node(None)
    holder.children = list(node.children)
    return serialise(holder)


# ----------------------------------------------------------------
# CSS subset
# ----------------------------------------------------------------

def _split_css(selector):
    """Split a CSS selector into [(combinator, compound_text)]
    — combinator is ' ' (descendant) or '>' (child); the first
    compound's combinator is ' '. Tracks [] and quotes so an
    attribute value may contain spaces or '>'."""
    parts, buf, depth, quote, pending = [], [], 0, None, " "
    i = 0
    text = selector.strip()

    def flush():
        piece = "".join(buf).strip()
        if piece:
            parts.append((pending, piece))
        buf.clear()

    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif depth == 0 and ch == ">":
            flush()
            pending = ">"
            i += 1
            while i < len(text) and text[i].isspace():
                i += 1
            continue
        elif depth == 0 and ch.isspace():
            flush()
            if parts or buf:
                pending = " "
            i += 1
            while i < len(text) and text[i].isspace():
                i += 1
            continue
        else:
            buf.append(ch)
        i += 1
    flush()
    if not parts:
        raise ProfileError("empty CSS selector")
    return parts


_COMPOUND_TOKEN = re.compile(r"""
    (?P<tag>\*|[a-zA-Z][a-zA-Z0-9-]*)
  | \.(?P<cls>[a-zA-Z0-9_-]+)
  | \#(?P<ident>[a-zA-Z0-9_-]+)
  | \[(?P<attr>[a-zA-Z][a-zA-Z0-9_-]*)
      (?:\s*=\s*(?P<val>"[^"]*"|'[^']*'|[a-zA-Z0-9_-]+))?\]
""", re.X)


def _parse_compound(text, whole):
    """One compound selector -> (tag|None, classes, id, attrs).
    Raises ProfileError naming the whole selector on anything
    outside the grammar."""
    tag, classes, ident, attrs = None, [], None, []
    pos = 0
    for m in _COMPOUND_TOKEN.finditer(text):
        if m.start() != pos:
            raise ProfileError(
                "unsupported CSS selector %r — the vocabulary "
                "is tag / * / .class / #id / [attr] / "
                "[attr=\"value\"], joined by space and >"
                % whole)
        pos = m.end()
        if m.group("tag") is not None:
            if tag is not None or classes or ident or attrs:
                raise ProfileError(
                    "unsupported CSS selector %r — a tag must "
                    "lead its compound" % whole)
            tag = m.group("tag").lower()
        elif m.group("cls") is not None:
            classes.append(m.group("cls"))
        elif m.group("ident") is not None:
            ident = m.group("ident")
        else:
            val = m.group("val")
            if val and val[0] in "\"'":
                val = val[1:-1]
            attrs.append((m.group("attr").lower(), val))
    if pos != len(text) or (tag is None and not classes
                            and ident is None and not attrs):
        raise ProfileError(
            "unsupported CSS selector %r — the vocabulary is "
            "tag / * / .class / #id / [attr] / [attr=\"value\"], "
            "joined by space and >" % whole)
    return (tag, classes, ident, attrs)


def _match_compound(node, compound):
    tag, classes, ident, attrs = compound
    if node.tag is None:
        return False
    if tag and tag != "*" and node.tag != tag:
        return False
    if ident is not None and node.attr("id") != ident:
        return False
    have = node.classes()
    if any(c not in have for c in classes):
        return False
    for name, val in attrs:
        actual = node.attr(name)
        if actual is None:
            return False
        if val is not None and actual != val:
            return False
    return True


def css_select(context, selector):
    """Elements under `context` matching the CSS subset
    selector, document order, deduplicated. A bare "." returns
    the context element itself."""
    if selector.strip() == ".":
        return [context] if context.tag is not None else []
    steps = [(comb, _parse_compound(piece, selector))
             for comb, piece in _split_css(selector)]
    current = [context]
    for combinator, compound in steps:
        nxt, seen = [], set()
        for base in current:
            if combinator == ">":
                candidates = [c for c in base.children
                              if isinstance(c, _Node)]
            else:
                candidates = _iter_elements(base)
            for cand in candidates:
                if id(cand) not in seen \
                        and _match_compound(cand, compound):
                    seen.add(id(cand))
                    nxt.append(cand)
        current = nxt
    return current


# ----------------------------------------------------------------
# XPath subset
# ----------------------------------------------------------------

_XPATH_STEP_RE = re.compile(r"""
    ^(?P<tag>\*|[a-zA-Z][a-zA-Z0-9_-]*)
     (?P<preds>(?:\[[^\]]*\])*)$
""", re.X)
_XPATH_PRED_RE = re.compile(r"""
    \[(?:@(?P<attr>[a-zA-Z][a-zA-Z0-9_-]*)
        (?:\s*=\s*(?P<val>"[^"]*"|'[^']*'))?
      |contains\(\s*@(?P<cattr>[a-zA-Z][a-zA-Z0-9_-]*)
        \s*,\s*(?P<cval>"[^"]*"|'[^']*')\s*\)
      |(?P<pos>[0-9]+))\]
""", re.X)


def _split_xpath(expr):
    """Split an XPath-subset expression into (axis, step_text)
    pairs — axis '//' (descendants) or '/' (children) — plus an
    optional terminal ('@attr' | 'text()'). Quote/bracket aware
    so attribute values may contain '/'."""
    text = expr.strip()
    if text.startswith(".//"):
        axis, i = "//", 3
    elif text.startswith("//"):
        axis, i = "//", 2
    else:
        raise ProfileError(
            "unsupported XPath %r — expressions start with // "
            "or .//" % expr)
    steps, buf, depth, quote = [], [], 0, None
    terminal = None
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            depth -= 1
            buf.append(ch)
        elif ch == "/" and depth == 0:
            piece = "".join(buf).strip()
            buf.clear()
            if piece:
                steps.append((axis, piece))
            if i + 1 < len(text) and text[i + 1] == "/":
                axis = "//"
                i += 2
            else:
                axis = "/"
                i += 1
            continue
        else:
            buf.append(ch)
        i += 1
    piece = "".join(buf).strip()
    if piece:
        if piece.startswith("@") or piece == "text()":
            terminal = piece
        else:
            steps.append((axis, piece))
    if not steps:
        raise ProfileError(
            "unsupported XPath %r — no element steps" % expr)
    return steps, terminal


def _parse_xpath_step(step_text, whole):
    if step_text.startswith("@") or step_text == "text()":
        raise ProfileError(
            "unsupported XPath %r — @attr / text() are only "
            "allowed as the final step" % whole)
    m = _XPATH_STEP_RE.match(step_text)
    if not m:
        raise ProfileError(
            "unsupported XPath %r — steps are tag / * with "
            "[@attr], [@attr='v'], [contains(@attr,'v')] or "
            "[n] predicates" % whole)
    preds = []
    rest = m.group("preds") or ""
    pos = 0
    for pm in _XPATH_PRED_RE.finditer(rest):
        if pm.start() != pos:
            raise ProfileError(
                "unsupported XPath predicate in %r — the "
                "vocabulary is [@attr], [@attr='v'], "
                "[contains(@attr,'v')], [n]" % whole)
        pos = pm.end()
        if pm.group("pos"):
            preds.append(("pos", int(pm.group("pos"))))
        elif pm.group("cattr"):
            val = pm.group("cval")[1:-1]
            preds.append(("contains", pm.group("cattr").lower(),
                          val))
        else:
            val = pm.group("val")
            if val:
                val = val[1:-1]
            preds.append(("attr", pm.group("attr").lower(), val))
    if pos != len(rest):
        raise ProfileError(
            "unsupported XPath predicate in %r" % whole)
    return (m.group("tag").lower(), preds)


def _xpath_eval(context, expr):
    """Returns (nodes, terminal): terminal is None, '@attr' or
    'text()'."""
    steps, terminal = _split_xpath(expr)
    parsed = [_parse_xpath_step(s, expr) for _a, s in steps]
    current = [context]
    for (axis, _raw), (tag, preds) in zip(steps, parsed):
        nxt = []
        for base in current:
            if axis == "//":
                candidates = [el for el in _iter_elements(base)
                              if tag == "*" or el.tag == tag]
            else:
                candidates = [c for c in base.children
                              if isinstance(c, _Node)
                              and (tag == "*" or c.tag == tag)]
            for kind, *rest in preds:
                if kind == "attr":
                    name, val = rest
                    candidates = [
                        c for c in candidates
                        if c.attr(name) is not None
                        and (val is None or c.attr(name) == val)]
                elif kind == "contains":
                    name, val = rest
                    candidates = [
                        c for c in candidates
                        if val in (c.attr(name) or "")]
                elif kind == "pos":
                    n = rest[0]
                    by_parent = {}
                    for c in candidates:
                        by_parent.setdefault(id(c.parent),
                                             []).append(c)
                    keep = []
                    for group in by_parent.values():
                        if 1 <= n <= len(group):
                            keep.append(group[n - 1])
                    candidates = keep
            nxt.extend(candidates)
        seen, deduped = set(), []
        for cand in nxt:
            if id(cand) not in seen:
                seen.add(id(cand))
                deduped.append(cand)
        current = deduped
    return current, terminal


def xpath_select(context, expr):
    nodes, terminal = _xpath_eval(context, expr)
    if terminal is not None:
        raise ProfileError(
            "unsupported XPath %r for element selection — "
            "@attr / text() end a value expression" % expr)
    return nodes


def xpath_value(context, expr):
    """The string value of an XPath-subset expression: the
    terminal @attr / text(), or the first matched element's
    text. None when nothing matches."""
    nodes, terminal = _xpath_eval(context, expr)
    if not nodes:
        return None
    node = nodes[0]
    if terminal is None or terminal == "text()":
        return node_text(node)
    return node.attr(terminal[1:])


def is_xpath(selector):
    text = selector.strip()
    return text.startswith("/") or text.startswith(".//")


def select(context, selector):
    """Dispatch on dialect: a leading / means XPath, anything
    else is the CSS subset."""
    if is_xpath(selector):
        return xpath_select(context, selector)
    return css_select(context, selector)


def select_value(context, selector):
    """A field's value: element text (or the @attr / text()
    terminal for XPath)."""
    if is_xpath(selector):
        return xpath_value(context, selector)
    nodes = css_select(context, selector)
    if not nodes:
        return None
    return node_text(nodes[0])


def validate_selector(selector, where):
    """Parse-check a selector at profile load: the refusal
    names the selector and where it sits."""
    if not isinstance(selector, str) or not selector.strip():
        raise ProfileError("%s: selector must be a non-empty "
                           "string" % where)
    try:
        if is_xpath(selector):
            steps, _t = _split_xpath(selector)
            for _a, s in steps:
                _parse_xpath_step(s, selector)
        elif selector.strip() != ".":
            for _c, piece in _split_css(selector):
                _parse_compound(piece, selector)
    except ProfileError as exc:
        raise ProfileError("%s: %s" % (where, exc)) from exc


# ----------------------------------------------------------------
# Profiles: load + closed-vocabulary validation
# ----------------------------------------------------------------

def _check_keys(obj, allowed, where):
    if not isinstance(obj, dict):
        raise ProfileError("%s must be an object" % where)
    for key in obj:
        if key not in allowed:
            raise ProfileError(
                "%s: unknown key %r — the vocabulary is %s; a "
                "profile is never partially applied, so the "
                "whole file is refused"
                % (where, key, ", ".join(sorted(allowed))))


def _validate_field(field, where):
    _check_keys(field, _FIELD_KEYS, where)
    sel = field.get("selector")
    if sel is not None:
        validate_selector(sel, where)
    attr = field.get("attr", "text")
    if attr not in ("text", "html") and not _ATTR_RE.match(attr):
        raise ProfileError(
            "%s: unsupported attr %r — 'text', 'html' or an "
            "attribute name" % (where, attr))
    transform = field.get("transform", "none")
    if transform not in TRANSFORMS:
        raise ProfileError(
            "%s: unknown transform %r — the vocabulary is %s"
            % (where, transform, ", ".join(TRANSFORMS)))
    if "required" in field \
            and not isinstance(field["required"], bool):
        raise ProfileError("%s: 'required' must be true/false"
                           % where)


def validate_profiles(data, source="profiles"):
    """Validate the whole profiles document. ANY defect refuses
    the whole file by name — a profile is data with a closed
    vocabulary, never partially applied."""
    if not isinstance(data, dict):
        raise ProfileError("%s must be a JSON object" % source)
    for key in data:
        if key not in ("version", "profiles"):
            raise ProfileError(
                "%s: unknown top-level key %r" % (source, key))
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        raise ProfileError("%s: 'profiles' must be a list"
                           % source)
    seen = set()
    for i, profile in enumerate(profiles):
        where = "%s: profile #%d" % (source, i)
        _check_keys(profile, _PROFILE_KEYS, where)
        name = profile.get("name")
        if not name or not isinstance(name, str):
            raise ProfileError("%s needs a name" % where)
        where = "%s: profile %r" % (source, name)
        if name == GENERIC_PROFILE["name"]:
            raise ProfileError(
                "%s: the name 'generic' is reserved for the "
                "built-in fallback" % where)
        if name in seen:
            raise ProfileError("%s: duplicate profile name %r"
                               % (source, name))
        seen.add(name)
        for pat in profile.get("url_patterns") or []:
            if not isinstance(pat, str):
                raise ProfileError(
                    "%s: url_patterns must be strings" % where)
            try:
                re.compile(pat)
            except re.error as exc:
                raise ProfileError(
                    "%s: url_pattern %r does not compile: %s"
                    % (where, pat, exc)) from exc
        for j, shape in enumerate(profile.get("shape") or []):
            swhere = "%s shape #%d" % (where, j)
            _check_keys(shape, _SHAPE_KEYS, swhere)
            if "selector" not in shape:
                raise ProfileError("%s needs a selector"
                                   % swhere)
            validate_selector(shape["selector"], swhere)
            count = shape.get("min_count", 1)
            if not isinstance(count, int) or count < 1:
                raise ProfileError(
                    "%s: min_count must be a positive integer"
                    % swhere)
        if profile.get("keep") is not None:
            validate_selector(profile["keep"],
                              "%s keep" % where)
        for sel in profile.get("strip") or []:
            validate_selector(sel, "%s strip" % where)
        fit = profile.get("fit")
        if fit is not None:
            _check_keys(fit, _FIT_KEYS, "%s fit" % where)
            for key in ("min_text_chars",):
                if key in fit and (not isinstance(fit[key], int)
                                   or fit[key] < 0):
                    raise ProfileError(
                        "%s fit: %s must be a non-negative "
                        "integer" % (where, key))
            for key in ("max_link_density", "min_text_density"):
                if key in fit and (not isinstance(
                        fit[key], (int, float))
                        or not 0 <= fit[key] <= 1):
                    raise ProfileError(
                        "%s fit: %s must be a number in "
                        "[0, 1]" % (where, key))
        items = profile.get("items")
        if items is not None:
            _check_keys(items, _ITEMS_KEYS, "%s items" % where)
            if "selector" not in items:
                raise ProfileError(
                    "%s items needs a selector" % where)
            validate_selector(items["selector"],
                              "%s items" % where)
            fields = items.get("fields")
            if not isinstance(fields, dict) or not fields:
                raise ProfileError(
                    "%s items needs a non-empty 'fields' "
                    "object" % where)
            for fname, field in fields.items():
                _validate_field(field, "%s field %r"
                                % (where, fname))
    return profiles


def load_profiles(root=ROOT):
    """The tree's scrape profiles (file order) — NOT including
    the built-in generic fallback, which select_profile()
    appends by construction. An absent file is an empty list
    (stated by check); a malformed one is a loud ProfileError."""
    path = Path(root) / PROFILES_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError("scrape profiles %s are unreadable: "
                           "%s" % (path, exc)) from exc
    return validate_profiles(data, source=str(path))


def get_profile(profiles, name):
    """A profile by name, the built-in generic included."""
    if name == GENERIC_PROFILE["name"]:
        return GENERIC_PROFILE
    for profile in profiles:
        if profile.get("name") == name:
            return profile
    return None


def _fit_of(profile):
    fit = dict(GENERIC_PROFILE["fit"])
    fit.update(profile.get("fit") or {})
    return fit


# ----------------------------------------------------------------
# Selection
# ----------------------------------------------------------------

def select_profile(url, html_text, profiles, explicit=None):
    """Choose the profile for a page. Returns (profile,
    selection) — selection is 'explicit', 'url', 'shape' or
    'generic-fallback', and the fallback is always stated,
    never silent. `profiles` is load_profiles()' output (file
    profiles only); the generic fallback is built in."""
    if explicit is not None:
        profile = get_profile(profiles, explicit)
        if profile is None:
            raise ProfileError(
                "unknown scrape profile %r — the profiles are "
                "%s plus the built-in 'generic'"
                % (explicit,
                   ", ".join(repr(p["name"]) for p in profiles)
                   or "(none on file)"))
        return profile, "explicit"
    for profile in profiles:
        for pat in profile.get("url_patterns") or []:
            if re.search(pat, url or ""):
                return profile, "url"
    if html_text:
        root = parse_html(html_text)
        for profile in profiles:
            shape = profile.get("shape") or []
            if shape and all(
                    len(select(root, s["selector"]))
                    >= s.get("min_count", 1) for s in shape):
                return profile, "shape"
    return GENERIC_PROFILE, "generic-fallback"


# ----------------------------------------------------------------
# Fit-Markdown: strip / keep / density pruning, all recorded
# ----------------------------------------------------------------

def _detach(node):
    if node.parent is not None:
        node.parent.children = [
            c for c in node.parent.children if c is not node]
        node.parent = None


def _is_attached(node, root):
    while node is not None:
        if node is root:
            return True
        node = node.parent
    return False


def _ancestors(node):
    out = set()
    node = node.parent
    while node is not None:
        out.add(id(node))
        node = node.parent
    return out


def fit_markdown(html_text, profile):
    """Rewrite `html_text` under `profile`'s strip / keep /
    fit rules. Returns (new_html, fidelity): fidelity records
    every removal by rule with the measured values, plus
    counts — what was dropped is never silent. When the
    profile carries no strip, no keep and fit is disabled (the
    generic fallback), the input is returned byte-identical
    with fidelity['applied'] False."""
    fit = _fit_of(profile)
    strips = list(profile.get("strip") or [])
    keep_sel = profile.get("keep")
    fidelity = {
        "applied": False,
        "profile": profile.get("name"),
        "stripped": {},          # selector -> elements removed
        "keep": None,            # {selector, matched} when set
        "pruned": [],            # per-element fit records
        "pruned_counts": {},     # fit rule -> count
    }
    if not strips and not keep_sel and not fit.get("enabled"):
        return html_text, fidelity
    root = parse_html(html_text)
    # 1. Profile strips.
    for sel in strips:
        matched = select(root, sel)
        for node in matched:
            if _is_attached(node, root):
                _detach(node)
        if matched:
            fidelity["stripped"][sel] = len(matched)
            fidelity["applied"] = True
    # 2. Keep root: retain the first match and its ancestors /
    #    descendants; everything else goes. A keep selector
    #    that matches nothing leaves the document otherwise
    #    intact — a rotted keep rule must not empty a capture
    #    (wiki_site_rules' discipline, restated).
    protected = set()
    if keep_sel:
        matched = select(root, keep_sel)
        fidelity["keep"] = {"selector": keep_sel,
                            "matched": bool(matched)}
        if matched:
            keep_node = matched[0]
            protected = _ancestors(keep_node) | {id(keep_node)}
            stack = [keep_node]
            while stack:
                cur = stack.pop()
                for c in cur.children:
                    if isinstance(c, _Node):
                        protected.add(id(c))
                        stack.append(c)
            for el in list(_iter_elements(root)):
                if id(el) not in protected \
                        and _is_attached(el, root):
                    _detach(el)
            fidelity["applied"] = True
    # 3. Fit pruning (crawl4ai's pruning-filter idea, clean
    #    re-implementation): block elements scored by text
    #    density and link density, deepest first so a pruned
    #    parent is never scored on already-pruned children.
    if fit.get("enabled"):
        blocks = [el for el in _iter_elements(root)
                  if el.tag in BLOCK_TAGS]
        blocks.sort(key=lambda el: -len(_ancestors(el)))
        for el in blocks:
            if not _is_attached(el, root):
                continue
            if id(el) in protected or el.tag in (
                    "html", "head", "body", "title"):
                continue
            if any(d.tag == "img" for d in _iter_elements(el)):
                continue  # media survives; it is not boilerplate
            text = _collapse(node_text(el))
            text_chars = len(text)
            link_chars = sum(
                len(_collapse(node_text(a)))
                for a in _iter_elements(el) if a.tag == "a")
            link_density = (link_chars / text_chars
                            if text_chars else 0.0)
            density = text_chars / max(len(serialise(el)), 1)
            rule = None
            if text_chars < fit["min_text_chars"]:
                rule = "fit:min-text"
            elif link_density > fit["max_link_density"]:
                rule = "fit:link-density"
            elif density < fit["min_text_density"]:
                rule = "fit:text-density"
            if rule:
                fidelity["pruned"].append({
                    "rule": rule,
                    "element": el.descriptor(),
                    "text_chars": text_chars,
                    "link_density": round(link_density, 3),
                    "text_density": round(density, 3),
                })
                fidelity["pruned_counts"][rule] = \
                    fidelity["pruned_counts"].get(rule, 0) + 1
                _detach(el)
                fidelity["applied"] = True
    return serialise(root), fidelity


# ----------------------------------------------------------------
# Schema-based item extraction (the feedless half)
# ----------------------------------------------------------------

_DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%B %d, %Y",
                 "%b %d, %Y", "%d %B %Y", "%m/%d/%Y", "%Y/%m/%d")


def _apply_transform(value, transform):
    if value is None or transform in (None, "none"):
        return value
    if transform == "strip":
        return value.strip()
    if transform == "collapse_ws":
        return _collapse(value)
    if transform == "iso_date":
        text = value.strip()
        m = re.search(r"\d{4}-\d{2}-\d{2}", text)
        if m:
            return m.group(0)
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).strftime(
                    "%Y-%m-%d")
            except ValueError:
                continue
        return value  # unparseable: the source's own words stand
    return value


def _field_value(item_node, field, base_url):
    sel = field.get("selector")
    attr = field.get("attr", "text")
    if sel is None or sel == ".":
        node = item_node
        value = node_text(node) if attr == "text" else (
            _inner_html(node) if attr == "html"
            else node.attr(attr))
    elif is_xpath(sel):
        if attr == "text":
            value = xpath_value(item_node, sel)
        elif attr == "html":
            nodes = xpath_select(item_node, sel)
            value = _inner_html(nodes[0]) if nodes else None
        else:
            value = xpath_value(item_node, sel.rstrip("/") +
                                "/@" + attr) \
                if not sel.rstrip().endswith("@" + attr) else \
                xpath_value(item_node, sel)
    else:
        nodes = css_select(item_node, sel)
        if not nodes:
            return None
        node = nodes[0]
        value = node_text(node) if attr == "text" else (
            _inner_html(node) if attr == "html"
            else node.attr(attr))
    if value is not None and attr in ("href", "src") and base_url:
        value = urljoin(base_url, value)
    return _apply_transform(value, field.get("transform", "none"))


def extract_items(html_text, profile, base_url=None):
    """Extract feed-shaped items from a page under the
    profile's `items` schema. Returns (items, record): items
    are dicts of field -> value; the record says how many item
    elements were found, how many were extracted, and every
    skipped item with the required field it lacked — a partial
    extraction is reported, never silently trimmed."""
    items_spec = profile.get("items")
    if not items_spec:
        raise ProfileError(
            "scrape profile %r declares no 'items' schema — "
            "it cannot extract items" % profile.get("name"))
    root = parse_html(html_text)
    nodes = select(root, items_spec["selector"])
    items, skipped = [], []
    for idx, node in enumerate(nodes):
        item = {}
        missing = None
        for fname, field in items_spec["fields"].items():
            value = _field_value(node, field, base_url)
            if value is not None and value != "":
                item[fname] = value
            elif field.get("required"):
                missing = fname
                break
        if missing is not None:
            skipped.append({"index": idx, "missing": missing})
        else:
            items.append(item)
    record = {
        "profile": profile.get("name"),
        "selector": items_spec["selector"],
        "found": len(nodes),
        "extracted": len(items),
        "skipped": skipped,
    }
    return items, record


# ----------------------------------------------------------------
# CLI
# ----------------------------------------------------------------

def _load_or_die(root):
    try:
        return load_profiles(root)
    except ProfileError as exc:
        print("wiki_scrape_profiles: %s" % exc, file=sys.stderr)
        raise SystemExit(1)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("list")
    p = sub.add_parser("match")
    p.add_argument("url")
    p.add_argument("--file", default=None,
                   help="a saved page to shape-match against")
    p = sub.add_parser("extract")
    p.add_argument("file")
    p.add_argument("--profile", required=True)
    p.add_argument("--base", default=None,
                   help="base URL for resolving item links")
    p = sub.add_parser("fit")
    p.add_argument("file")
    p.add_argument("--profile", required=True)
    args = ap.parse_args(argv)
    profiles = _load_or_die(args.root)
    try:
        if args.cmd == "check":
            path = args.root / PROFILES_FILE
            print("scrape profiles: %d profile(s) in %s "
                  "(+ the built-in 'generic' fallback)"
                  % (len(profiles),
                     path if path.is_file() else
                     "%s (absent — generic only)" % path))
            for profile in profiles:
                print("  %s — %s" % (profile["name"],
                                     profile.get("note") or ""))
        elif args.cmd == "list":
            for profile in profiles + [GENERIC_PROFILE]:
                print("%s\t%s" % (profile["name"],
                                  profile.get("note") or ""))
        elif args.cmd == "match":
            text = None
            if args.file:
                text = Path(args.file).read_text(
                    encoding="utf-8", errors="replace")
            profile, selection = select_profile(
                args.url, text, profiles)
            print(json.dumps(
                {"profile": profile["name"],
                 "selection": selection},
                indent=2, sort_keys=True))
        elif args.cmd == "extract":
            profile = get_profile(profiles, args.profile)
            if profile is None:
                raise ProfileError(
                    "unknown scrape profile %r" % args.profile)
            text = Path(args.file).read_text(
                encoding="utf-8", errors="replace")
            items, record = extract_items(
                text, profile, base_url=args.base)
            print(json.dumps({"record": record, "items": items},
                             indent=2, sort_keys=True))
        elif args.cmd == "fit":
            profile = get_profile(profiles, args.profile)
            if profile is None:
                raise ProfileError(
                    "unknown scrape profile %r" % args.profile)
            text = Path(args.file).read_text(
                encoding="utf-8", errors="replace")
            new_text, fidelity = fit_markdown(text, profile)
            print(json.dumps(fidelity, indent=2, sort_keys=True),
                  file=sys.stderr)
            sys.stdout.write(new_text)
    except ProfileError as exc:
        print("wiki_scrape_profiles: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
