"""Adaptive pacing for the JD Edge slow lane.

Runs at the platform risk-control ceiling without crossing it: a slow-start
interval converges toward the sustainable request cadence, any warning signal
backs off (and a hard rate-limit enters a session cooldown), and jitter keeps
the request pattern from being clockwork.

This module has no I/O; it is a pure controller the edge session adapter feeds
with per-task health observations.
"""

from __future__ import annotations

from dataclasses import dataclass
import random
import time


HARD_WARNING_CATEGORIES = frozenset(
    {
        "rate_limited",
        "browser_rate_limited",
        "captcha_required",
        "browser_captcha_required",
        "browser_authentication_required",
    }
)


@dataclass(frozen=True)
class PaceParams:
    """Tunables for the slow lane. All durations are in seconds."""

    initial_interval: float = 45.0
    # 2026-08-11 hardened for the scale campaign: humans do not click page-to-page
    # every 20s for a sustained session. A 30s floor keeps ~19 requests inside a
    # 600s window (enough for 5 topics x 2 pages) while staying below JD's
    # behavioral detector; 0.35 jitter widens the natural variance instead of the
    # clockwork 0.25 band that trips "too regular" heuristics.
    floor_interval: float = 30.0
    ceiling_interval: float = 120.0
    cooldown_seconds: float = 120.0
    down_factor: float = 0.75
    up_factor: float = 2.0
    jitter_ratio: float = 0.35
    slow_page_threshold_seconds: float = 15.0
    max_empty_streak: int = 2


class JdPaceController:
    """Slow-start + backoff + cooldown pacing shared by one edge session."""

    def __init__(
        self,
        params: PaceParams | None = None,
        *,
        clock: "Callable[[], float]" = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.params = params if params is not None else PaceParams()
        if (
            not isinstance(self.params.initial_interval, (int, float))
            or self.params.initial_interval <= 0
            or self.params.floor_interval <= 0
            or self.params.ceiling_interval < self.params.floor_interval
        ):
            raise ValueError("pace intervals must be positive and ordered")
        self._clock = clock
        self._rng = rng if rng is not None else random.Random()
        self._interval = float(self.params.initial_interval)
        self._cool_until = 0.0
        self._empty_streak = 0

    @property
    def interval_seconds(self) -> float:
        return self._interval

    @property
    def in_cooldown(self) -> bool:
        return self._clock() < self._cool_until

    def on_healthy(self) -> None:
        """A request returned a ready page with candidates within budget."""
        self._empty_streak = 0
        self._interval = max(
            self.params.floor_interval, self._interval * self.params.down_factor
        )

    def on_warning(
        self,
        category: str = "",
        *,
        slow_seconds: float | None = None,
    ) -> None:
        """Back off after a warning; hard warnings enter a session cooldown."""
        if category in HARD_WARNING_CATEGORIES:
            self._cool_until = max(
                self._cool_until,
                self._clock() + self.params.cooldown_seconds,
            )
            self._interval = float(self.params.initial_interval)
            self._empty_streak = 0
            return
        if slow_seconds is not None and slow_seconds < self.params.slow_page_threshold_seconds:
            return
        self._interval = min(
            self.params.ceiling_interval, self._interval * self.params.up_factor
        )

    def on_empty(self) -> None:
        """A ready page returned zero candidates; repeated empties back off."""
        self._empty_streak += 1
        if self._empty_streak >= self.params.max_empty_streak:
            self._empty_streak = 0
            self.on_warning("")

    def next_delay(self) -> float:
        """Seconds to sleep before the next request (0 means none)."""
        now = self._clock()
        if now < self._cool_until:
            return self._cool_until - now
        jitter = 1.0 + (self._rng.random() * 2.0 - 1.0) * self.params.jitter_ratio
        return max(0.0, self._interval * jitter)

    def reset(self) -> None:
        """Restart slow-start (e.g. after a successful cooldown)."""
        self._interval = float(self.params.initial_interval)
        self._cool_until = 0.0
        self._empty_streak = 0


__all__ = [
    "HARD_WARNING_CATEGORIES",
    "JdPaceController",
    "PaceParams",
]
