# The MCP read door

A standard, lightweight **MCP server over stdio** that gives any
MCP client — Claude Code, Codex, and their kin — read-only access
to this wiki. Stdlib-only Python 3, no tokens, no registry, no
daemon: the client spawns the process, talks newline-delimited
JSON-RPC, and the process exits when the client does.

```sh
python3 tools/mcp-read/server.py            # serves the repo it lives in
python3 tools/mcp-read/server.py --root /path/to/wiki-repo
LLM_WIKI_ROOT=/path/to/wiki-repo python3 tools/mcp-read/server.py
```

## The split: this door reads, the gateway governs writes

This wiki has two agent doors, deliberately:

| | **Read door** (here) | **Gateway** (`tools/gateway/`) |
|---|---|---|
| Purpose | read the corpus | govern every change to it |
| Transport | MCP over stdio | MCP over stdio |
| Auth | none — a local process the owner runs | scoped bearer tokens, re-checked per request |
| Writes | **none — no write verb exists** | staged proposals only; review, eval gate and owner authorisation before promotion |
| Record | none | hash-chained Black Box ledger of every act |

If a client needs to change the wiki, it uses the gateway. The
read door exists so that *reading* — the thing agents do most —
does not need the gateway's token machinery, and so that a plain,
standard MCP client can be pointed at the wiki as-is.

## Configure a client

```json
{
  "mcpServers": {
    "wikicitadel": {
      "command": "python3",
      "args": ["/path/to/wikicitadel/tools/mcp-read/server.py"]
    }
  }
}
```

Add `"--root", "/path/to/other-wiki"` to `args` (or set
`LLM_WIKI_ROOT` in `env`) to serve a different wiki repo than
the one the server lives in.

## Tools

Exactly eight, all reads:

| Tool | Arguments | Returns |
|---|---|---|
| `wiki_search` | `query` (required), `limit` (default 10), `scope`: `wiki` (default) \| `raw` \| `all` | Ranked results (`page_id`, `score`, `snippet`, freshness where a signal exists), the engine's severance block, and a `withheld_count` (below) |
| `wiki_read_page` | `page` — id, repo-relative path, stem, or title | `page`, parsed `frontmatter`, full `text` |
| `wiki_read_source` | `path` — repo-relative raw path | `path`, `sensitivity`, `text` — or a refusal (below) |
| `wiki_neighbors` | `page`, optional `type`, `direction`: `out` \| `in` \| `both` | The page's typed wikilink edges (the Lens's graph) |
| `wiki_path` | `from_page`, `to_page` (both required), `max_depth` (default 6) | Shortest directed wikilink path (`from`, `to`, `path`, `relations`), or `path: null` with a `note` when no directed path exists |
| `wiki_census` | — | Page/edge counts by relation and kind, orphan pages and `orphan_count` |
| `wiki_claim` | optional `query` substring filter (default: all claim pages) | Claim pages with their lifecycle `status` and outcome counts |
| `wiki_cite` | optional `page`, optional `cite_id` | Verbatim cited passages from the citation lockfile; a passage the sensitivity gate bars is withheld, with the reason stated (below) |

## The gates still apply

No tokens does not mean no rules. The read rule is **imported,
not re-implemented**, from the traversal door
(`scripts/wiki_traverse.py`), and search delegates to
`scripts/wiki_search.py`, so two properties hold by construction:

- **Retrieval severance (item 20).** `wiki_search` runs the
  wiki's own hybrid engine, whose severance stage excludes
  superseded claims by register lookup
  (`evaluation/retrieval-severance.json`). A severed claim never
  surfaces through search; the pack's `severance` block names
  what was excluded for the query. The record itself stays in
  the corpus and findable by queries that do not hunt the
  severed claim — supersede, don't delete.
- **Sensitivity composition (Phase 6).** `wiki_read_source`
  classifies the path against `evaluation/sensitivity.json`
  and applies the traversal door's rule table under the door's
  fixed identity stance: **the owner's agent (`agent`), never
  the owner**. By that table:
  - `public` / `internal` — served;
  - `personal` / `family-sensitive` — served (the owner's agent
    already holds this material under the memory-transparency
    rule);
  - `credential-adjacent` / `export-only` — **refused**, with
    the reason stated (`refused: … is class 'credential-adjacent'
    in the sensitivity register …`). These classes are
    owner-only-ever; no flag or environment variable widens the
    stance, because an agent door must not become the side
    channel around that rule;
  - `unclassified` — served, with the class reported and a
    stamp: *UNCLASSIFIED — no class on the register; not
    thereby public.* Absence of a class is a state of
    ignorance, never a promotion to public.

  At `scope` `raw`/`all`, `wiki_search` passes every raw hit
  through the same gate before returning it: a barred hit is
  withheld — its snippet and text never leave the process —
  and reported only as part of `withheld_count`.

  The same gate applies inside `wiki_cite`: a citation whose
  source class bars this door's identity returns its citation
  record with the verbatim passage withheld (`quote: null`)
  and the reason stated — the citation is not hidden, the
  passage is.

Refusals and failures come back as MCP error results
(`isError: true`) whose text states the reason; a missing page
and a barred source are both errors, never empty successes.

## Frozen reads (`--pin`)

The traversal CLI's `--pin <commit>` frozen read is available
here in both shapes:

```sh
python3 tools/mcp-read/server.py --pin <commit>   # whole session
```

or per call: every tool accepts an optional `pin` argument
pinning that one call. Semantics are the traversal door's
own (`resolve_pinned_root`, imported): the commit is
verified, its tree extracted read-only by `git archive`,
and the working tree is never written, checked out, or
moved. A pinned result carries `pin: <resolved commit>`;
an unpinned result has no `pin` field and is unchanged
from before. An unresolvable pin is refused — per call as
an error result, at startup as exit 2 before serving.

## Tests

```sh
cd tools/mcp-read
python3 -m unittest discover -s tests        # fixture wiki only
```

The suite speaks real JSON-RPC to the server against a fixture
wiki in a temp dir, and pins: the handshake, the exact eight-tool
surface, severance cutting a hunted claim while the record stays
findable otherwise, wholesale page severance, the
credential-adjacent refusal (read and search), the
unclassified stamp, the shortest-path and no-path cases, claim
listing with lifecycle status, verbatim citations with a gated
passage withheld, and byte-identical fixture checksums after
a full call battery (the door writes nothing).
