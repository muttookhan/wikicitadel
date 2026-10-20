# WikiCitadel Gateway — core (pre-activation)

MCP gateway + Black Box for a WikiCitadel wiki, implementing the
gateway design (access flow, scopes, the Black Box ledger). See
**BUILD-RECORD.md** for what works, test results, and the owner gate
decisions required before activation. No real tokens exist; the
watcher is a standalone script, not an installed service.

```bash
cd tools/gateway
python3 -m unittest discover -s tests        # 13 tests, fixtures only
python3 -m gateway serve                     # MCP server on stdio
python3 -m gateway verify                    # verify the Black Box chain
python3 -m gateway anchor                    # record chain head for git
python3 -m gateway metrics                   # consultation report (§6)
python3 watcher/watcher.py --root <tree> --state-dir <dir> --once
```

Configuration is via `GATEWAY_WIKI_ROOT`, `GATEWAY_STATE_DIR`,
`GATEWAY_REGISTRY`, `GATEWAY_LEDGER_DIR`, `GATEWAY_STAGING_DIR`,
`GATEWAY_GIT_COMMIT` (see `gateway/config.py`). All state defaults to
`~/.local/state/wikicitadel-gateway/` — outside git, always.
