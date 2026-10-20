"""Core logic for the local wiki editor.

Stdlib only. All filesystem logic lives here, factored away from the
HTTP layer so it can be unit-tested directly without a live server.

Safety model in brief (see README.md for the full statement):

* Every caller-supplied path is resolved against the wiki root and
  must stay inside it after resolution -- ``..``, absolute paths and
  symlinks escaping the root are all refused.
* Only ``.md`` files are readable, writable or creatable.
* A save requires the sha256 token of the content as loaded; if the
  file on disk has changed since, the save is refused.
* A save preserves frontmatter byte-for-byte except for an
  ``updated:`` date field, when that field already exists.
* Before a save overwrites anything, the previous bytes are copied
  to the caller-supplied backup directory, mirroring the page's
  path relative to the wiki root.
* Creating a page never overwrites an existing page.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import date
from pathlib import Path

__all__ = [
    "ALLOWED_TYPES",
    "AlreadyExistsError",
    "ConcurrencyError",
    "EditorError",
    "PageNotFoundError",
    "PathEscapeError",
    "build_skeleton",
    "create_page",
    "list_pages",
    "parse_metadata",
    "read_page",
    "resolve_safe_path",
    "save_page",
    "sha256_token",
    "split_frontmatter",
    "update_updated_field",
]

# Page types from AGENTS.md: ``type`` is one of these.
ALLOWED_TYPES = ("source", "entity", "concept", "synthesis", "query")


class EditorError(Exception):
    """Base class for editor errors."""


class PathEscapeError(EditorError, ValueError):
    """A path would escape the wiki root, or is not a .md path."""


class ConcurrencyError(EditorError):
    """The file changed on disk since it was loaded."""


class AlreadyExistsError(EditorError):
    """A create was attempted over an existing page."""


class PageNotFoundError(EditorError, FileNotFoundError):
    """The requested page does not exist."""


def sha256_token(data: bytes) -> str:
    """Optimistic-concurrency token: sha256 hex of the exact bytes."""
    return hashlib.sha256(data).hexdigest()


def split_frontmatter(content: str) -> tuple[str | None, str]:
    """Split *content* into (frontmatter_raw, body).

    ``frontmatter_raw`` includes both ``---`` delimiter lines and
    their line endings, exactly as they appear, or is ``None`` when
    the content carries no frontmatter. ``body`` is everything after
    the closing delimiter line, exactly as it appears.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, content
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "".join(lines[: idx + 1]), "".join(lines[idx + 1 :])
    # Opening delimiter with no closing one: not frontmatter.
    return None, content


_FIELD_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*$")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_metadata(content: str) -> dict[str, str]:
    """Return first-occurrence frontmatter fields as plain strings.

    This is deliberately a small line parser, not a YAML parser:
    the editor only needs ``title`` / ``stage`` / ``type`` for the
    listing, and save preserves the raw frontmatter untouched, so
    no full YAML round-trip is ever required (or safe).
    """
    frontmatter_raw, _body = split_frontmatter(content)
    if frontmatter_raw is None:
        return {}
    fields: dict[str, str] = {}
    for line in frontmatter_raw.splitlines()[1:-1]:
        match = _FIELD_RE.match(line)
        if match and match.group(1) not in fields:
            fields[match.group(1)] = _unquote(match.group(2))
    return fields


def update_updated_field(frontmatter_raw: str, today: str) -> str:
    """Return *frontmatter_raw* with only its ``updated:`` line changed.

    Every other byte is preserved. If there is no ``updated:`` line,
    the frontmatter is returned unchanged -- a field is never added.
    """
    lines = frontmatter_raw.splitlines(keepends=True)
    for idx in range(1, len(lines) - 1):
        if re.match(r"^updated\s*:", lines[idx]):
            ending = ""
            if lines[idx].endswith("\r\n"):
                ending = "\r\n"
            elif lines[idx].endswith("\n"):
                ending = "\n"
            lines[idx] = f"updated: {today}{ending}"
            break
    return "".join(lines)


def resolve_safe_path(wiki_root: str | Path, rel_path: str | Path) -> Path:
    """Resolve *rel_path* inside *wiki_root* or raise PathEscapeError.

    Refuses absolute paths, non-``.md`` paths, and any path whose
    resolved location lies outside the resolved wiki root (which
    covers both ``..`` traversal and symlinks escaping the root).
    The target need not exist.
    """
    rel_str = str(rel_path)
    if not rel_str or "\x00" in rel_str:
        raise PathEscapeError("empty page path")
    rel = Path(rel_str)
    if rel.is_absolute():
        raise PathEscapeError(f"absolute paths are not allowed: {rel_str!r}")
    if rel.suffix != ".md":
        raise PathEscapeError(f"only .md files are allowed: {rel_str!r}")
    root = Path(wiki_root).resolve()
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise PathEscapeError(
            f"path escapes the wiki root: {rel_str!r}"
        ) from None
    return candidate


def _relative_posix(root: Path, candidate: Path) -> str:
    return candidate.relative_to(root).as_posix()


def list_pages(wiki_root: str | Path) -> list[dict[str, str]]:
    """List every ``wiki/**/*.md`` page with title/stage/type.

    Pages are sorted by path relative to the wiki root. Symlinks
    whose resolved target escapes the root are skipped, never served.
    A page with no frontmatter title falls back to its file stem.
    """
    root = Path(wiki_root).resolve()
    pages: list[dict[str, str]] = []
    if not root.is_dir():
        return pages
    for path in sorted(root.rglob("*.md")):
        try:
            resolved = path.resolve()
            rel = resolved.relative_to(root)
        except (OSError, ValueError):
            continue
        if not resolved.is_file():
            continue
        try:
            content = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        metadata = parse_metadata(content)
        pages.append(
            {
                "path": rel.as_posix(),
                "title": metadata.get("title") or resolved.stem,
                "stage": metadata.get("stage", ""),
                "type": metadata.get("type", ""),
            }
        )
    pages.sort(key=lambda page: page["path"])
    return pages


def read_page(wiki_root: str | Path, rel_path: str | Path) -> dict[str, str]:
    """Read one page: content, frontmatter, body, and its token."""
    root = Path(wiki_root).resolve()
    candidate = resolve_safe_path(root, rel_path)
    if not candidate.is_file():
        raise PageNotFoundError(f"no such page: {rel_path!r}")
    data = candidate.read_bytes()
    content = data.decode("utf-8")
    frontmatter_raw, body = split_frontmatter(content)
    metadata = parse_metadata(content)
    return {
        "path": _relative_posix(root, candidate),
        "content": content,
        "frontmatter": frontmatter_raw or "",
        "body": body,
        "token": sha256_token(data),
        "title": metadata.get("title") or candidate.stem,
        "stage": metadata.get("stage", ""),
        "type": metadata.get("type", ""),
    }


def save_page(
    wiki_root: str | Path,
    backup_dir: str | Path | None,
    rel_path: str | Path,
    new_body: str,
    expected_token: str,
    *,
    today: str | None = None,
) -> dict[str, str | None]:
    """Replace a page's body, preserving its frontmatter.

    The frontmatter is kept byte-for-byte except an existing
    ``updated:`` field, which is set to *today* (default: today,
    local date, ISO format). The previous bytes are first copied
    under *backup_dir* (mirroring the page's relative path) when a
    backup dir is supplied. Raises ConcurrencyError if the file's
    current sha256 differs from *expected_token*.
    """
    if today is None:
        today = date.today().isoformat()
    root = Path(wiki_root).resolve()
    candidate = resolve_safe_path(root, rel_path)
    if not candidate.is_file():
        raise PageNotFoundError(f"no such page: {rel_path!r}")
    current_bytes = candidate.read_bytes()
    if sha256_token(current_bytes) != expected_token:
        raise ConcurrencyError(
            "the page changed on disk since it was loaded; "
            "reload it and re-apply the edit"
        )
    current_text = current_bytes.decode("utf-8")
    frontmatter_raw, _old_body = split_frontmatter(current_text)
    if frontmatter_raw is not None:
        new_frontmatter = update_updated_field(frontmatter_raw, today)
        if not new_frontmatter.endswith("\n") and new_body:
            new_frontmatter += "\n"
    else:
        new_frontmatter = ""
    new_content = new_frontmatter + new_body

    backup_path: Path | None = None
    if backup_dir is not None:
        backup_root = Path(backup_dir).resolve()
        backup_path = backup_root / candidate.relative_to(root)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(current_bytes)

    # Write via a temp file in the same directory, then replace, so
    # a crash mid-write cannot leave a truncated page.
    fd, tmp_name = tempfile.mkstemp(
        dir=str(candidate.parent), prefix=".editor-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(new_content.encode("utf-8"))
        os.replace(tmp_name, candidate)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return {
        "path": _relative_posix(root, candidate),
        "token": sha256_token(new_content.encode("utf-8")),
        "backup_path": str(backup_path) if backup_path is not None else None,
        "content": new_content,
    }


def _flow_list(values: list[str] | None) -> str:
    if not values:
        return "[]"
    rendered = ", ".join('"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"' for v in values)
    return f"[{rendered}]"


def build_skeleton(
    title: str,
    page_type: str = "concept",
    *,
    today: str | None = None,
    tags: list[str] | None = None,
    sources: list[str] | None = None,
) -> str:
    """Build the required frontmatter skeleton from AGENTS.md.

    Required fields: ``title``, ``type``, ``created``, ``updated``,
    ``sources``, ``tags`` -- followed by an ``# <title>`` heading.
    """
    if today is None:
        today = date.today().isoformat()
    if page_type not in ALLOWED_TYPES:
        raise ValueError(
            f"type must be one of {', '.join(ALLOWED_TYPES)}: {page_type!r}"
        )
    if not title or not title.strip():
        raise ValueError("a page title is required")
    title = title.strip()
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    return (
        "---\n"
        f'title: "{escaped}"\n'
        f"type: {page_type}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"sources: {_flow_list(sources)}\n"
        f"tags: {_flow_list(tags)}\n"
        "---\n"
        "\n"
        f"# {title}\n"
        "\n"
    )


def create_page(
    wiki_root: str | Path,
    rel_path: str | Path,
    title: str,
    page_type: str = "concept",
    *,
    today: str | None = None,
    tags: list[str] | None = None,
    sources: list[str] | None = None,
) -> dict[str, str]:
    """Create a new page under the wiki root; never overwrite.

    The page is written with the AGENTS.md frontmatter skeleton.
    Raises AlreadyExistsError if anything already sits at the path.
    """
    root = Path(wiki_root).resolve()
    candidate = resolve_safe_path(root, rel_path)
    if os.path.lexists(candidate):
        raise AlreadyExistsError(f"page already exists: {rel_path!r}")
    content = build_skeleton(
        title, page_type, today=today, tags=tags, sources=sources
    )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    # Re-check after creating parents: a symlinked parent created or
    # swapped in the meantime must not let the write escape.
    resolved_again = candidate.resolve()
    try:
        resolved_again.relative_to(root)
    except ValueError:
        raise PathEscapeError(
            f"path escapes the wiki root: {rel_path!r}"
        ) from None
    try:
        with resolved_again.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError:
        raise AlreadyExistsError(f"page already exists: {rel_path!r}") from None
    return {
        "path": _relative_posix(root, resolved_again),
        "content": content,
        "token": sha256_token(content.encode("utf-8")),
    }
