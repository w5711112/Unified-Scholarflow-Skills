"""Compact throughput and completion controller for marketplace discovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math


WINDOW_SECONDS = 30.0
TARGET_PER_SECOND = 10.0
MINIMUM_CANDIDATES = 6000
SEARCH_LIMIT_SECONDS = 600.0

_BLOCKING_SOURCE_STATES = frozenset(
    {"blocked", "authentication_required", "captcha_required", "rate_limited"}
)


@dataclass(frozen=True)
class MarketplaceThroughputDecision:
    state: str
    next_action: str
    recent_per_second: float
    average_per_second: float
    duplicate_rate: float
    acceptance_passed: bool


def _number(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _scope_is_complete(
    scope: Mapping[str, object], source_states: Mapping[str, str]
) -> bool:
    recent = scope.get("recent_candidate_additions")
    if not isinstance(recent, Sequence) or isinstance(recent, (str, bytes)):
        return False
    try:
        additions = tuple(_count(value, "recent candidate addition") for value in recent)
    except ValueError:
        return False
    if any(state in _BLOCKING_SOURCE_STATES for state in source_states.values()):
        return False
    api_available = scope.get("api_available") is True
    return (
        scope.get("query_generation_exhausted") is True
        and scope.get("healthy_cursors_open") == 0
        and scope.get("healthy_cursors_blocked") == 0
        and scope.get("edge_plan_completed") is True
        and (not api_available or scope.get("api_cursor_completed") is True)
        and len(additions) >= 3
        and sum(additions[:3]) <= 1
        and scope.get("untried_high_yield_families") == 0
    )


def decide_marketplace_throughput(
    *,
    discovery_seconds: float,
    total_unique_candidates: int,
    recent_window_candidates: int,
    max_zero_gap_seconds: float,
    raw_observations: int,
    source_states: Mapping[str, str],
    scope_evidence: Mapping[str, object],
    search_limit_seconds: float = SEARCH_LIMIT_SECONDS,
    jd_slow_lane: bool = False,
    wall_elapsed_seconds: float | None = None,
) -> MarketplaceThroughputDecision:
    """Choose the next route using only compact aggregate evidence.

    ``jd_slow_lane`` relaxes the zero-gap window and throughput targets so a
    rate-limited marketplace source can crawl at its platform-allowed pace
    without tripping the "slow -> switch source" controller.

    The slow lane paces every request (slow-start 180s -> 90s floor), so most
    of the window is deliberate pacing and ``discovery_seconds`` (pure in-flight
    request time) can never reach ``search_limit_seconds``.  When the caller
    supplies ``wall_elapsed_seconds`` the slow lane gates acceptance on the
    wall-clock window consumed instead -- "ran the whole window at the
    platform-allowed pace with card fields" -- which matches the SKILL's stated
    acceptance for the JD slow lane.
    """
    seconds = _number(discovery_seconds, "discovery_seconds")
    total = _count(total_unique_candidates, "total_unique_candidates")
    recent = _count(recent_window_candidates, "recent_window_candidates")
    zero_gap = _number(max_zero_gap_seconds, "max_zero_gap_seconds")
    raw = _count(raw_observations, "raw_observations")
    if (
        isinstance(search_limit_seconds, bool)
        or not isinstance(search_limit_seconds, (int, float))
        or search_limit_seconds <= 0
    ):
        raise ValueError("search_limit_seconds must be a positive number")
    if not isinstance(source_states, Mapping) or any(
        not isinstance(source, str)
        or not source.strip()
        or not isinstance(status, str)
        or not status.strip()
        for source, status in source_states.items()
    ):
        raise ValueError("source_states must map source names to states")
    if not isinstance(scope_evidence, Mapping):
        raise ValueError("scope_evidence must be a mapping")

    window = WINDOW_SECONDS * (3 if jd_slow_lane else 1)
    target = 1.0 if jd_slow_lane else TARGET_PER_SECOND
    minimum = 60 if jd_slow_lane else MINIMUM_CANDIDATES
    # The slow lane gates its acceptance time on the wall-clock window consumed
    # (pacing is deliberate, not idle), falling back to pure request time when
    # the caller has no monotonic run start.
    gate_seconds = seconds
    if jd_slow_lane and wall_elapsed_seconds is not None:
        gate_seconds = _number(wall_elapsed_seconds, "wall_elapsed_seconds")
    recent_rate = recent / window
    average_rate = 0.0 if gate_seconds == 0 else total / gate_seconds
    duplicate_rate = 0.0 if raw == 0 else max(0.0, 1.0 - total / raw)
    # 慢速车道按平台允许的节奏跑满窗口即达标，不要求绝对速率（用户已确认）。
    rate_satisfied = average_rate >= target
    acceptance = (
        gate_seconds >= float(search_limit_seconds)
        and total >= minimum
        and (rate_satisfied or jd_slow_lane)
        and zero_gap < window
    )

    if gate_seconds >= float(search_limit_seconds):
        state, action = "ten_minute_limit", "stop_time_limit"
    elif _scope_is_complete(scope_evidence, source_states):
        state, action = "deterministic_scope_complete", "stop_scope_complete"
    elif zero_gap >= window:
        state, action = (
            "zero_window",
            "expand_query_family" if jd_slow_lane else "switch_source",
        )
    elif any(
        source_state in _BLOCKING_SOURCE_STATES
        for source_state in source_states.values()
    ):
        state, action = "source_blocked", "cool_blocked_source"
    elif gate_seconds < window:
        state, action = "warmup", "keep_routes"
    elif duplicate_rate >= 0.90 and recent_rate < target:
        state, action = "duplicate_saturation", "change_route_shape"
    elif recent_rate < target:
        state, action = "slow", "expand_query_family"
    else:
        state, action = "healthy", "keep_routes"

    return MarketplaceThroughputDecision(
        state=state,
        next_action=action,
        recent_per_second=recent_rate,
        average_per_second=average_rate,
        duplicate_rate=duplicate_rate,
        acceptance_passed=acceptance,
    )
