#!/usr/bin/env python3
"""Multi-provider model routing for the Ask door (15-gap item 7,
2026-10-20).

An ADDITIVE layer beside the existing Ask modules. Nothing in the
current pickup flow imports this module, and importing it changes
no existing behaviour: it becomes live only when a caller invokes
it explicitly. Wiring it into the pickup is a separate, later act
behind the abstention + conflict regression gate (see AGENTS.md,
"Abstention and conflict regression gate", and ROUTER.md beside
this file).

What this module does — decisions and records, never calls:

(a) **Provider registry.** A provider is DATA: ``name``, ``kind``
    (``local`` / ``remote``), ``model`` (the model id, as a
    string), ``cost_per_1k_input`` / ``cost_per_1k_output``
    (numbers, in the operator's currency unit), ``enabled``, an
    optional ``latency_class`` (``fast`` / ``standard`` / ``slow``,
    default ``standard``) and an optional ``task_classes`` list
    (absent = supports every known task class). Registries load
    from a JSON config file via :func:`load_registry`; with no
    file, :data:`DEFAULT_PROVIDERS` applies — a safe default in
    which the only enabled provider is a local placeholder for
    cheap mechanical tasks and the remote placeholder ships
    DISABLED, so an ``answer`` route on the default registry fails
    closed until an operator writes a real config.

(b) **Routing.** :func:`route` picks a provider for a task class
    deterministically: eligibility first (enabled, supports the
    task class, ``local_only``, latency budget, cost caps), then a
    total order — lowest cost basis, then fastest latency class,
    then name — so the same inputs always give the same provider,
    with the reasons stated in the result. The cost basis is the
    estimated cost when the caller supplies token estimates, else
    the blended per-1k rate (input rate + output rate). Fail
    closed: an unknown task class, malformed constraints, or no
    eligible provider returns an explicit error result
    (``ok`` false, a stable ``code``, ``provider`` None) — never a
    silent fall-back to an expensive or disabled provider.

(c) **Response cache.** :class:`ResponseCache` is a
    content-addressed on-disk cache under a caller-supplied
    directory: the key is the sha256 of the normalised prompt
    (Unicode NFC, whitespace runs collapsed, stripped) together
    with the provider name and model id. Entries carry a TTL;
    hits, misses, writes and expiries are counted per instance.

(d) **Cost ledger.** :class:`CostLedger` is an append-only JSONL
    ledger. Each entry records the provider, the model, the token
    counts EXACTLY as the caller supplies them (both counts are
    required arguments — this module never invents a token count),
    the rates, the computed cost, and whether the response was a
    cache hit. A cache hit costs 0.0 by definition (no invocation
    happened); the entry also carries ``cost_if_uncached`` so the
    saving is on the record.

(e) **No network, no credentials.** This module opens no sockets,
    imports no HTTP client, and reads no environment variables.
    A registry entry carrying a credential-like key (``api_key``
    and friends) is a validation ERROR: the router stores no
    secrets. Actual model invocation stays with the existing code
    that already does it; this layer only decides and records.

Costs are rounded to 10 decimal places at computation time — far
below any real per-token price — so ledger arithmetic does not
accumulate binary float dust (0.1 + 0.2 style artefacts).

Pure stdlib; importable without network access.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: The task classes the router knows. Anything else fails closed.
TASK_CLASSES = ("answer", "extract", "summarise")

#: Provider kinds.
PROVIDER_KINDS = ("local", "remote")

#: Latency classes, fastest first; the rank is the sort/comparison
#: key. A routing constraint names the SLOWEST acceptable class:
#: asking for "fast" admits only fast providers, "standard" admits
#: fast and standard, "slow" admits all.
LATENCY_CLASSES = ("fast", "standard", "slow")
LATENCY_RANK = {name: rank for rank, name in enumerate(LATENCY_CLASSES)}
DEFAULT_LATENCY_CLASS = "standard"

#: Keys a provider entry may carry. Anything else is a validation
#: error — a typo in a config file must surface, not be ignored.
PROVIDER_KEYS = frozenset({
    "name", "kind", "model",
    "cost_per_1k_input", "cost_per_1k_output",
    "enabled", "latency_class", "task_classes",
})

#: Substrings that mark a key as credential-like. A provider entry
#: carrying one is refused outright (see module docstring, (e)).
_CREDENTIAL_KEY_PARTS = (
    "api_key", "apikey", "api-key", "secret", "password",
    "passwd", "token", "credential", "auth",
)

#: Keys a constraints dict may carry (see route()).
CONSTRAINT_KEYS = frozenset({
    "local_only", "latency_class", "max_cost", "max_cost_per_1k",
    "estimated_input_tokens", "estimated_output_tokens",
})

#: Default cache TTL: one day. Callers pass their own to the
#: ResponseCache constructor; None means entries never expire.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

#: Decimal places costs are rounded to (see module docstring).
COST_ROUND = 10


class RouterError(ValueError):
    """A registry, cache or ledger input this module refuses.

    Raised for load-time and record-time validation failures.
    route() itself does not raise for routing failures — it
    returns an explicit error result (fail closed, see route()).
    """


# ---------------------------------------------------------------------------
# (a) Provider registry
# ---------------------------------------------------------------------------

#: The safe default registry (see module docstring). Placeholder
#: model ids and zero placeholder rates: the local placeholder is
#: enabled for the mechanical task classes only; the remote
#: placeholder ships disabled, so routing an "answer" against the
#: default registry is an explicit error, not a silent call.
DEFAULT_PROVIDERS = [
    {
        "name": "local-placeholder",
        "kind": "local",
        "model": "local/unconfigured",
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "enabled": True,
        "latency_class": "standard",
        "task_classes": ["extract", "summarise"],
    },
    {
        "name": "remote-placeholder",
        "kind": "remote",
        "model": "remote/unconfigured",
        "cost_per_1k_input": 0.0,
        "cost_per_1k_output": 0.0,
        "enabled": False,
        "latency_class": "fast",
        "task_classes": ["answer", "extract", "summarise"],
    },
]


def _is_number(value) -> bool:
    """True for a real int/float (bools are not numbers here)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_cost(value, label, errors):
    """Validate one cost field; append to *errors*, return float."""
    if not _is_number(value):
        errors.append("%s must be a number" % label)
        return 0.0
    value = float(value)
    if not math.isfinite(value):
        errors.append("%s must be finite" % label)
        return 0.0
    if value < 0:
        errors.append("%s must be >= 0" % label)
        return 0.0
    return value


def validate_registry(raw) -> list:
    """Validation errors for a raw registry value; [] means valid.

    *raw* is the parsed JSON form: either a bare list of provider
    entries or an object with a ``providers`` list. The per-entry
    rules are stated in the module docstring and in ROUTER.md.
    """
    if isinstance(raw, dict):
        if "providers" not in raw:
            return ["registry object must carry a 'providers' list"]
        entries = raw["providers"]
    elif isinstance(raw, list):
        entries = raw
    else:
        return ["registry must be a list of providers or an object "
                "with a 'providers' list"]
    if not isinstance(entries, list):
        return ["'providers' must be a list"]

    errors = []
    seen_names = set()
    for index, entry in enumerate(entries):
        label = "providers[%d]" % index
        if not isinstance(entry, dict):
            errors.append("%s must be an object" % label)
            continue
        for key in sorted(entry):
            lowered = str(key).lower()
            if any(part in lowered for part in _CREDENTIAL_KEY_PARTS):
                errors.append(
                    "%s: credential-like key %r is not allowed — "
                    "the router stores no credentials" % (label, key))
            elif key not in PROVIDER_KEYS:
                errors.append("%s: unknown key %r" % (label, key))
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append("%s: 'name' must be a non-empty string" % label)
        elif name.strip() in seen_names:
            errors.append(
                "%s: duplicate provider name %r" % (label, name.strip()))
        else:
            seen_names.add(name.strip())
            label = "provider %r" % name.strip()
        if entry.get("kind") not in PROVIDER_KINDS:
            errors.append(
                "%s: 'kind' must be one of %s"
                % (label, ", ".join(PROVIDER_KINDS)))
        model = entry.get("model")
        if not isinstance(model, str) or not model.strip():
            errors.append("%s: 'model' must be a non-empty string" % label)
        for field in ("cost_per_1k_input", "cost_per_1k_output"):
            if field not in entry:
                errors.append("%s: %r is required" % (label, field))
            else:
                _check_cost(entry[field], "%s: %r" % (label, field), errors)
        if "enabled" in entry and not isinstance(entry["enabled"], bool):
            errors.append("%s: 'enabled' must be a boolean" % label)
        latency = entry.get("latency_class", DEFAULT_LATENCY_CLASS)
        if latency not in LATENCY_CLASSES:
            errors.append(
                "%s: 'latency_class' must be one of %s"
                % (label, ", ".join(LATENCY_CLASSES)))
        if "task_classes" in entry:
            tasks = entry["task_classes"]
            if not isinstance(tasks, list) or not tasks:
                errors.append(
                    "%s: 'task_classes' must be a non-empty list" % label)
            else:
                for task in tasks:
                    if task not in TASK_CLASSES:
                        errors.append(
                            "%s: unknown task class %r in "
                            "'task_classes' (known: %s)"
                            % (label, task, ", ".join(TASK_CLASSES)))
                if len(set(tasks)) != len(tasks):
                    errors.append(
                        "%s: 'task_classes' contains duplicates" % label)
    return errors


def _normalise_provider(entry: dict) -> dict:
    """One validated raw entry -> the normalised provider dict."""
    tasks = entry.get("task_classes")
    if tasks is None:
        ordered_tasks = list(TASK_CLASSES)
    else:
        ordered_tasks = [t for t in TASK_CLASSES if t in tasks]
    return {
        "name": entry["name"].strip(),
        "kind": entry["kind"],
        "model": entry["model"].strip(),
        "cost_per_1k_input": float(entry["cost_per_1k_input"]),
        "cost_per_1k_output": float(entry["cost_per_1k_output"]),
        "enabled": bool(entry.get("enabled", True)),
        "latency_class": entry.get("latency_class", DEFAULT_LATENCY_CLASS),
        "task_classes": ordered_tasks,
    }


def normalise_registry(raw) -> list:
    """Normalised provider list for a valid raw registry.

    Raises RouterError listing every validation error when *raw*
    is invalid (the validate_registry list, joined).
    """
    errors = validate_registry(raw)
    if errors:
        raise RouterError("invalid provider registry: " + "; ".join(errors))
    entries = raw["providers"] if isinstance(raw, dict) else raw
    return [_normalise_provider(entry) for entry in entries]


def load_registry(source=None) -> list:
    """Load a provider registry: normalised provider dicts.

    *source* may be:

    - None — the safe default (:data:`DEFAULT_PROVIDERS`);
    - a path (str / Path) to a JSON config file — a missing file
      or malformed JSON raises RouterError, never a silent
      fall-back to the default;
    - an already-parsed dict (``{"providers": [...]}``) or list.

    Raises RouterError on any validation error.
    """
    if source is None:
        return normalise_registry(DEFAULT_PROVIDERS)
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise RouterError("registry config file not found: %s" % path)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RouterError(
                "registry config %s is not valid JSON: %s" % (path, exc))
        return normalise_registry(raw)
    if isinstance(source, (dict, list)):
        return normalise_registry(source)
    raise RouterError(
        "registry source must be None, a path, a dict or a list, "
        "not %s" % type(source).__name__)


def provider_by_name(providers, name):
    """The normalised provider dict named *name*, or None."""
    for provider in providers or []:
        if provider.get("name") == name:
            return provider
    return None


# ---------------------------------------------------------------------------
# Cost computation
# ---------------------------------------------------------------------------

def _check_tokens(value, label):
    """Validate one caller-supplied token count; return it as int.

    Token counts come from the caller or not at all: bools,
    non-integers and negatives are refused, and no caller of this
    helper gets a default substituted.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise RouterError("%s must be an integer token count" % label)
    if value < 0:
        raise RouterError("%s must be >= 0" % label)
    return value


def compute_cost(provider, input_tokens, output_tokens) -> float:
    """The exact cost of one call at *provider*'s stated rates.

    (input_tokens / 1000) * cost_per_1k_input +
    (output_tokens / 1000) * cost_per_1k_output, rounded to
    COST_ROUND decimal places. Both token counts are required —
    they are the caller's numbers, never estimated here.
    """
    input_tokens = _check_tokens(input_tokens, "input_tokens")
    output_tokens = _check_tokens(output_tokens, "output_tokens")
    cost = (
        (input_tokens / 1000.0) * float(provider["cost_per_1k_input"])
        + (output_tokens / 1000.0) * float(provider["cost_per_1k_output"])
    )
    return round(cost, COST_ROUND)


def blended_per_1k(provider) -> float:
    """A provider's blended per-1k rate: input rate + output rate.

    The cost basis route() compares when the caller supplies no
    token estimates (1k tokens in plus 1k tokens out).
    """
    return round(
        float(provider["cost_per_1k_input"])
        + float(provider["cost_per_1k_output"]),
        COST_ROUND,
    )


# ---------------------------------------------------------------------------
# (b) Routing
# ---------------------------------------------------------------------------

def _route_error(code, message, task_class, rejected=None, reasons=None):
    """A fail-closed routing result: explicit, provider-free."""
    return {
        "ok": False,
        "code": code,
        "error": message,
        "task_class": task_class,
        "provider": None,
        "provider_name": None,
        "model": None,
        "kind": None,
        "estimated_cost": None,
        "cost_basis": None,
        "reasons": list(reasons or []),
        "rejected": list(rejected or []),
        "alternatives": [],
    }


def _validate_constraints(constraints):
    """(clean constraints dict, error message or None)."""
    if constraints is None:
        return {}, None
    if not isinstance(constraints, dict):
        return None, "constraints must be an object"
    unknown = sorted(set(constraints) - CONSTRAINT_KEYS)
    if unknown:
        return None, ("unknown constraint(s): %s (known: %s)"
                      % (", ".join(unknown),
                         ", ".join(sorted(CONSTRAINT_KEYS))))
    clean = {}
    if "local_only" in constraints:
        if not isinstance(constraints["local_only"], bool):
            return None, "'local_only' must be a boolean"
        clean["local_only"] = constraints["local_only"]
    if "latency_class" in constraints:
        if constraints["latency_class"] not in LATENCY_CLASSES:
            return None, ("'latency_class' must be one of %s"
                          % ", ".join(LATENCY_CLASSES))
        clean["latency_class"] = constraints["latency_class"]
    for field in ("max_cost", "max_cost_per_1k"):
        if field in constraints:
            value = constraints[field]
            if not _is_number(value) or not math.isfinite(float(value)) \
                    or float(value) < 0:
                return None, "%r must be a finite number >= 0" % field
            clean[field] = float(value)
    for field in ("estimated_input_tokens", "estimated_output_tokens"):
        if field in constraints:
            try:
                clean[field] = _check_tokens(constraints[field], field)
            except RouterError as exc:
                return None, str(exc)
    if "max_cost" in clean and not (
            "estimated_input_tokens" in clean
            and "estimated_output_tokens" in clean):
        return None, ("'max_cost' requires both "
                      "'estimated_input_tokens' and "
                      "'estimated_output_tokens' — a cost cap cannot "
                      "be checked without the caller's token estimates")
    return clean, None


def route(task_class, constraints=None, providers=None) -> dict:
    """Pick a provider for *task_class*, deterministically.

    *providers* is a normalised registry (see load_registry);
    None means the safe default registry. *constraints* may carry
    ``local_only`` (bool), ``latency_class`` (slowest acceptable),
    ``max_cost_per_1k`` (cap on the blended per-1k rate),
    ``max_cost`` (cap on the estimated total; requires both token
    estimates) and ``estimated_input_tokens`` /
    ``estimated_output_tokens``.

    Success result::

        {"ok": True, "code": "ok", "error": None,
         "task_class": ..., "provider": {normalised provider},
         "provider_name": ..., "model": ..., "kind": ...,
         "estimated_cost": float or None (None = no estimates
         supplied), "cost_basis": "estimated_tokens" |
         "per_1k_blended", "reasons": [str, ...],
         "rejected": [{"provider": name, "reason": str}, ...],
         "alternatives": [names of the other eligible providers,
         in rank order]}

    Failure is an explicit result with the same keys, ``ok``
    false, a stable ``code`` (``unknown_task_class`` /
    ``invalid_constraints`` / ``invalid_registry`` /
    ``no_eligible_provider``) and ``provider`` None. Selection
    order among eligible providers is a total order — cost basis,
    then latency rank, then name — so registry order in the
    config file never affects the outcome.
    """
    if providers is None:
        registry = load_registry(None)
    else:
        try:
            registry = normalise_registry(providers)
        except RouterError as exc:
            return _route_error(
                "invalid_registry", str(exc), task_class)

    if not isinstance(task_class, str) \
            or task_class.strip() not in TASK_CLASSES:
        return _route_error(
            "unknown_task_class",
            "unknown task class %r (known: %s)"
            % (task_class, ", ".join(TASK_CLASSES)),
            task_class,
            reasons=["task class is not one of the known classes; "
                     "failing closed rather than guessing a route"])
    task = task_class.strip()

    clean, problem = _validate_constraints(constraints)
    if problem is not None:
        return _route_error(
            "invalid_constraints", problem, task,
            reasons=["constraints failed validation; failing closed"])

    have_estimates = "estimated_input_tokens" in clean
    rejected = []
    eligible = []  # (cost_basis_value, latency_rank, name, provider, est)
    for provider in sorted(registry, key=lambda p: p["name"]):
        name = provider["name"]
        if not provider["enabled"]:
            rejected.append({"provider": name, "reason": "disabled"})
            continue
        if task not in provider["task_classes"]:
            rejected.append({
                "provider": name,
                "reason": "does not support task class %r" % task})
            continue
        if clean.get("local_only") and provider["kind"] != "local":
            rejected.append({
                "provider": name,
                "reason": "kind %r excluded by local_only"
                          % provider["kind"]})
            continue
        if "latency_class" in clean and LATENCY_RANK[
                provider["latency_class"]] > LATENCY_RANK[
                clean["latency_class"]]:
            rejected.append({
                "provider": name,
                "reason": "latency class %r exceeds the requested %r"
                          % (provider["latency_class"],
                             clean["latency_class"])})
            continue
        blended = blended_per_1k(provider)
        if "max_cost_per_1k" in clean and blended > clean["max_cost_per_1k"]:
            rejected.append({
                "provider": name,
                "reason": "blended per-1k cost %.4f exceeds "
                          "max_cost_per_1k %.4f"
                          % (blended, clean["max_cost_per_1k"])})
            continue
        estimated = None
        if have_estimates:
            estimated = compute_cost(
                provider,
                clean["estimated_input_tokens"],
                clean["estimated_output_tokens"])
            if "max_cost" in clean and estimated > clean["max_cost"]:
                rejected.append({
                    "provider": name,
                    "reason": "estimated cost %.4f exceeds max_cost %.4f"
                              % (estimated, clean["max_cost"])})
                continue
        basis = estimated if have_estimates else blended
        eligible.append((basis, LATENCY_RANK[provider["latency_class"]],
                         name, provider, estimated))

    if not eligible:
        return _route_error(
            "no_eligible_provider",
            "no eligible provider for task class %r under the "
            "given constraints" % task,
            task,
            rejected=rejected,
            reasons=["every provider was rejected (see 'rejected'); "
                     "failing closed rather than defaulting to an "
                     "ineligible provider"])

    eligible.sort(key=lambda item: (item[0], item[1], item[2]))
    basis, _rank, name, provider, estimated = eligible[0]
    basis_label = ("estimated_tokens" if have_estimates
                   else "per_1k_blended")
    reasons = [
        "%d of %d provider(s) eligible for task class %r"
        % (len(eligible), len(registry), task),
        "selected %r: lowest %s cost (%s) among eligible providers"
        % (name, basis_label,
           ("%.4f" % basis) if basis is not None else "n/a"),
        "deterministic order: cost basis, then latency class, "
        "then provider name",
    ]
    if clean.get("local_only"):
        reasons.append(
            "local_only honoured: only kind 'local' providers "
            "were eligible")
    if "latency_class" in clean:
        reasons.append(
            "latency budget %r honoured (provider is %r)"
            % (clean["latency_class"], provider["latency_class"]))
    if "max_cost" in clean:
        reasons.append(
            "estimated cost %.4f within max_cost %.4f"
            % (estimated, clean["max_cost"]))
    if "max_cost_per_1k" in clean:
        reasons.append(
            "blended per-1k cost %.4f within max_cost_per_1k %.4f"
            % (blended_per_1k(provider), clean["max_cost_per_1k"]))
    return {
        "ok": True,
        "code": "ok",
        "error": None,
        "task_class": task,
        "provider": provider,
        "provider_name": provider["name"],
        "model": provider["model"],
        "kind": provider["kind"],
        "estimated_cost": estimated,
        "cost_basis": basis_label,
        "reasons": reasons,
        "rejected": rejected,
        "alternatives": [item[2] for item in eligible[1:]],
    }


# ---------------------------------------------------------------------------
# (c) Response cache
# ---------------------------------------------------------------------------

def normalise_prompt(prompt) -> str:
    """The cache's prompt normal form.

    Unicode NFC, every whitespace run collapsed to one space,
    stripped. Case is preserved: prompts that differ in case are
    different prompts.
    """
    text = unicodedata.normalize("NFC", str(prompt))
    return " ".join(text.split())


def cache_key(prompt, provider, model=None) -> str:
    """The content address of one (prompt, provider, model) triple.

    sha256 hex of the JSON list [normalised prompt, provider name,
    model id]. *provider* may be a provider dict or a bare name;
    *model* defaults to the dict's model (a bare name without an
    explicit model is a RouterError — the model is part of the
    address, so it is never guessed).
    """
    if isinstance(provider, dict):
        name = provider.get("name")
        if model is None:
            model = provider.get("model")
    else:
        name = provider
    if not isinstance(name, str) or not name.strip():
        raise RouterError("cache key needs a provider name")
    if not isinstance(model, str) or not model.strip():
        raise RouterError(
            "cache key needs a model id (pass the provider dict "
            "or an explicit model)")
    material = json.dumps(
        [normalise_prompt(prompt), name.strip(), model.strip()],
        ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class ResponseCache:
    """Content-addressed on-disk response cache.

    One JSON file per entry under *cache_dir* (created on first
    write), named by its cache key. An entry is::

        {"key", "provider", "model", "prompt" (normalised form),
         "created" (epoch float), "expires" (epoch float or
         None), "response" (any JSON value)}

    Accounting is per instance and in memory: ``hits``,
    ``misses``, ``writes``, ``expiries`` (an expired entry counts
    as a miss AND an expiry, and its file is removed). A corrupt
    or mismatched entry file counts as a miss and is removed, so
    a damaged cache heals instead of erroring every lookup. The
    cache directory holds prompts and responses in plaintext —
    choosing where it lives is the caller's decision.
    """

    def __init__(self, cache_dir, ttl_seconds=DEFAULT_TTL_SECONDS):
        if ttl_seconds is not None:
            if not _is_number(ttl_seconds) or float(ttl_seconds) < 0:
                raise RouterError(
                    "ttl_seconds must be a number >= 0 or None")
            ttl_seconds = float(ttl_seconds)
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.hits = 0
        self.misses = 0
        self.writes = 0
        self.expiries = 0

    def _path_for(self, key):
        return self.cache_dir / (key + ".json")

    def get(self, prompt, provider, model=None, now=None):
        """The cache entry for this triple, or None on a miss.

        *now* is an epoch float for tests/clock control; the wall
        clock is used when it is omitted.
        """
        key = cache_key(prompt, provider, model)
        now = time.time() if now is None else float(now)
        path = self._path_for(key)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            entry = None
        if not isinstance(entry, dict) or entry.get("key") != key:
            self.misses += 1
            self._remove(path)
            return None
        expires = entry.get("expires")
        if expires is not None and now >= float(expires):
            self.misses += 1
            self.expiries += 1
            self._remove(path)
            return None
        self.hits += 1
        return entry

    def get_response(self, prompt, provider, model=None, now=None):
        """The cached response value, or None on a miss.

        (A stored response of None is indistinguishable from a
        miss through this helper; use get() when that matters.)
        """
        entry = self.get(prompt, provider, model, now=now)
        return None if entry is None else entry.get("response")

    def put(self, prompt, provider, model=None, response=None, now=None):
        """Store *response* for this triple; returns the cache key.

        *response* must be JSON-serialisable — that is checked
        before anything is written. The write is atomic (temp file
        + os.replace) so a crashed writer never leaves a torn
        entry.
        """
        key = cache_key(prompt, provider, model)
        if isinstance(provider, dict):
            name = provider.get("name")
            model_id = model if model is not None else provider.get("model")
        else:
            name, model_id = provider, model
        now = time.time() if now is None else float(now)
        entry = {
            "key": key,
            "provider": name,
            "model": model_id,
            "prompt": normalise_prompt(prompt),
            "created": now,
            "expires": (None if self.ttl_seconds is None
                        else now + self.ttl_seconds),
            "response": response,
        }
        try:
            text = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise RouterError("response is not JSON-serialisable: %s" % exc)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self._path_for(key).with_suffix(".json.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self._path_for(key))
        self.writes += 1
        return key

    @staticmethod
    def _remove(path):
        try:
            path.unlink()
        except OSError:
            pass

    def stats(self) -> dict:
        """This instance's accounting counters."""
        lookups = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writes": self.writes,
            "expiries": self.expiries,
            "hit_rate": (self.hits / lookups) if lookups else 0.0,
        }


# ---------------------------------------------------------------------------
# (d) Cost ledger
# ---------------------------------------------------------------------------

def _iso_utc(epoch) -> str:
    """An ISO-8601 UTC timestamp for an epoch float."""
    return datetime.fromtimestamp(
        float(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")


class CostLedger:
    """Append-only JSONL cost ledger at *path*.

    record() appends exactly one line per call and never rewrites
    earlier lines; the parent directory is created on first use.
    Token counts are required arguments supplied by the caller —
    there is deliberately no default and no estimation here.
    """

    def __init__(self, path):
        self.path = Path(path)

    def record(self, provider, input_tokens, output_tokens,
               cache_hit=False, task_class=None, timestamp=None) -> dict:
        """Append one usage entry; returns the entry dict.

        *provider* is a normalised provider dict (its name, model
        and rates are what get recorded). On a cache hit the
        recorded ``cost`` is 0.0 — no invocation happened — and
        ``cost_if_uncached`` carries what the same tokens would
        have cost; on a miss the two are equal.
        """
        if not isinstance(provider, dict) \
                or not provider.get("name") or not provider.get("model"):
            raise RouterError(
                "ledger record needs a normalised provider dict "
                "(name + model + rates)")
        if not isinstance(cache_hit, bool):
            raise RouterError("'cache_hit' must be a boolean")
        if task_class is not None and task_class not in TASK_CLASSES:
            raise RouterError(
                "unknown task class %r (known: %s)"
                % (task_class, ", ".join(TASK_CLASSES)))
        uncached = compute_cost(provider, input_tokens, output_tokens)
        entry = {
            "ts": _iso_utc(time.time() if timestamp is None
                           else timestamp),
            "provider": provider["name"],
            "model": provider["model"],
            "task_class": task_class,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_per_1k_input": float(provider["cost_per_1k_input"]),
            "cost_per_1k_output": float(provider["cost_per_1k_output"]),
            "cost": 0.0 if cache_hit else uncached,
            "cost_if_uncached": uncached,
            "cache": "hit" if cache_hit else "miss",
            "cache_hit": cache_hit,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False,
                                    sort_keys=True) + "\n")
        return entry

    def totals(self) -> dict:
        """Aggregate this ledger: read_totals() over its path."""
        return read_totals(self.path)


def read_totals(path) -> dict:
    """Aggregate a cost-ledger JSONL file.

    Returns entry/token/cost totals overall and per provider,
    cache hit/miss counts, and a ``malformed`` count for lines
    that are not valid entry objects (surfaced, never silently
    dropped). A missing file aggregates to all zeros — the
    honest empty state.
    """
    totals = {
        "entries": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_cost": 0.0,
        "cost_if_uncached": 0.0,
        "cache_hits": 0,
        "cache_misses": 0,
        "malformed": 0,
        "by_provider": {},
    }
    path = Path(path)
    if not path.is_file():
        return totals
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            totals["malformed"] += 1
            continue
        if not isinstance(entry, dict) or "provider" not in entry:
            totals["malformed"] += 1
            continue
        totals["entries"] += 1
        totals["input_tokens"] += int(entry.get("input_tokens") or 0)
        totals["output_tokens"] += int(entry.get("output_tokens") or 0)
        totals["total_cost"] += float(entry.get("cost") or 0.0)
        totals["cost_if_uncached"] += float(
            entry.get("cost_if_uncached") or 0.0)
        if entry.get("cache_hit"):
            totals["cache_hits"] += 1
        else:
            totals["cache_misses"] += 1
        bucket = totals["by_provider"].setdefault(
            entry["provider"],
            {"entries": 0, "input_tokens": 0, "output_tokens": 0,
             "total_cost": 0.0})
        bucket["entries"] += 1
        bucket["input_tokens"] += int(entry.get("input_tokens") or 0)
        bucket["output_tokens"] += int(entry.get("output_tokens") or 0)
        bucket["total_cost"] += float(entry.get("cost") or 0.0)
    totals["total_cost"] = round(totals["total_cost"], COST_ROUND)
    totals["cost_if_uncached"] = round(
        totals["cost_if_uncached"], COST_ROUND)
    for bucket in totals["by_provider"].values():
        bucket["total_cost"] = round(bucket["total_cost"], COST_ROUND)
    return totals


# ---------------------------------------------------------------------------
# Convenience bundle
# ---------------------------------------------------------------------------

class Router:
    """A registry plus (optionally) a cache and a ledger.

    The intended wiring, when a caller adopts this layer: route a
    task, check the cache for the routed provider, invoke the
    model through the EXISTING invocation code only on a miss,
    store the response, and record usage. This class performs the
    routing, cache and ledger steps; the invocation step is the
    caller's and is deliberately not represented here.
    """

    def __init__(self, providers=None, cache=None, ledger=None):
        self.providers = load_registry(providers)
        self.cache = cache
        self.ledger = ledger

    @classmethod
    def from_config(cls, config_path, cache=None, ledger=None):
        """A Router whose registry loads from a JSON config file."""
        return cls(providers=load_registry(config_path),
                   cache=cache, ledger=ledger)

    def route(self, task_class, constraints=None) -> dict:
        """route() over this Router's registry."""
        return route(task_class, constraints=constraints,
                     providers=self.providers)

    def cache_lookup(self, decision, prompt, now=None):
        """The cache entry for a routing decision, or None.

        None also when no cache is configured or the decision is
        a routing failure (a failure has no provider to key on).
        """
        if self.cache is None or not decision.get("ok"):
            return None
        return self.cache.get(prompt, decision["provider"], now=now)

    def cache_store(self, decision, prompt, response, now=None):
        """Store a response under a routing decision; key or None."""
        if self.cache is None or not decision.get("ok"):
            return None
        return self.cache.put(prompt, decision["provider"],
                              response=response, now=now)

    def record_usage(self, decision, input_tokens, output_tokens,
                     cache_hit=False, timestamp=None) -> dict:
        """Ledger-record one usage against a routing decision.

        Raises RouterError when no ledger is configured or the
        decision is a routing failure (there is no provider to
        charge the usage to — recording it anyway would invent
        an attribution).
        """
        if self.ledger is None:
            raise RouterError("no cost ledger configured on this Router")
        if not decision.get("ok"):
            raise RouterError(
                "cannot record usage for a failed routing decision "
                "(%s)" % decision.get("code"))
        return self.ledger.record(
            decision["provider"], input_tokens, output_tokens,
            cache_hit=cache_hit, task_class=decision.get("task_class"),
            timestamp=timestamp)
