# Lens compiler — build tooling for the WikiCitadel Lens

Implements the front-end blueprint
(`wiki/syntheses/lens-frontend-blueprint.md`, milestones FE-0…FE-6
in local form): a single deterministic build that turns the
canonical wiki repository into a static site.

**Constitutional rule (from the design):** markdown + git is the
only storage. The Lens is a lens, never a second master, never a
second engine. Everything emitted here can be deleted and rebuilt
without losing knowledge.

## Layout

- `lenslib.py` — the one shared parser (frontmatter, body,
  wikilinks, citations, ledes, markdown→HTML) plus the reference
  BM25 implementation used for search postings. Its scoring is a
  faithful port of `scripts/wiki_search.py`; the build runs a
  parity check against that script on a fixed query set and
  reports PASS/FAIL.
- `build_lens.py` — the compiler: parse → page artefacts → one
  edge table (`edges.jsonl`) → graph bundle (multi-signal
  relevance, Louvain communities, seeded precomputed layout,
  insights) → search artefacts → mode extracts (timeline,
  decisions, cards, briefing) → Black Box summary → stamp.
- `assets/` — the shell (`shell.html`), stylesheet (`lens.css`,
  tokens from `wiki/syntheses/lens-design-system.md`), and the
  client (`app.js`) that renders the seven reading modes, Search,
  and the Black Box from the artefacts.
- `rebuild.sh` — the one-command rebuild (the freshness
  mechanism; run after every wiki push).
- `smoke_test.js` — the client smoke suite (Node, DOM stub):
  artefact checks (counts, colours, insights, the site-root
  `staticwebapp.config.json` auth wall) plus renderer checks for
  every mode. Run `node tools/lens/smoke_test.js` after a build.

Since the nashsu parity pass (compiler 1.1), the graph bundle also
carries header stats, type groups with the legend colours, weighted
degree per node, community metrics, and five computed insight
categories; a `knowledge.json` artefact feeds the Knowledge | Files
left panel; and every build emits `staticwebapp.config.json` at the
site root (the portal's auth wall: `/*` requires the `owner` role,
`/login` and 401s redirect to the platform AAD sign-in).

## Live queries over markdown (`wiki-query` blocks)

A wiki page may embed a fenced block whose info string is
`wiki-query`: a tiny declarative query over page metadata
(frontmatter type / tags / status, section, link targets, and
the created / updated / as_of dates), with list or table output,
sort, and limit. At page render the block is replaced by the
computed list or table — standing pages (current-state, the
filing area) carry self-updating lists instead of hand-maintained
ones. The full grammar is specified in the comment-headed section
at the evaluator in `lenslib.py` (`parse_wiki_query` /
`run_wiki_query` / `expand_wiki_queries`); tests are in
`scripts/tests/test_lens_wiki_query.py`.

**"Live" is honest here:** the Lens is a static build, so a query
is evaluated at build time against the corpus and re-evaluated on
every rebuild — and the Lens rebuilds on every push. Between
builds, a rendered list is a snapshot of the corpus at the build
stamp; it does not change on its own. A malformed block renders a
visible warning callout in place (never a build failure, never
silence), and a query with no matches renders a one-line note.

## Graph analytics (the build)

The Graph mode carries three computed analytics over the edge
table, all deterministic at build (functions in `lenslib.py`,
tests in `scripts/tests/test_lens_graph_analytics.py`):

**Typed link edges.** Every row of `data/edges.jsonl` carries a
`type` and a `section`. For a wikilink, the type is **inferred
from the heading the link sits under** (pattern: wiki-to-graph;
vocabulary: zby/commonplace, MIT) via this mapping — keywords
match at a word start in the lowercased heading, rules in
priority order, first match wins:

| Type | Heading keywords |
|---|---|
| `contradicts` | contradict, conflict, disagree, dispute, contested, tension |
| `supersedes` | supersede, replaces, replaced by, deprecated, obsolete, retired |
| `grounds` | evidence, ground, basis, provenance, citation, sources |
| `exemplifies` | example, exemplif, illustrat, case study, instance |
| `extends` | extend, extens, elaborat, builds on, built on, expansion, follow-up, followup |
| `mentions` | *(default — no keyword matched, or no heading yet)* |

Wikilink edges dedupe per (target, type): one page linking
another as both evidence and contradiction yields two typed
edges. A frontmatter `links:` edge keeps its author-declared
relation as its type; a citation's type is `cites`. In
`graph.json`, each direct pair aggregates its typed edges as
`types` (counts) plus the dominant `relation`, so the graph —
and the inspector's "Related — and why" list — can reason about
a link's meaning, not just its existence.

**Edge provenance labels (W1.8).** Every edge row, and every
pair edge in `graph.json`, also carries a three-way
`provenance` label — EXTRACTED / INFERRED / AMBIGUOUS — plus a
`confidence` in [0, 1] and a `polarity` (pattern: the
legal-graphify-skill's EXTRACTED / INFERRED / AMBIGUOUS tag,
dual-licensed MIT OR Apache-2.0, generalised in
`lenslib.py`'s edge-label section, where the assignment table
lives). Declared relations and citations are EXTRACTED at
1.0; a heading-inferred type is INFERRED at 0.75; a pair
asserting two distinct specific types is AMBIGUOUS at 0.5; a
derived pair is INFERRED at a signal confidence. In the
canvas, inferred pairs draw dashed and ambiguous pairs rust
dotted; the inspector names the label and confidence. The
labels are additive — the `epistemic` tag is unchanged, and
an edge without labels is unlabeled, never invalid.
`scripts/wiki_edge_labels.py` reports the labels the
existing corpus's edges carry, rule by rule.

**Page-outline mindmaps (W2).** Every page also ships as a
mindmap: the reader's Mindmap tab renders the page's own
heading outline — headings nested by level, exactly as
written — with the wikilinks written under each heading as
leaf references, computed at build time by `mindmapview.py`
from the same lenslib parsing as the page artefacts and
shipped as `data/mindmaps.json` / `data/mindmaps.js`. A
resolved leaf links to its page; an unresolved one is a
dashed boundary leaf, never a pretend link. A page with no
headings shows an explicit empty state. The view adapts the
Markmap pattern (markmap.js.org, MIT) — idea and foldable-
branch interaction credited; the generator and renderer are
this tree's own code.

**Margin notes (W2).** The Read view carries a margin-notes
layer on the W3C Web Annotation Data Model (clean
re-implementation from the W3C Recommendation; the pattern was
evidenced by the Round 10 Annotorious prototype trial and by
Hypothesis, which stand as research evidence, no code taken).
A note is an Annotation with a TextualBody, targeting the page
by its canonical path — or, for a passage note, a
SpecificResource refined by TextQuoteSelector +
TextPositionSelector + a FragmentSelector text fragment. The
store is this browser's localStorage (`lens-annotations`)
only: the build never sees notes, no artefact or corpus file
can contain one, a note never changes its page, and the only
way out is the reader's own export — a JSON-LD
AnnotationCollection file the Export button downloads and the
Import button reads back (round-trip pinned by
`tests/test_margin_notes.py`). Anchor honesty: on render, a
passage note's quoted words must be found — at the stored
offsets, or uniquely elsewhere with the stored context
disambiguating repeats — before the note shows as attached;
otherwise it lists as ORPHANED with its words preserved,
attached to nothing, never silently re-anchored to different
text. Selector kinds this surface does not create (an imported
SVGSelector, the IIIF-aware case) are stored and re-exported
verbatim and list as page notes.

**Semantic zoom (W2).** The Graph mode's Zoom control moves
between three levels whose content changes with scale, not
just size (Sensecape pattern, re-implemented): *Overview* —
one supernode per community, placed at the centroid of its
member pages, sized by their total link weight, labelled and
sized from the community summaries and cluster digests;
*Community* — one community expanded into its member pages at
their page positions (direct links drawn, as at page level),
the other communities collapsed around it with their boundary
links aggregated; *Pages* — the full graph, the default. The
`zoom` block in `graph.json` is computed at build in
`lenslib.py` (`graph_zoom_levels`) from the SAME rendered
Louvain partition the nodes, summaries, and digests carry —
zooming never re-clusters, in the build or the client; the
client only renders the levels and folds the As-of filter
over the shipped edge table. Overview edges aggregate every
weighted relation pair between two communities (the weights
the communities were computed from), the As-of scrub applies
at every level (a community shows when at least one member
existed by the date), freshness colour at Overview is the
band of the median member update date, and type colour is
the community's plurality member type. The full rule set is
stated on the artefact itself (`zoom.rules`).

**Deterministic hierarchical layout (W2).** The Graph mode's
Layout control offers a second position set beside the
default seeded force layout: a layered (hierarchical) layout
over the DIRECTED link graph — pages ranked by longest path
from the pages that link to them — computed at build by
`graphlayout.py` and shipped as the `layouts.hierarchical`
block in `graph.json`. The layout is deterministic: the same
graph rebuilds to byte-identical positions, the property
reviewable graph diffs need. The item's named engine,
@hpcc-js/wasm-graphviz, is not available in this environment
(no Graphviz binary; the package, though published on npm, is
not vendored or installed here and installs are out of
bounds), so the shipped engine is the house clean-room
implementation of the published Sugiyama/dot layered method
(Sugiyama et al. 1981; Gansner et al. 1993) — the artefact's
`engine` field names it honestly, and the module header
states the door for the real engine. Community supernodes
keep the centroid rule under both layouts (the hierarchical
centroids ship as `zoom_positions`), positions are computed
over the full graph (the As-of filter only hides pages), and
when the block is absent the view is force-only, unchanged.

**Co-citation.** Two pages are co-cited when a third page links
to both. Selecting a node in the Graph shows a "Co-cited with"
panel: the co-cited pages, how many pages cite them together,
and the citing sentences where the two links appear in one
sentence (the strongest evidence). Entries are mutual by
construction (a pair is listed from both sides or neither).

**Link prediction — "Missing link?"** Pairs with no direct link
but at least one common neighbour are scored with Adamic–Adar
(Σ 1/ln(degree) over common neighbours) and the top 12 are
published as *computed suggestions* — an Insights lane and a
Graph report card, always labelled as suggestions. Nothing is
ever written back to a wiki page.

**Communities.** The rendered clusters are the build's
deterministic Louvain partition, named for their hub page and
shown as graph colouring (with the standing disclaimer that
clusters are computed, never canonical). Label propagation —
the Graph Analysis plugin's algorithm — is implemented in
`lenslib.py` and measured against the same weights every build:
on this corpus it collapses (its largest community swallows
the super-hubs' whole neighbourhood), so the graph report
carries both methods' community count and largest share, and
the rendered partition stays Louvain until the corpus shape
changes that measurement.

**Graph analytics pack (W1.7, 2026-10-22).** The graphology
algorithm family, cleanly re-implemented in `lenslib.py` from the
published algorithms (no graphology code used; attributions in
the section header there): full two-phase **Louvain** (Blondel
et al. 2008) with Newman–Girvan **modularity**, the **centrality
suite** — weighted PageRank (Brin & Page 1998), Brandes
betweenness (2001), Wasserman–Faust closeness (1994),
eigenvector centrality, Watts–Strogatz + Onnela weighted
clustering — **graph-level metrics** (density, components,
diameter/radius), a **link-prediction pack** publishing the
Common Neighbours lane beside Adamic–Adar over the same
"missing link?" pairs, and **per-cluster digest pages**: one
precomputed digest per rendered community, crawled from its hub
over links and backlinks to depth 2 (members with crawl depths,
strongest internal edges, boundary edges, the cluster's top
co-cited pair with its citing sentence). Two new artefacts:
`data/graph-metrics.json` and `data/cluster-digests.json`
(+ `.js` twins), rendered by the Graph report section. The
full Louvain is measured against the rendered partition, not
swapped in: at this build it finds 4 communities at modularity
0.4597 against the rendered partition's 14 at 0.4261 — the
comparison rides in `community_methods` beside label
propagation's, and the rendered partition changes only by a
separate decision. Tests: `scripts/tests/test_lens_graph_pack.py`
(hand-computed fixtures: two triangles + bridge, a star, a path;
determinism pinned for every function).

**GRAPH_REPORT.** Each build emits `data/graph-report.json`
(+ `.js` twin): god nodes (top pages by weighted degree), the
communities, surprising connections, the missing-link
suggestions, the typed-edge census, and suggested questions —
each question a fixed template over a computed fact, its basis
stated (pattern: Graphify, Apache-2.0). The Graph list view
renders it as the "Graph report" section.

## Trails + source-adjacent evidence (item 62)

**Trails** are authored reading paths over the built typed-edge
graph. Definitions live as data in `tools/lens/trails.json`
(authored only — a trail enters by editing the register on the
record); each step after the first names, in `via`, the edge type
walked into it. The build validates every hop against the edge
table (`lenslib.build_trails_artefact`) and emits
`data/trails.json` (+ `.js` twin); a trail whose page or hop no
longer exists is dropped with its reasons on the artefact, never
rendered as curated. The **Trails** view (More group) walks a
trail step by step, naming the edge type at each hop, and the
walk is serialised in the URL — `#/trails/<id>?stack=<page,
page,...>&at=<n>` (the stacked-notes form; `lenslib.trail_url` /
`parse_trail_url` are the canonical serialiser pair) — so a trail
link is resumable and shareable inside the portal.

**Source-adjacent evidence**: page artefacts carry
`cite_passages` — for each claim on the page whose `^[cite:]`
marker is in the citation lockfile (`evaluation/citation-
lockfile.json`, read by `lenslib.load_citation_lockfile`), the
claim paired with the lockfile's VERBATIM TextQuoteSelector
passage. The reading view shows the pairs under "Claims and
their sources". A claim whose passage the lockfile cannot
produce shows nothing — never a paraphrase dressed as a quote.
(Together this extends the Ask door's claim↔passage pairing,
batch 2.1, to ordinary compiled-page reading.)
Tests: `scripts/tests/test_lens_trails.py` + the smoke suite's
trails/pairing checks.

## Proposal diff view (wave-3 item C2)

The gateway stages proposed page changes as file pairs in
`staging/proposed/` — a full proposed page text (`<id>.md`) beside
a manifest (`<id>.json`: proposer, task, staged date, the content
SHA-256 the promotion gate binds to, and the gateway's own check
verdicts). The build reads those pairs and emits
`data/proposals.json` (+ `.js` twin): every **draft** proposal,
oldest first, with a per-hunk unified diff (3 lines of context)
against the current page text — a proposal whose target does not
exist yet renders as a pure-additions diff and is marked a new
page. The Lens shows them in the **Proposals** view (More group,
next to Decisions), each headed by its manifest facts, under the
standing line: *Decisions are made in chat — this view only
displays.*

Display only is structural, not a promise: the view's markup
contains no button, form, or action hook, and the smoke suite
asserts that absence. Already-decided proposals (state other than
`draft`) are excluded and named in the artefact's `excluded`
list; staged files without a manifest (the pre-gateway Ask
filings), malformed manifests, and a missing `staging/` directory
all degrade to recorded `skipped` entries or an empty view with a
note — never a build failure. The parsing/diff logic lives in
`lenslib.build_proposals_artefact` / `unified_diff_hunks`
(tests: `scripts/tests/test_lens_proposals.py`).

Build context: the deployment pipeline checks out the whole repo
(full depth) and runs `tools/lens/rebuild.sh` from the root, so
`staging/` reaches the deployment build whenever it is part of
the checked-out tree. Only committed staging files are in that
tree — drafts staged locally but never committed appear in local
builds only, until an integration commit carries them.

## Review Center (Wave-5 item)

The `#/review` view shows what needs review in one prioritised
worklist, computed at build time by `scripts/wiki_review_state.py`
(loaded by the builder, never mirrored): the periodic review
layer's queue (attestation expiry, FSRS re-verification, evidence
TTL, Pending Review sections, source changes, cadence) merged
with the pages' declared `review_state` frontmatter — the field
set `review_state` (`unreviewed` / `in-review` / `reviewed`),
`reviewed_on`, `reviewed_by`, `review_due` — whose effective
state (current / stale / unverifiable) is derived, never stamped.
Priorities: P1 attestation-expired / reverify-overdue /
pending-review-open / invalid review record; P2 evidence-due /
source-changed / review-state-stale; P3 the rest; then most
overdue, then path. The view also carries the review-state census
and a register-only review history (owner attestations are read,
never written). Display only: recording a review is an act on the
page itself. The same computation writes
`evaluation/review-center.json` / `.md` and an AI-reviewer
payload (`review-center-payload.jsonl`) when run as a CLI.

## Build

```sh
tools/lens/rebuild.sh            # -> ~/workspace/lens-site
```

Output: `index.html` (the shell), `lens.css`, `app.js`, and
`data/` artefacts (`pages/<id>.html` + `.json`, `routes.json`,
`edges.jsonl`, `graph.json`, `graph-report.json`, `search/…`,
`timeline.json`,
`decisions.json`, `cards.json`, `briefing.json`,
`blackbox-summary.json`, plus `.js` twins of each JSON payload so
the shell also works opened straight from disk).

Every artefact is stamped with `generated_at` and the git HEAD
it was built from. Same HEAD + same builder ⇒ byte-identical
artefacts except the stamp.

## OKF conformance export (sibling export, the build)

Beside the `llms.txt` / `llms-full.txt` exports above, the wiki can
be emitted as an **OKF v0.2 bundle** (Open Knowledge Format, Google
Cloud — SPEC.md in GoogleCloudPlatform/open-knowledge-format,
checked live 2026-10-20: still v0.2) for interchange with other
OKF consumers. It is a sibling export, not a replacement: the
Lens stays the reading portal; the bundle is a derived artefact,
read-only over the wiki, deletable and rebuildable like every
other build output. **Manually run only** — it is deliberately
not wired into the nightly sweep or any cron.

```sh
python3 scripts/wiki_okf_export.py export   # -> exports/okf-bundle (+ check)
python3 scripts/wiki_okf_export.py check [--bundle DIR] [--json PATH]
```

The bundle mirrors the wiki tree (`access/` and `talk/`
excluded): one OKF concept per compiled page with the frontmatter
mapped — `title`/`type`/`tags` verbatim, `sources` as
`{id, resource}` entries, `status` mapped into OKF's
draft|stable|deprecated vocabulary, and everything OKF has no
field for (`created`, `updated`, `confidence`, `claim`, `as_of`,
inline-citation counts, any extra key) preserved verbatim under
an `llm_wiki:` extension namespace — omitted rather than
invented, flagged rather than dropped, and `verified` is never
fabricated from our confidence axis. `index.md` and `log.md`
become the SPEC §8/§9 reserved files (the index gains the
permitted `okf_version: "0.2"` frontmatter; log entries regroup
newest-first under date headings). A `manifest.json` records the
spec source, git HEAD, and a SHA-256 per file. `check` validates
a bundle on disk against SPEC §11 + the §5/§10 family rules and
reports each file PASS / PASS-WITH-OMISSIONS / FAIL. The full
mapping table lives in the script's docstring; tests are in
`scripts/tests/test_wiki_okf_export.py`.

## Zero results, standing queries, ⌘K (the surfaces build, items 58 + 60)

A search that finds nothing renders a **designed zero-results
surface** (`zeroResultsHtml` in `assets/app.js`), not a bare
end: Baymard's five recovery strategies as the wave-7 lane
states them — nearest sections (page titles carrying the
query's words, by section), broader searches that do match
(drop-a-keyword variants, each with a live result count and
its top hit as preview), recently viewed pages, an "Ask
Agent" route carrying the same words, and the most-linked
pages as the popular floor. Item 59's corpus-vocabulary
corrections and the relaxation ladder render directly above
it (the surfaces build's `suggestionsFor` / `searchWithLadder`
— the ladder names the rung it climbed, including "exhausted"),
and when facet filters are active the zero page carries the
reset control itself (`clearFacets`).

**Save the failed search.** The zero surface offers "Watch
this search". The Lens is read-only and has **no honest client
write path into the wiki**, so the page does not save anything:
the button sends the request to the agent through the existing
Ask door (`POST /api/ask`, the same question store as Ask
Agent), and the surface shows the exact record the agent files
if the door is unreachable. Filing is the agent's act:

```
python3 scripts/wiki_standing_queries.py add \
  --name "<name>" --query "<search>" --from zero-results
```

**The register** is `evaluation/standing-queries.jsonl` — one
JSON object per standing query: `id` (`sq-NNNN`), `name` (the
owner's name for it), `query`, `saved_from`, `created_at`,
`last_looked_at` / `last_looked_head`, `seen` (page id →
sha256 of the page's search text at last look), `advances`,
optional `paused`. `scripts/wiki_standing_queries.py` also
lists, pauses, resumes and removes (`list|pause|resume|remove`).

**Build-time diff.** Every build re-runs each non-paused query
with the same hybrid ranking the search artefacts carry
(`lenslib.standing_queries_report`), capped at 10 hits, and the
Briefing gains a **Standing queries** section: per query, the
pages that are *new* (not in `seen`) or *changed* (hash
differs) since the last-looked stamp. Stamp discipline: a
stamp advances **only** in a build that reports the query —
its first build (which sets the baseline: what matches then
is the starting point, reported as a baseline, never as
"new") or a build that found new/changed hits. The advance is
written back to the register file by the build — a visible
working-tree change the next commit carries, never silent.
(This is the one deliberate exception to byte-identical
rebuilds: a second build at the same HEAD correctly reports
nothing new.) In the CI pipeline the checkout is ephemeral,
so the committed register is what persists. Logic tests:
`scripts/tests/test_lens_standing_queries.py`.

**Recent/frequent strip + ⌘K.** The nav column carries a
recent-searches / frequent-pages strip fed by a client-side
log in the browser's `localStorage` (`lens-query-log`,
`lens-page-views`) — two deliberately distinct tiers (find
18): the automatic chronological recents and the deliberate
named saves above. Nothing leaves the browser. The **⌘K /
Ctrl-K palette** (topbar button too) is a keyboard-first
overlay over the existing merged search: page-name matches +
the hybrid lane for pages, fuzzy-matched views, and actions
(ask, copy-link), grouped by kind, with recents shown before
typing.

## What is deliberately not here

- **No deployment.** Hosting behind private auth is an
  owner gate decision (blueprint FE-1/FE-8, design §10). This
  tooling builds the site; it does not publish it.
- **No gateway, no writes.** Ask in this build is a local,
  extractive preview over the same retrieval lanes; the real
  Ask, the Black Box ledger, review actions, and per-page raw
  views arrive with the the build gateway.
- **No accounts, tokens, or secrets** are created or needed.


## State-shaped views, reading profile, Briefing honesty (items 63–65)

**State** (More group) renders two build-time views over the real
registers, computed in `stateviews.py`: an **evidence-and-gap
matrix** (topics = frontmatter tags × five verification states —
owner-verified / cited / re-verification-due / superseded /
unverified — one mosaic square per page; empty cells in the
owner-verified and cited columns are listed as the work list) and
**claim histories aggregated by shared lifecycle prefix**
(LifeFlow form) from claim frontmatter, the citation lockfile,
the treatment and severance registers, attestation frontmatter,
the re-verification schedule/history, and the outcomes log. The
artefact is `data/state.json` (also in `modes.js` as `state`).

**Argument maps (63c):** a fenced ` ```argdown ` block in any page
compiles at build to an inline SVG map via `stateviews.parse_argdown`
— an own parser for the subset our pages would use ([statements],
<arguments>, `+` support / `−` attack relations, #tags, {meta});
nothing is vendored (Argdown itself is MIT, argdown.org). The
source block stays on the page as the source of truth; lines
outside the subset are named on the figure, never dropped. Census
in `state.json.argdown` — zero blocks today is a true count.

**Reading profile (64):** the **Reading** mode (More group) sets
the owner's typography by timed calibration — six candidate
settings (Inter / Fraunces / Atkinson Hyperlegible, incl. the BDA
Comfort preset), passages drawn from the wiki's own pages, WPM
scored only when both recognition answers are right
(`scoreCalibration` in `app.js`); the winner is stored in
localStorage and applied portal-wide via the `--read-*` CSS
variables. Atkinson Hyperlegible is self-hosted WOFF2 with its
OFL licence in `assets/fonts/`. Per synthesis N1 the profile
never contains RSVP or Bionic Reading. A line-focus mode
(1/3/5 lines, pointer or arrow keys) lives on every reading page.
`tools/lens/wcag_gate.py` is the WCAG numeric lane over the built
artefact (contrast computed from the palette, target sizes, focus
visibility, §1.4.8/§1.4.12 inspections) — it reports one live AA
finding at the Phase-8 build (dark chip text on `--status-broken`,
3.73:1) and does not fix the owner's palette.

**Briefing honesty (65):** the Briefing carries bullet graphs
(value bar + target tick + declared bands, geometry computed in
`stateviews.bullet_geometry` from a zero baseline) for the metrics
that pass the vanity admission rule, same-scale sparklines per
lint lane from the nightly filings, and the re-verification
forecast with the due-now claims as a leading block. The current
stat blocks are labelled **context** under the rule; verdicts are
recorded in `briefing.honesty.admission_verdicts` and in
`tools/lens/CHART-HONESTY.md`, the build checklist every chart
answers to. Tests: `tools/lens/tests/test_phase8.py`; the smoke
suite's Phase-8 lane reports separately from the main counts.
