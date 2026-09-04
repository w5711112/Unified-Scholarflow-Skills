"""Deterministic global control plane for market-scale URL discovery."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from threading import Lock, RLock
import time
import uuid

if __package__ in {None, ""}:
    skill_root = str(Path(__file__).resolve().parents[1])
    if skill_root not in sys.path:
        sys.path.insert(0, skill_root)

from scripts.aggregate_evidence import (
    BackendConcurrencyState,
    ConcurrencyPolicy,
    ConcurrencySignal,
    CoverageState,
    DiscoveryRound,
    SEARCH_LIMIT_SECONDS,
    advance_concurrency,
    decide_stop,
)
from scripts.build_query_matrix import QueryDimensions, iter_query_matrix, query_batch
from scripts.domestic_marketplace_query import (
    DEFAULT_EDGE_USER_DATA_DIR,
    MarketplaceQueryCursor,
    MarketplaceQueryDimensions,
    query_batch as marketplace_query_batch,
    query_total as marketplace_query_total,
)
from scripts.backend_runner import (
    ADAPTER_REGISTRY,
    Adapter,
    AdapterFailure,
    browser_batch_adapter as browser_batch_ingest_adapter,
    edge_marketplace_session_adapter,
    run_adapter,
    run_adapter_group,
)
from scripts.discover_sitemaps import (
    DEFAULT_PRODUCT_HOSTNAMES,
    DEFAULT_PRODUCT_PATH_HINTS,
    DiscoveryConfig,
    Fetcher,
    fetch_url,
    iter_discovery_events,
)
from scripts.normalize_and_dedupe import (
    BatchSpec,
    SqliteUrlLedger,
    UrlObservation,
    normalize_url,
)
from scripts.marketplace_throughput import (
    WINDOW_SECONDS as MARKETPLACE_WINDOW_SECONDS,
    decide_marketplace_throughput,
)
from scripts.jd_pace import PaceParams
from scripts.jd_continuation import (
    FAMILY_ROTATION_FAILURE_CATEGORIES,
    HARD_JD_FAILURE_CATEGORIES,
    JdPageRequest,
    SOFT_JD_FAILURE_CATEGORIES,
    current_request,
    advance_to_next_topic,
    page_verified,
    recovery_failed,
    soft_failure,
)
from scripts.runtime_manager import RuntimeManager


SCHEMA_VERSION = 2
RUN_KINDS = frozenset({"preflight_probe", "backend_batch", "market_discovery"})
RUN_TYPES = frozenset(
    {
        "quick_direct",
        "open_web_research",
        "catalog_enumeration",
        "bounded_dataset_extract",
    }
)
SUCCESS_STATUSES = frozenset(
    {
        "search_saturated",
        "ten_minute_limit",
        "deterministic_scope_complete",
    }
)
EXECUTABLE_TASK_STATUSES = frozenset({"pending", "leased", "interrupted", "cooling"})
EDGE_COOLDOWN_SECONDS = PaceParams().cooldown_seconds
JD_REQUEST_DEADLINE_SECONDS = 45.0
JD_WALL_CLEANUP_MARGIN_SECONDS = 2.0
ADAPTER_POLICIES: dict[str, dict[str, object]] = {
    "searxng": {"tier": 2, "tiers": [2, 4], "tool_limit": 4, "host_limit": 4},
    "common_crawl": {
        "tier": 1,
        "tiers": [1, 2],
        "tool_limit": 2,
        "host_limit": 2,
    },
    "sitemap": {
        "tier": 4,
        "tiers": [4, 8, 16],
        "tool_limit": 16,
        "host_limit": 16,
    },
    "page": {"tier": 1, "tiers": [1, 2], "tool_limit": 2, "host_limit": 2},
    "dataset": {
        "tier": 4,
        "tiers": [4, 8, 16, 24, 32, 40],
        "tool_limit": 40,
        "host_limit": 40,
    },
    "bulk_api": {
        "tier": 4,
        "tiers": [4, 8, 16, 24, 32, 40],
        "tool_limit": 40,
        "host_limit": 40,
    },
}
DEFAULT_ADAPTER_POLICY: dict[str, object] = {
    "tier": 1,
    "tiers": [1],
    "tool_limit": 1,
    "host_limit": 1,
}


def _default_concurrency(adapter: object) -> dict[str, object]:
    name = _nonempty_text(adapter, "adapter")
    return deepcopy(ADAPTER_POLICIES.get(name, DEFAULT_ADAPTER_POLICY))


def _ensure_task_concurrency(task: dict[str, object]) -> None:
    concurrency = task.get("concurrency")
    if concurrency is None:
        task["concurrency"] = _default_concurrency(task.get("adapter"))
    elif not isinstance(concurrency, Mapping):
        raise ValueError("task concurrency must be a mapping")


def _nonempty_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _text_set(value: object, name: str) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{name} must contain non-empty strings")
    return sorted({item.strip().casefold() for item in value})


def create_run_state(
    config: Mapping[str, object],
    *,
    run_id: str,
    parent: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Create one JSON-compatible discovery state without performing I/O."""
    if not isinstance(config, Mapping):
        raise ValueError("config must be a mapping")
    normalized_run_id = _nonempty_text(run_id, "run_id")
    run_kind = config.get("run_kind", "market_discovery")
    if run_kind not in RUN_KINDS:
        raise ValueError("run_kind must be supported")
    run_type = config.get("run_type", "open_web_research")
    if run_type not in RUN_TYPES:
        raise ValueError("run_type must be supported")
    configured_limit = config.get("search_limit_seconds", SEARCH_LIMIT_SECONDS)
    if (
        isinstance(configured_limit, bool)
        or not isinstance(configured_limit, (int, float))
        or not 1 <= float(configured_limit) <= 3600
    ):
        raise ValueError("search_limit_seconds must be from 1 to 3600")
    normalized_limit = float(configured_limit)
    scope_completion = config.get("scope_completion")
    if scope_completion is not None and not isinstance(scope_completion, Mapping):
        raise ValueError("scope_completion must be a mapping or None")
    configured_ledger = config.get("ledger_path")
    if not isinstance(configured_ledger, (str, os.PathLike)):
        raise ValueError("ledger_path must be a filesystem path")
    ledger_path = str(Path(configured_ledger).resolve())
    scope = _nonempty_text(config.get("scope_fingerprint"), "scope_fingerprint")
    if parent is not None and not isinstance(parent, Mapping):
        raise ValueError("parent must be a mapping or None")
    source_pool = config.get("source_pool", [])
    if not isinstance(source_pool, list) or any(
        not isinstance(task, Mapping) for task in source_pool
    ):
        raise ValueError("source_pool must be a list of mappings")

    state: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": normalized_run_id,
        "parent_run_id": None if parent is None else parent.get("run_id"),
        "run_kind": run_kind,
        "run_type": run_type,
        "search_limit_seconds": normalized_limit,
        "scope_completion": deepcopy(scope_completion),
        "ledger_path": ledger_path,
        "topic": _nonempty_text(config.get("topic"), "topic"),
        "scope_fingerprint": scope,
        "status": "running",
        "time_sessions": {},
        "current_time_session_id": _nonempty_text(
            config.get("time_session_id", f"{normalized_run_id}:session-1"),
            "time_session_id",
        ),
        "applicable_sources": _text_set(
            config.get("applicable_sources", []), "applicable_sources"
        ),
        "attempted_sources": [],
        "query_dimensions": {
            "applicable": _text_set(
                config.get("query_dimensions", []), "query_dimensions"
            ),
            "attempted": [],
        },
        "coverage_gaps": _text_set(
            config.get("coverage_gaps", []), "coverage_gaps"
        ),
        "domain_concentrated": bool(config.get("domain_concentrated", False)),
        "continued_discovery_unlikely_to_change": bool(
            config.get("continued_discovery_unlikely_to_change", False)
        ),
        "rounds": [],
        "source_pool": deepcopy(source_pool),
        "source_templates": deepcopy(config.get("source_templates", [])),
        "query_generation": _query_generation_state(config),
        "marketplace_plan": _marketplace_plan_state(config, run_type=run_type),
        "marketplace_discovery": (
            {
                "enabled": True,
                "total_unique_candidates": 0,
                "recent_activity": [],
                "aligned_windows": [],
                "last_candidate_search_second": None,
                "max_zero_gap_seconds": 0.0,
                "sources": {},
                "scope_summary": {
                    "sources": {},
                    "last_three_candidate_additions": (),
                },
                "scope_evidence": {
                    "query_generation_exhausted": False,
                    "healthy_cursors_open": 0,
                    "healthy_cursors_blocked": 0,
                    "edge_plan_completed": False,
                    "api_available": False,
                    "api_cursor_completed": False,
                    "recent_candidate_additions": (),
                    "untried_high_yield_families": 1,
                },
                "decision": None,
            }
            if run_type == "catalog_enumeration"
            else None
        ),
        "expanded_seed_ids": [],
        "failed_route_ids": [],
        "failures": [],
        "ingested_batch_ids": [],
        "counters": {
            "raw_url_observations": 0,
            "successful_pages": 0,
            "structured_records": 0,
            "unique_urls": 0,
            "previous_verified_objects": 0,
            "new_verified_objects": 0,
            "overlap_verified_objects": 0,
            "invalidated_objects": 0,
            "cumulative_verified_objects": 0,
        },
        "verified_objects": {},
        "invalidations": [],
        "checkpoints": [],
        "backend_runtime": {"peak_inflight": 0, "groups": {}},
        "stop_evidence": None,
    }
    continuation = config.get("jd_continuation")
    if continuation is not None:
        if not isinstance(continuation, Mapping):
            raise ValueError("jd_continuation must be a mapping or None")
        state["jd_continuation"] = deepcopy(dict(continuation))
        state["jd_full_window"] = bool(config.get("jd_full_window", False))
    debug_page_limit = config.get("jd_debug_page_limit")
    if debug_page_limit is not None:
        if (
            isinstance(debug_page_limit, bool)
            or not isinstance(debug_page_limit, int)
            or not 1 <= debug_page_limit <= 512
        ):
            raise ValueError("jd_debug_page_limit must be from 1 to 512")
        state["jd_debug_page_limit"] = debug_page_limit
    wall_deadline = config.get("wall_deadline")
    if wall_deadline is not None:
        if (
            isinstance(wall_deadline, bool)
            or not isinstance(wall_deadline, (int, float))
            or not math.isfinite(float(wall_deadline))
            or float(wall_deadline) <= 0
        ):
            raise ValueError("wall_deadline must be positive and finite")
        state["wall_deadline"] = float(wall_deadline)
    if parent is not None:
        if parent.get("scope_fingerprint") != scope:
            raise ValueError("parent-scope-mismatch")
        inherited = parent.get("verified_objects", {})
        if not isinstance(inherited, Mapping):
            raise ValueError("parent-verified-objects-must-be-a-mapping")
        state["verified_objects"] = deepcopy(dict(inherited))
        state["counters"]["previous_verified_objects"] = len(inherited)
        state["counters"]["cumulative_verified_objects"] = len(inherited)
    by_id = {
        task["task_id"]: task
        for task in state["source_pool"]
    }
    state["source_pool"] = [by_id[task_id] for task_id in sorted(by_id)]
    for task in state["source_pool"]:
        _ensure_task_concurrency(task)
    ensure_query_tasks(state)
    return state


def _finite_nonnegative(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def record_discovery_interval(
    state: dict[str, object],
    start: float,
    end: float,
    *,
    session_id: str | None = None,
) -> None:
    """Merge one active discovery interval within its monotonic-clock session."""
    left = _finite_nonnegative(start, "start")
    right = _finite_nonnegative(end, "end")
    if left > right:
        raise ValueError("discovery interval must satisfy 0 <= start <= end")
    session = _nonempty_text(
        session_id or state.get("current_time_session_id"), "session_id"
    )
    sessions = state.get("time_sessions")
    if not isinstance(sessions, dict):
        raise ValueError("time_sessions must be a mapping")
    existing = sessions.get(session, [])
    if not isinstance(existing, list):
        raise ValueError("time session intervals must be a list")
    intervals = sorted([*existing, [left, right]])
    merged: list[list[float]] = []
    for interval_start, interval_end in intervals:
        interval_start = _finite_nonnegative(interval_start, "interval_start")
        interval_end = _finite_nonnegative(interval_end, "interval_end")
        if interval_start > interval_end:
            raise ValueError("stored discovery interval is reversed")
        if not merged or interval_start > merged[-1][1]:
            merged.append([interval_start, interval_end])
        else:
            merged[-1][1] = max(merged[-1][1], interval_end)
    sessions[session] = merged


def pure_search_seconds(state: Mapping[str, object]) -> float:
    sessions = state.get("time_sessions")
    if not isinstance(sessions, Mapping):
        raise ValueError("time_sessions must be a mapping")
    total = 0.0
    for intervals in sessions.values():
        if not isinstance(intervals, list):
            raise ValueError("time session intervals must be a list")
        for start, end in intervals:
            left = _finite_nonnegative(start, "interval_start")
            right = _finite_nonnegative(end, "interval_end")
            if left > right:
                raise ValueError("stored discovery interval is reversed")
            total += right - left
    return total


def _wall_elapsed_seconds(state: Mapping[str, object]) -> float | None:
    """Return wall-clock seconds since the driver started, when recorded.

    The JD slow lane paces every request, so ``pure_search_seconds`` (in-flight
    request time only) can never reach ``search_limit_seconds``.  The driver
    records ``wall_started_at`` (monotonic) so acceptance can gate on the window
    actually consumed.  ``None`` means the caller did not record a start, and
    the throughput controller falls back to pure request time.
    """
    started = state.get("wall_started_at")
    if (
        isinstance(started, bool)
        or not isinstance(started, (int, float))
        or not math.isfinite(float(started))
    ):
        return None
    return max(0.0, time.perf_counter() - float(started))


def _rounds(state: Mapping[str, object]) -> tuple[DiscoveryRound, ...]:
    raw_rounds = state.get("rounds", [])
    if not isinstance(raw_rounds, list):
        raise ValueError("rounds must be a list")
    return tuple(
        DiscoveryRound(
            query_family=round_["query_family"],
            source_class=round_["source_class"],
            new_valid_urls=round_["new_valid_urls"],
            new_entities=round_["new_entities"],
            new_fields=round_["new_fields"],
            mostly_duplicates=round_["mostly_duplicates"],
        )
        for round_ in raw_rounds
    )


def _coverage(state: Mapping[str, object]) -> CoverageState:
    dimensions = state.get("query_dimensions")
    if not isinstance(dimensions, Mapping):
        raise ValueError("query_dimensions must be a mapping")
    gaps = set(state.get("coverage_gaps", []))
    return CoverageState(
        applicable_query_dimensions=set(dimensions.get("applicable", [])),
        attempted_query_dimensions=set(dimensions.get("attempted", [])),
        unresolved_region_gaps=set(),
        unresolved_language_gaps=set(),
        unresolved_time_gaps=set(),
        unresolved_platform_gaps=gaps,
        domain_concentrated=bool(state.get("domain_concentrated", False)),
        continued_discovery_unlikely_to_change=bool(
            state.get("continued_discovery_unlikely_to_change", False)
        ),
    )


def _has_executable_work(state: Mapping[str, object]) -> bool:
    source_pool = state.get("source_pool", [])
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    return any(
        isinstance(task, Mapping) and task.get("status") in EXECUTABLE_TASK_STATUSES
        for task in source_pool
    )


def _deterministic_scope_complete(state: Mapping[str, object]) -> bool:
    marketplace = state.get("marketplace_discovery")
    if isinstance(marketplace, Mapping):
        decision = marketplace.get("decision")
        if isinstance(decision, Mapping):
            return decision.get("state") == "deterministic_scope_complete"
    if state.get("run_type") != "bounded_dataset_extract":
        return False
    completion = state.get("scope_completion")
    if not isinstance(completion, Mapping):
        return False
    boundary = completion.get("boundary")
    if not isinstance(boundary, str) or not boundary.strip():
        return False
    values: dict[str, int] = {}
    for name in ("expected_pages", "completed_pages", "failed_pages"):
        value = completion.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return False
        values[name] = value
    return (
        values["expected_pages"] > 0
        and values["completed_pages"] == values["expected_pages"]
        and values["failed_pages"] == 0
    )


def _task_id(template: Mapping[str, object], query: str) -> str:
    backend = _nonempty_text(template.get("backend"), "template backend")
    family = _nonempty_text(
        template.get("query_family"), "template query_family"
    )
    identity = f"{backend}\0{family}\0{query}"
    return f"{backend}:{sha256(identity.encode('utf-8')).hexdigest()[:16]}"


def _substitute_query(value: object, query: str) -> object:
    if isinstance(value, str):
        return value.replace("{query}", query)
    if isinstance(value, list):
        return [_substitute_query(item, query) for item in value]
    if isinstance(value, Mapping):
        return {key: _substitute_query(item, query) for key, item in value.items()}
    return deepcopy(value)


def _normalized_query_matrix(matrix: object) -> dict[str, list[str]]:
    if not isinstance(matrix, Mapping):
        raise ValueError("query_matrix must be a mapping")
    allowed = set(QueryDimensions.__dataclass_fields__)
    unknown = set(matrix) - allowed
    if unknown:
        raise ValueError(f"unknown query dimension: {sorted(unknown)[0]}")
    normalized: dict[str, list[str]] = {}
    for name, values in matrix.items():
        if not isinstance(values, list) or any(
            not isinstance(value, str) for value in values
        ):
            raise ValueError(f"{name} must be an array of strings")
        normalized[name] = list(values)
    if "topics" not in normalized:
        raise ValueError("query_matrix requires topics")
    return normalized


def _query_dimensions(matrix: Mapping[str, object]) -> QueryDimensions:
    return QueryDimensions(
        **{name: tuple(values) for name, values in matrix.items()}
    )


def _query_task(
    template: Mapping[str, object], query: str, *, origin: str
) -> dict[str, object]:
    concurrency = template.get("concurrency")
    if concurrency is None:
        concurrency = _default_concurrency(template.get("adapter"))
    elif not isinstance(concurrency, Mapping):
        raise ValueError("source template concurrency must be a mapping")
    payload_template = template.get("payload_template", {})
    if not isinstance(payload_template, Mapping):
        raise ValueError("payload_template must be a mapping")
    return {
        "task_id": _task_id(template, query),
        "source_class": _nonempty_text(
            template.get("source_class"), "template source_class"
        ),
        "backend": _nonempty_text(template.get("backend"), "template backend"),
        "query_family": _nonempty_text(
            template.get("query_family"), "template query_family"
        ),
        "query_dimensions": _text_set(
            template.get("query_dimensions", []), "template query_dimensions"
        ),
        "coverage_targets": _text_set(
            template.get("coverage_targets", []), "template coverage_targets"
        ),
        "adapter": _nonempty_text(template.get("adapter"), "template adapter"),
        "payload": _substitute_query(payload_template, query),
        "status": "pending",
        "score_inputs": {},
        "concurrency": deepcopy(dict(concurrency)),
        "query_origin": origin,
    }


def _query_generation_state(config: Mapping[str, object]) -> dict[str, object] | None:
    matrix = config.get("query_matrix")
    if matrix is None:
        return None
    normalized = _normalized_query_matrix(matrix)
    settings = config.get("query_generation", {})
    if not isinstance(settings, Mapping):
        raise ValueError("query_generation must be a mapping")
    batch_size = settings.get("batch_size", 8)
    max_batch_size = settings.get("max_batch_size", 64)
    low_watermark = settings.get("low_watermark", 4)
    for name, value in (
        ("batch_size", batch_size),
        ("max_batch_size", max_batch_size),
        ("low_watermark", low_watermark),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"query_generation {name} must be a positive integer")
    if max_batch_size > 64 or batch_size > max_batch_size:
        raise ValueError("query_generation batch sizes must satisfy batch <= max <= 64")
    return {
        "matrix": normalized,
        "offset": 0,
        "batch_size": batch_size,
        "max_batch_size": max_batch_size,
        "low_watermark": low_watermark,
        "exhausted": False,
        "last_canonical_yield": None,
        "last_batch_failed": False,
    }


def _marketplace_dimensions(value: object) -> MarketplaceQueryDimensions:
    if not isinstance(value, Mapping):
        raise ValueError("marketplace_plan dimensions must be a mapping")
    allowed = set(MarketplaceQueryDimensions.__dataclass_fields__)
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"unknown marketplace dimension: {sorted(unknown)[0]}")
    normalized: dict[str, object] = {}
    for name in allowed:
        if name == "topic":
            if name not in value:
                raise ValueError("marketplace dimensions requires topic")
            normalized[name] = value[name]
            continue
        raw = value.get(name, [])
        if not isinstance(raw, list):
            raise ValueError(f"marketplace dimension {name} must be an array")
        normalized[name] = tuple(raw)
    return MarketplaceQueryDimensions(**normalized)


def _marketplace_plan_state(
    config: Mapping[str, object], *, run_type: object
) -> dict[str, object] | None:
    raw = config.get("marketplace_plan")
    if raw is None:
        return None
    if run_type != "catalog_enumeration":
        raise ValueError("marketplace_plan requires catalog_enumeration")
    if not isinstance(raw, Mapping):
        raise ValueError("marketplace_plan must be a mapping")
    raw_topic_dimensions = raw.get("topic_dimensions")
    if raw_topic_dimensions is None:
        raw_topic_dimensions = [raw.get("dimensions")]
    if not isinstance(raw_topic_dimensions, list) or not raw_topic_dimensions:
        raise ValueError("marketplace_plan topic_dimensions must be a non-empty array")
    topic_dimensions = [
        _marketplace_dimensions(value) for value in raw_topic_dimensions
    ]
    if len({item.topic.casefold() for item in topic_dimensions}) != len(topic_dimensions):
        raise ValueError("marketplace_plan topics must not contain duplicates")
    dimensions = topic_dimensions[0]
    platforms = raw.get("platforms", ["jd"])
    if not isinstance(platforms, list) or not platforms:
        raise ValueError("marketplace_plan platforms must be a non-empty array")
    normalized_platforms = tuple(platforms)
    topic_totals = {
        platform: [
            marketplace_query_total(item, platforms=(platform,))
            for item in topic_dimensions
        ]
        for platform in normalized_platforms
    }
    totals = {
        platform: sum(topic_totals[platform]) for platform in normalized_platforms
    }
    batch_size = raw.get("batch_size", 8)
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 8 <= batch_size <= 64
    ):
        raise ValueError("marketplace_plan batch_size must be from 8 to 64")
    dimensions_json = {
        name: (
            getattr(dimensions, name)
            if name == "topic"
            else list(getattr(dimensions, name))
        )
        for name in MarketplaceQueryDimensions.__dataclass_fields__
    }
    topic_dimensions_json = [
        {
            name: (
                getattr(item, name)
                if name == "topic"
                else list(getattr(item, name))
            )
            for name in MarketplaceQueryDimensions.__dataclass_fields__
        }
        for item in topic_dimensions
    ]
    return {
        "dimensions": dimensions_json,
        "topic_dimensions": topic_dimensions_json,
        "platforms": list(normalized_platforms),
        "offset": 0,
        "platform_offsets": {platform: 0 for platform in normalized_platforms},
        "platform_totals": totals,
        "topic_offsets": {
            platform: [0 for _ in topic_dimensions]
            for platform in normalized_platforms
        },
        "topic_totals": topic_totals,
        "platform_exhausted": {platform: False for platform in normalized_platforms},
        "batch_size": batch_size,
        "exhausted": False,
        "platform_health": {platform: "healthy" for platform in normalized_platforms},
        "platform_cool_until": {platform: 0.0 for platform in normalized_platforms},
        "platform_recovery_probe": {
            platform: False for platform in normalized_platforms
        },
        "jd_slow_lane": bool(raw.get("jd_slow_lane", False)),
        "last_new_rate": None,
    }


def _marketplace_task(cursor: MarketplaceQueryCursor) -> dict[str, object]:
    cursor_value = {
        "cursor_id": cursor.cursor_id,
        "ordinal": cursor.ordinal,
        "platform": cursor.platform,
        "query_family": cursor.query_family,
        "page_number": cursor.page_number,
        "sort": cursor.sort,
        "category": cursor.category,
        "price_band": cursor.price_band,
    }
    return {
        "task_id": f"searxng:{cursor.cursor_id}",
        "source_class": "search_engine",
        "backend": "searxng",
        "query_family": cursor.query_family,
        "query_dimensions": ["platform", "brand", "specification", "category", "price"],
        "coverage_targets": [f"platform:{cursor.platform}"],
        "adapter": "searxng",
        "payload": {
            "query": cursor.query,
            "query_family": cursor.query_family,
            "engines": list(cursor.engines),
            "pageno": cursor.page_number,
            "language": "zh-CN",
        },
        "status": "pending",
        "score_inputs": {},
        "concurrency": _default_concurrency("searxng"),
        "query_origin": "marketplace",
        "marketplace_cursor": cursor_value,
    }


def _ensure_marketplace_query_tasks(
    state: dict[str, object], plan: dict[str, object]
) -> int:
    source_pool = state.get("source_pool")
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    platforms = plan.get("platforms")
    offsets = plan.get("platform_offsets")
    totals = plan.get("platform_totals")
    topic_offsets = plan.get("topic_offsets")
    topic_totals = plan.get("topic_totals")
    exhausted = plan.get("platform_exhausted")
    health = plan.get("platform_health")
    if not all(
        isinstance(value, dict)
        for value in (offsets, totals, topic_offsets, topic_totals, exhausted, health)
    ) or not isinstance(platforms, list):
        raise ValueError("marketplace_plan state is malformed")
    cool_until = plan.get("platform_cool_until")
    recovery_probe = plan.get("platform_recovery_probe")
    if not isinstance(cool_until, dict) or not isinstance(recovery_probe, dict):
        raise ValueError("marketplace_plan cooldown state must be a mapping")
    # 冷却到期前始终先恢复平台车道，即使此刻没有可执行任务或已 exhaust。
    now = time.perf_counter()
    for platform in platforms:
        if health.get(platform) == "cooling" and float(cool_until.get(platform, 0.0)) <= now:
            health[platform] = "healthy"
            recovery_probe[platform] = True
    active = sum(
        1
        for task in source_pool
        if isinstance(task, Mapping)
        and task.get("query_origin") == "marketplace"
        and task.get("status") in {"pending", "leased", "interrupted"}
    )
    if active or plan.get("exhausted"):
        return 0
    raw_topic_dimensions = plan.get("topic_dimensions")
    if raw_topic_dimensions is None:
        raw_topic_dimensions = [plan.get("dimensions")]
    if not isinstance(raw_topic_dimensions, list) or not raw_topic_dimensions:
        raise ValueError("marketplace_plan topic_dimensions must be a non-empty array")
    dimensions_list = [
        _marketplace_dimensions(value) for value in raw_topic_dimensions
    ]
    existing = {
        task.get("task_id") for task in source_pool if isinstance(task, Mapping)
    }
    limit = int(plan["batch_size"])
    added = 0
    while added < limit:
        progressed = False
        for topic_index, dimensions in enumerate(dimensions_list):
            for platform in platforms:
                if added >= limit:
                    break
                if health.get(platform) != "healthy" or exhausted.get(platform):
                    continue
                platform_topic_offsets = topic_offsets.get(platform)
                platform_topic_totals = topic_totals.get(platform)
                if not isinstance(platform_topic_offsets, list) or not isinstance(platform_topic_totals, list):
                    raise ValueError("marketplace topic counters must be arrays")
                offset = int(platform_topic_offsets[topic_index])
                if offset >= int(platform_topic_totals[topic_index]):
                    continue
                batch = marketplace_query_batch(
                    dimensions,
                    offset=offset,
                    limit=1,
                    platforms=(platform,),
                )
                if not batch:
                    platform_topic_offsets[topic_index] = int(platform_topic_totals[topic_index])
                    continue
                cursor = batch[0]
                platform_topic_offsets[topic_index] = offset + 1
                offsets[platform] = sum(int(value) for value in platform_topic_offsets)
                progressed = True
                task = _marketplace_task(cursor)
                if task["task_id"] not in existing:
                    source_pool.append(task)
                    existing.add(task["task_id"])
                    added += 1
            if added >= limit:
                break
        if not progressed:
            break
    for platform in platforms:
        exhausted[platform] = int(offsets[platform]) >= int(totals[platform])
    plan["offset"] = sum(int(value) for value in offsets.values())
    has_blocked = any(health.get(platform) != "healthy" for platform in platforms)
    plan["exhausted"] = all(bool(exhausted[platform]) for platform in platforms) and not has_blocked
    source_pool.sort(key=lambda task: str(task["task_id"]))
    return added


def expand_query_tasks(config: Mapping[str, object]) -> list[dict[str, object]]:
    """Compatibility helper that expands a caller-requested finite matrix."""
    matrix = config.get("query_matrix")
    templates = config.get("source_templates", [])
    if matrix is None:
        return []
    normalized = _normalized_query_matrix(matrix)
    if not isinstance(templates, list) or any(
        not isinstance(template, Mapping) for template in templates
    ):
        raise ValueError("source_templates must be a list of mappings")
    return [
        _query_task(template, query, origin="compatibility")
        for query in iter_query_matrix(_query_dimensions(normalized))
        for template in templates
    ]


def _edge_task_for_request(
    request: JdPageRequest, *, user_data_dir: str | None = None
) -> dict[str, object]:
    """Materialize exactly one transient Edge task from the continuation head.

    ``user_data_dir`` selects which owned Edge profile runs this request. A run
    uses one profile uniformly; alternating profiles across spaced runs spreads
    JD's behavioral risk budget (each profile is its own slow lane).
    """
    identity = f"jd\0{request.topic}\0{request.query_family}"
    cursor_id = f"jd:{sha256(identity.encode('utf-8')).hexdigest()[:20]}"
    return {
        "task_id": (
            f"edge-continuation:{cursor_id}:page-{request.page_number}:"
            f"attempt-{request.recovery_attempt}"
        ),
        "source_class": "marketplace_list",
        "backend": "edge:jd",
        "query_family": request.query_family,
        "query_dimensions": ["platform"],
        "coverage_targets": ["platform:jd"],
        "adapter": "edge_marketplace",
        "payload": {
            "platform": "jd",
            "query": request.query,
            "query_family": request.query_family,
            "cursor": {
                "cursor_id": cursor_id,
                "ordinal": request.family_index,
                "page_number": request.page_number,
            },
            "user_data_dir": user_data_dir or DEFAULT_EDGE_USER_DATA_DIR,
            "deadline_seconds": JD_REQUEST_DEADLINE_SECONDS,
            "max_items": 1000,
            "session_action": request.session_action,
            "pagination_enabled": True,
        },
        "status": "pending",
        "score_inputs": {},
        "concurrency": {"tier": 1, "tool_limit": 1, "host_limit": 1},
    }


def _has_active_jd_task(state: Mapping[str, object]) -> bool:
    source_pool = state.get("source_pool")
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    return any(
        isinstance(task, Mapping)
        and task.get("adapter") == "edge_marketplace"
        and _task_platform(task) == "jd"
        and task.get("status") in EXECUTABLE_TASK_STATUSES
        for task in source_pool
    )


def _remaining_budget_allows_jd_request(state: Mapping[str, object]) -> bool:
    wall_deadline = state.get("wall_deadline")
    if wall_deadline is None:
        return True
    if (
        isinstance(wall_deadline, bool)
        or not isinstance(wall_deadline, (int, float))
    ):
        raise ValueError("wall_deadline must be numeric")
    required = (
        PaceParams().initial_interval
        + JD_REQUEST_DEADLINE_SECONDS
        + JD_WALL_CLEANUP_MARGIN_SECONDS
    )
    return float(wall_deadline) - time.perf_counter() >= required


def _ensure_jd_continuation_task(state: dict[str, object]) -> int:
    """Lazily materialize only the current JD continuation request."""
    plan = state.get("jd_continuation")
    if not isinstance(plan, dict):
        return 0
    marketplace_plan = state.get("marketplace_plan")
    if isinstance(marketplace_plan, Mapping):
        health = marketplace_plan.get("platform_health")
        if isinstance(health, Mapping) and health.get("jd") != "healthy":
            return 0
    request = current_request(plan)
    if request is None or _has_active_jd_task(state):
        return 0
    debug_page_limit = state.get("jd_debug_page_limit")
    if isinstance(debug_page_limit, int) and request.page_number > debug_page_limit:
        state["jd_debug_page_limit_reached"] = True
        # The cap is a per-topic total: rotate to the next topic instead of
        # leaving the plan parked here (which would idle the whole window for
        # every topic after the first). Materialize the next topic's first page
        # in this same call so multi-topic runs keep flowing.
        advance_to_next_topic(plan)
        request = current_request(plan)
        if request is None:
            return 0
    if not _remaining_budget_allows_jd_request(state):
        state["wall_budget_exhausted"] = True
        return 0
    source_pool = state.get("source_pool")
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    source_pool.append(_edge_task_for_request(request))
    return 1


def ensure_query_tasks(state: dict[str, object]) -> int:
    """Materialize at most one resumable query window below the low watermark."""
    if "jd_continuation" in state:
        if not isinstance(state["jd_continuation"], dict):
            raise ValueError("jd_continuation must be a mapping")
        return _ensure_jd_continuation_task(state)
    marketplace_plan = state.get("marketplace_plan")
    if marketplace_plan is not None:
        if not isinstance(marketplace_plan, dict):
            raise ValueError("marketplace_plan must be a mapping or None")
        return _ensure_marketplace_query_tasks(state, marketplace_plan)
    generation = state.get("query_generation")
    if generation is None:
        return 0
    if not isinstance(generation, dict):
        raise ValueError("query_generation must be a mapping or None")
    source_pool = state.get("source_pool")
    templates = state.get("source_templates")
    if not isinstance(source_pool, list) or not isinstance(templates, list):
        raise ValueError("query task state is malformed")
    active = sum(
        1
        for task in source_pool
        if isinstance(task, Mapping)
        and task.get("query_origin") == "matrix"
        and task.get("status") in {"pending", "leased", "interrupted"}
    )
    if active >= int(generation["low_watermark"]) or generation.get("exhausted"):
        return 0

    batch_size = int(generation["batch_size"])
    canonical_yield = generation.get("last_canonical_yield")
    if generation.get("last_batch_failed"):
        pass
    elif isinstance(canonical_yield, (int, float)) and canonical_yield >= 0.25:
        batch_size = min(int(generation["max_batch_size"]), batch_size * 2)
    elif isinstance(canonical_yield, (int, float)) and canonical_yield < 0.05:
        batch_size = min(8, int(generation["max_batch_size"]))
    generation["batch_size"] = batch_size

    batch = query_batch(
        _query_dimensions(generation["matrix"]),
        offset=int(generation["offset"]),
        limit=batch_size,
    )
    existing = {task["task_id"] for task in source_pool if isinstance(task, Mapping)}
    added = 0
    for query in batch.queries:
        for template in templates:
            task = _query_task(template, query, origin="matrix")
            if task["task_id"] not in existing:
                source_pool.append(task)
                existing.add(task["task_id"])
                added += 1
    source_pool.sort(key=lambda task: str(task["task_id"]))
    generation["offset"] = batch.next_offset
    generation["exhausted"] = batch.exhausted
    generation["last_canonical_yield"] = None
    generation["last_batch_failed"] = False
    return added


def enqueue_feedback_tasks(
    state: dict[str, object], seeds: Sequence[Mapping[str, str]]
) -> int:
    """Expand newly discovered topics once through the configured templates."""
    if isinstance(seeds, (str, bytes)) or not isinstance(seeds, Sequence):
        raise ValueError("seeds must be a sequence")
    templates = state.get("source_templates", [])
    seen = set(state.get("expanded_seed_ids", []))
    source_pool = state.get("source_pool")
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    existing = {task["task_id"] for task in source_pool}
    added = 0
    for seed in seeds:
        if not isinstance(seed, Mapping):
            raise ValueError("feedback seed must be a mapping")
        topic = _nonempty_text(seed.get("topic"), "feedback topic")
        family = _nonempty_text(
            seed.get("query_family"), "feedback query_family"
        )
        seed_id = sha256(
            f"{topic.casefold()}\0{family.casefold()}".encode("utf-8")
        ).hexdigest()
        if seed_id in seen:
            continue
        generated = expand_query_tasks(
            {
                "query_matrix": {"topics": [topic], "qualifiers": [family]},
                "source_templates": templates,
            }
        )
        for task in generated:
            if task["task_id"] not in existing:
                source_pool.append(task)
                existing.add(task["task_id"])
                added += 1
        seen.add(seed_id)
    state["expanded_seed_ids"] = sorted(seen)
    return added


def _task_score(task: Mapping[str, object], unresolved_gaps: set[str]) -> float:
    metrics = task.get("score_inputs", {})
    if not isinstance(metrics, Mapping):
        raise ValueError("score_inputs must be a mapping")
    covered = set(task.get("coverage_targets", []))
    gap_bonus = 20.0 * len(covered & unresolved_gaps)
    return (
        100.0 * float(metrics.get("object_yield", 0.0))
        + 40.0 * float(metrics.get("canonical_yield", 0.0))
        + gap_bonus
        + 10.0 * float(metrics.get("source_diversity", 1.0))
        + min(10.0, float(metrics.get("raw_rate", 0.0)) / 50.0)
        - 30.0 * float(metrics.get("duplicate_rate", 0.0))
        - 40.0 * float(metrics.get("failure_rate", 0.0))
        - 30.0 * float(metrics.get("domain_concentration", 0.0))
        - 10.0 * float(metrics.get("access_cost", 0.0))
    )


def rank_source_tasks(
    state: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    source_pool = state.get("source_pool", [])
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    gaps = set(state.get("coverage_gaps", []))
    plan = state.get("marketplace_plan")
    unavailable_platforms: set[str] = set()
    if isinstance(plan, Mapping):
        health = plan.get("platform_health")
        if isinstance(health, dict):
            unavailable_platforms = {
                str(platform)
                for platform, status in health.items()
                if status != "healthy"
            }
    eligible = [
        task
        for task in source_pool
        if isinstance(task, dict)
        and task.get("status") in {"pending", "interrupted"}
        and not (
            task.get("adapter") == "edge_marketplace"
            and _task_platform(task) in unavailable_platforms
        )
    ]
    return tuple(
        sorted(
            eligible,
            key=lambda task: (-_task_score(task, gaps), _task_rank_identity(task)),
        )
    )


def _task_rank_identity(task: Mapping[str, object]) -> tuple[object, ...]:
    payload = task.get("payload")
    cursor = payload.get("cursor") if isinstance(payload, Mapping) else None
    if task.get("adapter") == "edge_marketplace" and isinstance(cursor, Mapping):
        page_number = cursor.get("page_number")
        ordinal = cursor.get("ordinal")
        sequence_index = task.get("sequence_index")
        if (
            isinstance(page_number, int)
            and not isinstance(page_number, bool)
            and isinstance(ordinal, int)
            and not isinstance(ordinal, bool)
        ):
            return (
                0,
                str(payload.get("platform", "")),
                (
                    0,
                    sequence_index,
                ) if (
                    isinstance(sequence_index, int)
                    and not isinstance(sequence_index, bool)
                    and sequence_index >= 0
                ) else (
                    1,
                    str(cursor.get("cursor_id", "")),
                ),
                str(cursor.get("cursor_id", "")),
                ordinal,
                page_number,
                str(task.get("task_id", "")),
            )
    return (1, str(task.get("task_id", "")))


def select_next_tasks(
    state: dict[str, object], *, max_tasks: int = 1
) -> tuple[dict[str, object], ...]:
    if isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 1:
        raise ValueError("max_tasks must be a positive integer")
    ensure_query_tasks(state)
    ranked = rank_source_tasks(state)
    selected: list[dict[str, object]] = []
    selected_ids: set[str] = set()
    selected_adapters: set[str] = set()
    for task in ranked:
        adapter = _nonempty_text(task.get("adapter"), "adapter")
        if adapter in selected_adapters:
            continue
        selected.append(task)
        selected_ids.add(str(task["task_id"]))
        selected_adapters.add(adapter)
        if len(selected) >= max_tasks:
            break
    if len(selected) < max_tasks:
        for task in ranked:
            task_id = str(task["task_id"])
            if task_id in selected_ids:
                continue
            selected.append(task)
            selected_ids.add(task_id)
            if len(selected) >= max_tasks:
                break
    for task in selected:
        task["status"] = "leased"
        task["attempts"] = int(task.get("attempts", 0)) + 1
        task["lease_id"] = (
            f"{state['run_id']}:{task['task_id']}:{task['attempts']}"
        )
        task["time_session_id"] = state["current_time_session_id"]
        task["lease_started"] = time.perf_counter()
    return tuple(selected)


def _find_task(state: Mapping[str, object], task_id: str) -> dict[str, object]:
    normalized = _nonempty_text(task_id, "task_id")
    source_pool = state.get("source_pool", [])
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    for task in source_pool:
        if isinstance(task, dict) and task.get("task_id") == normalized:
            return task
    raise ValueError("unknown-task-id")


def _plan_jd_slow_lane(state: Mapping[str, object]) -> bool:
    plan = state.get("marketplace_plan")
    if isinstance(plan, Mapping):
        return plan.get("jd_slow_lane") is True
    return False


def _task_platform(task: Mapping[str, object]) -> str | None:
    payload = task.get("payload")
    if isinstance(payload, Mapping) and isinstance(payload.get("platform"), str):
        return payload["platform"]
    cursor = task.get("marketplace_cursor")
    if isinstance(cursor, Mapping) and isinstance(cursor.get("platform"), str):
        return cursor["platform"]
    backend = task.get("backend")
    if isinstance(backend, str) and backend.startswith("edge:"):
        return backend.split(":", 1)[1]
    return None


def _set_platform_cooling(state: dict[str, object], task: Mapping[str, object]) -> None:
    plan = state.get("marketplace_plan")
    platform = _task_platform(task)
    if not isinstance(plan, Mapping) or platform is None:
        return
    health = plan.get("platform_health")
    cool_until = plan.get("platform_cool_until")
    recovery_probe = plan.get("platform_recovery_probe")
    if (
        not isinstance(health, dict)
        or not isinstance(cool_until, dict)
        or not isinstance(recovery_probe, dict)
    ):
        return
    if health.get(platform) == "healthy":
        health[platform] = "cooling"
    cool_until[platform] = max(
        float(cool_until.get(platform, 0.0)),
        time.perf_counter() + EDGE_COOLDOWN_SECONDS,
    )
    recovery_probe[platform] = False


def _set_platform_blocked(state: dict[str, object], task: Mapping[str, object]) -> None:
    plan = state.get("marketplace_plan")
    platform = _task_platform(task)
    if not isinstance(plan, Mapping) or platform is None:
        return
    health = plan.get("platform_health")
    cool_until = plan.get("platform_cool_until")
    recovery_probe = plan.get("platform_recovery_probe")
    if (
        not isinstance(health, dict)
        or not isinstance(cool_until, dict)
        or not isinstance(recovery_probe, dict)
    ):
        return
    health[platform] = "blocked"
    cool_until[platform] = 0.0
    recovery_probe[platform] = False


def apply_channel_signal(
    state: dict[str, object], task_id: str, signal: Mapping[str, object]
) -> None:
    """Apply pressure to one channel without changing unrelated backends."""
    if not isinstance(signal, Mapping):
        raise ValueError("signal must be a mapping")
    task = _find_task(state, task_id)
    concurrency = task.get("concurrency")
    if not isinstance(concurrency, dict):
        raise ValueError("task concurrency must be a mapping")
    captcha_rate = float(signal.get("captcha_rate", 0.0))
    empty_body_rate = float(signal.get("empty_body_rate", 0.0))
    page_pressure = task.get("adapter") == "page" and (
        captcha_rate > 0 or empty_body_rate > 0
    )
    concurrency_signal = ConcurrencySignal(
        rate_limited=bool(signal.get("rate_limited", False) or page_pressure),
        error_rate=max(float(signal.get("error_rate", 0.0)), 0.10 if page_pressure else 0.0),
        latency_ratio=float(signal.get("latency_ratio", 1.0)),
        rate_limit_streak=max(
            int(signal.get("rate_limit_streak", 0)), 2 if page_pressure else 0
        ),
    )
    raw_tiers = concurrency.get("tiers", [24, 32, 40])
    if not isinstance(raw_tiers, (list, tuple)):
        raise ValueError("concurrency tiers must be an array")
    policy = ConcurrencyPolicy(tuple(raw_tiers))
    current = BackendConcurrencyState(
        backend=str(task["backend"]),
        tier=int(concurrency.get("tier", policy.tiers[0])),
        policy=policy,
    )
    transition = advance_concurrency(
        current,
        tool_limit=int(concurrency.get("tool_limit", 40)),
        host_limit=int(concurrency.get("host_limit", 40)),
        signal=concurrency_signal,
        window_complete=True,
    )
    concurrency["tier"] = transition.next_tier
    concurrency["last_action"] = transition.action


def record_task_failure(
    state: dict[str, object],
    task_id: str,
    *,
    error_category: str,
    next_route: Mapping[str, object] | None,
) -> None:
    """Record a failed route and forbid retrying the same route unchanged."""
    task = _find_task(state, task_id)
    category = _nonempty_text(error_category, "error_category")
    route = {
        "backend": task["backend"],
        "query_family": task["query_family"],
        "payload": task["payload"],
    }
    route_id = sha256(
        json.dumps(route, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    failed_route_ids = state.setdefault("failed_route_ids", [])
    if route_id in failed_route_ids:
        raise ValueError("unchanged-failed-route")
    failed_route_ids.append(route_id)
    failures = state.setdefault("failures", [])
    failures.append(
        {
            "task_id": task_id,
            "error_category": category,
            "failed_route_id": route_id,
            "next_route": None if next_route is None else dict(next_route),
        }
    )
    task["status"] = "failed"


SUPPORTED_METRIC_STAGES = frozenset(
    {
        "raw_url_observation",
        "canonical_url",
        "product_candidate",
        "marketplace_candidate",
        "verified_model",
    }
)


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _marketplace_scope_evidence(
    working: Mapping[str, object], scope_summary: Mapping[str, object]
) -> dict[str, object]:
    sources = scope_summary.get("sources", {})
    if not isinstance(sources, Mapping):
        raise ValueError("marketplace cursor sources must be a mapping")
    open_cursors = 0
    blocked_cursors = 0
    edge_attempted = False
    edge_complete = True
    api_available = False
    api_complete = True
    for source, raw_counts in sources.items():
        if not isinstance(source, str) or not isinstance(raw_counts, Mapping):
            raise ValueError("invalid marketplace cursor source summary")
        attempted = _nonnegative_int(raw_counts.get("attempted"), "attempted")
        open_count = _nonnegative_int(raw_counts.get("open"), "open")
        blocked = _nonnegative_int(raw_counts.get("blocked"), "blocked")
        exhausted = _nonnegative_int(raw_counts.get("exhausted"), "exhausted")
        open_cursors += open_count
        blocked_cursors += blocked
        if source.startswith("edge:"):
            edge_attempted = edge_attempted or attempted > 0
            edge_complete = edge_complete and open_count == 0 and blocked == 0
        if source.startswith("jd_api"):
            api_available = True
            api_complete = (
                api_complete
                and attempted > 0
                and exhausted == attempted
                and open_count == 0
                and blocked == 0
            )
    plan = working.get("marketplace_plan")
    generation_exhausted = (
        isinstance(plan, Mapping) and plan.get("exhausted") is True
    )
    recent = scope_summary.get("last_three_candidate_additions", ())
    if not isinstance(recent, (list, tuple)):
        raise ValueError("recent marketplace additions must be an array")
    return {
        "query_generation_exhausted": generation_exhausted,
        "healthy_cursors_open": open_cursors,
        "healthy_cursors_blocked": blocked_cursors,
        "edge_plan_completed": edge_attempted and edge_complete,
        "api_available": api_available,
        "api_cursor_completed": api_available and api_complete,
        "recent_candidate_additions": tuple(
            _nonnegative_int(value, "recent candidate addition") for value in recent
        ),
        "untried_high_yield_families": 0 if generation_exhausted else 1,
    }


def _update_marketplace_discovery(
    working: dict[str, object],
    *,
    task: Mapping[str, object],
    result: Mapping[str, object],
    candidate_additions: int,
    total_unique_candidates: int,
    scope_summary: Mapping[str, object],
    active_intervals: Sequence[Sequence[object]],
) -> None:
    discovery = working.get("marketplace_discovery")
    if not isinstance(discovery, dict) or discovery.get("enabled") is not True:
        raise ValueError("marketplace metric requires catalog_enumeration")
    search_second = pure_search_seconds(working)
    activity = discovery.get("recent_activity")
    if not isinstance(activity, list):
        raise ValueError("marketplace recent activity must be a list")
    source = _nonempty_text(task.get("source_class"), "source_class").casefold()
    if candidate_additions:
        activity.append(
            {
                "search_second": search_second,
                "count": candidate_additions,
                "source": source,
            }
        )
    cutoff = max(0.0, search_second - MARKETPLACE_WINDOW_SECONDS)
    activity[:] = [
        item
        for item in activity
        if isinstance(item, Mapping)
        and float(item.get("search_second", -1.0)) >= cutoff
    ]

    prior_candidate_second = discovery.get("last_candidate_search_second")
    if prior_candidate_second is None:
        zero_gap = search_second
    else:
        zero_gap = search_second - _finite_nonnegative(
            prior_candidate_second, "last_candidate_search_second"
        )
    interval_gap = max(
        (
            _finite_nonnegative(interval[1], "interval end")
            - _finite_nonnegative(interval[0], "interval start")
            for interval in active_intervals
        ),
        default=0.0,
    )
    discovery["max_zero_gap_seconds"] = max(
        _finite_nonnegative(
            discovery.get("max_zero_gap_seconds", 0.0), "max_zero_gap_seconds"
        ),
        zero_gap,
        interval_gap,
    )
    if candidate_additions:
        discovery["last_candidate_search_second"] = search_second

    windows = discovery.get("aligned_windows")
    if not isinstance(windows, list):
        raise ValueError("marketplace aligned windows must be a list")
    window_end = (
        MARKETPLACE_WINDOW_SECONDS
        if search_second == 0
        else math.ceil(search_second / MARKETPLACE_WINDOW_SECONDS)
        * MARKETPLACE_WINDOW_SECONDS
    )
    if windows and windows[-1].get("window_end_second") == window_end:
        windows[-1]["candidate_additions"] += candidate_additions
    else:
        windows.append(
            {
                "window_end_second": window_end,
                "candidate_additions": candidate_additions,
            }
        )
    del windows[:-20]

    source_state = result.get("marketplace_source_state")
    if source_state is None:
        source_state = (
            "blocked"
            if result.get("end_reason") == "failed"
            else "exhausted"
            if result.get("end_reason") == "queue_exhausted"
            else "available"
        )
    allowed_states = {
        "available",
        "cooling",
        "blocked",
        "authentication_required",
        "captcha_required",
        "rate_limited",
        "exhausted",
    }
    if source_state not in allowed_states:
        raise ValueError("unsupported-marketplace-source-state")
    source_totals = discovery.get("sources")
    if not isinstance(source_totals, dict):
        raise ValueError("marketplace sources must be a mapping")
    prior = source_totals.get(source, {})
    if not isinstance(prior, Mapping):
        raise ValueError("marketplace source total must be a mapping")
    source_totals[source] = {
        "state": source_state,
        "batches": int(prior.get("batches", 0)) + 1,
        "raw_observations": int(prior.get("raw_observations", 0))
        + _nonnegative_int(
            result["ledger_counts"].get("raw_url_observations"),
            "raw_url_observations",
        ),
        "candidate_additions": int(prior.get("candidate_additions", 0))
        + candidate_additions,
    }
    evidence = _marketplace_scope_evidence(working, scope_summary)
    recent_candidates = sum(int(item["count"]) for item in activity)
    counters = working.get("counters", {})
    if not isinstance(counters, Mapping):
        raise ValueError("counters must be a mapping")
    decision = decide_marketplace_throughput(
        discovery_seconds=search_second,
        total_unique_candidates=total_unique_candidates,
        recent_window_candidates=recent_candidates,
        max_zero_gap_seconds=discovery["max_zero_gap_seconds"],
        raw_observations=_nonnegative_int(
            counters.get("raw_url_observations"), "raw_url_observations"
        ),
        source_states={
            name: str(values["state"])
            for name, values in source_totals.items()
        },
        scope_evidence=evidence,
        search_limit_seconds=float(working["search_limit_seconds"]),
        jd_slow_lane=_plan_jd_slow_lane(working),
        wall_elapsed_seconds=_wall_elapsed_seconds(working),
    )
    discovery["total_unique_candidates"] = total_unique_candidates
    discovery["scope_summary"] = deepcopy(dict(scope_summary))
    discovery["scope_evidence"] = evidence
    discovery["decision"] = asdict(decision)
    plan = working.get("marketplace_plan")
    if isinstance(plan, dict):
        plan["last_new_rate"] = decision.recent_per_second
        plan["recommended_action"] = decision.next_action


def _refresh_marketplace_decision(state: dict[str, object]) -> None:
    """Recompute the marketplace decision from current state.

    Called by ``evaluate_global_status`` so the slow lane's wall-clock acceptance
    is evaluated against the current wall elapsed, not a stale decision computed
    before a long cooldown consumed the rest of the window.
    """
    discovery = state.get("marketplace_discovery")
    counters = state.get("counters")
    if (
        not isinstance(discovery, dict)
        or discovery.get("enabled") is not True
        or not isinstance(counters, Mapping)
    ):
        return
    sources = discovery.get("sources")
    scope_evidence = discovery.get("scope_evidence")
    if not isinstance(sources, dict) or not isinstance(scope_evidence, Mapping):
        return
    search_second = pure_search_seconds(state)
    cutoff = max(0.0, search_second - MARKETPLACE_WINDOW_SECONDS)
    recent_candidates = sum(
        int(item.get("count", 0))
        for item in discovery.get("recent_activity", [])
        if isinstance(item, Mapping)
        and float(item.get("search_second", -1.0)) >= cutoff
    )
    decision = decide_marketplace_throughput(
        discovery_seconds=search_second,
        total_unique_candidates=_nonnegative_int(
            discovery.get("total_unique_candidates", 0),
            "total_unique_candidates",
        ),
        recent_window_candidates=recent_candidates,
        max_zero_gap_seconds=_finite_nonnegative(
            discovery.get("max_zero_gap_seconds", 0.0), "max_zero_gap_seconds"
        ),
        raw_observations=_nonnegative_int(
            counters.get("raw_url_observations"), "raw_url_observations"
        ),
        source_states={
            name: str(values["state"]) for name, values in sources.items()
        },
        scope_evidence=scope_evidence,
        search_limit_seconds=float(state["search_limit_seconds"]),
        jd_slow_lane=_plan_jd_slow_lane(state),
        wall_elapsed_seconds=_wall_elapsed_seconds(state),
    )
    discovery["decision"] = asdict(decision)
    plan = state.get("marketplace_plan")
    if isinstance(plan, dict):
        plan["last_new_rate"] = decision.recent_per_second
        plan["recommended_action"] = decision.next_action


def cumulative_verified_count(state: Mapping[str, object]) -> int:
    objects = state.get("verified_objects")
    if not isinstance(objects, Mapping):
        raise ValueError("verified_objects must be a mapping")
    return len(objects)


def _validated_evidence(value: object, name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{name} must contain evidence URLs")
    normalized: list[str] = []
    for raw in value:
        canonical = normalize_url(raw) if isinstance(raw, str) else None
        if canonical is None:
            raise ValueError(f"{name} must contain valid HTTP(S) URLs")
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _merge_verified_objects(
    working: dict[str, object], objects: object
) -> tuple[int, int]:
    if not isinstance(objects, list):
        raise ValueError("verified_objects must be a list")
    ledger = working.get("verified_objects")
    if not isinstance(ledger, dict):
        raise ValueError("verified_objects ledger must be a mapping")
    additions = 0
    overlaps = 0
    for item in objects:
        if not isinstance(item, Mapping):
            raise ValueError("verified object must be a mapping")
        object_id = _nonempty_text(item.get("object_id"), "object_id").casefold()
        evidence = _validated_evidence(item.get("evidence"), "object evidence")
        if object_id in ledger:
            overlaps += 1
            prior = ledger[object_id]
            if not isinstance(prior, Mapping):
                raise ValueError("stored verified object must be a mapping")
            merged_evidence = list(prior.get("evidence", []))
            for url in evidence:
                if url not in merged_evidence:
                    merged_evidence.append(url)
            ledger[object_id] = {**dict(prior), **dict(item), "evidence": merged_evidence}
        else:
            additions += 1
            ledger[object_id] = {**dict(item), "object_id": object_id, "evidence": evidence}
    return additions, overlaps


def _apply_invalidations(
    working: dict[str, object], invalidations: object, *, batch_id: str
) -> int:
    if not isinstance(invalidations, list):
        raise ValueError("invalidations must be a list")
    objects = working.get("verified_objects")
    audit = working.get("invalidations")
    if not isinstance(objects, dict) or not isinstance(audit, list):
        raise ValueError("invalid lineage ledgers")
    removed = 0
    for invalidation in invalidations:
        if not isinstance(invalidation, Mapping):
            raise ValueError("invalidation-evidence-required")
        raw_id = invalidation.get("object_id")
        object_id = raw_id.strip().casefold() if isinstance(raw_id, str) else ""
        reason = invalidation.get("reason")
        new_evidence = invalidation.get("new_evidence")
        if (
            not object_id
            or object_id not in objects
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise ValueError("invalidation-evidence-required")
        try:
            evidence = _validated_evidence(new_evidence, "invalidation evidence")
        except ValueError as error:
            raise ValueError("invalidation-evidence-required") from error
        previous = objects.pop(object_id)
        audit.append(
            {
                **dict(invalidation),
                "object_id": object_id,
                "reason": reason.strip(),
                "new_evidence": evidence,
                "batch_id": batch_id,
                "previous_evidence": list(previous.get("evidence", [])),
            }
        )
        removed += 1
    return removed


def _validate_batch_round(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("round must be a mapping")
    round_ = DiscoveryRound(
        query_family=value.get("query_family"),
        source_class=value.get("source_class"),
        new_valid_urls=value.get("new_valid_urls"),
        new_entities=value.get("new_entities"),
        new_fields=value.get("new_fields"),
        mostly_duplicates=value.get("mostly_duplicates"),
    )
    return {
        "query_family": round_.query_family,
        "source_class": round_.source_class,
        "new_valid_urls": round_.new_valid_urls,
        "new_entities": round_.new_entities,
        "new_fields": round_.new_fields,
        "mostly_duplicates": round_.mostly_duplicates,
    }


def _browser_cursor_identity(
    payload: Mapping[str, object],
) -> tuple[str, str, int, str]:
    if not isinstance(payload, Mapping):
        raise ValueError("browser batch must be a mapping")
    platform = _nonempty_text(payload.get("platform"), "browser platform").casefold()
    if platform not in {"jd", "taobao"}:
        raise ValueError("unsupported-browser-marketplace")
    cursor = payload.get("cursor")
    if not isinstance(cursor, Mapping):
        raise ValueError("browser cursor must be a mapping")
    cursor_id = _nonempty_text(cursor.get("cursor_id"), "browser cursor_id")
    page_number = _nonnegative_int(cursor.get("page_number"), "browser page_number")
    if page_number < 1:
        raise ValueError("browser page_number must be positive")
    identity = json.dumps(
        {
            "platform": platform,
            "cursor_id": cursor_id,
            "page_number": page_number,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = sha256(identity.encode("utf-8")).hexdigest()[:24]
    return platform, cursor_id, page_number, digest


def _record_browser_failure_state(
    state: dict[str, object],
    *,
    task: dict[str, object],
    cursor_digest: str,
    failure: AdapterFailure,
    task_status: str = "blocked",
) -> None:
    task["status"] = task_status
    task.pop("lease_started_at", None)
    category_states = {
        "browser_authentication_required": "authentication_required",
        "browser_captcha_required": "captcha_required",
        "captcha_required": "captcha_required",
        "browser_page_structure_changed": "page_structure_changed",
        "browser_rate_limited": "rate_limited",
        "rate_limited": "rate_limited",
        "edge_worker_output_invalid": "cooling",
        "edge_worker_exit_failure": "cooling",
        "edge_worker_timeout": "cooling",
        "edge_remote_debugging_disabled": "unavailable",
        "edge_active_port_invalid": "unavailable",
    }
    if failure.category in SOFT_JD_FAILURE_CATEGORIES:
        source_state = "recovering"
    elif failure.category.startswith("edge_cdp_"):
        source_state = "failed"
    else:
        source_state = category_states.get(failure.category, "blocked")
    failures = state.get("failures")
    if not isinstance(failures, list):
        raise ValueError("failures must be a list")
    failure_key = (task["task_id"], failure.category)
    if not any(
        isinstance(item, Mapping)
        and (item.get("task_id"), item.get("error_category")) == failure_key
        for item in failures
    ):
        failures.append(
            {
                "task_id": task["task_id"],
                "error_category": failure.category,
                "retryable": bool(failure.retryable),
                "cursor_digest": cursor_digest,
            }
        )
    state["attempted_sources"] = sorted(
        set(state.get("attempted_sources", [])) | {"marketplace_list"}
    )
    discovery = state.get("marketplace_discovery")
    if not isinstance(discovery, dict) or discovery.get("enabled") is not True:
        raise ValueError("browser batch requires catalog_enumeration")
    sources = discovery.get("sources")
    if not isinstance(sources, dict):
        raise ValueError("marketplace sources must be a mapping")
    prior = sources.get("marketplace_list", {})
    if not isinstance(prior, Mapping):
        raise ValueError("marketplace source total must be a mapping")
    sources["marketplace_list"] = {
        "state": source_state,
        "batches": int(prior.get("batches", 0)),
        "raw_observations": int(prior.get("raw_observations", 0)),
        "candidate_additions": int(prior.get("candidate_additions", 0)),
        "blocked_attempts": int(prior.get("blocked_attempts", 0)) + 1,
    }
    with SqliteUrlLedger(_nonempty_text(state.get("ledger_path"), "ledger_path")) as ledger:
        scope_summary = ledger.marketplace_scope_summary()
        total_candidates = ledger.marketplace_candidate_count()
    evidence = _marketplace_scope_evidence(state, scope_summary)
    activity = discovery.get("recent_activity", [])
    if not isinstance(activity, list):
        raise ValueError("marketplace recent activity must be a list")
    search_second = pure_search_seconds(state)
    cutoff = max(0.0, search_second - MARKETPLACE_WINDOW_SECONDS)
    recent_candidates = sum(
        int(item.get("count", 0))
        for item in activity
        if isinstance(item, Mapping)
        and float(item.get("search_second", -1.0)) >= cutoff
    )
    counters = state.get("counters")
    if not isinstance(counters, Mapping):
        raise ValueError("counters must be a mapping")
    decision = decide_marketplace_throughput(
        discovery_seconds=search_second,
        total_unique_candidates=total_candidates,
        recent_window_candidates=recent_candidates,
        max_zero_gap_seconds=_finite_nonnegative(
            discovery.get("max_zero_gap_seconds", 0.0), "max_zero_gap_seconds"
        ),
        raw_observations=_nonnegative_int(
            counters.get("raw_url_observations"), "raw_url_observations"
        ),
        source_states={
            name: str(value["state"]) for name, value in sources.items()
        },
        scope_evidence=evidence,
        search_limit_seconds=float(state["search_limit_seconds"]),
        jd_slow_lane=_plan_jd_slow_lane(state),
        wall_elapsed_seconds=_wall_elapsed_seconds(state),
    )
    discovery["total_unique_candidates"] = total_candidates
    discovery["scope_summary"] = scope_summary
    discovery["scope_evidence"] = evidence
    discovery["decision"] = asdict(decision)
    evaluate_global_status(state)


def ingest_browser_batch(
    state: dict[str, object],
    payload: Mapping[str, object],
    *,
    adapter: Adapter = browser_batch_ingest_adapter,
) -> dict[str, object]:
    """Commit one Edge public projection without storing items in scheduler state."""
    if state.get("run_type") != "catalog_enumeration":
        raise ValueError("browser batch requires catalog_enumeration")
    platform, _cursor_id, _page_number, cursor_digest = _browser_cursor_identity(
        payload
    )
    task_id = f"edge-browser:{cursor_digest}"
    lease_id = f"{state['run_id']}:edge-browser:{cursor_digest}"
    if lease_id in state.get("ingested_batch_ids", []):
        return state
    source_pool = state.get("source_pool")
    if not isinstance(source_pool, list):
        raise ValueError("source_pool must be a list")
    matches = [task for task in source_pool if task.get("task_id") == task_id]
    if len(matches) > 1:
        raise ValueError("duplicate-browser-cursor-task")
    if matches:
        task = matches[0]
        if task.get("adapter") != "browser_batch_ingest":
            raise ValueError("browser-cursor-task-conflict")
    else:
        task = {
            "task_id": task_id,
            "source_class": "marketplace_list",
            "backend": f"edge:{platform}",
            "query_family": f"browser-cursor:{cursor_digest}",
            "query_dimensions": ["platform"],
            "coverage_targets": [f"platform:{platform}"],
            "adapter": "browser_batch_ingest",
            "payload": {"cursor_digest": cursor_digest},
            "status": "leased",
            "score_inputs": {},
            "concurrency": _default_concurrency("browser_batch_ingest"),
            "lease_id": lease_id,
        }
        source_pool.append(task)
        source_pool.sort(key=lambda item: str(item["task_id"]))
    task["status"] = "leased"
    task["lease_id"] = lease_id
    envelope = {
        "type": "task-envelope",
        "run_id": state["run_id"],
        "scope_fingerprint": state["scope_fingerprint"],
        "task_id": task_id,
        "lease_id": lease_id,
        "time_session_id": state["current_time_session_id"],
        "adapter": "browser_batch_ingest",
        "payload": payload,
    }
    try:
        result = run_adapter(
            envelope,
            ledger_path=_nonempty_text(state.get("ledger_path"), "ledger_path"),
            adapter=adapter,
        )
    except AdapterFailure as failure:
        evidence_task = {
            **task,
            "query_family": payload.get("query_family", task.get("query_family")),
            "payload": payload,
        }
        if failure.category in HARD_JD_FAILURE_CATEGORIES:
            _set_platform_blocked(state, evidence_task)
        _record_marketplace_recovery_event(
            state,
            evidence_task,
            category=failure.category,
            projection_evidence=failure.projection_evidence,
        )
        _record_browser_failure_state(
            state,
            task=task,
            cursor_digest=cursor_digest,
            failure=failure,
        )
        return state

    round_value = result.get("round")
    cursor = result.get("cursor_evidence")
    counts = result.get("ledger_counts")
    if not all(isinstance(value, Mapping) for value in (round_value, cursor, counts)):
        raise ValueError("browser adapter omitted compact evidence")
    task["query_family"] = _nonempty_text(
        round_value.get("query_family"), "browser query_family"
    )
    cursor_status = _nonempty_text(cursor.get("status"), "browser cursor status")
    ledger_status = "blocked" if cursor_status == "stalled" else cursor_status
    with SqliteUrlLedger(_nonempty_text(state.get("ledger_path"), "ledger_path")) as ledger:
        ledger.record_marketplace_cursor(
            cursor_id=f"{platform}:{cursor_digest}",
            source=f"edge:{platform}",
            query_family=str(task["query_family"]),
            status=ledger_status,
            last_batch_id=str(result["batch_id"]),
            unique_candidate_additions=_nonnegative_int(
                counts.get("unique_candidate_additions"),
                "unique_candidate_additions",
            ),
        )
    if cursor_status == "stalled":
        result["marketplace_source_state"] = "blocked"
    ingest_batch_result(state, result)
    completed_task = _find_task(state, task_id)
    completed_task["status"] = "blocked" if cursor_status == "stalled" else "exhausted"
    evaluate_global_status(state)
    return state


def ingest_batch_result(
    state: dict[str, object], result: Mapping[str, object]
) -> dict[str, object]:
    """Atomically merge one idempotent backend batch into a global run."""
    if not isinstance(result, Mapping):
        raise ValueError("batch result must be a mapping")
    batch_id = _nonempty_text(result.get("batch_id"), "batch_id")
    ingested = state.get("ingested_batch_ids", [])
    if not isinstance(ingested, list):
        raise ValueError("ingested_batch_ids must be a list")
    if batch_id in ingested:
        return state
    if result.get("run_id") != state.get("run_id"):
        raise ValueError("batch-run-mismatch")
    if result.get("scope_fingerprint") != state.get("scope_fingerprint"):
        raise ValueError("batch-scope-mismatch")
    stage = result.get("metric_stage")
    if stage not in SUPPORTED_METRIC_STAGES:
        raise ValueError("unsupported-metric-stage")

    working = deepcopy(state)
    task = _find_task(working, _nonempty_text(result.get("task_id"), "task_id"))
    if task.get("status") not in {"leased", "interrupted"}:
        raise ValueError("batch-task-not-leased")
    if result.get("ledger_committed") is not True:
        raise ValueError("ledger-batch-not-committed")
    if "urls" in result:
        raise ValueError("batch result must not contain urls")
    ledger_counts = result.get("ledger_counts")
    if not isinstance(ledger_counts, Mapping):
        raise ValueError("ledger_counts must be a mapping")
    with SqliteUrlLedger(_nonempty_text(working.get("ledger_path"), "ledger_path")) as ledger:
        committed = ledger.batch_stats(batch_id)
        if committed is None:
            raise ValueError("ledger-batch-not-committed")
        total_unique_urls = ledger.stats().unique_urls
        total_unique_candidates = (
            ledger.marketplace_candidate_count()
            if stage == "marketplace_candidate"
            else None
        )
        marketplace_scope_summary = (
            ledger.marketplace_scope_summary()
            if stage == "marketplace_candidate"
            else None
        )
    if (
        committed.run_id != working.get("run_id")
        or committed.task_id != task.get("task_id")
        or committed.adapter != task.get("adapter")
        or committed.scope_fingerprint != working.get("scope_fingerprint")
    ):
        raise ValueError("ledger-batch-identity-mismatch")
    ledger_raw = _nonnegative_int(
        ledger_counts.get("raw_url_observations"), "raw_url_observations"
    )
    ledger_valid = _nonnegative_int(
        ledger_counts.get("valid_urls"), "valid_urls"
    )
    unique_additions = _nonnegative_int(
        ledger_counts.get("unique_additions"), "unique_additions"
    )
    claimed_total_unique = _nonnegative_int(
        ledger_counts.get("total_unique_urls"), "total_unique_urls"
    )
    if (
        ledger_raw != committed.raw_url_observations
        or ledger_valid != committed.valid_urls
        or unique_additions != committed.unique_additions
        # A backend group can commit later batches before the scheduler ingests
        # this result.  The per-batch counts stay exact, while this cumulative
        # value is a commit-time snapshot that may trail the current ledger.
        or claimed_total_unique > total_unique_urls
    ):
        raise ValueError("ledger-counts-mismatch")
    candidate_additions = 0
    if stage == "marketplace_candidate":
        candidate_additions = _nonnegative_int(
            ledger_counts.get("unique_candidate_additions"),
            "unique_candidate_additions",
        )
        claimed_total_candidates = _nonnegative_int(
            ledger_counts.get("total_unique_candidates"),
            "total_unique_candidates",
        )
        if (
            candidate_additions != committed.unique_candidate_additions
            or total_unique_candidates is None
            or claimed_total_candidates > total_unique_candidates
        ):
            raise ValueError("ledger-candidate-counts-mismatch")
    session_id = _nonempty_text(
        result.get("time_session_id"), "time_session_id"
    )
    intervals = result.get("active_intervals")
    if not isinstance(intervals, list):
        raise ValueError("active_intervals must be a list")
    for interval in intervals:
        if not isinstance(interval, list) or len(interval) != 2:
            raise ValueError("active interval must contain start and end")
        record_discovery_interval(
            working, interval[0], interval[1], session_id=session_id
        )

    telemetry = result.get("telemetry")
    if not isinstance(telemetry, Mapping):
        raise ValueError("telemetry must be a mapping")
    counters = working.get("counters")
    if not isinstance(counters, dict):
        raise ValueError("counters must be a mapping")
    telemetry_raw = _nonnegative_int(
        telemetry.get("raw_url_observations"), "raw_url_observations"
    )
    if telemetry_raw != ledger_raw:
        raise ValueError("ledger-telemetry-count-mismatch")
    counters["raw_url_observations"] = int(
        counters.get("raw_url_observations", 0)
    ) + ledger_raw
    for field in ("successful_pages", "structured_records"):
        counters[field] = int(counters.get(field, 0)) + _nonnegative_int(
            telemetry.get(field), field
        )
    counters["unique_urls"] = total_unique_urls

    additions, overlaps = _merge_verified_objects(
        working, result.get("verified_objects")
    )
    removed = _apply_invalidations(
        working, result.get("invalidations"), batch_id=batch_id
    )
    counters["new_verified_objects"] += additions
    counters["overlap_verified_objects"] += overlaps
    counters["invalidated_objects"] += removed
    counters["cumulative_verified_objects"] = cumulative_verified_count(working)

    round_ = _validate_batch_round(result.get("round"))
    if round_["source_class"].strip().casefold() != str(task["source_class"]).strip().casefold():
        raise ValueError("batch-source-class-mismatch")
    working["rounds"].append(round_)
    working["attempted_sources"] = sorted(
        set(working["attempted_sources"]) | {str(task["source_class"]).casefold()}
    )
    dimensions = working.get("query_dimensions")
    if not isinstance(dimensions, dict):
        raise ValueError("query_dimensions must be a mapping")
    dimensions["attempted"] = sorted(
        set(dimensions.get("attempted", []))
        | {str(value).casefold() for value in task.get("query_dimensions", [])}
    )

    seeds = result.get("new_seeds")
    if not isinstance(seeds, list):
        raise ValueError("new_seeds must be a list")
    enqueue_feedback_tasks(working, seeds)
    end_reason = _nonempty_text(result.get("end_reason"), "end_reason")
    if end_reason != committed.end_reason:
        raise ValueError("ledger-end-reason-mismatch")
    if end_reason == "queue_exhausted":
        task["status"] = "exhausted"
    elif end_reason == "partial":
        task["status"] = "pending"
    elif end_reason == "failed":
        task["status"] = "failed"
    else:
        raise ValueError("unsupported-end-reason")

    if stage == "marketplace_candidate":
        if total_unique_candidates is None or marketplace_scope_summary is None:
            raise ValueError("marketplace ledger summary missing")
        _update_marketplace_discovery(
            working,
            task=task,
            result=result,
            candidate_additions=candidate_additions,
            total_unique_candidates=total_unique_candidates,
            scope_summary=marketplace_scope_summary,
            active_intervals=intervals,
        )

    if "scope_completion" in result:
        completion = result.get("scope_completion")
        if not isinstance(completion, Mapping):
            raise ValueError("scope_completion must be a mapping")
        boundary = _nonempty_text(completion.get("boundary"), "scope boundary")
        working["scope_completion"] = {
            "boundary": boundary,
            "expected_pages": _nonnegative_int(
                completion.get("expected_pages"), "expected_pages"
            ),
            "completed_pages": _nonnegative_int(
                completion.get("completed_pages"), "completed_pages"
            ),
            "failed_pages": _nonnegative_int(
                completion.get("failed_pages"), "failed_pages"
            ),
        }

    elapsed = sum(float(end) - float(start) for start, end in intervals)
    raw_count = _nonnegative_int(
        telemetry.get("raw_url_observations"), "raw_url_observations"
    )
    task["score_inputs"] = {
        "raw_rate": 0.0 if elapsed <= 0 else raw_count / elapsed,
        "canonical_yield": 0.0 if raw_count == 0 else unique_additions / raw_count,
        "object_yield": 0.0 if raw_count == 0 else additions / raw_count,
        "duplicate_rate": 0.0 if raw_count == 0 else 1.0 - unique_additions / raw_count,
        "failure_rate": 0.0,
    }
    if task.get("query_origin") == "matrix":
        generation = working.get("query_generation")
        if not isinstance(generation, dict):
            raise ValueError("matrix task requires query_generation state")
        generation["last_canonical_yield"] = task["score_inputs"][
            "canonical_yield"
        ]
        generation["last_batch_failed"] = end_reason == "failed"
    working["ingested_batch_ids"].append(batch_id)
    working["checkpoints"].append(
        {
            "batch_id": batch_id,
            "task_id": task["task_id"],
            "metric_stage": stage,
            "pure_search_seconds": pure_search_seconds(working),
            "raw_url_observations": counters["raw_url_observations"],
            "unique_urls": counters["unique_urls"],
            "cumulative_verified_objects": counters["cumulative_verified_objects"],
        }
    )
    evaluate_global_status(working)
    state.clear()
    state.update(working)
    return state


def reconcile_committed_batches(state: dict[str, object]) -> dict[str, object]:
    """Replay committed ledger summaries missing from durable JSON state."""
    ledger_path = Path(_nonempty_text(state.get("ledger_path"), "ledger_path"))
    if not ledger_path.exists():
        return state
    ingested = state.get("ingested_batch_ids", [])
    if not isinstance(ingested, list):
        raise ValueError("ingested_batch_ids must be a list")
    with SqliteUrlLedger(ledger_path) as ledger:
        missing = tuple(
            batch
            for batch in ledger.committed_batches()
            if batch.batch_id not in ingested
        )
    for batch in missing:
        result = batch.terminal_summary.get("scheduler_result")
        if result is None:
            continue
        if not isinstance(result, Mapping):
            raise ValueError("invalid-ledger-scheduler-result")
        ingest_batch_result(state, result)
    return state


def evaluate_global_status(state: dict[str, object]) -> str:
    """Evaluate the unified time, saturation, and bounded-scope conditions."""
    counters = state.get("counters", {})
    if not isinstance(counters, Mapping):
        raise ValueError("counters must be a mapping")
    # 用当前墙钟窗口刷新 marketplace 决策，避免长冷却吞掉窗口后读到陈旧决策。
    _refresh_marketplace_decision(state)
    decision = decide_stop(
        discovery_seconds=pure_search_seconds(state),
        unique_urls=int(counters.get("unique_urls", 0)),
        recent_rounds=_rounds(state),
        applicable_sources=set(state.get("applicable_sources", [])),
        attempted_sources=set(state.get("attempted_sources", [])),
        coverage_state=_coverage(state),
        search_limit_seconds=float(state["search_limit_seconds"]),
    )
    marketplace = state.get("marketplace_discovery")
    marketplace_decision = (
        marketplace.get("decision") if isinstance(marketplace, Mapping) else None
    )
    marketplace_state = (
        marketplace_decision.get("state")
        if isinstance(marketplace_decision, Mapping)
        else None
    )
    if (
        marketplace_state == "ten_minute_limit"
        or decision.reason == "ten-minute-search-limit"
    ):
        status = "ten_minute_limit"
    elif marketplace_state == "deterministic_scope_complete":
        status = "deterministic_scope_complete"
    elif isinstance(marketplace, Mapping) and marketplace.get("enabled") is True:
        status = "running" if _has_executable_work(state) else "incomplete_blocked"
    elif decision.reason == "ten-minute-search-limit":
        status = "ten_minute_limit"
    elif _deterministic_scope_complete(state):
        status = "deterministic_scope_complete"
    elif decision.reason == "search-saturated":
        status = "search_saturated"
    elif _has_executable_work(state):
        status = "running"
    else:
        status = "incomplete_blocked"
    state["status"] = status
    if status == "deterministic_scope_complete":
        completion_evidence = state.get("scope_completion")
        if completion_evidence is None and isinstance(marketplace, Mapping):
            completion_evidence = marketplace.get("scope_evidence")
        state["stop_evidence"] = {
            "reason": "deterministic-scope-complete",
            "pure_search_seconds": pure_search_seconds(state),
            "scope_completion": deepcopy(completion_evidence),
        }
    elif status == "ten_minute_limit":
        state["stop_evidence"] = {
            "reason": "ten-minute-search-limit",
            "pure_search_seconds": pure_search_seconds(state),
        }
    elif decision.stop:
        state["stop_evidence"] = {
            "reason": decision.reason,
            "pure_search_seconds": pure_search_seconds(state),
        }
    else:
        state["stop_evidence"] = None
    return status


def finalize_run(state: dict[str, object]) -> dict[str, object]:
    """Finalize only a complete global market-discovery run."""
    if state.get("run_kind") != "market_discovery":
        raise ValueError("only-market-discovery-can-finalize")
    status = evaluate_global_status(state)
    if status not in SUCCESS_STATUSES:
        raise ValueError("global-stop-not-satisfied")
    for task in state.get("source_pool", []):
        if isinstance(task, dict) and task.get("status") in {"leased", "interrupted"}:
            task["status"] = "abandoned"
            for key in (
                "lease_id",
                "time_session_id",
                "lease_started",
                "lease_started_at",
                "interrupted_lease_id",
            ):
                task.pop(key, None)
    with SqliteUrlLedger(_nonempty_text(state.get("ledger_path"), "ledger_path")) as ledger:
        recovery = ledger.marketplace_recovery_summary(
            run_id=_nonempty_text(state.get("run_id"), "run_id")
        )
        state["query_family_counts"] = ledger.marketplace_query_family_counts(
            run_id=_nonempty_text(state.get("run_id"), "run_id")
        )
    state["recoveries"] = recovery["recoveries"]
    state["abandoned_families"] = recovery["abandoned_families"]
    state["hard_blocks"] = recovery["hard_blocks"]
    return state


def migrate_state_v1_to_v2(state: Mapping[str, object]) -> dict[str, object]:
    """Explicitly migrate legacy scheduler state without mutating the caller."""
    if not isinstance(state, Mapping) or state.get("schema_version") != 1:
        raise ValueError("migration-requires-schema-version-1")
    migrated = deepcopy(dict(state))
    migrated["schema_version"] = SCHEMA_VERSION
    migrated["run_type"] = (
        "open_web_research"
        if migrated.get("run_kind") == "market_discovery"
        else "quick_direct"
    )
    migrated["search_limit_seconds"] = SEARCH_LIMIT_SECONDS
    migrated["scope_completion"] = None
    migrated["query_generation"] = None
    migrated["backend_runtime"] = {"peak_inflight": 0, "groups": {}}
    migrated["ledger_path"] = str(
        (
            Path(".codex-runtime")
            / "searching-at-scale"
            / f"{_nonempty_text(migrated.get('run_id'), 'run_id')}.sqlite"
        ).resolve()
    )
    migrated.pop("canonical_urls", None)
    return validate_state(migrated)


def validate_state(state: object) -> dict[str, object]:
    """Validate the durable state shape used by every CLI command."""
    if not isinstance(state, dict):
        raise ValueError("state must be a JSON object")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported-state-schema")
    _nonempty_text(state.get("run_id"), "run_id")
    _nonempty_text(state.get("scope_fingerprint"), "scope_fingerprint")
    if state.get("run_kind") not in RUN_KINDS:
        raise ValueError("unsupported-run-kind")
    if state.get("run_type") not in RUN_TYPES:
        raise ValueError("unsupported-run-type")
    limit = state.get("search_limit_seconds")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, (int, float))
        or not 1 <= float(limit) <= 3600
    ):
        raise ValueError("search_limit_seconds must be from 1 to 3600")
    if state.get("scope_completion") is not None and not isinstance(
        state.get("scope_completion"), Mapping
    ):
        raise ValueError("scope_completion must be a mapping or None")
    _nonempty_text(state.get("ledger_path"), "ledger_path")
    if "canonical_urls" in state:
        raise ValueError("canonical_urls must not be stored in scheduler state")
    if state.get("query_generation") is not None and not isinstance(
        state.get("query_generation"), Mapping
    ):
        raise ValueError("query_generation must be a mapping or None")
    _nonempty_text(
        state.get("current_time_session_id"), "current_time_session_id"
    )
    pure_search_seconds(state)
    for field in (
        "source_pool",
        "ingested_batch_ids",
        "rounds",
        "invalidations",
        "checkpoints",
    ):
        if not isinstance(state.get(field), list):
            raise ValueError(f"{field} must be a list")
    if not isinstance(state.get("counters"), dict):
        raise ValueError("counters must be a mapping")
    runtime = state.get("backend_runtime")
    if runtime is not None and not isinstance(runtime, Mapping):
        raise ValueError("backend_runtime must be a mapping")
    return state


def save_state_atomic(path: Path | str, state: Mapping[str, object]) -> None:
    """Atomically persist one validated state under the caller's scoped path."""
    validated = validate_state(deepcopy(dict(state)))
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(validated, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def load_state(path: Path | str) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid-state-json") from error
    return reconcile_committed_batches(validate_state(payload))


def resume_state(
    state: dict[str, object], *, session_id: str | None = None
) -> dict[str, object]:
    """Start a new monotonic-clock session and make interrupted leases retryable."""
    validate_state(state)
    reconcile_committed_batches(state)
    new_session = _nonempty_text(
        session_id or f"session-{uuid.uuid4().hex}", "session_id"
    )
    for task in state["source_pool"]:
        if isinstance(task, dict) and task.get("status") == "leased":
            task["status"] = "interrupted"
            task["interrupted_lease_id"] = task.get("lease_id")
    state["current_time_session_id"] = new_session
    evaluate_global_status(state)
    return state


def run_builtin_task(
    state: dict[str, object],
    task_id: str,
    *,
    sitemap_fetcher: Fetcher = fetch_url,
) -> dict[str, object]:
    """Execute one leased dependency-free Sitemap task as a backend batch."""
    task = _find_task(state, task_id)
    if task.get("status") != "leased":
        raise ValueError("builtin-task-not-leased")
    if task.get("adapter") != "sitemap":
        raise ValueError("unsupported-builtin-adapter")
    payload = task.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("task payload must be a mapping")
    config = DiscoveryConfig(
        seeds=tuple(payload.get("seeds", ())),
        explicit_sitemaps=tuple(payload.get("explicit_sitemaps", ())),
        scope_mode=str(payload.get("scope_mode", "market")),
        timeout_seconds=float(payload.get("timeout_seconds", 15.0)),
        max_document_bytes=int(payload.get("max_document_bytes", 16 * 1024 * 1024)),
        max_depth=int(payload.get("max_depth", 8)),
        product_path_hints=tuple(
            payload.get("product_path_hints", DEFAULT_PRODUCT_PATH_HINTS)
        ),
        product_hostnames=tuple(
            payload.get("product_hostnames", DEFAULT_PRODUCT_HOSTNAMES)
        ),
    )
    events = list(iter_discovery_events(config, fetcher=sitemap_fetcher))
    if not events or events[-1].get("type") != "summary":
        raise ValueError("sitemap-batch-missing-summary")
    summary = dict(events[-1])
    urls = [
        event["url"]
        for event in events
        if event.get("type") == "url" and isinstance(event.get("url"), str)
    ]
    elapsed = float(summary.get("pure_discovery_seconds", 0.0))
    started = _finite_nonnegative(task.get("lease_started"), "lease_started")
    batch_id = _nonempty_text(task.get("lease_id"), "lease_id")
    spec = BatchSpec(
        batch_id=batch_id,
        run_id=_nonempty_text(state.get("run_id"), "run_id"),
        task_id=_nonempty_text(task.get("task_id"), "task_id"),
        adapter=_nonempty_text(task.get("adapter"), "adapter"),
        scope_fingerprint=_nonempty_text(
            state.get("scope_fingerprint"), "scope_fingerprint"
        ),
    )

    def scheduler_result(
        raw_url_observations: int,
        valid_urls: int,
        unique_additions: int,
        total_unique_urls: int,
    ) -> dict[str, object]:
        return {
            "batch_id": batch_id,
            "task_id": task["task_id"],
            "run_id": state["run_id"],
            "scope_fingerprint": state["scope_fingerprint"],
            "metric_stage": "product_candidate",
            "time_session_id": task["time_session_id"],
            "ledger_committed": True,
            "ledger_counts": {
                "raw_url_observations": raw_url_observations,
                "valid_urls": valid_urls,
                "unique_additions": unique_additions,
                "total_unique_urls": total_unique_urls,
            },
            "active_intervals": [[started, started + elapsed]],
            "verified_objects": [],
            "invalidations": [],
            "new_seeds": [],
            "round": {
                "query_family": task["query_family"],
                "source_class": task["source_class"],
                "new_valid_urls": unique_additions,
                "new_entities": int(summary.get("product_page_candidates", 0)),
                "new_fields": 0,
                "mostly_duplicates": int(summary.get("primary_urls", 0)) == 0,
            },
            "end_reason": "queue_exhausted",
            "telemetry": {
                **summary,
                "raw_url_observations": raw_url_observations,
                "successful_pages": 0,
                "structured_records": 0,
            },
        }

    with SqliteUrlLedger(_nonempty_text(state.get("ledger_path"), "ledger_path")) as ledger:
        committed = ledger.batch_stats(batch_id)
        if committed is None:
            with ledger.batch(spec) as writer:
                unique_additions = 0
                for raw_url in urls:
                    outcome = writer.add(
                        UrlObservation(
                            url=raw_url,
                            title="",
                            snippet="",
                            channels=(str(task["backend"]),),
                            source_class=str(task["source_class"]),
                            query_family=str(task["query_family"]),
                            observed_at=str(time.time()),
                            metadata={},
                        )
                    )
                    unique_additions += int(not outcome.duplicate)
                result = scheduler_result(
                    len(urls),
                    len(urls),
                    unique_additions,
                    ledger.stats().unique_urls,
                )
                writer.finish(
                    {
                        "end_reason": "queue_exhausted",
                        "raw_url_observations": len(urls),
                        "valid_urls": len(urls),
                        "unique_additions": unique_additions,
                        "scheduler_result": result,
                    }
                )
            committed = ledger.batch_stats(batch_id)
        assert committed is not None
        total_unique_urls = ledger.stats().unique_urls
        stored_result = committed.terminal_summary.get("scheduler_result")
    if isinstance(stored_result, Mapping):
        return deepcopy(dict(stored_result))
    return scheduler_result(
        committed.raw_url_observations,
        committed.valid_urls,
        committed.unique_additions,
        total_unique_urls,
    )


def _task_envelope(state: Mapping[str, object], task: Mapping[str, object]) -> dict[str, object]:
    payload = task.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("task payload must be a mapping")
    normalized_payload = deepcopy(dict(payload))
    normalized_payload.setdefault("query_family", task["query_family"])
    if task.get("adapter") != "edge_marketplace":
        normalized_payload.setdefault("source_class", task["source_class"])
    if task.get("adapter") == "common_crawl":
        concurrency = task.get("concurrency", {})
        if not isinstance(concurrency, Mapping):
            raise ValueError("task concurrency must be a mapping")
        normalized_payload.setdefault(
            "workers", min(2, int(concurrency.get("tier", 1)))
        )
    return {
        "type": "task-envelope",
        "run_id": state["run_id"],
        "scope_fingerprint": state["scope_fingerprint"],
        "task_id": task["task_id"],
        "lease_id": task["lease_id"],
        "time_session_id": task["time_session_id"],
        "adapter": task["adapter"],
        "payload": normalized_payload,
    }


def _group_worker_limit(tasks: Sequence[Mapping[str, object]], adapter: str) -> int:
    limits: list[int] = []
    for task in tasks:
        concurrency = task.get("concurrency")
        if not isinstance(concurrency, Mapping):
            raise ValueError("task concurrency must be a mapping")
        limits.append(
            max(
                1,
                min(
                    int(concurrency.get("tier", 1)),
                    int(concurrency.get("tool_limit", 1)),
                    int(concurrency.get("host_limit", 1)),
                ),
            )
        )
    if adapter == "edge_marketplace":
        return 1
    return min(len(tasks), max(limits, default=1))


def _edge_cursor_digest(task: Mapping[str, object]) -> str:
    payload = task.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("edge task payload must be a mapping")
    cursor = payload.get("cursor")
    if not isinstance(cursor, Mapping):
        raise ValueError("edge task cursor must be a mapping")
    identity = json.dumps(
        {
            "platform": payload.get("platform"),
            "cursor": dict(cursor),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(identity.encode("utf-8")).hexdigest()[:24]


def _compact_edge_task(
    state: dict[str, object], task_id: str, cursor_digest: str
) -> None:
    task = _find_task(state, task_id)
    task["payload"] = {"cursor_digest": cursor_digest}
    task["query_family"] = f"edge-cursor:{cursor_digest}"


def _record_jd_continuation_result(
    state: dict[str, object], task: Mapping[str, object], cursor_status: str
) -> None:
    plan = state.get("jd_continuation")
    if not isinstance(plan, dict) or _task_platform(task) != "jd":
        return
    if cursor_status == "advanced":
        page_verified(plan)
    elif cursor_status == "exhausted":
        _record_marketplace_recovery_event(
            state,
            task,
            category="page_exhausted",
            projection_evidence=None,
        )
        recovery_failed(plan, "page_exhausted")


def _record_edge_cursor_result(
    state: dict[str, object], result: Mapping[str, object], ledger_path: Path
) -> str:
    task_id = _nonempty_text(result.get("task_id"), "task_id")
    task = _find_task(state, task_id)
    cursor_digest = _edge_cursor_digest(task)
    cursor = result.get("cursor_evidence")
    counts = result.get("ledger_counts")
    round_value = result.get("round")
    if not all(isinstance(value, Mapping) for value in (cursor, counts, round_value)):
        raise ValueError("edge backend omitted compact cursor evidence")
    cursor_status = _nonempty_text(cursor.get("status"), "cursor status")
    _record_jd_continuation_result(state, task, cursor_status)
    ledger_status = "blocked" if cursor_status == "stalled" else cursor_status
    with SqliteUrlLedger(ledger_path) as ledger:
        ledger.record_marketplace_cursor(
            cursor_id=f"{cursor.get('platform')}:{cursor_digest}",
            source=_nonempty_text(task.get("backend"), "edge backend"),
            query_family=_nonempty_text(
                round_value.get("query_family"), "query_family"
            ),
            status=ledger_status,
            last_batch_id=_nonempty_text(result.get("batch_id"), "batch_id"),
            unique_candidate_additions=_nonnegative_int(
                counts.get("unique_candidate_additions"),
                "unique_candidate_additions",
            ),
        )
    return cursor_digest


def _transition_jd_continuation_failure(
    state: dict[str, object], task: Mapping[str, object], category: str
) -> bool:
    plan = state.get("jd_continuation")
    if not isinstance(plan, dict) or _task_platform(task) != "jd":
        return False
    if category in HARD_JD_FAILURE_CATEGORIES:
        _set_platform_blocked(state, task)
    elif category in SOFT_JD_FAILURE_CATEGORIES:
        soft_failure(plan, category)
    elif category in FAMILY_ROTATION_FAILURE_CATEGORIES:
        recovery_failed(plan, category)
    else:
        return False
    return True


def _record_marketplace_recovery_event(
    state: dict[str, object],
    task: Mapping[str, object],
    *,
    category: str,
    projection_evidence: Mapping[str, object] | None,
) -> bool:
    dispositions = {
        **{value: "retry_same_page" for value in SOFT_JD_FAILURE_CATEGORIES},
        **{value: "rotate_family" for value in FAMILY_ROTATION_FAILURE_CATEGORIES},
        **{value: "hard_block" for value in HARD_JD_FAILURE_CATEGORIES},
    }
    disposition = dispositions.get(category)
    if disposition is None or _task_platform(task) != "jd":
        return False
    payload = task.get("payload")
    if not isinstance(payload, Mapping):
        raise RuntimeError("recovery-evidence-invalid: task payload")
    cursor = payload.get("cursor")
    if not isinstance(cursor, Mapping):
        raise RuntimeError("recovery-evidence-invalid: task cursor")
    platform = _nonempty_text(payload.get("platform"), "recovery platform").casefold()
    query_family = _nonempty_text(
        payload.get("query_family", task.get("query_family")), "recovery query_family"
    )
    page_number = _nonnegative_int(
        cursor.get("page_number"), "recovery page_number"
    )
    plan = state.get("jd_continuation")
    stage: object = (
        plan.get("recovery_stage") if isinstance(plan, Mapping) else "initial"
    )
    attempt: object = plan.get("recovery_attempt") if isinstance(plan, Mapping) else 0
    if projection_evidence is not None:
        if set(projection_evidence) != {
            "platform",
            "requested_page_number",
            "observed_page_number",
            "diagnostics",
        }:
            raise RuntimeError("recovery-evidence-invalid: projection keys")
        diagnostics = projection_evidence.get("diagnostics")
        if not isinstance(diagnostics, Mapping):
            raise RuntimeError("recovery-evidence-invalid: diagnostics")
        if (
            projection_evidence.get("platform") != platform
            or projection_evidence.get("requested_page_number") != page_number
            or projection_evidence.get("observed_page_number") != page_number
        ):
            raise RuntimeError("recovery-evidence-mismatch")
        projected_stage = diagnostics.get("recovery_stage")
        projected_attempt = diagnostics.get("recovery_attempt")
        if stage is not None and (stage, attempt) != (
            projected_stage,
            projected_attempt,
        ):
            raise RuntimeError("recovery-evidence-mismatch")
        stage, attempt = projected_stage, projected_attempt
    try:
        with SqliteUrlLedger(
            _nonempty_text(state.get("ledger_path"), "ledger_path")
        ) as ledger:
            ledger.record_marketplace_recovery(
                run_id=_nonempty_text(state.get("run_id"), "run_id"),
                platform=platform,
                query_family=query_family,
                page_number=page_number,
                recovery_stage=_nonempty_text(stage, "recovery_stage"),
                attempt=_nonnegative_int(attempt, "recovery_attempt"),
                category=category,
                disposition=disposition,
            )
    except Exception as error:
        raise RuntimeError("recovery-ledger-write-failed") from error
    return True


def _record_edge_backend_failure(
    state: dict[str, object], task: Mapping[str, object], failure: AdapterFailure
) -> None:
    task_id = _nonempty_text(task.get("task_id"), "task_id")
    current = _find_task(state, task_id)
    lease_id = _nonempty_text(current.get("lease_id"), "failure lease_id")
    if current.get("handled_failure_lease_id") == lease_id:
        return
    current["handled_failure_lease_id"] = lease_id
    hard_failure = failure.category in HARD_JD_FAILURE_CATEGORIES
    if hard_failure:
        current["status"] = "blocked"
    cursor_digest = _edge_cursor_digest(current)
    if hard_failure:
        _set_platform_blocked(state, current)
    try:
        recovery_recorded = _record_marketplace_recovery_event(
            state,
            current,
            category=failure.category,
            projection_evidence=failure.projection_evidence,
        )
    except Exception:
        if not hard_failure:
            current.pop("handled_failure_lease_id", None)
        raise
    continuation_handled = recovery_recorded
    if recovery_recorded and failure.category not in HARD_JD_FAILURE_CATEGORIES:
        continuation_handled = _transition_jd_continuation_failure(
            state, current, failure.category
        )
    if continuation_handled:
        status = (
            "blocked"
            if hard_failure
            else "failed"
        )
    elif failure.category in {
        "edge_remote_debugging_disabled",
        "edge_active_port_invalid",
    }:
        status = "unavailable"
    elif failure.category in {
        "browser_authentication_required",
        "browser_page_structure_changed",
        "edge_navigation_outside_allowlist",
    }:
        status = "blocked"
    elif failure.category in {
        "rate_limited",
        "browser_rate_limited",
        "captcha_required",
        "browser_captcha_required",
    }:
        status = "blocked"
        _set_platform_blocked(state, current)
    elif failure.category in {
        # 本地数据面瞬态不等同于京东限流；仅短暂冷却后重试同一 cursor。
        "edge_worker_output_invalid",
        "edge_worker_exit_failure",
        "edge_worker_timeout",
    }:
        status = "cooling"
        _set_platform_cooling(state, current)
    else:
        status = "failed"
    _record_browser_failure_state(
        state,
        task=current,
        cursor_digest=cursor_digest,
        failure=failure,
        task_status=status,
    )
    _compact_edge_task(state, task_id, cursor_digest)


def _mark_backend_unavailable(
    state: dict[str, object],
    tasks: Sequence[Mapping[str, object]],
    *,
    category: str,
) -> None:
    normalized_category = _nonempty_text(category, "error category")
    failures = state.setdefault("failures", [])
    if not isinstance(failures, list):
        raise ValueError("failures must be a list")
    for selected in tasks:
        task = _find_task(state, str(selected["task_id"]))
        if task.get("status") == "leased":
            task["status"] = "unavailable"
        failures.append(
            {
                "task_id": task["task_id"],
                "error_category": normalized_category,
                "next_route": "continue_other_backends",
            }
        )


def _bounded_edge_payload(
    payload: Mapping[str, object], *, remaining_seconds: float
) -> dict[str, object]:
    """Cap one Edge request to the unspent pure-search budget."""
    if (
        isinstance(remaining_seconds, bool)
        or not isinstance(remaining_seconds, (int, float))
        or not math.isfinite(float(remaining_seconds))
        or float(remaining_seconds) <= 0
    ):
        raise ValueError("remaining_seconds must be positive and finite")
    current = payload.get("deadline_seconds")
    if (
        isinstance(current, bool)
        or not isinstance(current, (int, float))
        or float(current) <= 0
    ):
        raise ValueError("edge deadline_seconds must be positive")
    bounded = dict(payload)
    bounded["deadline_seconds"] = min(
        float(current), float(remaining_seconds)
    )
    return bounded


def run_backend_tasks(
    state: dict[str, object],
    *,
    max_tasks: int = 8,
    adapters: Mapping[str, Adapter] | None = None,
    runtime_manager_factory: Callable[..., object] = RuntimeManager,
    spool_dir: Path | str | None = None,
    edge_session_adapter: Adapter | None = None,
) -> tuple[dict[str, object], ...]:
    """Lease and execute a bounded set of backend tasks without resident services."""
    validate_state(state)
    if evaluate_global_status(state) in SUCCESS_STATUSES:
        return ()
    selected = select_next_tasks(state, max_tasks=max_tasks)
    if not selected:
        evaluate_global_status(state)
        return ()

    available_adapters = dict(ADAPTER_REGISTRY)
    if adapters is not None:
        if not isinstance(adapters, Mapping):
            raise ValueError("adapters must be a mapping or None")
        available_adapters.update(adapters)
    if edge_session_adapter is not None and not callable(edge_session_adapter):
        raise ValueError("edge_session_adapter must be callable or None")

    ledger_path = Path(_nonempty_text(state.get("ledger_path"), "ledger_path"))
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    owns_spool_dir = spool_dir is None
    if spool_dir is None:
        run_digest = sha256(str(state["run_id"]).encode("utf-8")).hexdigest()[:12]
        target_spool = Path(
            tempfile.mkdtemp(
                prefix=f"sat-{run_digest}-",
                dir=ledger_path.parent,
            )
        )
    else:
        target_spool = Path(spool_dir)
        target_spool.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[dict[str, object]]] = {}
    for task in selected:
        groups.setdefault(str(task["adapter"]), []).append(task)
    results: list[dict[str, object]] = []
    runtime = state.setdefault(
        "backend_runtime", {"peak_inflight": 0, "groups": {}}
    )
    if not isinstance(runtime, dict):
        raise ValueError("backend_runtime must be a mapping")
    runtime_groups = runtime.setdefault("groups", {})
    if not isinstance(runtime_groups, dict):
        raise ValueError("backend_runtime groups must be a mapping")
    state_lock = RLock()
    ledger_commit_lock = Lock()
    runtime_intervals: list[list[float]] = []

    def execute_group(
        adapter_name: str,
        tasks: Sequence[dict[str, object]],
        envelopes: Sequence[Mapping[str, object]],
    ) -> None:
        adapter = available_adapters.get(adapter_name)
        if adapter is None:
            with state_lock:
                _mark_backend_unavailable(
                    state, tasks, category="adapter_unavailable"
                )
            return
        group_telemetry: dict[str, object] = {}

        live_edge_ingested: set[str] = set()
        live_edge_failed: set[str] = set()

        def ingest_live_edge_result(result: dict[str, object]) -> None:
            with state_lock:
                with ledger_commit_lock:
                    cursor_digest = _record_edge_cursor_result(
                        state, result, ledger_path
                    )
                    ingest_batch_result(state, result)
                task_id = str(result["task_id"])
                _find_task(state, task_id)["status"] = "exhausted"
                _compact_edge_task(state, task_id, cursor_digest)
                live_edge_ingested.add(task_id)

        def record_live_edge_activity(
            task_id: str, start: float, end: float, succeeded: bool
        ) -> None:
            if succeeded:
                return
            with state_lock:
                task = _find_task(state, task_id)
                record_discovery_interval(
                    state,
                    start,
                    end,
                    session_id=str(task["time_session_id"]),
                )

        def record_live_edge_failure(
            task_id: str, failure: AdapterFailure
        ) -> None:
            with state_lock:
                task = _find_task(state, task_id)
                _record_edge_backend_failure(state, task, failure)
                if failure.category == "wall_budget_exhausted":
                    state["wall_budget_exhausted"] = True
                live_edge_failed.add(task_id)

        def group_budget_open() -> bool:
            with state_lock:
                wall_deadline = state.get("wall_deadline")
                if (
                    isinstance(wall_deadline, (int, float))
                    and not isinstance(wall_deadline, bool)
                    and time.perf_counter() >= float(wall_deadline)
                ):
                    return False
                if pure_search_seconds(state) >= float(
                    state["search_limit_seconds"]
                ):
                    return False
                if adapter_name != "edge_marketplace":
                    return True
                discovery = state.get("marketplace_discovery")
                decision = (
                    discovery.get("decision")
                    if isinstance(discovery, Mapping)
                    else None
                )
                if not isinstance(decision, Mapping):
                    return True
                action = decision.get("next_action")
                if action == "switch_source":
                    return False
                if action != "cool_blocked_source":
                    return True
                plan = state.get("marketplace_plan")
                recovery = (
                    plan.get("platform_recovery_probe")
                    if isinstance(plan, Mapping)
                    else None
                )
                return isinstance(recovery, Mapping) and any(
                    recovery.get(_task_platform(task)) is True for task in tasks
                )

        def run_group(
            selected_adapter: Adapter, *, budgeted_edge: bool = False
        ) -> tuple[dict[str, object], ...]:
            executing_adapter = selected_adapter
            if budgeted_edge:
                def bounded_adapter(
                    payload: Mapping[str, object],
                ) -> Iterator[Mapping[str, object]]:
                    with state_lock:
                        remaining = max(
                            0.0,
                            float(state["search_limit_seconds"])
                            - pure_search_seconds(state),
                        )
                        plan = state.get("marketplace_plan")
                        recovery = (
                            plan.get("platform_recovery_probe")
                            if isinstance(plan, Mapping)
                            else None
                        )
                        platform = payload.get("platform")
                        if isinstance(recovery, dict) and isinstance(platform, str):
                            recovery[platform] = False
                    if remaining <= 0:
                        raise AdapterFailure(
                            "search_budget_exhausted", retryable=False
                        )
                    yield from selected_adapter(
                        _bounded_edge_payload(
                            payload, remaining_seconds=remaining
                        )
                    )

                consume_active_interval = getattr(
                    selected_adapter, "consume_active_interval", None
                )
                if callable(consume_active_interval):
                    setattr(
                        bounded_adapter,
                        "consume_active_interval",
                        consume_active_interval,
                    )
                executing_adapter = bounded_adapter
            return run_adapter_group(
                envelopes,
                ledger_path=ledger_path,
                adapter=executing_adapter,
                max_workers=_group_worker_limit(tasks, adapter_name),
                spool_dir=target_spool,
                telemetry=group_telemetry,
                result_callback=(
                    ingest_live_edge_result if budgeted_edge else None
                ),
                activity_callback=(
                    record_live_edge_activity if budgeted_edge else None
                ),
                failure_callback=(
                    record_live_edge_failure if budgeted_edge else None
                ),
                should_continue=group_budget_open,
                commit_lock=ledger_commit_lock,
            )

        uses_default_edge_session = (
            adapter_name == "edge_marketplace"
            and adapter is ADAPTER_REGISTRY["edge_marketplace"]
        )
        if uses_default_edge_session:
            try:
                if edge_session_adapter is not None:
                    completed = run_group(
                        edge_session_adapter, budgeted_edge=True
                    )
                else:
                    wall_deadline = state.get("wall_deadline")
                    session_options = (
                        {"wall_deadline": float(wall_deadline)}
                        if isinstance(wall_deadline, (int, float))
                        and not isinstance(wall_deadline, bool)
                        else {}
                    )
                    with edge_marketplace_session_adapter(
                        **session_options
                    ) as session_adapter:
                        completed = run_group(session_adapter, budgeted_edge=True)
            except AdapterFailure as failure:
                with state_lock:
                    for task in tasks:
                        _record_edge_backend_failure(state, task, failure)
                    runtime_groups[adapter_name] = {
                        "max_workers": 1,
                        "peak_inflight": 0,
                        "submitted_tasks": 0,
                        "failures": [
                            {
                                "task_id": task["task_id"],
                                "category": failure.category,
                                "retryable": failure.retryable,
                            }
                            for task in tasks
                        ],
                    }
                return
        else:
            completed = run_group(adapter)
        attempt_intervals = group_telemetry.pop("attempt_intervals", [])
        with state_lock:
            runtime_intervals.extend(
                interval
                for interval in attempt_intervals
                if isinstance(interval, list) and len(interval) == 2
            )
            current_runtime = state.setdefault(
                "backend_runtime", {"peak_inflight": 0, "groups": {}}
            )
            if not isinstance(current_runtime, dict):
                raise ValueError("backend_runtime must be a mapping")
            current_groups = current_runtime.setdefault("groups", {})
            if not isinstance(current_groups, dict):
                raise ValueError("backend_runtime groups must be a mapping")
            current_groups[adapter_name] = group_telemetry
            current_runtime["peak_inflight"] = max(
                int(current_runtime.get("peak_inflight", 0)),
                int(group_telemetry.get("peak_inflight", 0)),
            )
            submitted_count = int(
                group_telemetry.get("submitted_tasks", len(tasks))
            )
            submitted_tasks = list(tasks[:submitted_count])
            for task in tasks[submitted_count:]:
                current = _find_task(state, str(task["task_id"]))
                if current.get("status") == "leased":
                    current["status"] = "pending"
                    current["attempts"] = max(
                        0, int(current.get("attempts", 1)) - 1
                    )
                    for key in ("lease_id", "time_session_id", "lease_started"):
                        current.pop(key, None)
            completed_ids = {str(result["task_id"]) for result in completed}
            for result in completed:
                cursor_digest = None
                task_id = str(result["task_id"])
                with ledger_commit_lock:
                    if (
                        adapter_name == "edge_marketplace"
                        and task_id not in live_edge_ingested
                    ):
                        cursor_digest = _record_edge_cursor_result(
                            state, result, ledger_path
                        )
                    if task_id not in live_edge_ingested:
                        ingest_batch_result(state, result)
                if cursor_digest is not None:
                    _find_task(state, task_id)["status"] = "exhausted"
                    _compact_edge_task(state, task_id, cursor_digest)
                results.append(result)
            failed_tasks = [
                task
                for task in submitted_tasks
                if str(task["task_id"]) not in completed_ids
            ]
            if failed_tasks:
                failure_items = group_telemetry.get("failures", [])
                failure_by_task = {
                    str(item.get("task_id")): item
                    for item in failure_items
                    if isinstance(item, Mapping)
                }
                generic_failures: list[Mapping[str, object]] = []
                for task in failed_tasks:
                    failure_item = failure_by_task.get(str(task["task_id"]))
                    if adapter_name != "edge_marketplace" or failure_item is None:
                        generic_failures.append(task)
                        continue
                    if str(task["task_id"]) in live_edge_failed:
                        continue
                    _record_edge_backend_failure(
                        state,
                        task,
                        AdapterFailure(
                            _nonempty_text(
                                failure_item.get("category"), "error category"
                            ),
                            bool(failure_item.get("retryable", False)),
                        ),
                    )
                if generic_failures:
                    _mark_backend_unavailable(
                        state,
                        generic_failures,
                        category="backend_adapter_failed",
                    )
                    for task in generic_failures:
                        _find_task(state, str(task["task_id"]))[
                            "status"
                        ] = "failed"

    def execute_selected_group(
        adapter_name: str, tasks: Sequence[dict[str, object]]
    ) -> None:
            envelopes = [_task_envelope(state, task) for task in tasks]
            needs_runtime = adapter_name == "searxng" and any(
                not isinstance(envelope["payload"].get("base_url"), str)
                for envelope in envelopes
            )
            if not needs_runtime:
                execute_group(adapter_name, tasks, envelopes)
                return
            try:
                manager = runtime_manager_factory(
                    run_id=str(state["run_id"]), temp_parent=target_spool
                )
                with manager.searxng() as managed:
                    if not bool(getattr(managed, "available", False)):
                        with state_lock:
                            _mark_backend_unavailable(
                                state,
                                tasks,
                                category=str(
                                    getattr(managed, "reason", None)
                                    or "searxng_unavailable"
                                ),
                            )
                        return
                    base_url = getattr(managed, "base_url", None)
                    if not isinstance(base_url, str) or not base_url:
                        with state_lock:
                            _mark_backend_unavailable(
                                state, tasks, category="searxng_unavailable"
                            )
                        return
                    runtime_envelopes = deepcopy(envelopes)
                    for envelope in runtime_envelopes:
                        envelope["payload"]["base_url"] = base_url
                    execute_group(adapter_name, tasks, runtime_envelopes)
            except KeyboardInterrupt:
                raise
            except Exception as error:
                with state_lock:
                    _mark_backend_unavailable(
                        state,
                        tasks,
                        category=f"searxng_runtime_{type(error).__name__.casefold()}",
                    )

    def aggregate_peak_inflight(intervals: Sequence[Sequence[float]]) -> int:
        boundaries: list[tuple[float, int]] = []
        for interval in intervals:
            if len(interval) != 2:
                continue
            boundaries.append((float(interval[0]), 1))
            boundaries.append((float(interval[1]), -1))
        active = 0
        peak = 0
        for _, change in sorted(boundaries, key=lambda item: (item[0], item[1])):
            active += change
            peak = max(peak, active)
        return peak

    try:
        group_items = list(groups.items())
        if len(group_items) == 1:
            execute_selected_group(*group_items[0])
        else:
            with ThreadPoolExecutor(max_workers=len(group_items)) as executor:
                futures = [
                    executor.submit(execute_selected_group, adapter_name, tasks)
                    for adapter_name, tasks in group_items
                ]
                for future in futures:
                    future.result()
        with state_lock:
            current_runtime = state.get("backend_runtime")
            if not isinstance(current_runtime, dict):
                raise ValueError("backend_runtime must be a mapping")
            current_runtime["peak_inflight"] = max(
                int(current_runtime.get("peak_inflight", 0)),
                aggregate_peak_inflight(runtime_intervals),
            )
        order = {
            str(task["task_id"]): index for index, task in enumerate(selected)
        }
        results.sort(key=lambda result: order[str(result["task_id"])])
        evaluate_global_status(state)
        return tuple(results)
    except KeyboardInterrupt:
        for selected_task in selected:
            task = _find_task(state, str(selected_task["task_id"]))
            if task.get("status") == "leased":
                task["status"] = "interrupted"
                task["interrupted_lease_id"] = task.get("lease_id")
        evaluate_global_status(state)
        raise
    except Exception:
        for selected_task in selected:
            task = _find_task(state, str(selected_task["task_id"]))
            if task.get("status") == "leased":
                task["status"] = "interrupted"
                task["interrupted_lease_id"] = task.get("lease_id")
        evaluate_global_status(state)
        raise
    finally:
        if owns_spool_dir:
            try:
                target_spool.rmdir()
            except OSError:
                pass


def status_payload(state: dict[str, object]) -> dict[str, object]:
    status = evaluate_global_status(state)
    payload = {
        "run_id": state["run_id"],
        "run_kind": state["run_kind"],
        "run_type": state["run_type"],
        "search_limit_seconds": state["search_limit_seconds"],
        "status": status,
        "pure_search_seconds": pure_search_seconds(state),
        "global_stop_reason": (
            None
            if state.get("stop_evidence") is None
            else state["stop_evidence"].get("reason")
        ),
        "cumulative_verified_objects": cumulative_verified_count(state),
        "coverage_gaps": state["coverage_gaps"],
        "backend_concurrency": deepcopy(
            state.get("backend_runtime", {"peak_inflight": 0, "groups": {}})
        ),
    }
    discovery = state.get("marketplace_discovery")
    if isinstance(discovery, Mapping) and discovery.get("enabled") is True:
        decision = discovery.get("decision")
        payload["marketplace"] = {
            "unique_candidates": int(
                discovery.get("total_unique_candidates", 0)
            ),
            "recent_per_second": (
                None
                if not isinstance(decision, Mapping)
                else decision.get("recent_per_second")
            ),
            "controller_state": (
                None if not isinstance(decision, Mapping) else decision.get("state")
            ),
            "next_action": (
                None
                if not isinstance(decision, Mapping)
                else decision.get("next_action")
            ),
            "max_zero_gap_seconds": float(
                discovery.get("max_zero_gap_seconds", 0.0)
            ),
        }
    return payload


def _read_json(path: str) -> object:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("invalid-json-input") from error


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Global market discovery scheduler"
    )
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--config", required=True)
    start.add_argument("--state", required=True)
    start.add_argument("--run-id")
    start.add_argument("--parent")

    next_ = commands.add_parser("next")
    next_.add_argument("--state", required=True)
    next_.add_argument("--max-tasks", type=int, default=1)

    ingest = commands.add_parser("ingest")
    ingest.add_argument("--state", required=True)
    ingest.add_argument("--batch-result", required=True)

    browser_ingest = commands.add_parser("ingest-browser-batch")
    browser_ingest.add_argument("--state", required=True)
    browser_ingest.add_argument("--batch", required=True)

    builtins = commands.add_parser("run-builtins")
    builtins.add_argument("--state", required=True)

    backends = commands.add_parser("run-backends")
    backends.add_argument("--state", required=True)
    backends.add_argument("--max-tasks", type=int, default=8)
    backends.add_argument("--spool-dir")

    status = commands.add_parser("status")
    status.add_argument("--state", required=True)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--state", required=True)

    resume = commands.add_parser("resume")
    resume.add_argument("--state", required=True)
    resume.add_argument("--session-id")

    migrate = commands.add_parser("migrate-state")
    migrate.add_argument("--state", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "start":
            config = _read_json(arguments.config)
            if not isinstance(config, Mapping):
                raise ValueError("config must be a JSON object")
            parent = None if arguments.parent is None else load_state(arguments.parent)
            state = create_run_state(
                config,
                run_id=arguments.run_id or f"run-{uuid.uuid4().hex}",
                parent=parent,
            )
            save_state_atomic(arguments.state, state)
            _print_json(status_payload(state))
            return 0

        if arguments.command == "migrate-state":
            legacy = _read_json(arguments.state)
            if not isinstance(legacy, Mapping):
                raise ValueError("state must be a JSON object")
            state = migrate_state_v1_to_v2(legacy)
            save_state_atomic(arguments.state, state)
            _print_json(status_payload(state))
            return 0

        state = load_state(arguments.state)
        if arguments.command == "next":
            status = evaluate_global_status(state)
            if status == "incomplete_blocked":
                _print_json({"tasks": [], **status_payload(state)})
                return 4
            tasks = select_next_tasks(state, max_tasks=arguments.max_tasks)
            save_state_atomic(arguments.state, state)
            _print_json({"tasks": [_task_envelope(state, task) for task in tasks]})
            return 0
        if arguments.command == "ingest":
            result = _read_json(arguments.batch_result)
            if not isinstance(result, Mapping):
                raise ValueError("batch result must be a JSON object")
            ingest_batch_result(state, result)
            save_state_atomic(arguments.state, state)
            _print_json(status_payload(state))
            return 0
        if arguments.command == "ingest-browser-batch":
            batch = _read_json(arguments.batch)
            if not isinstance(batch, Mapping):
                raise ValueError("browser batch must be a JSON object")
            ingest_browser_batch(state, batch)
            save_state_atomic(arguments.state, state)
            _print_json(status_payload(state))
            return 0
        if arguments.command == "run-builtins":
            while True:
                status = evaluate_global_status(state)
                if status in SUCCESS_STATUSES:
                    break
                ranked = rank_source_tasks(state)
                if not ranked:
                    save_state_atomic(arguments.state, state)
                    _print_json(status_payload(state))
                    return 4
                if ranked[0].get("adapter") != "sitemap":
                    break
                task = select_next_tasks(state)[0]
                ingest_batch_result(state, run_builtin_task(state, task["task_id"]))
            save_state_atomic(arguments.state, state)
            _print_json(status_payload(state))
            return 0
        if arguments.command == "run-backends":
            try:
                run_backend_tasks(
                    state,
                    max_tasks=arguments.max_tasks,
                    spool_dir=arguments.spool_dir,
                )
            except KeyboardInterrupt:
                save_state_atomic(arguments.state, state)
                _print_json(status_payload(state))
                return 130
            save_state_atomic(arguments.state, state)
            payload = status_payload(state)
            _print_json(payload)
            return 4 if payload["status"] == "incomplete_blocked" else 0
        if arguments.command == "status":
            payload = status_payload(state)
            save_state_atomic(arguments.state, state)
            _print_json(payload)
            return 0
        if arguments.command == "finalize":
            finalize_run(state)
            save_state_atomic(arguments.state, state)
            _print_json(status_payload(state))
            return 0
        if arguments.command == "resume":
            resume_state(state, session_id=arguments.session_id)
            save_state_atomic(arguments.state, state)
            _print_json(status_payload(state))
            return 0
        raise ValueError("unsupported-command")
    except (OSError, TypeError, ValueError) as error:
        print(str(error), file=sys.stderr)
        if arguments.command == "finalize" and "global-stop-not-satisfied" in str(error):
            return 3
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
