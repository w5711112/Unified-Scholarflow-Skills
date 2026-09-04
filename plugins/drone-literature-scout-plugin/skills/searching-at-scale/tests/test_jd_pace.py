"""Contract tests for the JD slow-lane adaptive pace controller."""

from __future__ import annotations

import random
import time
import unittest

from scripts.jd_pace import JdPaceController, PaceParams
from scripts.market_scheduler import EDGE_COOLDOWN_SECONDS


class JdPaceControllerTests(unittest.TestCase):
    def test_default_lane_uses_observed_safe_start_floor_and_cooldown(self) -> None:
        params = PaceParams()

        self.assertEqual(params.initial_interval, 45.0)
        self.assertEqual(params.floor_interval, 30.0)
        self.assertEqual(params.cooldown_seconds, 120.0)
        self.assertEqual(params.down_factor, 0.75)
        self.assertEqual(params.jitter_ratio, 0.35)
        self.assertEqual(EDGE_COOLDOWN_SECONDS, params.cooldown_seconds)

    def test_slow_start_healthy_requests_converge_to_floor(self) -> None:
        now = [1000.0]

        def clock() -> float:
            return now[0]

        controller = JdPaceController(
            PaceParams(
                initial_interval=45.0,
                floor_interval=20.0,
                down_factor=0.75,
            ),
            clock=clock,
            rng=random.Random(0),
        )
        self.assertAlmostEqual(controller.interval_seconds, 45.0)
        for _ in range(8):
            controller.on_healthy()
        self.assertAlmostEqual(controller.interval_seconds, 20.0)
        # Jitter stays inside the advertised band.
        delay = controller.next_delay()
        self.assertGreaterEqual(delay, 15.0)
        self.assertLessEqual(delay, 25.0)

    def test_hard_warning_triggers_cooldown_and_resets_slow_start(self) -> None:
        now = [1000.0]

        def clock() -> float:
            return now[0]

        controller = JdPaceController(
            PaceParams(
                initial_interval=45.0,
                floor_interval=20.0,
                cooldown_seconds=120.0,
            ),
            clock=clock,
            rng=random.Random(0),
        )
        for _ in range(4):
            controller.on_healthy()
        assert controller.interval_seconds < 45.0
        controller.on_warning("browser_rate_limited")
        self.assertTrue(controller.in_cooldown)
        self.assertAlmostEqual(controller.interval_seconds, 45.0)
        # The next delay is the remaining cooldown, not the jittered interval.
        self.assertGreaterEqual(controller.next_delay(), 119.0)

    def test_cooldown_expiry_returns_to_normal_pacing(self) -> None:
        now = [1000.0]

        def clock() -> float:
            return now[0]

        controller = JdPaceController(
            PaceParams(
                initial_interval=45.0,
                floor_interval=20.0,
                cooldown_seconds=120.0,
            ),
            clock=clock,
            rng=random.Random(0),
        )
        controller.on_warning("rate_limited")
        now[0] += 130.0
        self.assertFalse(controller.in_cooldown)
        delay = controller.next_delay()
        self.assertLess(delay, 60.0)

    def test_non_hard_warning_backs_off_without_cooldown(self) -> None:
        now = [1000.0]

        def clock() -> float:
            return now[0]

        controller = JdPaceController(
            PaceParams(initial_interval=30.0, up_factor=2.0),
            clock=clock,
            rng=random.Random(0),
        )
        controller.on_warning("")  # e.g. slow page
        self.assertAlmostEqual(controller.interval_seconds, 60.0)
        self.assertFalse(controller.in_cooldown)

    def test_repeated_empty_pages_back_off(self) -> None:
        now = [1000.0]

        def clock() -> float:
            return now[0]

        controller = JdPaceController(
            PaceParams(initial_interval=30.0, up_factor=2.0, max_empty_streak=2),
            clock=clock,
            rng=random.Random(0),
        )
        controller.on_empty()
        self.assertAlmostEqual(controller.interval_seconds, 30.0)
        controller.on_empty()
        self.assertAlmostEqual(controller.interval_seconds, 60.0)


if __name__ == "__main__":
    unittest.main()
