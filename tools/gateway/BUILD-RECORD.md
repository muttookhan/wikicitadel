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

---

## Hosted gateway door (HTTP shim) — built 2026-11-08, NOT activated

**Approval:** owner ruling 2026-11-08, item 30 of his 30-item list:
"YES, BUILD IT". The approval covers BUILDING the door. It does NOT
approve activation, Azure hosting, real tokens, or any public
exposure. This section records the build; the activation gates 1–7
above stand unchanged and still open (restated at the end of this
section — none was taken by this build, and silence is not approval).

**What was built** (in both trees; the shim and its tests are
byte-identical across trees — the file carries no tree-specific
identity, token prefix, or seat name):

| Component | File(s) | What it does |
|---|---|---|
| HTTP shim | `gateway/http_server.py` | Stdlib-only (`http.server`) thin door over `Gateway._call_tool` in `server.py`. Every route is exactly one stdio tool call — same dispatch, scope checks, staging/promotion gates, Black Box ledger. No auth, scope, or write logic is reimplemented here. Binds loopback only (see below). `Authorization: Bearer <token>` header only, per-request re-authentication against the same salted-token registry. |
| Tests | `tests/test_http_server.py` | 12 tests, fixtures only (see below) |

**Routes** (`/v1/` versioned JSON; reads first):

- `GET /v1/whoami`, `GET /v1/search?q=&limit=`, `GET /v1/pages?path=`,
  `GET /v1/sources?path=`, `GET /v1/graph?path=`,
  `GET /v1/decisions`, `GET /v1/decisions/<id>`,
  `GET /v1/activity?actor=&limit=`, `GET /v1/lint`
- `POST /v1/proposals` — staging only, never a canonical write
- `GET /v1/proposals/<id>` — proposal status
- `POST /v1/proposals/<id>/promote` — promotion (see choice below)

**Localhost-only proof:** `make_server()` accepts only `127.0.0.1`,
`::1`, `localhost` (plus any other loopback address the `ipaddress`
module reports as loopback); any other host — `0.0.0.0`, a LAN
address, a public IP, a hostname — raises `ValueError` at startup.
There is no code path in this build that binds a public interface
and no Azure/DNS/hosting configuration anywhere in it. The manual
CLI (`python3 -m gateway.http_server`) defaults to `127.0.0.1:8765`;
tests use ephemeral localhost ports (port 0) and close the server
in teardown. The shim was never started as a service in this build.

**Promote-over-HTTP choice — EXPOSED through the shared code path.**
`POST /v1/proposals/<id>/promote` calls `wiki_promote_proposal`
through `Gateway._call_tool`, which is the exact same
`store.promote()` the stdio server uses: publish scope, review
manifest SHA-256 match, owner authorisation record with plan-hash
binding, G5 targets additionally requiring the Owner decision
reference; a staged file altered after review is quarantined, never
promoted. No second promotion implementation was written. (One
behaviour to note, inherited from stdio, not invented here: a
caller without publish scope gets the uniform no-leak denial —
HTTP 404 `not found or not available` — while a publish-scoped
caller refused by the manifest/authorisation gates gets the
uniform HTTP 403 `promotion refused`.)

**Test results** (`python3 -m unittest discover -s tests` from
`tools/gateway/`): **103 tests, all passing** — 91 pre-existing +
12 new HTTP tests. The new tests prove: loopback-only binding
(default host, accepted/refused hosts, live bind address);
no-token / forged-token / revoked-token denied + ledgered, rotation
kills the old token over HTTP; scoped reads over HTTP with the
byte-identical no-leak payloads for out-of-scope, missing, and
out-of-scope-decision objects; search ledger entries carry
`query_hash` + `query_length` and no query text (raw ledger bytes
checked); staging-only writes (canonical file absent after staging;
no canonical-write route — `POST` to a read route is 405 and the
target file is untouched); the promote ladder (no publish scope →
denied; no review manifest → refused; reviewed but not authorised
→ refused; authorised → promoted, file lands, commit SHA equals
git HEAD, exactly one allow-entry in the ledger); tamper →
quarantined, never promoted; and one Black Box entry per request
across a six-request batch (allow, auth-denied, search, unknown
route, malformed JSON, missing parameter) with the chain verifying
afterwards.

**Record page:** `wiki/syntheses/hosted-gateway-door-2026-11-08.md`
(design sources, gates passing, what is NOT built/deployed/
activated, remaining owner decisions, unified-memory Stage 6
overlap note).

**Recorded gaps (not silent redesigns):**

- **Versioned-path scheme:** no scheme for the *gateway tools* is
  specified anywhere in the design. The unified-memory plan's
  Round 6 sketch names Mem0-shaped paths (`GET /v3/memories` …)
  for the *memory API*, not for gateway tools, and those memory
  routes are NOT built here — they belong to that programme's
  Round 6 over its own API module. This door adopts `/v1/` as the
  first versioned gateway-tool surface.
- **Default port:** no port is specified by the design; the manual
  CLI's `8765` is a local convention recorded in `http_server.py`,
  not an approved public port.
- **Not built:** the Mem0-shaped memory routes, `POST
  /v1/chat/completions`, the `GET /v1/events/` feed, webhooks, and
  any dashboard/Lens view — all Round 6 items of the
  unified-memory programme, none of them part of this item.
  This build realises the Round 6 sketch's shim under this item's
  approval; Stage 6 must reuse it, not duplicate it.
- **HTTP surface is the 13 design tools' read/write subset only:**
  `handoff_create`, `list_proposals`, `reject_proposal`, the
  Round 1 listings and the context card are NOT exposed over HTTP
  — the task's route list covers the §4.6 read tools plus
  stage/status/promote, and nothing beyond it was added.

## Owner gate decisions still required before real activation (restated)

Gates 1–7 above, unchanged: (1) initial identity/scope table;
(2) token-provisioning ceremony + secret location; (3) watcher
installation; (4) gateway transport + Azure hosting shape — this
build supplies the HTTP transport *implementation* only, the
hosting decision is still the owner's; (5) ledger + staging
relocation; (6) which harnesses are onboarded first; (7)
git-commit-on-promotion. Until gates 1–2 are decided, the correct
operating state remains the one verified above: **the gateway
runs, everything is denied, and every denial is recorded.**
