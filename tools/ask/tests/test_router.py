"""Tests for the multi-provider model routing lane (15-gap item 7).

Covers ``tools/ask/router.py``: registry load + validation,
deterministic routing per task class, the local-only / latency /
cost constraints, exact cost computation, the content-addressed
cache (hit / miss / TTL), the append-only cost ledger and its
totals, and the fail-closed cases. The router is additive: no
existing Ask module is imported here, and nothing here touches
the network.

Run from the repo root:
    python3 -m unittest discover -s tools/ask/tests -v
or directly:
    python3 tools/ask/tests/test_router.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import router  # noqa: E402


def provider(name, kind="remote", model=None, cin=0.0, cout=0.0,
             enabled=True, latency="standard", tasks=None):
    entry = {
        "name": name,
        "kind": kind,
        "model": model if model is not None else name + "-model",
        "cost_per_1k_input": cin,
        "cost_per_1k_output": cout,
        "enabled": enabled,
        "latency_class": latency,
    }
    if tasks is not None:
        entry["task_classes"] = tasks
    return entry


def fixture_registry():
    # alpha-local is the only local that answers; beta-local is
    # free but slow and mechanical-only; gamma-remote is the
    # cheapest all-round remote; delta-remote is disabled.
    return [
        provider("alpha-local", kind="local", cin=0.50, cout=0.50,
                 latency="fast"),
        provider("beta-local", kind="local", cin=0.0, cout=0.0,
                 latency="slow", tasks=["extract", "summarise"]),
        provider("gamma-remote", kind="remote", cin=0.10, cout=0.20,
                 latency="standard"),
        provider("delta-remote", kind="remote", cin=0.0, cout=0.0,
                 enabled=False, latency="fast"),
    ]


class TestRegistryLoad(unittest.TestCase):
    def test_default_registry_is_the_safe_default(self):
        registry = router.load_registry(None)
        by_name = {p["name"]: p for p in registry}
        self.assertIn("local-placeholder", by_name)
        self.assertTrue(by_name["local-placeholder"]["enabled"])
        self.assertEqual(by_name["local-placeholder"]["kind"], "local")
        # The remote placeholder ships disabled, and the local
        # placeholder does not claim the answer task class.
        self.assertFalse(by_name["remote-placeholder"]["enabled"])
        self.assertNotIn(
            "answer", by_name["local-placeholder"]["task_classes"])

    def test_load_from_json_file_and_normalisation(self):
        raw = {"providers": [{
            "name": "  solo  ", "kind": "local", "model": "m1",
            "cost_per_1k_input": 1, "cost_per_1k_output": 2,
        }]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "providers.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            registry = router.load_registry(path)
        self.assertEqual(len(registry), 1)
        solo = registry[0]
        self.assertEqual(solo["name"], "solo")
        self.assertEqual(solo["cost_per_1k_input"], 1.0)
        self.assertTrue(solo["enabled"])  # default
        self.assertEqual(solo["latency_class"], "standard")  # default
        self.assertEqual(solo["task_classes"],
                         list(router.TASK_CLASSES))  # default: all

    def test_bare_list_config_accepted(self):
        registry = router.load_registry([provider("one")])
        self.assertEqual([p["name"] for p in registry], ["one"])

    def test_missing_file_raises_not_silent_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(router.RouterError):
                router.load_registry(Path(tmp) / "absent.json")

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(router.RouterError):
                router.load_registry(path)

    def test_task_classes_normalised_to_canonical_order(self):
        registry = router.load_registry(
            [provider("p", tasks=["summarise", "answer"])])
        self.assertEqual(registry[0]["task_classes"],
                         ["answer", "summarise"])


class TestRegistryValidation(unittest.TestCase):
    def test_valid_registry_has_no_errors(self):
        self.assertEqual(router.validate_registry(fixture_registry()), [])

    def test_empty_provider_list_is_valid_shape(self):
        # Valid shape; routing over it fails closed (tested below).
        self.assertEqual(router.validate_registry([]), [])

    def test_duplicate_name_is_an_error(self):
        errors = router.validate_registry(
            [provider("dup"), provider("dup")])
        self.assertTrue(any("duplicate" in e for e in errors))

    def test_bad_kind_is_an_error(self):
        errors = router.validate_registry([provider("p", kind="cloud")])
        self.assertTrue(any("'kind'" in e for e in errors))

    def test_negative_cost_is_an_error(self):
        errors = router.validate_registry([provider("p", cin=-1.0)])
        self.assertTrue(any(">= 0" in e for e in errors))

    def test_missing_model_is_an_error(self):
        entry = provider("p")
        entry["model"] = "  "
        errors = router.validate_registry([entry])
        self.assertTrue(any("'model'" in e for e in errors))

    def test_missing_cost_is_an_error(self):
        entry = provider("p")
        del entry["cost_per_1k_output"]
        errors = router.validate_registry([entry])
        self.assertTrue(any("cost_per_1k_output" in e for e in errors))

    def test_bool_cost_is_an_error(self):
        errors = router.validate_registry([provider("p", cin=True)])
        self.assertTrue(any("must be a number" in e for e in errors))

    def test_non_bool_enabled_is_an_error(self):
        entry = provider("p")
        entry["enabled"] = "yes"
        errors = router.validate_registry([entry])
        self.assertTrue(any("'enabled'" in e for e in errors))

    def test_bad_latency_is_an_error(self):
        errors = router.validate_registry(
            [provider("p", latency="instant")])
        self.assertTrue(any("'latency_class'" in e for e in errors))

    def test_unknown_task_class_in_provider_is_an_error(self):
        errors = router.validate_registry(
            [provider("p", tasks=["translate"])])
        self.assertTrue(any("unknown task class" in e for e in errors))

    def test_credential_key_is_refused_outright(self):
        entry = provider("p")
        entry["api_key"] = "sk-should-never-be-here"
        errors = router.validate_registry([entry])
        self.assertTrue(any("credential-like key" in e for e in errors))
        with self.assertRaises(router.RouterError):
            router.load_registry([entry])

    def test_unknown_key_is_an_error(self):
        entry = provider("p")
        entry["endpoint"] = "https://example.invalid"
        errors = router.validate_registry([entry])
        self.assertTrue(any("unknown key" in e for e in errors))

    def test_load_raises_with_all_errors_listed(self):
        with self.assertRaises(router.RouterError) as ctx:
            router.load_registry([provider("p", kind="cloud")])
        self.assertIn("invalid provider registry", str(ctx.exception))


class TestRouting(unittest.TestCase):
    def setUp(self):
        self.registry = fixture_registry()

    def test_answer_picks_cheapest_eligible(self):
        result = router.route("answer", providers=self.registry)
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_name"], "gamma-remote")
        self.assertEqual(result["model"], "gamma-remote-model")
        self.assertEqual(result["cost_basis"], "per_1k_blended")
        self.assertIsNone(result["estimated_cost"])
        self.assertTrue(result["reasons"])

    def test_extract_and_summarise_pick_the_free_local(self):
        for task in ("extract", "summarise"):
            result = router.route(task, providers=self.registry)
            self.assertTrue(result["ok"])
            self.assertEqual(result["provider_name"], "beta-local")
            self.assertEqual(result["kind"], "local")

    def test_routing_is_deterministic_under_registry_reordering(self):
        forward = router.route("answer", providers=self.registry)
        backward = router.route(
            "answer", providers=list(reversed(self.registry)))
        self.assertEqual(forward, backward)
        again = router.route("answer", providers=self.registry)
        self.assertEqual(forward, again)

    def test_disabled_provider_is_never_selected(self):
        result = router.route("extract", providers=self.registry)
        rejected = {r["provider"]: r["reason"]
                    for r in result["rejected"]}
        self.assertEqual(rejected["delta-remote"], "disabled")

    def test_local_only_honoured_even_when_remote_is_cheaper(self):
        result = router.route(
            "answer", constraints={"local_only": True},
            providers=self.registry)
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_name"], "alpha-local")
        self.assertEqual(result["kind"], "local")
        rejected = {r["provider"]: r["reason"]
                    for r in result["rejected"]}
        self.assertIn("local_only", rejected["gamma-remote"])
        self.assertTrue(any("local_only honoured" in r
                            for r in result["reasons"]))

    def test_latency_budget_excludes_slower_providers(self):
        result = router.route(
            "answer", constraints={"latency_class": "fast"},
            providers=self.registry)
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_name"], "alpha-local")

    def test_cost_tie_breaks_by_latency_then_name(self):
        registry = [
            provider("slow-free", cin=0.0, cout=0.0, latency="slow"),
            provider("fast-free", cin=0.0, cout=0.0, latency="fast"),
            provider("also-fast", cin=0.0, cout=0.0, latency="fast"),
        ]
        result = router.route("extract", providers=registry)
        self.assertEqual(result["provider_name"], "also-fast")
        self.assertEqual(result["alternatives"],
                         ["fast-free", "slow-free"])

    def test_max_cost_per_1k_filters(self):
        result = router.route(
            "answer", constraints={"max_cost_per_1k": 0.5},
            providers=self.registry)
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_name"], "gamma-remote")
        rejected = {r["provider"]: r["reason"]
                    for r in result["rejected"]}
        self.assertIn("max_cost_per_1k", rejected["alpha-local"])

    def test_max_cost_with_estimates(self):
        result = router.route(
            "answer",
            constraints={"max_cost": 0.50,
                         "estimated_input_tokens": 1000,
                         "estimated_output_tokens": 1000},
            providers=self.registry)
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider_name"], "gamma-remote")
        self.assertEqual(result["estimated_cost"], 0.3)
        self.assertEqual(result["cost_basis"], "estimated_tokens")

    def test_estimates_change_the_cost_basis_order(self):
        # gamma is cheaper blended, but with output-heavy estimates
        # alpha (flat 0.50/0.50) beats gamma on the output side:
        # alpha est = 0.5*1 + 0.5*10 = 5.5; gamma = 0.1 + 0.2*10 = 2.1
        # — gamma still wins; use input-heavy instead:
        # alpha = 0.5*10 + 0.5 = 5.5; gamma = 1.0 + 0.2 = 1.2. The
        # point pinned here is only that the estimate is computed
        # from the caller's numbers, exactly.
        result = router.route(
            "answer",
            constraints={"estimated_input_tokens": 10000,
                         "estimated_output_tokens": 1000},
            providers=self.registry)
        self.assertEqual(result["provider_name"], "gamma-remote")
        self.assertEqual(result["estimated_cost"], 1.2)


class TestRoutingFailClosed(unittest.TestCase):
    def test_unknown_task_class(self):
        result = router.route("translate", providers=fixture_registry())
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unknown_task_class")
        self.assertIsNone(result["provider"])

    def test_no_eligible_provider(self):
        result = router.route(
            "answer",
            constraints={"local_only": True, "max_cost_per_1k": 0.5},
            providers=fixture_registry())
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_eligible_provider")
        self.assertIsNone(result["provider"])
        self.assertTrue(result["rejected"])

    def test_only_disabled_providers_fail_closed(self):
        registry = [provider("off", enabled=False)]
        result = router.route("answer", providers=registry)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_eligible_provider")

    def test_empty_registry_fails_closed(self):
        result = router.route("answer", providers=[])
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_eligible_provider")

    def test_default_registry_answer_fails_closed(self):
        # The safe default: no real provider configured, so an
        # answer route is an explicit error, never a silent
        # fall-back to the disabled remote placeholder.
        result = router.route("answer")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "no_eligible_provider")
        mechanical = router.route("summarise")
        self.assertTrue(mechanical["ok"])
        self.assertEqual(mechanical["provider_name"],
                         "local-placeholder")

    def test_max_cost_without_estimates_is_an_error(self):
        result = router.route(
            "answer", constraints={"max_cost": 1.0},
            providers=fixture_registry())
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "invalid_constraints")
        self.assertIn("estimated_input_tokens", result["error"])

    def test_unknown_constraint_key_is_an_error(self):
        result = router.route(
            "answer", constraints={"cheap": True},
            providers=fixture_registry())
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "invalid_constraints")

    def test_bad_latency_constraint_is_an_error(self):
        result = router.route(
            "answer", constraints={"latency_class": "instant"},
            providers=fixture_registry())
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "invalid_constraints")

    def test_invalid_registry_is_an_error_result_not_a_guess(self):
        result = router.route(
            "answer", providers=[provider("p", kind="cloud")])
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "invalid_registry")
        self.assertIsNone(result["provider"])


class TestCostComputation(unittest.TestCase):
    def setUp(self):
        self.p = router.load_registry(
            [provider("priced", cin=0.5, cout=2.0)])[0]

    def test_exact_cost(self):
        # 2000 in at 0.5/1k = 1.0; 500 out at 2.0/1k = 1.0.
        self.assertEqual(router.compute_cost(self.p, 2000, 500), 2.0)

    def test_zero_tokens_cost_zero(self):
        self.assertEqual(router.compute_cost(self.p, 0, 0), 0.0)

    def test_fractional_cost_is_clean(self):
        p = router.load_registry(
            [provider("p", cin=0.10, cout=0.20)])[0]
        self.assertEqual(router.compute_cost(p, 1000, 1000), 0.3)

    def test_negative_tokens_refused(self):
        with self.assertRaises(router.RouterError):
            router.compute_cost(self.p, -1, 0)

    def test_non_integer_tokens_refused(self):
        with self.assertRaises(router.RouterError):
            router.compute_cost(self.p, 10.5, 0)
        with self.assertRaises(router.RouterError):
            router.compute_cost(self.p, True, 0)


class TestResponseCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = router.ResponseCache(
            Path(self.tmp.name) / "cache", ttl_seconds=60)
        self.p = router.load_registry(
            [provider("gamma-remote", cin=0.1, cout=0.2)])[0]

    def test_miss_then_put_then_hit(self):
        self.assertIsNone(
            self.cache.get("question?", self.p, now=1000.0))
        self.cache.put("question?", self.p,
                       response={"answer": "yes"}, now=1000.0)
        entry = self.cache.get("question?", self.p, now=1001.0)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["response"], {"answer": "yes"})
        self.assertEqual(entry["provider"], "gamma-remote")
        stats = self.cache.stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["writes"], 1)
        self.assertEqual(stats["hit_rate"], 0.5)

    def test_prompt_normalisation_shares_an_entry(self):
        self.cache.put("hello   world\nagain", self.p,
                       response="r", now=1000.0)
        self.assertEqual(
            self.cache.get_response("hello world again", self.p,
                                    now=1001.0), "r")
        self.assertEqual(
            router.cache_key("hello   world", self.p),
            router.cache_key("hello world", self.p))

    def test_key_depends_on_provider_and_model(self):
        other = router.load_registry([provider("other")])[0]
        self.cache.put("q", self.p, response="r", now=1000.0)
        self.assertIsNone(self.cache.get("q", other, now=1001.0))
        self.assertIsNone(
            self.cache.get("q", self.p, model="different",
                           now=1001.0))
        self.assertNotEqual(router.cache_key("q", self.p),
                            router.cache_key("q", other))

    def test_ttl_expiry_is_a_miss_and_removes_the_entry(self):
        key = self.cache.put("q", self.p, response="r", now=1000.0)
        path = Path(self.tmp.name) / "cache" / (key + ".json")
        self.assertTrue(path.is_file())
        self.assertIsNotNone(self.cache.get("q", self.p, now=1059.0))
        self.assertIsNone(self.cache.get("q", self.p, now=1061.0))
        self.assertFalse(path.is_file())
        stats = self.cache.stats()
        self.assertEqual(stats["expiries"], 1)
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)

    def test_no_ttl_never_expires(self):
        cache = router.ResponseCache(
            Path(self.tmp.name) / "forever", ttl_seconds=None)
        cache.put("q", self.p, response="r", now=1000.0)
        self.assertIsNotNone(cache.get("q", self.p, now=10 ** 12))

    def test_corrupt_entry_is_a_miss_not_a_crash(self):
        key = router.cache_key("q", self.p)
        cache_dir = Path(self.tmp.name) / "cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / (key + ".json")).write_text(
            "{torn", encoding="utf-8")
        self.assertIsNone(self.cache.get("q", self.p, now=1000.0))
        self.assertEqual(self.cache.stats()["misses"], 1)

    def test_unserialisable_response_refused_before_writing(self):
        with self.assertRaises(router.RouterError):
            self.cache.put("q", self.p, response=object(), now=1000.0)
        self.assertEqual(self.cache.stats()["writes"], 0)

    def test_bare_name_without_model_is_refused(self):
        with self.assertRaises(router.RouterError):
            router.cache_key("q", "gamma-remote")


class TestCostLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger" / "costs.jsonl"
        self.ledger = router.CostLedger(self.path)
        self.p = router.load_registry(
            [provider("priced", cin=0.5, cout=2.0)])[0]

    def test_record_appends_one_jsonl_entry_with_exact_cost(self):
        entry = self.ledger.record(
            self.p, 2000, 500, timestamp=1700000000.0)
        self.assertEqual(entry["provider"], "priced")
        self.assertEqual(entry["model"], "priced-model")
        self.assertEqual(entry["input_tokens"], 2000)
        self.assertEqual(entry["output_tokens"], 500)
        self.assertEqual(entry["cost"], 2.0)
        self.assertEqual(entry["cost_if_uncached"], 2.0)
        self.assertEqual(entry["cache"], "miss")
        self.assertFalse(entry["cache_hit"])
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), entry)

    def test_cache_hit_records_zero_cost_and_the_saving(self):
        entry = self.ledger.record(self.p, 2000, 500, cache_hit=True)
        self.assertEqual(entry["cost"], 0.0)
        self.assertEqual(entry["cost_if_uncached"], 2.0)
        self.assertEqual(entry["cache"], "hit")

    def test_ledger_is_append_only(self):
        self.ledger.record(self.p, 1000, 0)
        first = self.path.read_text(encoding="utf-8")
        self.ledger.record(self.p, 0, 1000)
        text = self.path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith(first))
        self.assertEqual(len(text.splitlines()), 2)

    def test_totals_aggregate_entries_and_providers(self):
        other = router.load_registry(
            [provider("other", cin=1.0, cout=1.0)])[0]
        self.ledger.record(self.p, 2000, 500)               # cost 2.0
        self.ledger.record(self.p, 2000, 500, cache_hit=True)  # cost 0
        self.ledger.record(other, 1000, 1000)               # cost 2.0
        totals = self.ledger.totals()
        self.assertEqual(totals["entries"], 3)
        self.assertEqual(totals["input_tokens"], 5000)
        self.assertEqual(totals["output_tokens"], 2000)
        self.assertEqual(totals["total_cost"], 4.0)
        self.assertEqual(totals["cost_if_uncached"], 6.0)
        self.assertEqual(totals["cache_hits"], 1)
        self.assertEqual(totals["cache_misses"], 2)
        self.assertEqual(totals["by_provider"]["priced"]["entries"], 2)
        self.assertEqual(
            totals["by_provider"]["priced"]["total_cost"], 2.0)
        self.assertEqual(
            totals["by_provider"]["other"]["total_cost"], 2.0)

    def test_totals_of_missing_file_are_zero(self):
        totals = router.read_totals(Path(self.tmp.name) / "none.jsonl")
        self.assertEqual(totals["entries"], 0)
        self.assertEqual(totals["total_cost"], 0.0)

    def test_totals_surface_malformed_lines(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"provider": "x"}\nnot json\n',
                             encoding="utf-8")
        totals = self.ledger.totals()
        self.assertEqual(totals["entries"], 1)
        self.assertEqual(totals["malformed"], 1)

    def test_token_counts_are_required_never_invented(self):
        with self.assertRaises(TypeError):
            self.ledger.record(self.p)
        with self.assertRaises(router.RouterError):
            self.ledger.record(self.p, -5, 0)


class TestRouterBundle(unittest.TestCase):
    def test_route_cache_and_ledger_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = router.Router(
                providers=fixture_registry(),
                cache=router.ResponseCache(Path(tmp) / "c"),
                ledger=router.CostLedger(Path(tmp) / "l.jsonl"))
            decision = bundle.route("extract")
            self.assertTrue(decision["ok"])
            self.assertIsNone(bundle.cache_lookup(decision, "q",
                                                  now=1000.0))
            bundle.cache_store(decision, "q", "the answer", now=1000.0)
            hit = bundle.cache_lookup(decision, "q", now=1001.0)
            self.assertEqual(hit["response"], "the answer")
            entry = bundle.record_usage(decision, 100, 50,
                                        cache_hit=True)
            self.assertEqual(entry["provider"], "beta-local")
            self.assertEqual(entry["task_class"], "extract")
            self.assertEqual(entry["cost"], 0.0)

    def test_failed_decision_records_no_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = router.Router(
                providers=fixture_registry(),
                ledger=router.CostLedger(Path(tmp) / "l.jsonl"))
            decision = bundle.route("translate")
            self.assertFalse(decision["ok"])
            with self.assertRaises(router.RouterError):
                bundle.record_usage(decision, 100, 50)
            self.assertIsNone(bundle.cache_lookup(decision, "q"))


class TestNoNetworkSurface(unittest.TestCase):
    def test_module_imports_no_network_or_credential_machinery(self):
        source = Path(router.__file__).read_text(encoding="utf-8")
        for forbidden in ("import socket", "import urllib",
                          "import requests", "import http.client",
                          "os.environ", "getenv"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
