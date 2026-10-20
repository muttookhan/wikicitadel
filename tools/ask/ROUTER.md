# Model routing lane — `tools/ask/router.py`

15-gap item 7: multi-provider / local-model routing with cost +
cache, for the Ask door. Built 2026-10-20 as an **additive**
module: nothing in the current pickup flow imports it, existing
Ask behaviour is unchanged, and it becomes live only when a caller
invokes it explicitly.

## Design

The router **decides and records; it never calls a model.** There
are no network calls, no HTTP client, no environment-variable
reads, and no API keys anywhere in the module — a registry entry
carrying a credential-like key (`api_key`, `secret`, `token`, …)
is a validation error, because the router stores no credentials.
Actual model invocation stays with the existing code that already
does it.

Four parts, all stdlib-only:

1. **Provider registry** — providers are data, loaded from a JSON
   config file (`load_registry(path)`), or the safe default when
   no file is given. A missing file or malformed JSON is an
   explicit error, never a silent fall-back.
2. **Routing** — `route(task_class, constraints, providers)`
   returns a decision dict with the chosen provider, the cost
   basis, human-readable `reasons`, per-provider `rejected`
   reasons, and the other eligible providers as `alternatives`.
3. **Response cache** — `ResponseCache`, content-addressed
   (sha256 of the normalised prompt + provider name + model id),
   one JSON file per entry under a caller-supplied directory,
   with a per-instance TTL and hit / miss / write / expiry
   accounting.
4. **Cost ledger** — `CostLedger`, append-only JSONL. Token
   counts are required arguments supplied by the caller (never
   invented, never estimated); each entry records provider,
   model, tokens, rates, computed cost, and cache hit/miss.
   `totals()` aggregates overall and per provider, and counts
   malformed lines instead of dropping them silently.

### Routing rule (deterministic, fail closed)

Eligibility, in order: provider enabled → supports the task class
(`answer` / `extract` / `summarise`; anything else is an
`unknown_task_class` error) → `local_only` (kind must be `local`)
→ latency budget (the constraint names the *slowest* acceptable
class: `fast` ⊂ `standard` ⊂ `slow`) → cost caps
(`max_cost_per_1k` on the blended per-1k rate; `max_cost` on the
estimated total, which requires both token estimates — a cap
without estimates is an `invalid_constraints` error).

Among eligible providers the order is total: lowest cost basis
(the estimated cost when the caller supplies token estimates,
else the blended per-1k rate = input + output rate), then fastest
latency class, then provider name. Registry order in the config
file therefore never affects the outcome. If no provider is
eligible the result is `ok: false, code: no_eligible_provider`
with every rejection reasoned — never a silent default to an
expensive, disabled, or non-local provider.

Costs are rounded to 10 decimal places at computation so ledger
arithmetic carries no binary float dust. A cache hit records
`cost: 0.0` (no invocation happened) plus `cost_if_uncached`, so
the saving is on the record.

### The safe default

With no config, the default registry is two placeholders: a
**local** placeholder (zero placeholder rates) enabled for
`extract` / `summarise` only, and a **remote** placeholder that
ships **disabled**. Routing an `answer` against the default
therefore fails closed with `no_eligible_provider` until an
operator writes a real config — the default can never quietly
send work to an unconfigured remote model.

## Config format

```json
{
  "providers": [
    {
      "name": "local-small",
      "kind": "local",
      "model": "<model id as the operator's runtime names it>",
      "cost_per_1k_input": 0.0,
      "cost_per_1k_output": 0.0,
      "enabled": true,
      "latency_class": "fast",
      "task_classes": ["extract", "summarise"]
    },
    {
      "name": "remote-main",
      "kind": "remote",
      "model": "<model id>",
      "cost_per_1k_input": 0.0,
      "cost_per_1k_output": 0.0,
      "enabled": false,
      "latency_class": "standard",
      "task_classes": ["answer", "extract", "summarise"]
    }
  ]
}
```

Rules: a bare list is accepted in place of the object; `name`
values are unique; `kind` is `local` or `remote`; both cost
fields are required, finite numbers ≥ 0; `enabled` defaults to
true; `latency_class` defaults to `standard`; `task_classes`
absent means all three known classes; unknown keys are errors
(a typo must surface). Rates are the operator's own data, in
whatever currency unit the operator accounts in — this repo
ships no real provider names, model ids, or prices.

Intended wiring (via the `Router` bundle class): route a task →
check the cache for the routed provider → on a miss, invoke the
model through the existing invocation code → store the response
in the cache → record usage in the ledger with the token counts
the invocation actually reported.

Note: cache entries hold the normalised prompt and the response
in plaintext JSON under the caller's chosen directory. Choosing
where that directory lives (and its retention) is the caller's
decision.

## Honest remainder

- **No live provider calls are wired.** The router is not
  imported by `pickup.py` or any other Ask module; no question
  is routed, cached, or ledgered in production yet.
- Wiring it into the pickup is a **follow-up behind the
  regression gate**: per AGENTS.md, any change to model routing
  re-runs the abstention battery
  (`scripts/wiki_abstention_check.py`) and the conflict slice
  (`scripts/wiki_conflict_score.py`) before integration. At this
  build the battery stands at 12/12 PASS and the full
  `tools/ask` suite is green with the new tests included
  (counts in the build report).
- No provider config file ships with the repo: the first real
  config (real model ids and the operator's real rates) is an
  operator act, recorded when it happens.
- Cache accounting is per process instance (in memory); the
  ledger is the durable record. Cache eviction beyond TTL
  (size caps, LRU) is not implemented — TTL only.
