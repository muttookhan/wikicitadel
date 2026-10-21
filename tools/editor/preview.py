"""Safe server-side Markdown preview for the local wiki editor.

Stdlib only. The renderer is deliberately small and its contract is
security-first:

* The input is HTML-escaped BEFORE any Markdown rule runs, and no
  rule ever un-escapes it. Raw HTML in a page therefore renders as
  inert visible text -- there is NO raw-HTML pass-through, ever.
  ``<script>alert(1)</script>`` in a page previews as the literal
  characters ``&lt;script&gt;...``, never as an element.
* Link targets are scheme-checked: only ``http:``, ``https:``,
  ``mailto:``, fragment (``#...``) and relative targets become
  ``href``s. Anything else (``javascript:``, ``data:``, ...) renders
  as plain text with no link.

Supported subset (anything else renders as plain paragraph text):

* ATX headings ``#`` .. ``######``
* paragraphs (blank-line separated)
* unordered lists (``-`` / ``*`` / ``+``) and ordered lists (``1.``)
* fenced code blocks (triple backtick; contents escaped, no inline
  formatting inside)
* inline code (single backtick), bold (``**x**``), italic
  (``*x*`` / ``_x_``)
* Markdown links ``[text](target)`` under the scheme rule above
* ``[[wikilinks]]`` -- rendered as a ``wikilink`` span naming the
  target (targets stay page paths; the preview does not resolve
  them)
* pipe tables: a header row, a ``---`` separator row, then body rows
* blockquotes (``>``) and horizontal rules (``---`` / ``***``)

Not supported (by design): raw HTML, images, nested lists, setext
headings, reference links, footnotes, task lists. Unsupported
constructs degrade to readable plain text, never to live markup.
"""

from __future__ import annotations

import html
import re

__all__ = ["render_markdown"]

_ALLOWED_SCHEMES = ("http:", "https:", "mailto:")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_STAR_RE = re.compile(r"\*([^*]+)\*")
_ITALIC_UNDER_RE = re.compile(r"(?<![\w])_([^_]+)_(?![\w])")
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


def _safe_href(target: str) -> str | None:
    """Return *target* if it may be an href, else None.

    *target* arrives already HTML-escaped, so quotes in it are
    ``&quot;`` and cannot break out of the attribute.
    """
    lowered = target.lower()
    if lowered.startswith(_ALLOWED_SCHEMES):
        return target
    if target.startswith(("#", "/", "./", "../")):
        return target
    # A bare relative page path (no scheme, no colon) is allowed.
    if ":" not in target:
        return target
    return None


def _render_inline(escaped: str) -> str:
    """Apply inline rules to text that is ALREADY HTML-escaped."""
    stash: list[str] = []

    def keep(fragment: str) -> str:
        stash.append(fragment)
        return f"\x00{len(stash) - 1}\x00"

    # Code spans first: their contents get no further formatting.
    escaped = _CODE_SPAN_RE.sub(
        lambda m: keep(f"<code>{m.group(1)}</code>"), escaped
    )
    # Wikilinks before ordinary links (both use brackets).
    escaped = _WIKILINK_RE.sub(
        lambda m: keep(
            '<span class="wikilink" data-target="'
            + m.group(1).strip()
            + '">'
            + (m.group(2) or m.group(1)).strip()
            + "</span>"
        ),
        escaped,
    )

    def _link(match: re.Match[str]) -> str:
        href = _safe_href(match.group(2))
        if href is None:
            return match.group(1)  # neutralised: text only, no link
        return keep(f'<a href="{href}">{match.group(1)}</a>')

    escaped = _LINK_RE.sub(_link, escaped)
    escaped = _BOLD_RE.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC_STAR_RE.sub(r"<em>\1</em>", escaped)
    escaped = _ITALIC_UNDER_RE.sub(r"<em>\1</em>", escaped)
    # Restore stashed fragments (code spans, wikilinks, links).
    return _PLACEHOLDER_RE.sub(lambda m: stash[int(m.group(1))], escaped)


def _split_row(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [cell.strip() for cell in row.split("|")]


def _is_table_start(lines: list[str], idx: int) -> bool:
    if idx + 1 >= len(lines):
        return False
    header, sep = lines[idx], lines[idx + 1]
    if "|" not in header:
        return False
    return bool(_TABLE_SEP_RE.match(sep)) and "-" in sep


def render_markdown(markdown_text: str) -> str:
    """Render the documented Markdown subset to a safe HTML fragment.

    The whole input is escaped first; every tag in the output is one
    this function generated itself.
    """
    escaped = html.escape(markdown_text, quote=True)
    lines = escaped.split("\n")
    out: list[str] = []
    idx = 0
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            out.append("<p>" + _render_inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()

        # Fenced code block.
        if stripped.startswith("```"):
            flush_paragraph()
            idx += 1
            code_lines: list[str] = []
            while idx < len(lines) and not lines[idx].strip().startswith("```"):
                code_lines.append(lines[idx])
                idx += 1
            idx += 1  # closing fence (or end of input)
            out.append(
                "<pre><code>" + "\n".join(code_lines) + "</code></pre>"
            )
            continue

        if not stripped:
            flush_paragraph()
            idx += 1
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            out.append(
                f"<h{level}>" + _render_inline(heading.group(2)) + f"</h{level}>"
            )
            idx += 1
            continue

        if _HR_RE.match(line):
            flush_paragraph()
            out.append("<hr>")
            idx += 1
            continue

        if stripped.startswith("&gt;"):
            flush_paragraph()
            quote_lines: list[str] = []
            while idx < len(lines) and lines[idx].strip().startswith("&gt;"):
                quote_lines.append(
                    lines[idx].strip()[len("&gt;"):].strip()
                )
                idx += 1
            out.append(
                "<blockquote><p>"
                + _render_inline(" ".join(quote_lines))
                + "</p></blockquote>"
            )
            continue

        if _is_table_start(lines, idx):
            flush_paragraph()
            header = _split_row(lines[idx])
            idx += 2  # header + separator
            rows: list[list[str]] = []
            while idx < len(lines) and lines[idx].strip() and "|" in lines[idx]:
                rows.append(_split_row(lines[idx]))
                idx += 1
            head_html = "".join(
                f"<th>{_render_inline(cell)}</th>" for cell in header
            )
            body_html = "".join(
                "<tr>"
                + "".join(f"<td>{_render_inline(cell)}</td>" for cell in row)
                + "</tr>"
                for row in rows
            )
            out.append(
                "<table><thead><tr>"
                + head_html
                + "</tr></thead><tbody>"
                + body_html
                + "</tbody></table>"
            )
            continue

        if _UL_RE.match(line) or _OL_RE.match(line):
            flush_paragraph()
            ordered = bool(_OL_RE.match(line)) and not _UL_RE.match(line)
            item_re = _OL_RE if ordered else _UL_RE
            items: list[str] = []
            while idx < len(lines) and item_re.match(lines[idx]):
                items.append(item_re.match(lines[idx]).group(1))  # type: ignore[union-attr]
                idx += 1
            tag = "ol" if ordered else "ul"
            out.append(
                f"<{tag}>"
                + "".join(f"<li>{_render_inline(item)}</li>" for item in items)
                + f"</{tag}>"
            )
            continue

        paragraph.append(stripped)
        idx += 1

    flush_paragraph()
    return "\n".join(out) + ("\n" if out else "")
