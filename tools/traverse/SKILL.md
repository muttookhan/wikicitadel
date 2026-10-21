---
name: wiki-traverse
description: Read the LLM Wiki through its read-only traversal door (scripts/wiki_traverse.py) — page reads, typed-edge graph walks, claim lookup, verbatim cited passages, and search — when you are an agent with a seat at the wiki and need its contents without raw shell access to the repo.
---

# Wiki Traverse — the read-only door

## When to use this

You are an agent working with a WikiCitadel wiki (the repo at
`~/workspace/wikicitadel`, canonical on the installation's git
remote) and you need to **read** it: find a page, see what it
links to, walk from one page to another, check a claim's
standing, pull the exact passage a citation rests on, or
search the corpus.

Use this door instead of `grep`/`find`/reading files yourself.
The graph moves are verbs here, so you spend tokens on the
graph instead of on file plumbing — and the door's
restrictions are properties of the tool, not promises you
make. (Pattern: Christian Tietze's `ta` CLI + SKILL.md.)

## The restriction, stated once and plainly

**This tool cannot write.** Its command surface contains no
mutating verb; it opens every file read-only and imports no
write path. There is no flag, mode or environment variable
that changes this. If your task needs a write, it does not go
through this door: filings go through your installation's
filings channel (its mail-in door, or your own filings branch,
if you hold one), and everything else goes through the gateway
(tools/gateway/) under its scopes. Do not ask this tool to
edit, stage, file, or fix anything — it will refuse because
it *cannot*, not because it is being difficult.

## Identity — say who you are

Every call carries `--as <identity>`. Admitted identities are
roles, configured per installation in the tool: `owner` (the
wiki's owner), `agent` (the primary agent), and one seat per
admitted collaborator agent (for example `collaborator-a`,
`collaborator-b`, or a `coordinator` seat). An identity not on
the installation's list is refused before any file is touched
(default-deny, the gateway's posture). Use your own identity;
borrowing a stronger one is a governance breach, and the
door's gate is keyed to it:

- The compiled layer (`wiki/`) and the evaluation registers
  are readable by every admitted identity.
- Raw sources are gated by the sensitivity register
  (evaluation/sensitivity.json): `credential-adjacent` and
  `export-only` material is served to the **owner only**;
  `personal` and `family-sensitive` material to **owner +
  agent**; `public`/`internal` to all admitted identities;
  **unclassified** material is served to all admitted
  identities but stamped UNCLASSIFIED — no class on the
  register is a state of ignorance, never a clearance.
- A non-owner/agent identity's `search` is restricted to the
  compiled layer (the tool says so in its output): ranked raw
  snippets cannot be class-filtered after the fact.

A refusal names the class and the register. It is the
register's rule firing, not a judgement on you.

## Commands

Run from anywhere; `--root` defaults to the tool's own repo.

```bash
T="python3 ~/workspace/wikicitadel/scripts/wiki_traverse.py --as <identity>"

$T page <name>                 # a compiled page, full text
$T source <raw/path>           # a raw source (gated, see above)
$T neighbours <page> [--type T] [--dir out|in|both]
$T path <from-page> <to-page> [--max-depth N]
$T census                      # the typed-edge census
$T claim [query]               # claim pages + lifecycle status
$T cite <page>                 # the page's citations, verbatim
$T cite --id c0001             # one citation by lockfile id
$T search "<query>" [--top N] [--scope wiki|raw|all]
```

- `<name>` resolves by repo-relative path, then path without
  suffix, then file stem, then frontmatter title — the same
  precedence as the validator, the search and the Lens.
- `neighbours` types are the graph's relations: `mentions`,
  `grounds`, `contradicts`, `extends`, `exemplifies`,
  `supersedes` (typed by the heading the link sits under, the
  Lens's own rules), the frontmatter-declared relations
  (`cites`, `corrects`, `derives-from`, `replaces-part-of`,
  `grounds`, …), and `cites` for `sources:` citation edges.
- `path` follows directed edges and reports the relation at
  each step; when no directed path exists it says whether an
  undirected connection does.
- `cite` returns the passage **verbatim as locked** in
  evaluation/citation-lockfile.json, with the claim it
  supports and the source lines. A passage whose source class
  your identity may not read is withheld, with the reason —
  the citation's existence and claim still show.
- `search` delegates to the wiki's hybrid search
  (BM25 + graph + severance + freshness annotations) — the
  annotations on hits are part of the answer: a hit marked
  re-verification-due or negative-standing is not a clean hit.
- Every command takes `--json` (after the subcommand) for a
  structured rendering of the same facts.

Exit codes: 0 ok · 1 refusal (unadmitted identity, gated raw,
no such page — the refusal on stderr says which) · 2 usage
error.

## Packing assembled context — Lost in the Middle

When you assemble retrieved pages into a context pack for an
answer, order is evidence handling, not cosmetics: models use
material at the head and the tail of a long context better than
material buried in the middle (Liu et al., "Lost in the
Middle"). The packing rule is therefore: the most relevant
pages sit first or last in the assembled pack, in
relevance-descending order at the edges, and the weakest pages
sit in the middle — never bury the strongest page mid-pack.
Packs of three or fewer need no rearrangement (every position
is edge-adjacent). The Ask door's packing module
(`tools/ask/evidence_packing.py`) applies this rule to packs of
four or more, and `scripts/wiki_packing_check.py` reports, for
a pack you have in hand, whether the rule holds.

## Worked habits

- **Orient before reading**: `census` once, then `neighbours`
  on the page you care about, then `page` on the two or three
  neighbours that matter. Cheaper than reading the index and
  guessing.
- **Check standing before relying**: `claim <topic>` shows
  whether a claim is a candidate or a rule and how its
  recorded outcomes split; `cite <page>` shows whether its
  citations' passages still say what the page says they say.
- **Trust the freshness lines** in `search` output: this wiki
  marks superseded and severed material rather than deleting
  it, and the door surfaces those marks rather than hiding
  them.
