# Wiki editor — local, single-user (15-gap item 6, scoped form)

A plain local editor for the wiki pages under `wiki/`, built only
on the Python standard library (`http.server`). It is the scoped
form of the "living editor surface" gap: a single-user local tool,
not a collaborative editor.

## Run

From the repository root:

```sh
python3 -m tools.editor.server \
    --wiki-root wiki \
    --backup-dir ~/wiki-editor-backups \
    --port 8765
```

Then open <http://127.0.0.1:8765/>.

- `--wiki-root` — the `wiki/` directory to edit (required).
- `--backup-dir` — directory that receives a pre-save backup copy
  of every page before it is overwritten, mirroring the page's
  path relative to the wiki root (required). Pick a directory
  outside the wiki tree so backups never show up as pages.
- `--port` — default 8765.
- `--templates-dir` — the `templates/` directory whose skeletons
  the new-page flow offers (default: `templates/` at the repository
  root, when run from a checkout).
- `--data-dir` — directory holding the recent-pages state file
  (default: `<backup-dir>/editor-state`).

Stop it with Ctrl-C. Nothing runs when the server is not running;
there is no daemon and no background state.

## What it does

- **List** — every `wiki/**/*.md` page, with the `title`, `stage`
  and `type` taken from its frontmatter (pages without a title
  fall back to their file name).
- **Edit** — one page at a time, body only, in a plain textarea.
  The form is a single self-contained HTML page: no external
  assets, no JavaScript at all.
- **Save** — replaces the body and:
  - preserves the frontmatter **byte-for-byte**, except that an
    existing `updated:` field is set to today's date (a field is
    never added to a page that does not already carry one, and a
    page with no frontmatter stays that way);
  - first copies the previous bytes to the backup directory;
  - refuses if the file changed on disk since it was loaded —
    the edit form carries a token (the sha256 of the loaded
    content) and a mismatch is a refusal (HTTP 409), never a
    silent overwrite. Reload and re-apply the edit.
- **Create** — a new page anywhere under `wiki/`, written with
  the required frontmatter skeleton from `AGENTS.md` (`title`,
  `type`, `created`, `updated`, `sources`, `tags`, then an
  `# <title>` heading). `type` must be one of `source`, `entity`,
  `concept`, `synthesis`, `query`. Creating over an existing
  page is refused — a create never overwrites.
- **Create from a template** — the new-page form also offers the
  skeletons under `templates/` (`templates/*.md` and
  `templates/capture/*.md`; preset trees are not page templates).
  Choosing one supplies the new page's body from that skeleton:
  its frontmatter is replaced by the standard skeleton,
  `YYYY-MM-DD` becomes today, `%:title` becomes the title, and a
  `# <...>` heading placeholder takes the title. Any other
  capture-style `%` prompts in a capture skeleton are left in
  place for the author to resolve. With no template chosen the
  page is the plain skeleton, exactly as before.
- **Preview** — every edit page carries a rendered preview pane
  of the saved body, a standalone preview lives at
  `/preview?path=...`, and the edit form's "Preview unsaved body"
  button POSTs to `/preview` to render a draft without writing
  or recording anything. Rendering is server-side, stdlib only,
  by `preview.py`: the input is HTML-escaped BEFORE any Markdown
  rule runs and there is NO raw-HTML pass-through, so markup in a
  page (a script tag, an event handler) previews as inert visible
  text. Supported subset: ATX headings, paragraphs, unordered and
  ordered lists, fenced code blocks, inline code, bold, italic,
  links (scheme-checked: `http:`, `https:`, `mailto:`, fragments
  and relative paths only — anything else renders as plain text),
  `[[wikilinks]]` (shown as a span naming the target), pipe
  tables, blockquotes and horizontal rules. Anything else renders
  as plain text.
- **Recent pages** — the index and `/recent` list the pages this
  server most recently opened, saved or created, most recent
  first. The log lives in memory and in a small state file
  (`recent.json`) under the editor's data dir, capped at 50
  entries; it is the server's own record, not a corpus artefact,
  and a missing or corrupt state file simply starts empty.

## Safety model

- **Loopback only.** The server binds to `127.0.0.1` and refuses
  any other bind address. There is no authentication because
  there is no network exposure: anyone who can reach the port is
  already running code on this machine.
- **Wiki root only.** Every path is resolved against the wiki
  root and must stay inside it after resolution. `..` traversal,
  absolute paths, and symlinks (file or directory) whose target
  escapes the root are refused; the listing silently skips
  escaping symlinks rather than serving them.
- **Markdown only.** Only `.md` files can be listed, read,
  saved or created.
- **No overwrite surprises.** Saves are guarded by the
  optimistic-concurrency token above; creates are exclusive.
  Saves are written via a temporary file in the same directory
  and an atomic replace, so an interrupted save cannot leave a
  truncated page.
- **Backups before writes.** A refused save writes no backup;
  a successful save always leaves the previous version in the
  backup directory first.
- **Stdlib only, own code.** No dependencies, no vendored code.

The logic lives in `core.py`, factored away from the HTTP layer
in `server.py` so it is testable without a server.

## Tests

```sh
python3 -m unittest tools.editor.tests.test_editor -v
# or
python3 -m unittest discover -s tools/editor/tests -v
```

The suite uses a temporary wiki fixture (the real corpus is
never touched) and covers: list/read/save round-trips,
frontmatter preservation, concurrency refusal, backups,
path-escape refusals (traversal, absolute, non-Markdown,
escaping symlinks), the create skeleton and overwrite refusal,
plus one live-server smoke test on an ephemeral port.

## Honest remainder

This is deliberately **not** a grand editor:

- **Single-user, local only.** No real-time co-editing, no
  presence, no operational transform / CRDT merging — concurrent
  edits are handled by refusing the second save, not by merging.
- **No rich text.** Editing is raw Markdown in a plain textarea:
  no WYSIWYG, no syntax highlighting, no wikilink completion.
  The preview is a reading aid for the documented subset only —
  constructs outside it (images, nested lists, reference links,
  raw HTML) render as plain text, never as live markup.
- **No corpus machinery.** The editor does not update
  `wiki/index.md` or `wiki/log.md`, run the validator or lint
  lanes, stage writes through the gateway, or commit anything
  to git. A page created here still needs its index entry and
  log line by the normal ingest discipline; git stays a human /
  coordinator step.
- **Frontmatter is preserved, not edited.** There is no
  frontmatter form; changing metadata means editing the file by
  another route. (The one exception is the automatic `updated:`
  date on save, described above.)
- **No access control beyond loopback**, no TLS, no upload, no
  image/file management, no search, no rename or delete.

Those are scope decisions for this lane, stated plainly so the
scoped form is never mistaken for the grand form.
