from __future__ import annotations

import unittest

from _test_paths import ensure_skill_root_on_path

ensure_skill_root_on_path()

from scripts.marketplace_throughput import (
    MINIMUM_CANDIDATES,
    SEARCH_LIMIT_SECONDS,
    TARGET_PER_SECOND,
    WINDOW_SECONDS,
    decide_marketplace_throughput,
)


def healthy_sources():
    return {"edge:jd": "available", "searxng": "available"}


def incomplete_scope():
    return {
        "query_generation_exhausted": False,
        "healthy_cursors_open": 1,
        "healthy_cursors_blocked": 0,
        "edge_plan_completed": False,
        "api_available": False,
        "api_cursor_completed": False,
        "recent_candidate_additions": [4, 3, 2],
        "untried_high_yield_families": 1,
    }


def complete_scope():
    return {
        "query_generation_exhausted": True,
        "healthy_cursors_open": 0,
        "healthy_cursors_blocked": 0,
        "edge_plan_completed": True,
        "api_available": False,
        "api_cursor_completed": False,
        "recent_candidate_additions": [1, 0, 0],
        "untried_high_yield_families": 0,
    }


class MarketplaceThroughputTests(unittest.TestCase):
    def test_constants_are_the_approved_contract(self):
        self.assertEqual(WINDOW_SECONDS, 30.0)
        self.assertEqual(TARGET_PER_SECOND, 10.0)
        self.assertEqual(MINIMUM_CANDIDATES, 6000)
        self.assertEqual(SEARCH_LIMIT_SECONDS, 600.0)

    def test_exactly_three_hundred_candidates_in_last_window_is_healthy(self):
        decision = decide_marketplace_throughput(
            discovery_seconds=60.0,
            total_unique_candidates=600,
            recent_window_candidates=300,
            max_zero_gap_seconds=12.0,
            raw_observations=900,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
        )
        self.assertEqual(decision.state, "healthy")
        self.assertEqual(decision.next_action, "keep_routes")
        self.assertEqual(decision.recent_per_second, 10.0)

    def test_thirty_seconds_without_a_candidate_forces_route_switch(self):
        decision = decide_marketplace_throughput(
            discovery_seconds=90.0,
            total_unique_candidates=450,
            recent_window_candidates=0,
            max_zero_gap_seconds=30.0,
            raw_observations=1200,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
        )
        self.assertEqual(decision.state, "zero_window")
        self.assertEqual(decision.next_action, "switch_source")

    def test_jd_slow_lane_tolerates_thirty_second_zero_gap(self):
        decision = decide_marketplace_throughput(
            discovery_seconds=90.0,
            total_unique_candidates=90,
            recent_window_candidates=0,
            max_zero_gap_seconds=30.0,
            raw_observations=120,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
            jd_slow_lane=True,
        )
        self.assertNotEqual(decision.state, "zero_window")
        self.assertNotEqual(decision.next_action, "switch_source")

    def test_jd_slow_lane_never_switches_source_on_zero_window(self):
        decision = decide_marketplace_throughput(
            discovery_seconds=120.0,
            total_unique_candidates=100,
            recent_window_candidates=0,
            max_zero_gap_seconds=95.0,
            raw_observations=120,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
            jd_slow_lane=True,
        )
        self.assertEqual(decision.state, "zero_window")
        self.assertEqual(decision.next_action, "expand_query_family")

    def test_jd_slow_lane_acceptance_uses_one_per_second_and_custom_limit(self):
        decision = decide_marketplace_throughput(
            discovery_seconds=300.0,
            total_unique_candidates=300,
            recent_window_candidates=90,
            max_zero_gap_seconds=10.0,
            raw_observations=400,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
            search_limit_seconds=300.0,
            jd_slow_lane=True,
        )
        self.assertEqual(decision.state, "ten_minute_limit")
        self.assertTrue(decision.acceptance_passed)

    def test_warmup_slow_duplicates_and_blocked_have_distinct_actions(self):
        cases = (
            (10.0, 50, 50, 50, healthy_sources(), "warmup", "keep_routes"),
            (60.0, 400, 250, 500, healthy_sources(), "slow", "expand_query_family"),
            (60.0, 100, 20, 5000, healthy_sources(), "duplicate_saturation", "change_route_shape"),
            (
                60.0,
                400,
                300,
                500,
                {"edge:jd": "captcha_required", "searxng": "available"},
                "source_blocked",
                "cool_blocked_source",
            ),
        )
        for seconds, total, recent, raw, sources, state, action in cases:
            with self.subTest(state=state):
                decision = decide_marketplace_throughput(
                    discovery_seconds=seconds,
                    total_unique_candidates=total,
                    recent_window_candidates=recent,
                    max_zero_gap_seconds=5.0,
                    raw_observations=raw,
                    source_states=sources,
                    scope_evidence=incomplete_scope(),
                )
                self.assertEqual(decision.state, state)
                self.assertEqual(decision.next_action, action)

    def test_verified_scope_completion_requires_no_auth_captcha_or_open_cursor(self):
        complete = decide_marketplace_throughput(
            discovery_seconds=120.0,
            total_unique_candidates=800,
            recent_window_candidates=3,
            max_zero_gap_seconds=20.0,
            raw_observations=1600,
            source_states=healthy_sources(),
            scope_evidence=complete_scope(),
        )
        self.assertEqual(complete.state, "deterministic_scope_complete")
        self.assertEqual(complete.next_action, "stop_scope_complete")

        for source_state in ("authentication_required", "captcha_required"):
            with self.subTest(source_state=source_state):
                blocked = decide_marketplace_throughput(
                    discovery_seconds=120.0,
                    total_unique_candidates=800,
                    recent_window_candidates=3,
                    max_zero_gap_seconds=20.0,
                    raw_observations=1600,
                    source_states={"edge:jd": source_state, "searxng": "available"},
                    scope_evidence=complete_scope(),
                )
                self.assertNotEqual(blocked.state, "deterministic_scope_complete")

    def test_time_boundary_and_acceptance_are_strict(self):
        before = decide_marketplace_throughput(
            discovery_seconds=599.999,
            total_unique_candidates=6000,
            recent_window_candidates=300,
            max_zero_gap_seconds=10.0,
            raw_observations=7000,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
        )
        at_limit = decide_marketplace_throughput(
            discovery_seconds=600.0,
            total_unique_candidates=6000,
            recent_window_candidates=300,
            max_zero_gap_seconds=10.0,
            raw_observations=7000,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
        )
        too_early = decide_marketplace_throughput(
            discovery_seconds=300.0,
            total_unique_candidates=6000,
            recent_window_candidates=300,
            max_zero_gap_seconds=10.0,
            raw_observations=7000,
            source_states=healthy_sources(),
            scope_evidence=incomplete_scope(),
        )

        self.assertNotEqual(before.state, "ten_minute_limit")
        self.assertFalse(before.acceptance_passed)
        self.assertEqual(at_limit.state, "ten_minute_limit")
        self.assertTrue(at_limit.acceptance_passed)
        self.assertFalse(too_early.acceptance_passed)


if __name__ == "__main__":
    unittest.main()
