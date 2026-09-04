from dataclasses import replace
import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.aggregate_evidence import (
    BackendCapability,
    ConcurrencySignal,
    CoverageState,
    DiscoveryRound,
    decide_stop,
    decide_throughput_route,
)


def complete_coverage() -> CoverageState:
    dimensions = {"region", "language", "time", "platform"}
    return CoverageState(
        applicable_query_dimensions=dimensions,
        attempted_query_dimensions=dimensions,
        unresolved_region_gaps=set(),
        unresolved_language_gaps=set(),
        unresolved_time_gaps=set(),
        unresolved_platform_gaps=set(),
        domain_concentrated=False,
        continued_discovery_unlikely_to_change=True,
    )


def saturated_rounds() -> tuple[DiscoveryRound, ...]:
    return (
        DiscoveryRound("family-a", "official", 0, 0, 0, True),
        DiscoveryRound("family-b", "media", 0, 0, 0, True),
        DiscoveryRound("family-c", "marketplace", 0, 0, 0, True),
    )


class StopAndConcurrencyTests(unittest.TestCase):
    def test_five_hundred_thousand_urls_do_not_stop(self):
        result = decide_stop(
            discovery_seconds=300,
            unique_urls=500_000,
            recent_rounds=(),
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media"},
        )
        self.assertFalse(result.stop)
        self.assertIsNone(result.reason)

    def test_large_entity_and_field_yields_prevent_saturation(self):
        rounds = (
            DiscoveryRound("family-a", "official", 0, 0, 0, True),
            DiscoveryRound("family-b", "media", 0, 0, 0, True),
            DiscoveryRound("family-c", "marketplace", 0, 500_000, 500_000, True),
        )
        result = decide_stop(
            discovery_seconds=599,
            unique_urls=500_000,
            recent_rounds=rounds,
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media", "marketplace"},
            coverage_state=complete_coverage(),
        )
        self.assertFalse(result.stop)

    def test_less_than_ten_minutes_does_not_time_stop(self):
        result = decide_stop(
            discovery_seconds=599.999,
            unique_urls=17,
            recent_rounds=(),
            applicable_sources={"official"},
            attempted_sources={"official"},
        )
        self.assertFalse(result.stop)
        self.assertIsNone(result.reason)

    def test_ten_minutes_always_stops(self):
        result = decide_stop(
            discovery_seconds=600,
            unique_urls=17,
            recent_rounds=(),
            applicable_sources={"official"},
            attempted_sources={"official"},
        )
        self.assertTrue(result.stop)
        self.assertEqual(result.reason, "ten-minute-search-limit")

    def test_ten_minutes_precedes_invalid_ancillary_telemetry(self):
        result = decide_stop(
            discovery_seconds=600,
            unique_urls=-1,
            recent_rounds=("stale-round",),
            applicable_sources=["malformed-source-container"],
            attempted_sources=None,
            coverage_state="stale-coverage",
        )
        self.assertEqual(result.reason, "ten-minute-search-limit")

    def test_saturation_needs_three_heterogeneous_zero_yield_rounds(self):
        rounds = tuple(
            DiscoveryRound(f"family-{i}", f"source-{i}", 0, 0, 0, True)
            for i in range(3)
        )
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=rounds,
            applicable_sources={"source-0", "source-1", "source-2"},
            attempted_sources={"source-0", "source-1", "source-2"},
            coverage_state=complete_coverage(),
        )
        self.assertTrue(result.stop)
        self.assertEqual(result.reason, "search-saturated")

    def test_saturation_uses_only_three_most_recent_rounds(self):
        rounds = (
            DiscoveryRound("old", "old-source", 99, 99, 99, False),
            *saturated_rounds(),
        )
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=rounds,
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media", "marketplace"},
            coverage_state=complete_coverage(),
        )
        self.assertEqual(result.reason, "search-saturated")

    def test_missing_coverage_state_prevents_saturation(self):
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=saturated_rounds(),
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media", "marketplace"},
        )
        self.assertFalse(result.stop)

    def test_each_outstanding_gap_prevents_saturation(self):
        for field in (
            "unresolved_region_gaps",
            "unresolved_language_gaps",
            "unresolved_time_gaps",
            "unresolved_platform_gaps",
        ):
            with self.subTest(field=field):
                coverage = replace(complete_coverage(), **{field: {"outstanding"}})
                result = decide_stop(
                    discovery_seconds=420,
                    unique_urls=900,
                    recent_rounds=saturated_rounds(),
                    applicable_sources={"official", "media", "marketplace"},
                    attempted_sources={"official", "media", "marketplace"},
                    coverage_state=coverage,
                )
                self.assertFalse(result.stop)

    def test_missing_query_dimension_prevents_saturation(self):
        coverage = replace(
            complete_coverage(),
            attempted_query_dimensions={"region", "language", "time"},
        )
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=saturated_rounds(),
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media", "marketplace"},
            coverage_state=coverage,
        )
        self.assertFalse(result.stop)

    def test_domain_concentration_prevents_saturation(self):
        coverage = replace(complete_coverage(), domain_concentrated=True)
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=saturated_rounds(),
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media", "marketplace"},
            coverage_state=coverage,
        )
        self.assertFalse(result.stop)

    def test_unstable_candidate_set_prevents_saturation(self):
        coverage = replace(
            complete_coverage(), continued_discovery_unlikely_to_change=False
        )
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=saturated_rounds(),
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media", "marketplace"},
            coverage_state=coverage,
        )
        self.assertFalse(result.stop)

    def test_whitespace_and_case_aliases_cannot_fake_heterogeneity(self):
        rounds = (
            DiscoveryRound("Family", "Official", 0, 0, 0, True),
            DiscoveryRound(" family ", " official ", 0, 0, 0, True),
            DiscoveryRound("FAMILY", "OFFICIAL", 0, 0, 0, True),
        )
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=rounds,
            applicable_sources={" OFFICIAL "},
            attempted_sources={"official"},
            coverage_state=complete_coverage(),
        )
        self.assertFalse(result.stop)

    def test_query_dimension_aliases_do_not_fake_complete_coverage(self):
        coverage = replace(
            complete_coverage(),
            applicable_query_dimensions={"Region", " region ", "PLATFORM"},
            attempted_query_dimensions={"region"},
        )
        result = decide_stop(
            discovery_seconds=420,
            unique_urls=900,
            recent_rounds=saturated_rounds(),
            applicable_sources={"official", "media", "marketplace"},
            attempted_sources={"official", "media", "marketplace"},
            coverage_state=coverage,
        )
        self.assertFalse(result.stop)

    def test_saturation_rejects_incomplete_or_homogeneous_rounds(self):
        cases = (
            (
                saturated_rounds(),
                {"official", "media"},
            ),
            (
                (
                    DiscoveryRound("same", "official", 0, 0, 0, True),
                    DiscoveryRound("same", "media", 0, 0, 0, True),
                    DiscoveryRound("same", "marketplace", 0, 0, 0, True),
                ),
                {"official", "media", "marketplace"},
            ),
            (
                (
                    DiscoveryRound("a", "same", 0, 0, 0, True),
                    DiscoveryRound("b", "same", 0, 0, 0, True),
                    DiscoveryRound("c", "same", 0, 0, 0, True),
                ),
                {"official", "media", "marketplace"},
            ),
            (
                (
                    DiscoveryRound("a", "official", 0, 0, 0, True),
                    DiscoveryRound("b", "media", 0, 0, 0, True),
                    DiscoveryRound("c", "marketplace", 0, 0, 0, False),
                ),
                {"official", "media", "marketplace"},
            ),
        )
        for rounds, attempted_sources in cases:
            with self.subTest(rounds=rounds, attempted_sources=attempted_sources):
                result = decide_stop(
                    discovery_seconds=420,
                    unique_urls=900,
                    recent_rounds=rounds,
                    applicable_sources={"official", "media", "marketplace"},
                    attempted_sources=attempted_sources,
                    coverage_state=complete_coverage(),
                )
                self.assertFalse(result.stop)

    def test_throughput_route_holds_during_warmup(self):
        decision = decide_throughput_route(
            discovery_seconds=4.9,
            batches=1,
            raw_url_observations=100,
            recent_window_seconds=2,
            recent_raw_url_observations=40,
            backends=(
                BackendCapability("web", "search", True, True),
                BackendCapability("common-crawl", "open_index", True, False),
            ),
        )
        self.assertEqual(decision.action, "continue")
        self.assertEqual(decision.reason, "warmup")
        self.assertFalse(decision.must_disclose)

    def test_throughput_route_continues_when_target_is_met(self):
        decision = decide_throughput_route(
            discovery_seconds=10,
            batches=2,
            raw_url_observations=600,
            recent_window_seconds=5,
            recent_raw_url_observations=260,
            backends=(),
        )
        self.assertEqual(decision.action, "continue")
        self.assertEqual(decision.reason, "target-met")
        self.assertEqual(decision.raw_rate, 60.0)
        self.assertEqual(decision.recent_raw_rate, 52.0)

    def test_throughput_route_prefers_unused_bulk_backend(self):
        decision = decide_throughput_route(
            discovery_seconds=8,
            batches=2,
            raw_url_observations=80,
            recent_window_seconds=3,
            recent_raw_url_observations=20,
            backends=(
                BackendCapability("web", "search", True, True),
                BackendCapability("github", "dataset", True, False),
                BackendCapability("common-crawl", "open_index", True, False),
                BackendCapability("page", "page", True, False),
            ),
        )
        self.assertEqual(decision.action, "add_bulk_backend")
        self.assertEqual(decision.target_backend, "common-crawl")
        self.assertFalse(decision.must_disclose)

    def test_throughput_route_switches_query_family_after_bulk_attempt(self):
        decision = decide_throughput_route(
            discovery_seconds=12,
            batches=3,
            raw_url_observations=120,
            recent_window_seconds=4,
            recent_raw_url_observations=16,
            backends=(
                BackendCapability("common-crawl", "open_index", True, True),
                BackendCapability("affiliate", "bulk_api", True, True),
            ),
        )
        self.assertEqual(decision.action, "switch_query_family")
        self.assertIsNone(decision.target_backend)
        self.assertFalse(decision.must_disclose)

    def test_throughput_route_declares_degraded_mode_and_15s_miss(self):
        decision = decide_throughput_route(
            discovery_seconds=15,
            batches=4,
            raw_url_observations=120,
            recent_window_seconds=5,
            recent_raw_url_observations=10,
            backends=(
                BackendCapability("web", "search", True, True),
                BackendCapability("page", "page", True, False),
            ),
        )
        self.assertEqual(decision.action, "search_only_degraded")
        self.assertTrue(decision.must_disclose)
        self.assertEqual(decision.reason, "bulk-backend-unavailable")

    def test_throughput_route_inputs_fail_closed(self):
        with self.assertRaises(ValueError):
            BackendCapability("bad", "unknown", True, False)
        with self.assertRaises(ValueError):
            BackendCapability("bad", "search", 1, False)
        with self.assertRaises(ValueError):
            decide_throughput_route(
                discovery_seconds=5,
                batches=2,
                raw_url_observations=1,
                recent_window_seconds=0,
                recent_raw_url_observations=1,
                backends=(),
            )

    def _concurrency_api(self):
        from scripts import aggregate_evidence as module

        names = (
            "BackendConcurrencyState",
            "advance_concurrency",
            "drain_compensation",
        )
        missing = [name for name in names if not hasattr(module, name)]
        self.assertEqual(
            missing,
            [],
            "stateful per-backend concurrency API is missing",
        )
        return tuple(getattr(module, name) for name in names)

    def test_searxng_policy_scales_only_from_two_to_four(self):
        from scripts import aggregate_evidence as module

        policy = module.ConcurrencyPolicy((2, 4))
        state = module.BackendConcurrencyState(
            backend="searxng",
            tier=2,
            policy=policy,
        )
        transition = module.advance_concurrency(
            state,
            tool_limit=8,
            host_limit=8,
            signal=ConcurrencySignal(False, 0.0, 1.0),
            window_complete=True,
        )
        self.assertEqual(transition.next_tier, 4)
        self.assertEqual(transition.state.policy.tiers, (2, 4))

    def test_common_crawl_policy_never_exceeds_two(self):
        from scripts import aggregate_evidence as module

        policy = module.ConcurrencyPolicy((1, 2))
        state = module.BackendConcurrencyState(
            backend="common-crawl",
            tier=2,
            policy=policy,
        )
        transition = module.advance_concurrency(
            state,
            tool_limit=40,
            host_limit=40,
            signal=ConcurrencySignal(False, 0.0, 1.0),
            window_complete=True,
        )
        self.assertEqual(transition.next_tier, 2)

    def test_healthy_windows_scale_from_24_to_32_then_40(self):
        State, advance, _ = self._concurrency_api()
        healthy = ConcurrencySignal(False, 0.0, 1.0)
        state = State(backend="web-search", tier=24)

        incomplete_24 = advance(
            state, 200, 300, healthy, window_complete=False
        )
        self.assertEqual(incomplete_24.next_tier, 24)
        complete_24 = advance(
            incomplete_24.state, 200, 300, healthy, window_complete=True
        )
        self.assertEqual(complete_24.next_tier, 32)

        incomplete_32 = advance(
            complete_24.state, 200, 300, healthy, window_complete=False
        )
        self.assertEqual(incomplete_32.next_tier, 32)
        complete_32 = advance(
            incomplete_32.state, 200, 300, healthy, window_complete=True
        )
        self.assertEqual(complete_32.next_tier, 40)

    def test_40_pressure_holds_32_until_healthy_recovery_window_completes(self):
        State, advance, _ = self._concurrency_api()
        healthy = ConcurrencySignal(False, 0.0, 1.0)
        pressure = ConcurrencySignal(True, 0.20, 2.0, rate_limit_streak=2)
        state = State(backend="web-search", tier=40)

        retreated = advance(
            state, 200, 300, pressure, window_complete=False
        )
        self.assertEqual(retreated.next_tier, 32)
        self.assertTrue(retreated.state.stabilizing_after_backoff)
        self.assertEqual(retreated.state.window_observations, 0)

        held = advance(
            retreated.state, 200, 300, healthy, window_complete=False
        )
        self.assertEqual(held.next_tier, 32)
        self.assertTrue(held.state.stabilizing_after_backoff)
        self.assertEqual(held.state.window_observations, 1)

        recovered = advance(
            held.state, 200, 300, healthy, window_complete=True
        )
        self.assertEqual(recovered.next_tier, 40)
        self.assertFalse(recovered.state.stabilizing_after_backoff)
        self.assertEqual(recovered.state.window_observations, 0)

    def test_40_pressure_holds_32_then_drops_24_only_after_unhealthy_window(self):
        State, advance, _ = self._concurrency_api()
        pressure = ConcurrencySignal(True, 0.20, 2.0, rate_limit_streak=2)
        state = State(backend="web-search", tier=40)

        retreated = advance(
            state, 200, 300, pressure, window_complete=False
        )
        held = advance(
            retreated.state, 200, 300, pressure, window_complete=False
        )
        self.assertEqual(held.next_tier, 32)
        self.assertTrue(held.state.stabilizing_after_backoff)
        self.assertTrue(held.state.window_had_material_pressure)

        dropped = advance(
            held.state, 200, 300, pressure, window_complete=True
        )
        self.assertEqual(dropped.next_tier, 24)
        self.assertFalse(dropped.state.stabilizing_after_backoff)
        self.assertEqual(dropped.state.window_observations, 0)

    def test_isolated_429_enqueues_and_drains_compensation_without_downshift(self):
        State, advance, drain = self._concurrency_api()
        isolated = ConcurrencySignal(True, 0.01, 1.0, rate_limit_streak=1)
        state = State(backend="web-search", tier=40)

        queued = advance(
            state,
            200,
            300,
            isolated,
            window_complete=False,
            failed_query_ids=("q-1", "q-2"),
            retry_backend="browser-search",
        )
        self.assertEqual(queued.next_tier, 40)
        self.assertTrue(queued.enqueue_compensation)
        self.assertEqual(queued.retained_error_count, 2)
        self.assertEqual(queued.retry_backend, "browser-search")
        self.assertEqual(queued.retry_tier, 40)
        self.assertEqual(queued.queue_depth, 2)
        self.assertEqual(
            tuple(item.query_id for item in queued.state.compensation_queue),
            ("q-1", "q-2"),
        )

        duplicate_failure = advance(
            queued.state,
            200,
            300,
            isolated,
            window_complete=False,
            failed_query_ids=("q-1",),
            retry_backend="browser-search",
        )
        self.assertEqual(duplicate_failure.next_tier, 40)
        self.assertEqual(duplicate_failure.queue_depth, 2)
        self.assertEqual(duplicate_failure.retained_error_count, 3)

        drained_one = drain(duplicate_failure.state, ("q-1",))
        self.assertEqual(drained_one.action, "drain-compensation")
        self.assertEqual(drained_one.queue_depth, 1)
        self.assertEqual(drained_one.retained_error_count, 3)
        self.assertEqual(drained_one.retry_backend, "browser-search")
        self.assertEqual(drained_one.retry_tier, 40)

        drained_all = drain(drained_one.state, ("q-2",))
        self.assertEqual(drained_all.queue_depth, 0)
        self.assertIsNone(drained_all.retry_backend)
        self.assertIsNone(drained_all.retry_tier)

    def test_isolated_429_with_complete_window_holds_all_three_tiers(self):
        State, advance, _ = self._concurrency_api()
        isolated = ConcurrencySignal(True, 0.01, 1.0, rate_limit_streak=1)

        for tier in (24, 32, 40):
            with self.subTest(tier=tier):
                transition = advance(
                    State(backend="web-search", tier=tier),
                    200,
                    300,
                    isolated,
                    window_complete=True,
                    failed_query_ids=(f"q-{tier}",),
                )
                self.assertEqual(transition.next_tier, tier)
                self.assertTrue(transition.enqueue_compensation)
                self.assertEqual(transition.retry_backend, "web-search")
                self.assertLess(transition.retry_tier, tier)

    def test_isolated_429_may_retry_same_tier_on_another_backend(self):
        State, advance, _ = self._concurrency_api()
        isolated = ConcurrencySignal(True, 0.01, 1.0, rate_limit_streak=1)
        transition = advance(
            State(backend="web-search", tier=24),
            200,
            300,
            isolated,
            window_complete=True,
            failed_query_ids=("q-alternate",),
            retry_backend="browser-search",
        )
        self.assertEqual(transition.next_tier, 24)
        self.assertEqual(transition.retry_backend, "browser-search")
        self.assertEqual(transition.retry_tier, 24)
    def test_backend_limits_are_independent_state(self):
        State, advance, _ = self._concurrency_api()
        healthy = ConcurrencySignal(False, 0.0, 1.0)
        pressure = ConcurrencySignal(True, 0.20, 2.0, rate_limit_streak=2)

        web = advance(
            State(backend="web-search", tier=24),
            200,
            300,
            healthy,
            window_complete=True,
        )
        browser = advance(
            State(backend="browser", tier=24),
            10,
            300,
            pressure,
            window_complete=True,
        )
        self.assertEqual(web.next_tier, 32)
        self.assertEqual(browser.next_tier, 10)
        self.assertEqual(web.state.backend, "web-search")
        self.assertEqual(browser.state.backend, "browser")

    def test_impossible_stop_and_stateful_concurrency_inputs_are_rejected(self):
        State, advance, drain = self._concurrency_api()
        with self.assertRaises(ValueError):
            decide_stop(
                discovery_seconds=-1,
                unique_urls=0,
                recent_rounds=(),
                applicable_sources=set(),
                attempted_sources=set(),
            )
        with self.assertRaises(ValueError):
            State(backend="", tier=24)
        with self.assertRaises(ValueError):
            State(backend="web-search", tier=0)
        with self.assertRaises(ValueError):
            ConcurrencySignal(False, 1.1, 1.0)
        with self.assertRaises(ValueError):
            ConcurrencySignal(False, 0.0, 1.0, rate_limit_streak=-1)
        with self.assertRaises(ValueError):
            advance(
                State(backend="web-search", tier=24),
                200,
                300,
                ConcurrencySignal(False, 0.0, 1.0),
                window_complete=1,
            )
        with self.assertRaises(ValueError):
            drain(State(backend="web-search", tier=24), ("missing",))
if __name__ == "__main__":
    unittest.main()
