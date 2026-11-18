# WikiCitadel Gateway — core (pre-activation)

MCP gateway + Black Box for a WikiCitadel wiki, implementing the
gateway design (access flow, scopes, the Black Box ledger). See
**BUILD-RECORD.md** for what works, test results, and the owner gate
decisions required before activation. No real tokens exist; the
watcher is a standalone script, not an installed service.

```bash
cd tools/gateway
python3 -m unittest discover -s tests        # 103 tests, fixtures only
python3 -m gateway serve                     # MCP server on stdio
python3 -m gateway.http_server               # HTTP door on localhost only (not activated)
python3 -m gateway verify                    # verify the Black Box chain
python3 -m gateway anchor                    # record chain head for git
python3 -m gateway metrics                   # consultation report (§6)
python3 watcher/watcher.py --root <tree> --state-dir <dir> --once
```

The HTTP door (`gateway/http_server.py`, built 2026-11-08 — see
**BUILD-RECORD.md** and `wiki/syntheses/hosted-gateway-door-2026-11-08.md`)
is a thin stdlib-only shim over the stdio server: same token registry,
same scopes, same staged-proposal gate, same Black Box ledger. It binds
**127.0.0.1 only** (any non-loopback bind is refused at startup), takes
`Authorization: Bearer <token>` per request, and serves versioned
`/v1/` JSON routes — reads first (`whoami`, `search`, `pages`,
`sources`, `graph`, `decisions`, `activity`, `lint`), staging at
`POST /v1/proposals`, promotion at `POST /v1/proposals/<id>/promote`
through the exact same `store.promote()` path stdio uses. It is a
module + tests: **not activated** — no real tokens, no service, no
hosting, no public port. Run it manually only against fixture state
(`GATEWAY_*` env vars, default port 8765, localhost only).

Configuration is via `GATEWAY_WIKI_ROOT`, `GATEWAY_STATE_DIR`,
`GATEWAY_REGISTRY`, `GATEWAY_LEDGER_DIR`, `GATEWAY_STAGING_DIR`,
`GATEWAY_GIT_COMMIT` (see `gateway/config.py`). All state defaults to
`~/.local/state/wikicitadel-gateway/` — outside git, always.
