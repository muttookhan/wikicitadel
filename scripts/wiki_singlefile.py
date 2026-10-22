#!/usr/bin/env python3
"""wiki_singlefile.py — single-file HTML capture: one
self-contained HTML file per web clip (implementation wave
W4, 2026-10-22).

Pattern: SingleFile (the browser extension that saves a page
as one HTML file; MPL-2.0 — this is a CLEAN RE-IMPLEMENTATION
from the idea only, no code taken). Where the extension's job
is a page a human is looking at, this one's job is narrower
and stricter: it is a PRESERVATION TRANSFORM over bytes a
clip already holds, wired into scripts/wiki_clip.py behind
--single-file. It produces a DERIVED VIEW that opens
standalone forever, beside — never instead of — the verbatim
preserved source, the snapshot bundle and the Markdown draft.

FETCH DISCIPLINE IS ABSOLUTE: this module has no network
code at all. It inlines ONLY assets the caller hands it —
for a clip, the files the clip's own snapshot bundle holds
beside its verified core. A reference whose bytes the
capture does not hold is left exactly as a reference and
NAMED in the record (the `not_held` list): the transform
never fetches a subresource, never follows a URL the page
merely mentions, and cannot be pointed at a live page. It
is not a crawler.

SANITISATION POSTURE (the converter path's own): the page
first runs through the gateway sanitiser wiki_convert
already uses (hidden elements and comments dropped,
invisible codepoints stripped), then this transform strips
what a standalone artefact must not carry: <script>
elements, on* event-handler attributes, javascript: /
vbscript: / data:text/html URLs in link/action positions,
meta-refresh and <base> elements — every neutralisation
COUNTED in the record. The preserved original stays
byte-verbatim in the snapshot bundle; the single file is
labelled a derived view in its own header comment and in
the clip sidecar, and carries no timestamp, so the same
held bytes always produce byte-identical output.

SIZE HONESTY: two named caps — MAX_ASSET_BYTES per asset
and MAX_TOTAL_INLINE_BYTES of inlined payload per file.
An asset over the per-asset cap is referenced, not
inlined, with its size recorded (`capped_out`); when the
total cap is spent, later held assets are skipped and
recorded (`total_cap_skipped`); the file is still written
with whatever fit, and the record says exactly what was
left out. Nothing is ever silently truncated.

WHAT INLINES: stylesheets (<link rel=stylesheet> becomes a
<style> element), images (<img src>, srcset candidates,
icon links, poster attributes, CSS url() targets) and
fonts (CSS url() targets), when held and under the caps.
Media, frames, embeds and other kinds are never inlined:
held ones are recorded as held-but-not-inlined, unheld
ones as not-held references. URLs already inline (data:,
blob:, #fragments) pass through untouched and unrecorded.

Held assets arrive as {absolute_url: (bytes, content_type
or None)}; references are resolved against the page URL
(and CSS url() targets against the stylesheet's own URL)
before lookup. The record this module returns is the
inline accounting the clip sidecar carries.
"""
import base64
import hashlib
import html as _html
import mimetypes
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Named caps (size honesty): a single asset larger than
# this is referenced, not inlined; the summed inlined
# payload of one file never exceeds the total.
MAX_ASSET_BYTES = 512 * 1024
MAX_TOTAL_INLINE_BYTES = 4 * 1024 * 1024

HEADER_COMMENT = (
    "<!-- Single-file capture: a DERIVED VIEW built by "
    "wiki_singlefile.py from the bytes this capture already "
    "held. The preserved original is byte-verbatim in the "
    "snapshot bundle. Active content was stripped and "
    "counted in the clip sidecar; assets were inlined only "
    "from the same capture — nothing was fetched. -->")

_INLINABLE_KINDS = ("stylesheet", "image", "font")
_ASSET_ATTRS = {
    # tag -> (attribute, kind); <link> and srcset are special.
    "img": ("src", "image"),
    "input": ("src", "image"),
    "video": ("src", "media"),
    "audio": ("src", "media"),
    "source": ("src", "media"),
    "iframe": ("src", "document"),
    "embed": ("src", "other"),
    "object": ("data", "other"),
}
_DANGEROUS_SCHEMES = ("javascript:", "vbscript:", "data:text/html")
_URL_ATTRS = ("href", "src", "action", "formaction", "cite",
              "background", "poster", "data", "ping")
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.S)
_EXT_KIND = {
    ".css": "stylesheet",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".gif": "image", ".webp": "image", ".svg": "image",
    ".bmp": "image", ".ico": "image", ".avif": "image",
    ".woff": "font", ".woff2": "font", ".ttf": "font",
    ".otf": "font", ".eot": "font",
}


def _kind_of(url, content_type=None):
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "text/css":
        return "stylesheet"
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("font/") or ct == "application/font-woff":
        return "font"
    if ct.startswith(("audio/", "video/")):
        return "media"
    suffix = Path(urlparse(url).path).suffix.lower()
    return _EXT_KIND.get(suffix, "other")


def _mime_of(url, content_type):
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct:
        return ct
    return mimetypes.guess_type(urlparse(url).path)[0] \
        or "application/octet-stream"


def _data_uri(url, data, content_type):
    return "data:%s;base64,%s" % (
        _mime_of(url, content_type),
        base64.b64encode(data).decode("ascii"))


def _gateway_sanitise(text):
    """The converter path's own sanitiser (wiki_convert's
    gateway module), applied to the page source exactly as
    wiki_convert applies it to HTML before conversion.
    Returns (cleaned_text, findings_count, verdict); the
    counts are None when the gateway module is unavailable,
    which the record states rather than hides."""
    try:
        import wiki_convert as wc
        san = wc._SANITIZE
    except Exception:
        san = None
    if san is None:
        return text, None, None
    cleaned, scan = san.clean_text(text)
    findings = scan.get("findings") or []
    return cleaned, len(findings), scan.get("verdict")


class _SingleFileParser(HTMLParser):
    """Token-stream transform: everything passes through
    verbatim (via get_starttag_text) except the tags this
    module deliberately rewrites or drops, so the derived
    view keeps the page's own bytes wherever it honestly
    can."""

    def __init__(self, page_url, held, account):
        super().__init__(convert_charrefs=False)
        self.page_url = page_url
        self.held = held
        self.acct = account
        self.out = []
        self.dropping = None      # tag name being dropped
        self.in_style = False     # buffering a <style> body
        self.style_buf = []
        self.header_done = False

    # -- accounting ------------------------------------------------
    def _account_ref(self, ref, kind_hint, base_url):
        """Resolve one reference and decide its fate.
        Returns (action, payload): ("inline", data_uri) /
        ("inline-css", css_text) / ("leave", None). Every
        non-inline fate is recorded here, once."""
        if ref is None:
            return "leave", None
        ref = ref.strip()
        if not ref or ref.startswith("#"):
            return "leave", None
        scheme = urlparse(ref).scheme.lower()
        if scheme in ("data", "blob"):
            return "leave", None       # already inline
        url = urljoin(base_url, ref)
        entry = self.held.get(url)
        kind = kind_hint or _kind_of(url,
                                     entry[1] if entry else None)
        if entry is None:
            self.acct.note_not_held(ref, url, kind)
            return "leave", None
        data, content_type = entry
        if kind not in _INLINABLE_KINDS:
            self.acct.note_held_not_inlined(
                ref, url, kind,
                "kind %r is never inlined" % kind)
            return "leave", None
        if len(data) > self.acct.max_asset:
            self.acct.note_capped(ref, url, kind, len(data))
            return "leave", None
        if self.acct.inline_total + len(data) \
                > self.acct.max_total:
            self.acct.note_total_skipped(ref, url, kind,
                                         len(data))
            return "leave", None
        self.acct.note_inlined(ref, url, kind, len(data),
                               _mime_of(url, content_type))
        if kind == "stylesheet":
            css = data.decode("utf-8", errors="replace")
            return "inline-css", self._process_css(css, url)
        return "inline", _data_uri(url, data, content_type)

    def _process_css(self, css, css_url):
        """Rewrite url() targets inside a stylesheet (or an
        inline <style> body) against held assets, resolved
        against the stylesheet's own URL."""
        def repl(m):
            ref = m.group(2)
            action, payload = self._account_ref(
                ref, None, css_url)
            if action == "inline":
                return "url(%s)" % payload
            return m.group(0)
        out = _CSS_URL_RE.sub(repl, css)
        # An inlined stylesheet must not be able to close
        # its own <style> element early.
        return re.sub(r"</style", r"<\\/style", out,
                      flags=re.I)

    # -- serialisation ---------------------------------------------
    def _emit_tag(self, tag, attrs, self_closing=False):
        parts = ["<", tag]
        for name, value in attrs:
            if value is None:
                parts.append(" %s" % name)
            else:
                parts.append(' %s="%s"' % (
                    name, _html.escape(value, quote=True)))
        parts.append("/>" if self_closing else ">")
        self.out.append("".join(parts))

    def _maybe_header(self):
        if not self.header_done:
            self.header_done = True
            self.out.append(HEADER_COMMENT + "\n")

    # -- HTMLParser hooks ------------------------------------------
    def handle_decl(self, decl):
        self.out.append("<!%s>" % decl)
        self._maybe_header()

    def handle_pi(self, data):
        self.out.append("<?%s>" % data)

    def handle_comment(self, data):
        self.out.append("<!--%s-->" % data)

    def handle_entityref(self, name):
        self.out.append("&%s;" % name)

    def handle_charref(self, name):
        self.out.append("&#%s;" % name)

    def handle_data(self, data):
        if self.dropping:
            return
        if self.in_style:
            self.style_buf.append(data)
            return
        self.out.append(data)

    def finish(self):
        """Flush a <style> body left open at end of input."""
        if self.in_style:
            self.out.append(self._process_css(
                "".join(self.style_buf), self.page_url))
            self.in_style = False
            self.style_buf = []

    def handle_endtag(self, tag):
        if self.dropping:
            if tag == self.dropping:
                self.dropping = None
            return
        if tag == "style" and self.in_style:
            self.out.append(self._process_css(
                "".join(self.style_buf), self.page_url))
            self.in_style = False
            self.style_buf = []
        self.out.append("</%s>" % tag)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, attrs, self_closing=True)

    def handle_starttag(self, tag, attrs):
        self._start(tag, attrs, self_closing=False)

    def _start(self, tag, attrs, self_closing):
        if self.dropping:
            return
        self._maybe_header()
        acct = self.acct
        raw = dict()          # first value per attribute name
        for name, value in attrs:
            raw.setdefault(name, value)
        if tag == "script":
            acct.san["scripts_removed"] += 1
            if not self_closing:
                self.dropping = "script"
            return
        if tag == "base":
            acct.san["base_elements_removed"] += 1
            return
        if tag == "meta" and (raw.get("http-equiv") or "") \
                .strip().lower() == "refresh":
            acct.san["meta_refresh_removed"] += 1
            return
        # Attribute-level sanitisation + accounting.
        new_attrs = []
        changed = False
        style_text = None
        for name, value in attrs:
            if name.startswith("on"):
                acct.san["event_handler_attributes_removed"] += 1
                changed = True
                continue
            if value is not None and name in _URL_ATTRS:
                stripped = value.strip().lower()
                if stripped.startswith(_DANGEROUS_SCHEMES):
                    acct.san["dangerous_urls_neutralised"] += 1
                    changed = True
                    if name in ("href", "action", "formaction"):
                        new_attrs.append(
                            (name, "#neutralised-by-capture"))
                    # a dangerous src/data is dropped outright
                    continue
            if name == "style" and value:
                style_text = value
            new_attrs.append((name, value))
        attrs = new_attrs
        raw = {}
        for name, value in attrs:
            raw.setdefault(name, value)
        # Charset: the derived view is UTF-8 (see build()).
        if tag == "meta" and raw.get("charset"):
            if raw["charset"].strip().lower() != "utf-8":
                acct.charset_declared = raw["charset"]
                attrs = [(n, "utf-8" if n == "charset" else v)
                         for n, v in attrs]
                changed = True
        # Asset handling per tag.
        if tag == "link":
            rel = (raw.get("rel") or "").lower().split()
            href = raw.get("href")
            if href and "stylesheet" in rel:
                action, payload = self._account_ref(
                    href, "stylesheet", self.page_url)
                if action == "inline-css":
                    self.out.append("<style>")
                    self.out.append(payload)
                    self.out.append("</style>")
                    return
                if action == "inline":
                    # A stylesheet whose bytes decoded as a
                    # data URI (non-UTF8 payload): keep the
                    # link shape, data-URI the href.
                    attrs = [(n, payload if n == "href" else v)
                             for n, v in attrs]
                    changed = True
            elif href and ("icon" in rel
                           or "apple-touch-icon" in rel):
                action, payload = self._account_ref(
                    href, "image", self.page_url)
                if action == "inline":
                    attrs = [(n, payload if n == "href" else v)
                             for n, v in attrs]
                    changed = True
            elif href:
                # Other link relations are references, not
                # rendering assets; record held/unheld state
                # only for the asset-ish preload kind.
                if "preload" in rel:
                    self._account_ref(href, None, self.page_url)
                    return self._emit_tag(tag, attrs,
                                          self_closing)
        elif tag in _ASSET_ATTRS:
            attr, kind = _ASSET_ATTRS[tag]
            if tag == "source":
                # <source> takes its kind from its parent;
                # media either way, never inlined — recorded
                # for accounting only.
                kind = "media"
            ref = raw.get(attr)
            if ref:
                action, payload = self._account_ref(
                    ref, kind, self.page_url)
                if action == "inline":
                    attrs = [(n, payload if n == attr else v)
                             for n, v in attrs]
                    changed = True
            if tag == "img" and raw.get("srcset"):
                new_srcset, did = self._rewrite_srcset(
                    raw["srcset"])
                if did:
                    attrs = [(n, new_srcset if n == "srcset"
                              else v) for n, v in attrs]
                    changed = True
            if tag == "video" and raw.get("poster"):
                action, payload = self._account_ref(
                    raw["poster"], "image", self.page_url)
                if action == "inline":
                    attrs = [(n, payload if n == "poster"
                              else v) for n, v in attrs]
                    changed = True
        if style_text is not None:
            new_style = self._process_css(style_text,
                                          self.page_url)
            if new_style != style_text:
                attrs = [(n, new_style if n == "style" else v)
                         for n, v in attrs]
                changed = True
        if changed:
            self._emit_tag(tag, attrs, self_closing)
        else:
            self.out.append(self.get_starttag_text())
        if tag == "style" and not self_closing:
            # The body is buffered and CSS-processed at the
            # end tag (url() targets inline from held assets,
            # resolved against the page URL).
            self.in_style = True
            self.style_buf = []

    def _rewrite_srcset(self, srcset):
        changed = False
        out = []
        for candidate in srcset.split(","):
            candidate = candidate.strip()
            if not candidate:
                continue
            parts = candidate.split()
            url = parts[0]
            if url.startswith(("data:", "blob:")):
                out.append(candidate)
                continue
            action, payload = self._account_ref(
                url, "image", self.page_url)
            if action == "inline":
                parts[0] = payload
                changed = True
            out.append(" ".join(parts))
        return ", ".join(out), changed


class _Account:
    """The inline accounting: every fate, named."""

    def __init__(self, max_asset, max_total):
        self.max_asset = max_asset
        self.max_total = max_total
        self.inline_total = 0
        self.inlined = []
        self.capped_out = []
        self.total_cap_skipped = []
        self.not_held = {}
        self.held_not_inlined = []
        self.san = {
            "scripts_removed": 0,
            "event_handler_attributes_removed": 0,
            "dangerous_urls_neutralised": 0,
            "meta_refresh_removed": 0,
            "base_elements_removed": 0,
        }
        self.charset_declared = None

    def note_inlined(self, ref, url, kind, size, mime):
        self.inline_total += size
        self.inlined.append({"ref": ref, "url": url,
                             "kind": kind, "bytes": size,
                             "mime": mime})

    def note_capped(self, ref, url, kind, size):
        self.capped_out.append({"ref": ref, "url": url,
                                "kind": kind, "bytes": size,
                                "cap": self.max_asset})

    def note_total_skipped(self, ref, url, kind, size):
        self.total_cap_skipped.append(
            {"ref": ref, "url": url, "kind": kind,
             "bytes": size})

    def note_not_held(self, ref, url, kind):
        row = self.not_held.get(url)
        if row is None:
            self.not_held[url] = {"ref": ref, "url": url,
                                  "kind": kind,
                                  "occurrences": 1}
        else:
            row["occurrences"] += 1

    def note_held_not_inlined(self, ref, url, kind, reason):
        self.held_not_inlined.append(
            {"ref": ref, "url": url, "kind": kind,
             "reason": reason})


def build_single_file(html_bytes, page_url, held_assets,
                      max_asset_bytes=MAX_ASSET_BYTES,
                      max_total_inline_bytes=MAX_TOTAL_INLINE_BYTES,
                      sanitise=True):
    """Build the single-file derived view. `held_assets`:
    {absolute_url: (bytes, content_type or None)} — the
    ONLY assets that can be inlined; this function fetches
    nothing. Returns (out_bytes, record). Deterministic:
    the same held bytes give byte-identical output (no
    timestamps anywhere in the artefact; the record's
    hashes are over content, not time)."""
    text = html_bytes.decode("utf-8", errors="replace")
    findings = verdict = None
    if sanitise:
        text, findings, verdict = _gateway_sanitise(text)
    acct = _Account(max_asset_bytes, max_total_inline_bytes)
    parser = _SingleFileParser(page_url, dict(held_assets),
                               acct)
    parser.feed(text)
    parser.close()
    parser.finish()
    out = "".join(parser.out).encode("utf-8")
    record = {
        "tool": "wiki_singlefile.py",
        "format": "single-file-html",
        "derived_view": True,
        "page_url": page_url,
        "caps": {"per_asset_bytes": max_asset_bytes,
                 "total_inline_bytes": max_total_inline_bytes},
        "inlined": acct.inlined,
        "inlined_bytes": acct.inline_total,
        "capped_out": acct.capped_out,
        "total_cap_skipped": acct.total_cap_skipped,
        "not_held": [acct.not_held[u]
                     for u in sorted(acct.not_held)],
        "held_not_inlined": acct.held_not_inlined,
        "sanitisation": dict(
            acct.san,
            gateway_findings=findings,
            gateway_verdict=verdict),
        "charset": {"declared": acct.charset_declared,
                    "output": "utf-8"},
        "sha256": hashlib.sha256(out).hexdigest(),
        "size_bytes": len(out),
    }
    return out, record
