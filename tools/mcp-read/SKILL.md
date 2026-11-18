---
name: wikicitadel-mcp-read
description: Use when a client is connected to the wikicitadel-read MCP server to read a WikiCitadel wiki through its eight read verbs — wiki_search, wiki_read_page, wiki_read_source, wiki_neighbors, wiki_path, wiki_claim, wiki_cite and wiki_census — with retrieval severance and sensitivity gating enforced by the server, and no write verb anywhere in the surface.
---

# WikiCitadel MCP read door

## When to use this

Use this when your client is connected to the wikicitadel-read
MCP server (`tools/mcp-read/server.py`) and you need to read
the wiki it serves: search first, read pages, walk links,
check claim standing, and pull citation passages. Everything
here is a read, served under the server's severance and
sensitivity rules.

## The restriction, stated once and plainly

The tools cannot write. There is no write verb in this
server's surface — not a disabled one, not a hidden one.
Writes go through the governed gateway (`tools/gateway/`)
or the filings channel, with their review and authorisation
machinery. Do not ask this door to change the wiki, and do
not work around it.

## Working pattern

1. **Search first** — `wiki_search` (severance applied by the
   engine, so hits are the standing record). Read the index
   page with `wiki_read_page` for the map of the corpus.
2. **Read what you cite** — `wiki_read_page` on the pages you
   will rely on. A search hit is a pointer, not evidence.
3. **Cite for the passage** — `wiki_cite` returns the
   verbatim cited passage from the citation lockfile. If a
   passage is withheld by the sensitivity gate, report the
   withholding, never paraphrase around it.
4. **Walk and check standing** — `wiki_neighbors` and
   `wiki_path` to walk the graph, `wiki_claim` to check a
   claim's lifecycle standing, `wiki_census` to size the
   graph before a broad sweep.
5. **Read raw sparingly** — `wiki_read_source` reaches the
   raw layer, sensitivity-gated; use it when the compiled
   page is not enough, and expect refusals with reasons
   where the gate requires them.

## Identity

One admitted identity, fixed as a stance in the server
itself (`DOOR_IDENTITY` in `server.py`): there is no
`--as` flag and nothing per call that selects or widens it.
A refusal is the door working as designed — state it
plainly, with the reason the server gave, and do not treat
it as an error to route around.
