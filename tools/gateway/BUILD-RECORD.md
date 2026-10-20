# Build Record — MCP Gateway + Black Box Core

**Location:** `tools/gateway/` · **Status:** core built and
test-proven against fixtures; **NOT activated** — no real tokens
issued, no watcher installed. Activation is gated on the owner
decisions listed at the end.

Spec implemented: the gateway design's target architecture
(write-gate matrix, multi-agent access flow), the Black Box design,
and the engineering spec's staging / promotion mechanics and
consultation measurement. Stdlib-only Python 3.12.

## What was built

| Component | File(s) | What it does |
|---|---|---|
| MCP gateway server | `gateway/server.py` | JSON-RPC 2.0 MCP over stdio; all 13 design tools (§4.6 list + `wiki_promote_proposal`): whoami, search, read_page, read_source, graph_neighbors, list/get_decision, stage_proposal, get_proposal_status, handoff_create, promote_proposal, blackbox_my_activity, lint_run |
| Token registry | `gateway/registry.py` | Bearer tokens `wct1.<identity>.<secret>`; only PBKDF2-HMAC-SHA256 salted hashes stored, in a registry file **outside git**; per-request re-authentication re-reads the registry, so revocation/rotation take effect on the very next request; **Reserved-seat fails closed** — issuance raises and authentication returns nothing while the seat is reserved (a governance decision) |
| Scope model | `gateway/scopes.py` | Scopes `wiki:read/propose/publish/admin`; per-identity read prefixes and raw-source prefixes; default-deny; `wiki/access/` requires admin; denied reads return the identical payload as missing objects (no existence leak, §5.2) |
| Wiki store + write path | `gateway/store.py` | BM25 search (same formulation as `scripts/wiki_search.py`), wikilink graph, decisions register reads, staging, review manifests, owner authorisations, promotion |
| Black Box ledger | `gateway/ledger.py` | Append-only hash-chained JSONL exactly per §5.3 (canonical JSON, `entry_hash = SHA-256(prev_hash ‖ entry)`), genesis entry naming schema/repo/git HEAD, `verify` recomputation, and an `anchor` step that records the chain head + emits git trailers for the anchor commit (Addendum 1) |
| Watcher (Door C) | `watcher/watcher.py` | Standalone polling watcher — **script only, not installed as a service**. Baseline-silent first run; create/modify/delete events with `attribution: unattributed-local` (honest weak attribution), gap marker on restart, own hash chain; excludes `.git/`, caches, and its own state |
| Consultation metrics | `gateway/metrics.py` | §6 signals from ledger data alone: consulted, read_before_write (compared by **ledger seq**, not 1-second timestamps), citation_coverage, consultation_depth, violations list; `gap_honesty` reported as null when Ask-lane data does not exist (not faked) |
| Admin CLI | `gateway/__main__.py` | `serve`, `issue`, `revoke`, `identities`, `review`, `authorise`, `verify`, `anchor`, `metrics` |
| Fixtures | `fixtures/make_fixtures.py` | Throwaway fixture wiki (git repo) + fixture registry: owner / agent / collaborator-a (scoped) / collaborator-b |
| Tests | `tests/test_gateway.py` | 13 end-to-end + unit tests, see below |

State layout (all **outside git**, default `~/.local/state/wikicitadel-gateway/`,
overridable by `GATEWAY_*` env vars): `registry.json`, `ledger/`,
`staging/`, `reviews/`, `authorisations/`, `anchors/`. Production
relocation of the ledger into `wiki/access/` and staging into the
repo's `staging/` is a config change at activation, not a code change.

## Write-path enforcement (Addendum 4 — in code, not prompts)

- Agents have **no canonical-write tool**. The only agent write is
  `wiki_stage_proposal`, restricted to `wiki/**/*.md` targets plus the
  two G5 schema files; `raw/`, `wiki/access/`, traversal targets are
  refused.
- `promote()` physically refuses unless **all** hold: caller has
  `wiki:publish`; a review manifest exists whose SHA-256 matches the
  staged file's current bytes; an **owner authorisation record**
  exists for that proposal (promotion is a separate Owner act). G5
  targets (decisions, `AGENTS.md`, `purpose.md`, `wiki/access/`)
  additionally require the authorisation to carry an Owner decision
  reference.
- A staged file altered after review fails the hash check, is moved
  to `staging/quarantine/` with the reason preserved, and cannot be
  promoted thereafter.
- With `GATEWAY_GIT_COMMIT=1`, promotion is one git commit carrying
  `Agent:` / `Session:` / `Sources:` / `Operation:` trailers
  (Addendum 1); the commit SHA is written into the Black Box promote
  entry and the proposal record — session → proposal → review
  manifest → commit linkage (§5.5 check 3).
- Search ledger entries record result page IDs, query length and a
  SHA-256 query hash — never query text (§5.3 privacy rule, tested).

## Test results

`python3 -m unittest discover -s tests` from `tools/gateway/`:
**13 tests, all passing** (three consecutive full runs after one fix).

- **Default-deny:** no token and forged token denied + `auth_denied`
  ledgered; reserved-seat issuance refused and a forged reserved-seat token rejected;
  revocation denies the next request; rotation kills the old token.
- **Scoped reads / no leak:** collaborator-a reads in-scope page + in-scope raw
  source; out-of-scope raw, out-of-scope decision page, and a missing
  in-scope page return byte-identical error payloads.
- **Propose→promote:** collaborator-a stages (canonical file absent); collaborator-a
  cannot promote; maintainer cannot promote without review manifest,
  then not without owner authorisation; after both, promotion lands
  the file, the fixture git log shows all four trailers, HEAD equals
  the ledger entry's `commit_shas[0]`.
- **Tamper:** staged file edited after review → hash mismatch,
  promotion refused, proposal quarantined, target never created.
- **Ledger:** chain verifies; genesis present with schema version;
  one altered byte in a copied ledger fails verification at exactly
  that entry's seq; anchor file's `entry_hash`/`seq` equal the chain
  head and trailers carry `Blackbox-Head`.
- **Watcher:** baseline run silent; create+modify+delete captured
  with `attribution: unattributed-local`; restart writes a
  `watcher_gap` entry with `last_heartbeat`; watcher chain verifies.
- **Metrics:** fixture session that searched/read 1 page and cited 2
  yields coverage 0.5 and depth 0.5 with both violations flagged; a
  zero-consultation session is flagged `consulted = false`.

**Bug found and fixed during the build:** §6's `read_before_write`
was first implemented on ledger timestamps; timestamps have
one-second resolution, making same-second read/write pairs
unordered (flaky test). Ordering is now taken from the monotonic
ledger `seq`. The spec's definition ("first read timestamp < first
write timestamp") should be read as ledger order.

**Pre-activation smoke check (real wiki root, default state dir):**
server starts against a real wiki root; with no production
registry in existence a forged token is denied and the denial is
ledgered; `verify` passes (genesis + denial); `anchor` records the
head against the repo's current git HEAD and emits the trailer
block. Nothing can authenticate until the owner ceremony runs —
that is the correct pre-activation posture.

## Deliberate narrowings vs. the full design picture

- **Transport is stdio.** The tool/scope/ledger semantics are
  transport-independent; the production transport + hosting
  shape is an owner gate (below), not decided here.
- **Review and authorisation are CLI operations**, not MCP tools —
  the design's §4.6 tool list has no review tool; the maintainer/
  owner acts are kept off the agent-facing surface on purpose.
- **The Lens read release, the thin-client files, and the
  flight-recorder page are not in this build** — this task covered the gateway + Black Box core.
  The ledger + anchor outputs are the inputs the flight-recorder
  generator will consume.
- Staging/ledger default to the state directory, not repo paths
  (`staging/`, `wiki/access/`); relocation is activation config.

## Owner gate decisions still required before real activation

Per the design's approval map — **none of these were taken by
this build, and silence is not approval:**

1. **Initial identity/scope table** — approve which identities get
   which scopes and which read/source prefixes (the fixture table is
   illustrative only: owner full; agent read+propose+publish;
   collaborator seats scoped read+propose; the reserved seat none).
2. **Token-provisioning ceremony** — who runs `issue`, how the
   one-time token reaches each agent's harness, rotation cadence,
   and confirmation that the registry lives at the default state-dir
   path (outside git) or another approved secret location.
3. **Watcher installation** — approve installing/running
   `watcher/watcher.py` as a service on the maintainer machine, its poll
   interval, and its ledger location.
4. **Gateway transport + hosting shape** — stdio-per-harness
   vs. a hosted HTTP endpoint on the installation's platform, and
   the resulting endpoint/auth exposure.
5. **Ledger + staging relocation** — approve moving the gateway
   ledger into `wiki/access/black-box-YYYY.jsonl` and staging into
   the repo's `staging/` at activation, and the session-end anchor
   routine (anchor file committed with the `Blackbox-*` trailers on
   every push to the canonical remote).
6. **Which harnesses are onboarded first** — the collaborator seats
   (thin-client files to be written per harness once 1–4 are decided).
7. **Git-commit-on-promotion** — whether production promotion commits
   directly (`GATEWAY_GIT_COMMIT=1`) or the maintainer commits
   promotions through the normal git-mediated workflow (Door B).

Until gates 1–2 are decided, the correct operating state is the one
verified above: **the gateway runs, everything is denied, and every
denial is recorded.**
