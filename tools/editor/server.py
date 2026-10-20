"""HTTP layer for the local wiki editor: stdlib ``http.server`` only.

Binds to 127.0.0.1 only. One self-contained HTML form page per
route, no external assets, no JavaScript at all. All real work is
delegated to :mod:`tools.editor.core`, so the logic is testable
without a live server.

Run::

    python3 -m tools.editor.server --wiki-root wiki \
        --backup-dir /path/to/backups [--port 8765]
"""

from __future__ import annotations

import argparse
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    from . import core
except ImportError:  # run as a plain script: python3 server.py
    import core  # type: ignore[no-redef]

_PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: sans-serif; margin: 2em; max-width: 60em; }}
textarea {{ width: 100%; }}
table {{ border-collapse: collapse; }}
td, th {{ padding: 0.25em 0.75em; text-align: left; }}
.error {{ color: #a00; }}
</style>
</head>
<body>
"""


def render_index(pages: list[dict[str, str]]) -> str:
    rows = "".join(
        "<tr><td><a href=\"/edit?path={path}\">{path}</a></td>"
        "<td>{title}</td><td>{stage}</td><td>{ptype}</td></tr>\n".format(
            path=html.escape(page["path"], quote=True),
            title=html.escape(page["title"]),
            stage=html.escape(page["stage"]),
            ptype=html.escape(page["type"]),
        )
        for page in pages
    )
    return (
        _PAGE_HEAD.format(title="Wiki pages")
        + "<h1>Wiki pages</h1>\n"
        + '<p><a href="/new">Create a new page</a></p>\n'
        + "<table><tr><th>Path</th><th>Title</th><th>Stage</th>"
        + "<th>Type</th></tr>\n"
        + rows
        + "</table>\n</body>\n</html>\n"
    )


def render_edit(page: dict[str, str]) -> str:
    return (
        _PAGE_HEAD.format(title="Edit " + html.escape(page["title"]))
        + f"<h1>Edit {html.escape(page['path'])}</h1>\n"
        + '<form method="post" action="/save">\n'
        + f'<input type="hidden" name="path" value="{html.escape(page["path"], quote=True)}">\n'
        + f'<input type="hidden" name="token" value="{html.escape(page["token"], quote=True)}">\n'
        + "<p>Frontmatter is preserved on save (only an existing "
        + "<code>updated:</code> date changes); edit the body:</p>\n"
        + f'<textarea name="body" rows="30">{html.escape(page["body"])}</textarea>\n'
        + '<p><input type="submit" value="Save"></p>\n'
        + "</form>\n"
        + '<p><a href="/">Back to the list</a></p>\n'
        + "</body>\n</html>\n"
    )


def render_new() -> str:
    options = "".join(
        f'<option value="{t}">{t}</option>\n' for t in core.ALLOWED_TYPES
    )
    return (
        _PAGE_HEAD.format(title="Create a page")
        + "<h1>Create a new page</h1>\n"
        + '<form method="post" action="/create">\n'
        + '<p>Path under wiki/ (for example concepts/my-page.md): '
        + '<input type="text" name="path" size="50"></p>\n'
        + '<p>Title: <input type="text" name="title" size="50"></p>\n'
        + f'<p>Type: <select name="page_type">{options}</select></p>\n'
        + '<p><input type="submit" value="Create"></p>\n'
        + "</form>\n"
        + '<p><a href="/">Back to the list</a></p>\n'
        + "</body>\n</html>\n"
    )


def render_message(title: str, message: str) -> str:
    return (
        _PAGE_HEAD.format(title=html.escape(title))
        + f"<h1>{html.escape(title)}</h1>\n"
        + f"<p>{html.escape(message)}</p>\n"
        + '<p><a href="/">Back to the list</a></p>\n'
        + "</body>\n</html>\n"
    )


def render_error(message: str) -> str:
    return (
        _PAGE_HEAD.format(title="Error")
        + "<h1>Error</h1>\n"
        + f'<p class="error">{html.escape(message)}</p>\n'
        + '<p><a href="/">Back to the list</a></p>\n'
        + "</body>\n</html>\n"
    )


class EditorHandler(BaseHTTPRequestHandler):
    """Request handler; wiki root and backup dir live on the server."""

    server: "EditorServer"

    # -- helpers ----------------------------------------------------
    def _send_html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error_status(self, exc: Exception) -> int:
        if isinstance(exc, core.PageNotFoundError):
            return 404
        if isinstance(exc, (core.ConcurrencyError, core.AlreadyExistsError)):
            return 409
        if isinstance(exc, (core.PathEscapeError, ValueError)):
            return 400
        return 500

    def _handle_error(self, exc: Exception) -> None:
        self._send_html(self._error_status(exc), render_error(str(exc)))

    def _form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        parsed = parse_qs(raw)
        return {key: values[0] for key, values in parsed.items() if values}

    # -- routes -----------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 (http.server naming)
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                pages = core.list_pages(self.server.wiki_root)
                self._send_html(200, render_index(pages))
            elif parsed.path == "/edit":
                query = parse_qs(parsed.query)
                rel = query.get("path", [""])[0]
                page = core.read_page(self.server.wiki_root, rel)
                self._send_html(200, render_edit(page))
            elif parsed.path == "/new":
                self._send_html(200, render_new())
            else:
                self._send_html(404, render_error("no such route"))
        except Exception as exc:  # surfaced as an error page, not hidden
            self._handle_error(exc)

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        parsed = urlparse(self.path)
        try:
            form = self._form()
            if parsed.path == "/save":
                result = core.save_page(
                    self.server.wiki_root,
                    self.server.backup_dir,
                    form.get("path", ""),
                    form.get("body", ""),
                    form.get("token", ""),
                )
                self._send_html(
                    200,
                    render_message("Saved", f"Saved {result['path']}."),
                )
            elif parsed.path == "/create":
                result = core.create_page(
                    self.server.wiki_root,
                    form.get("path", ""),
                    form.get("title", ""),
                    form.get("page_type", "concept"),
                )
                self._send_html(
                    200,
                    render_message("Created", f"Created {result['path']}."),
                )
            else:
                self._send_html(404, render_error("no such route"))
        except Exception as exc:
            self._handle_error(exc)


class EditorServer(ThreadingHTTPServer):
    """Threading HTTP server carrying the editor configuration."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        wiki_root: str | Path,
        backup_dir: str | Path | None,
    ) -> None:
        self.wiki_root = Path(wiki_root)
        self.backup_dir = Path(backup_dir) if backup_dir is not None else None
        super().__init__(server_address, EditorHandler)


def create_server(
    wiki_root: str | Path,
    backup_dir: str | Path | None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> EditorServer:
    """Create (but do not start) the editor server.

    Only the loopback address is accepted: this is a single-user
    local tool and must never be reachable from the network.
    """
    if host != "127.0.0.1":
        raise ValueError("the editor binds to 127.0.0.1 only")
    return EditorServer((host, port), wiki_root, backup_dir)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Local single-user editor for the LLM Wiki."
    )
    parser.add_argument(
        "--wiki-root",
        required=True,
        help="path to the wiki/ directory to edit",
    )
    parser.add_argument(
        "--backup-dir",
        required=True,
        help="directory receiving a pre-save backup copy of each page",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    server = create_server(
        args.wiki_root, args.backup_dir, host="127.0.0.1", port=args.port
    )
    host, port = server.server_address[:2]
    print(f"Wiki editor on http://{host}:{port}/ (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
