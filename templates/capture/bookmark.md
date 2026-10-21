---
title: "{title}"
capture_kind: bookmark
captured: {captured}
capture_date: {date}
captured_by: bookmarks-importer
source_file: "{source_file}"
bookmark_url: "{url}"
bookmark_folder: "{folder}"
bookmark_added: "{added}"
status: draft
confidence: observed
sources: []
tags: [bookmark]
# TODO (capture) — sensitivity: answer before ingest. One of
# public | internal | personal | family-sensitive | export-only |
# credential-adjacent (evaluation/sensitivity.json). While this
# line stands unanswered the draft is UNCLASSIFIED, and the
# ingest converter refuses unclassified material a home in raw/
# (item 51).
sensitivity: TODO
compiled_prompt:
compiled_converter:
compiled_date:
---

<!-- CAPTURE TEMPLATE — bookmark (Bookmarks Sync design, MIT,
     re-implemented; Marathon R7 lane BB). Rendered by
     scripts/wiki_bookmarks.py from a bookmark FILE the owner
     hands it — manual-first, no sync, no browser access, the
     URL recorded and never fetched. This draft waits in
     staging/bookmarks/ and is not a wiki page. -->

# Bookmark — {title}

**URL:** {url}
**Folder:** {folder}
**Bookmarked:** {added}
**Imported from:** {source_file}

## Why

[prompt: Why — why this bookmark belongs in the wiki; answered at ingest, never invented by the importer]
