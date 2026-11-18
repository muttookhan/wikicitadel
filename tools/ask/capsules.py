#!/usr/bin/env python3
"""Prompt Capsules for Lens Ask (Marathon R2 lane B1).

A Prompt Capsule is a named, reusable context bundle: a
markdown file in the ``capsules/`` directory at the tree root:

    ---
    name: marathon
    description: The marathon build programme's core pages.
    ---

    - queries/wiki-feature-survey-2026-10-19
    - queries/global-landscape-research-2026-10-20

The frontmatter carries ``name`` and ``description``; the body
lists page paths to pin (list items, ``[[wikilinks]]`` or bare
lines — each normalised to the page id under ``wiki/``, without
the ``.md`` suffix).

Ask packing: when a question NAMES a capsule — the capsule's
``name`` appearing in the question text as an exact,
whole-phrase match (case-insensitive; ``marathons`` does not
name the ``marathon`` capsule) — the capsule's pages are
materialised as candidate passages (:func:`capsule_passages`)
and packed FIRST: they carry ``"pinned": True``, and
``evidence_packing.pack_evidence`` considers pinned passages
before every unpinned one, in capsule order, under the same
token budget. The same severance/sensitivity rules apply
unchanged: severance filtering runs inside ``pack_evidence``
before ordering, so a capsule page that is severed (or whose
text carries a severed claim) is cut and recorded in the
result's ``severed`` list, never packed — a capsule is a
pinning convenience, never a severance bypass.

The flow for the pickup agent is::

    capsule, passages = pinned_candidates(question, wiki_dir)
    pack = pack_evidence(passages + candidates, severance=...)

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import re
from pathlib import Path

CAPSULES_RELATIVE_PATH = "capsules"


def repo_root() -> Path:
    """Repository root, derived from this file's location
    (tools/ask/capsules.py -> parents[2])."""
    return Path(__file__).resolve().parents[2]


def default_capsules_dir() -> Path:
    return repo_root() / CAPSULES_RELATIVE_PATH


def default_wiki_dir() -> Path:
    return repo_root() / "wiki"


def _page_key(page) -> str:
    """Normalise a pinned page reference to the page id under
    ``wiki/`` without the ``.md`` suffix (the same rule
    severance.py applies)."""
    p = str(page or "").strip().replace("\\", "/")
    if p.endswith(".md"):
        p = p[:-3]
    if p.startswith("wiki/"):
        p = p[len("wiki/"):]
    return p


def parse_capsule(text: str, source=None) -> dict:
    """Parse one capsule markdown file's text.

    Returns ``{"name", "description", "pages", "source"}``:
    ``pages`` is the pinned page ids in file order, de-duplicated
    (first occurrence wins). A file with no frontmatter ``name``
    falls back to its source file stem. Lines in the body that
    are headings or prose are ignored; list items, wikilinks and
    bare path-like lines (containing ``/`` or ending ``.md``)
    are pins.
    """
    lines = str(text).splitlines()
    frontmatter = {}
    body = lines
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                for raw in lines[1:index]:
                    if ":" in raw:
                        key, value = raw.split(":", 1)
                        frontmatter[key.strip().lower()] = (
                            value.strip().strip('"').strip("'")
                        )
                body = lines[index + 1:]
                break
    pages = []
    seen = set()
    for raw in body:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        is_list_item = line.startswith(("- ", "* ", "+ "))
        if is_list_item:
            line = line[2:].strip()
        match = re.search(r"\[\[([^\]]+)\]\]", line)
        first_token = line.split()[0] if line.split() else ""
        if match:
            candidate = match.group(1).split("|")[0]
        elif is_list_item or "/" in first_token \
                or first_token.endswith(".md"):
            # A list item is a pin even when it is a bare page
            # stem (``- overview``); a bare prose line is a pin
            # only when its FIRST token looks like a path.
            candidate = first_token
        else:
            continue
        page = _page_key(candidate)
        if page and page not in seen:
            seen.add(page)
            pages.append(page)
    name = frontmatter.get("name") or (
        Path(source).stem if source else ""
    )
    return {
        "name": name,
        "description": frontmatter.get("description", ""),
        "pages": pages,
        "source": str(source) if source else None,
    }


def load_capsule(path) -> dict:
    """Parse the capsule file at *path*."""
    path = Path(path)
    return parse_capsule(
        path.read_text(encoding="utf-8"), source=path
    )


def load_capsules(capsules_dir=None) -> list:
    """All capsules in *capsules_dir* (default: ``capsules/``
    at the tree root), in filename order. A missing directory
    gives ``[]`` — capsules are an optional bundle, never a
    requirement."""
    directory = (
        Path(capsules_dir) if capsules_dir is not None
        else default_capsules_dir()
    )
    if not directory.is_dir():
        return []
    return [
        load_capsule(path)
        for path in sorted(directory.glob("*.md"))
    ]


def find_capsule(question, capsules):
    """The capsule *question* names, or None.

    A question names a capsule when the capsule's ``name``
    appears in the question text as an exact whole phrase —
    case-insensitive, bounded by non-word characters — so
    naming is deliberate, never a substring accident. The
    first matching capsule (in the order given) wins.
    """
    text = str(question or "")
    if not text:
        return None
    for capsule in capsules or []:
        name = str(capsule.get("name") or "").strip()
        if not name:
            continue
        pattern = r"(?<!\w)%s(?!\w)" % re.escape(name)
        if re.search(pattern, text, re.IGNORECASE):
            return capsule
    return None


def capsule_passages(capsule: dict, wiki_dir=None) -> list:
    """Materialise a capsule's pinned pages as passages.

    Each pinned page that exists under *wiki_dir* (default:
    ``wiki/`` at the tree root) becomes one passage dict —
    ``{"page", "passage" (the page's full text), "pinned":
    True, "capsule": <name>}`` — in capsule order. A pinned
    page that does not exist is skipped (it cannot be
    evidence); severance is NOT applied here — it runs inside
    ``pack_evidence``, so a severed capsule page is cut at
    packing time, on the record, like any other passage.
    """
    wiki = (
        Path(wiki_dir) if wiki_dir is not None
        else default_wiki_dir()
    )
    passages = []
    for page in capsule.get("pages") or []:
        path = wiki / (_page_key(page) + ".md")
        if not path.is_file():
            continue
        passages.append({
            "page": _page_key(page),
            "passage": path.read_text(encoding="utf-8"),
            "pinned": True,
            "capsule": capsule.get("name"),
        })
    return passages


def pinned_candidates(question, wiki_dir=None, capsules_dir=None):
    """``(capsule, passages)`` for the capsule *question* names.

    Returns ``(None, [])`` when the question names no capsule in
    the capsules directory — the ordinary, capsule-free flow.
    """
    capsule = find_capsule(
        question, load_capsules(capsules_dir)
    )
    if capsule is None:
        return None, []
    return capsule, capsule_passages(capsule, wiki_dir)
