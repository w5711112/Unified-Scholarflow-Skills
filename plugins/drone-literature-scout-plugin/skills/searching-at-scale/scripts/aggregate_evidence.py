"""Pure helpers for discovery stopping, concurrency, evidence, and progress.

The module owns no search state and performs no file or network I/O.  In
particular, volume counters are reported but never used as stop conditions.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
import json
import math
from types import MappingProxyType
from typing import Literal
from urllib.parse import urlsplit


SEARCH_LIMIT_SECONDS = 600.0
StopReason = Literal["search-saturated", "ten-minute-search-limit"]
SourceGrade = Literal["A", "B", "C", "D", "E"]


def _require_nonempty_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")

def _canonical_identity(value: str) -> str:
    return value.strip().casefold()


def _require_count(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_finite_nonnegative(value: object, name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{name} must be a finite non-negative number")


BackendKind = Literal[
    "search", "sitemap", "open_index", "dataset", "bulk_api", "page"
]
ThroughputAction = Literal[
    "continue",
    "add_bulk_backend",
    "switch_query_family",
    "search_only_degraded",
]
BULK_BACKEND_KINDS = frozenset(
    {"sitemap", "open_index", "dataset", "bulk_api"}
)
RAW_URL_TARGET_PER_SECOND = 50.0


@dataclass(frozen=True)
class BackendCapability:
    name: str
    kind: BackendKind
    available: bool
    attempted: bool

    def __post_init__(self) -> None:
        _require_nonempty_text(self.name, "name")
        if self.kind not in {
            "search",
            "sitemap",
            "open_index",
            "dataset",
            "bulk_api",
            "page",
        }:
            raise ValueError("kind must be a supported backend kind")
        if type(self.available) is not bool:
            raise ValueError("available must be a boolean")
        if type(self.attempted) is not bool:
            raise ValueError("attempted must be a boolean")
        object.__setattr__(self, "name", self.name.strip())


@dataclass(frozen=True)
class ThroughputRouteDecision:
    action: ThroughputAction
    target_backend: str | None
    raw_rate: float
    recent_raw_rate: float
    must_disclose: bool
    reason: str


def _observed_rate(count: int, seconds: float, name: str) -> float:
    _require_count(count, name)
    _require_finite_nonnegative(seconds, f"{name}_seconds")
    if seconds == 0:
        if count:
            raise ValueError(f"{name} cannot be positive at zero seconds")
        return 0.0
    return count / seconds


def decide_throughput_route(
    *,
    discovery_seconds: float,
    batches: int,
    raw_url_observations: int,
    recent_window_seconds: float,
    recent_raw_url_observations: int,
    backends: tuple[BackendCapability, ...],
) -> ThroughputRouteDecision:
    """Choose the next discovery route without changing concurrency state."""
    _require_finite_nonnegative(discovery_seconds, "discovery_seconds")
    _require_count(batches, "batches")
    raw_rate = _observed_rate(
        raw_url_observations,
        discovery_seconds,
        "raw_url_observations",
    )
    recent_rate = _observed_rate(
        recent_raw_url_observations,
        recent_window_seconds,
        "recent_raw_url_observations",
    )
    if not isinstance(backends, tuple) or not all(
        isinstance(backend, BackendCapability) for backend in backends
    ):
        raise ValueError("backends must be a tuple of BackendCapability values")

    if discovery_seconds < 5 or batches < 2:
        return ThroughputRouteDecision(
            "continue",
            None,
            raw_rate,
            recent_rate,
            False,
            "warmup",
        )

    target_met = (
        raw_rate >= RAW_URL_TARGET_PER_SECOND
        and recent_rate >= RAW_URL_TARGET_PER_SECOND
    )
    if target_met:
        return ThroughputRouteDecision(
            "continue",
            None,
            raw_rate,
            recent_rate,
            False,
            "target-met",
        )

    must_disclose = discovery_seconds >= 15
    available_bulk = tuple(
        backend
        for backend in backends
        if backend.available and backend.kind in BULK_BACKEND_KINDS
    )
    unused_bulk = sorted(
        (backend for backend in available_bulk if not backend.attempted),
        key=lambda backend: _canonical_identity(backend.name),
    )
    if unused_bulk:
        return ThroughputRouteDecision(
            "add_bulk_backend",
            unused_bulk[0].name,
            raw_rate,
            recent_rate,
            must_disclose,
            "below-target-add-bulk-backend",
        )
    if available_bulk:
        return ThroughputRouteDecision(
            "switch_query_family",
            None,
            raw_rate,
            recent_rate,
            must_disclose,
            "bulk-backends-exhausted",
        )
    return ThroughputRouteDecision(
        "search_only_degraded",
        None,
        raw_rate,
        recent_rate,
        must_disclose,
        "bulk-backend-unavailable",
    )


@dataclass(frozen=True)
class DiscoveryRound:
    query_family: str
    source_class: str
    new_valid_urls: int
    new_entities: int
    new_fields: int
    mostly_duplicates: bool

    def __post_init__(self) -> None:
        _require_nonempty_text(self.query_family, "query_family")
        _require_nonempty_text(self.source_class, "source_class")
        _require_count(self.new_valid_urls, "new_valid_urls")
        _require_count(self.new_entities, "new_entities")
        _require_count(self.new_fields, "new_fields")
        if not isinstance(self.mostly_duplicates, bool):
            raise ValueError("mostly_duplicates must be a boolean")


@dataclass(frozen=True)
class StopDecision:
    stop: bool
    reason: StopReason | None

@dataclass(frozen=True)
class CoverageState:
    applicable_query_dimensions: frozenset[str]
    attempted_query_dimensions: frozenset[str]
    unresolved_region_gaps: frozenset[str]
    unresolved_language_gaps: frozenset[str]
    unresolved_time_gaps: frozenset[str]
    unresolved_platform_gaps: frozenset[str]
    domain_concentrated: bool
    continued_discovery_unlikely_to_change: bool

    def __post_init__(self) -> None:
        set_fields = (
            "applicable_query_dimensions",
            "attempted_query_dimensions",
            "unresolved_region_gaps",
            "unresolved_language_gaps",
            "unresolved_time_gaps",
            "unresolved_platform_gaps",
        )
        for name in set_fields:
            values = getattr(self, name)
            if not isinstance(values, (set, frozenset)) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError(f"{name} must be a set of non-empty strings")
            object.__setattr__(
                self,
                name,
                frozenset(_canonical_identity(value) for value in values),
            )
        if not isinstance(self.domain_concentrated, bool):
            raise ValueError("domain_concentrated must be a boolean")
        if not isinstance(self.continued_discovery_unlikely_to_change, bool):
            raise ValueError(
                "continued_discovery_unlikely_to_change must be a boolean"
            )

    @property
    def saturation_ready(self) -> bool:
        complete_dimensions = (
            bool(self.applicable_query_dimensions)
            and self.applicable_query_dimensions
            <= self.attempted_query_dimensions
        )
        no_gaps = not any(
            (
                self.unresolved_region_gaps,
                self.unresolved_language_gaps,
                self.unresolved_time_gaps,
                self.unresolved_platform_gaps,
            )
        )
        return (
            complete_dimensions
            and no_gaps
            and not self.domain_concentrated
            and self.continued_discovery_unlikely_to_change
        )


def decide_stop(
    *,
    discovery_seconds: float,
    unique_urls: int,
    recent_rounds: tuple[DiscoveryRound, ...],
    applicable_sources: set[str],
    attempted_sources: set[str],
    coverage_state: CoverageState | None = None,
    search_limit_seconds: float = SEARCH_LIMIT_SECONDS,
) -> StopDecision:
    """Return one of the two permitted discovery stop decisions.

    The hard deadline depends only on valid pure-search time.  Volume counters
    are validated for reporting consistency and absent from decision branches.
    Saturation additionally requires explicit, complete coverage telemetry.
    """

    _require_finite_nonnegative(discovery_seconds, "discovery_seconds")
    if isinstance(search_limit_seconds, bool) or not isinstance(
        search_limit_seconds, (int, float)
    ) or search_limit_seconds <= 0:
        raise ValueError("search_limit_seconds must be a positive number")
    if discovery_seconds >= float(search_limit_seconds):
        return StopDecision(True, "ten-minute-search-limit")

    _require_count(unique_urls, "unique_urls")
    if not isinstance(recent_rounds, tuple) or not all(
        isinstance(round_, DiscoveryRound) for round_ in recent_rounds
    ):
        raise ValueError("recent_rounds must be a tuple of DiscoveryRound values")
    canonical_sources: dict[str, frozenset[str]] = {}
    for name, sources in (
        ("applicable_sources", applicable_sources),
        ("attempted_sources", attempted_sources),
    ):
        if not isinstance(sources, set) or any(
            not isinstance(source, str) or not source.strip() for source in sources
        ):
            raise ValueError(f"{name} must be a set of non-empty strings")
        canonical_sources[name] = frozenset(
            _canonical_identity(source) for source in sources
        )
    if coverage_state is not None and not isinstance(coverage_state, CoverageState):
        raise ValueError("coverage_state must be a CoverageState or None")

    last = recent_rounds[-3:]
    canonical_applicable = canonical_sources["applicable_sources"]
    canonical_attempted = canonical_sources["attempted_sources"]
    complete_sources = (
        bool(canonical_applicable)
        and canonical_applicable <= canonical_attempted
    )
    diverse = (
        len({_canonical_identity(round_.query_family) for round_ in last}) == 3
        and len({_canonical_identity(round_.source_class) for round_ in last}) == 3
    )
    empty = all(
        round_.new_valid_urls == 0
        and round_.new_entities == 0
        and round_.new_fields == 0
        and round_.mostly_duplicates
        for round_ in last
    )
    coverage_ready = (
        coverage_state is not None and coverage_state.saturation_ready
    )
    if (
        len(last) == 3
        and complete_sources
        and diverse
        and empty
        and coverage_ready
    ):
        return StopDecision(True, "search-saturated")
    return StopDecision(False, None)


@dataclass(frozen=True)
class ConcurrencySignal:
    rate_limited: bool
    error_rate: float
    latency_ratio: float
    rate_limit_streak: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.rate_limited, bool):
            raise ValueError("rate_limited must be a boolean")
        _require_finite_nonnegative(self.error_rate, "error_rate")
        _require_finite_nonnegative(self.latency_ratio, "latency_ratio")
        if self.error_rate > 1:
            raise ValueError("error_rate must not exceed 1")
        _require_count(self.rate_limit_streak, "rate_limit_streak")


ConcurrencyAction = Literal[
    "hold", "scale-up", "retreat-one-tier", "backoff", "limit-cap",
    "stabilize-after-backoff", "drain-compensation",
]


@dataclass(frozen=True)
class ConcurrencyPolicy:
    tiers: tuple[int, ...] = (24, 32, 40)

    def __post_init__(self) -> None:
        if not isinstance(self.tiers, tuple) or not self.tiers:
            raise ValueError("tiers must be a non-empty tuple")
        if any(
            isinstance(tier, bool) or not isinstance(tier, int) or tier < 1
            for tier in self.tiers
        ):
            raise ValueError("tiers must contain positive integers")
        if tuple(sorted(set(self.tiers))) != self.tiers:
            raise ValueError("tiers must be unique and strictly ascending")


@dataclass(frozen=True)
class CompensationItem:
    query_id: str
    retry_backend: str
    retry_tier: int

    def __post_init__(self) -> None:
        _require_nonempty_text(self.query_id, "query_id")
        _require_nonempty_text(self.retry_backend, "retry_backend")
        if isinstance(self.retry_tier, bool) or self.retry_tier < 1:
            raise ValueError("retry_tier must be a positive integer")


@dataclass(frozen=True)
class BackendConcurrencyState:
    backend: str
    tier: int = 24
    policy: ConcurrencyPolicy = ConcurrencyPolicy()
    stabilizing_after_backoff: bool = False
    window_observations: int = 0
    window_had_material_pressure: bool = False
    compensation_queue: tuple[CompensationItem, ...] = ()
    retained_error_count: int = 0

    def __post_init__(self) -> None:
        _require_nonempty_text(self.backend, "backend")
        if isinstance(self.tier, bool) or not isinstance(self.tier, int) or self.tier < 1:
            raise ValueError("tier must be a positive integer")
        if not isinstance(self.policy, ConcurrencyPolicy):
            raise ValueError("policy must be a ConcurrencyPolicy")
        if not isinstance(self.stabilizing_after_backoff, bool) or not isinstance(
            self.window_had_material_pressure, bool
        ):
            raise ValueError("concurrency state flags must be booleans")
        _require_count(self.window_observations, "window_observations")
        _require_count(self.retained_error_count, "retained_error_count")
        if not isinstance(self.compensation_queue, tuple) or not all(
            isinstance(item, CompensationItem) for item in self.compensation_queue
        ):
            raise ValueError("compensation_queue must contain CompensationItem values")
        ids = [item.query_id for item in self.compensation_queue]
        if len(ids) != len(set(ids)):
            raise ValueError("compensation_queue query IDs must be unique")


@dataclass(frozen=True)
class ConcurrencyTransition:
    state: BackendConcurrencyState
    previous_tier: int
    action: ConcurrencyAction
    enqueued_count: int = 0

    @property
    def next_tier(self) -> int:
        return self.state.tier

    @property
    def enqueue_compensation(self) -> bool:
        return self.enqueued_count > 0

    @property
    def retained_error_count(self) -> int:
        return self.state.retained_error_count

    @property
    def queue_depth(self) -> int:
        return len(self.state.compensation_queue)

    @property
    def retry_backend(self) -> str | None:
        return self.state.compensation_queue[0].retry_backend if self.queue_depth else None

    @property
    def retry_tier(self) -> int | None:
        return self.state.compensation_queue[0].retry_tier if self.queue_depth else None


def _material_pressure(signal: ConcurrencySignal) -> bool:
    return (
        (signal.rate_limited and signal.rate_limit_streak >= 2)
        or signal.error_rate >= 0.10
        or signal.latency_ratio >= 1.50
    )


def _live_limit(tool_limit: int, host_limit: int) -> int:
    for name, value in (("tool_limit", tool_limit), ("host_limit", host_limit)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    return min(tool_limit, host_limit)


def _query_ids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple) or any(
        not isinstance(value, str) or not value.strip() for value in values
    ):
        raise ValueError(f"{name} must be a tuple of non-empty strings")
    ids = tuple(value.strip() for value in values)
    if len(ids) != len(set(ids)):
        raise ValueError(f"{name} must not contain duplicates")
    return ids


def _adjacent_policy_tier(
    policy: ConcurrencyPolicy,
    current: int,
    direction: int,
) -> int:
    if direction > 0:
        return next((tier for tier in policy.tiers if tier > current), current)
    lower = [tier for tier in policy.tiers if tier < current]
    return lower[-1] if lower else max(1, int(current * 0.70))


def _retry_tier(
    current: int,
    live_limit: int,
    alternate_backend: bool,
    policy: ConcurrencyPolicy,
) -> int:
    if alternate_backend:
        return min(current, live_limit)
    lower = _adjacent_policy_tier(policy, current, -1)
    return max(1, min(lower, live_limit))


def _step_tier(
    state: BackendConcurrencyState,
    signal: ConcurrencySignal,
    window_complete: bool,
    live_limit: int,
) -> tuple[int, bool, int, bool, ConcurrencyAction]:
    tier = state.tier
    if tier > live_limit:
        return live_limit, False, 0, False, "limit-cap"

    material = _material_pressure(signal)
    if signal.rate_limited and not material:
        action = "stabilize-after-backoff" if state.stabilizing_after_backoff else "hold"
        return tier, state.stabilizing_after_backoff, state.window_observations, state.window_had_material_pressure, action
    if tier >= state.policy.tiers[-1]:
        if material:
            target = _adjacent_policy_tier(state.policy, tier, -1)
            return min(target, live_limit), True, 0, False, "retreat-one-tier"
        return min(tier, live_limit), False, 0, False, "hold"

    observations = state.window_observations + 1
    pressured = state.window_had_material_pressure or material
    if not window_complete:
        action = "stabilize-after-backoff" if state.stabilizing_after_backoff else "hold"
        return tier, state.stabilizing_after_backoff, observations, pressured, action
    if pressured:
        target = _adjacent_policy_tier(state.policy, tier, -1)
        return target, False, 0, False, "backoff"
    target = _adjacent_policy_tier(state.policy, tier, 1)
    return min(target, live_limit), False, 0, False, "scale-up"


def advance_concurrency(
    state: BackendConcurrencyState,
    tool_limit: int,
    host_limit: int,
    signal: ConcurrencySignal,
    *,
    window_complete: bool,
    failed_query_ids: tuple[str, ...] = (),
    retry_backend: str | None = None,
) -> ConcurrencyTransition:
    """Apply one batch to an explicit per-backend concurrency policy."""

    if not isinstance(state, BackendConcurrencyState):
        raise ValueError("state must be a BackendConcurrencyState")
    if not isinstance(signal, ConcurrencySignal):
        raise ValueError("signal must be a ConcurrencySignal")
    if not isinstance(window_complete, bool):
        raise ValueError("window_complete must be a boolean")
    failed = _query_ids(failed_query_ids, "failed_query_ids")
    if retry_backend is not None:
        _require_nonempty_text(retry_backend, "retry_backend")
    limit = _live_limit(tool_limit, host_limit)

    target_backend = retry_backend.strip() if retry_backend else state.backend
    alternate = target_backend.casefold() != state.backend.casefold()
    retry_tier = _retry_tier(state.tier, limit, alternate, state.policy)
    queue = list(state.compensation_queue)
    queued = {item.query_id for item in queue}
    for query_id in failed:
        if query_id not in queued:
            queue.append(CompensationItem(query_id, target_backend, retry_tier))
            queued.add(query_id)
    enqueued = len(queue) - len(state.compensation_queue)

    tier, recovery, observations, pressured, action = _step_tier(
        state, signal, window_complete, limit
    )
    next_state = BackendConcurrencyState(
        backend=state.backend,
        tier=tier,
        policy=state.policy,
        stabilizing_after_backoff=recovery,
        window_observations=observations,
        window_had_material_pressure=pressured,
        compensation_queue=tuple(queue),
        retained_error_count=state.retained_error_count + len(failed),
    )
    return ConcurrencyTransition(next_state, state.tier, action, enqueued)


def drain_compensation(
    state: BackendConcurrencyState,
    completed_query_ids: tuple[str, ...],
) -> ConcurrencyTransition:
    """Drain completed retries without erasing historical error counts."""

    if not isinstance(state, BackendConcurrencyState):
        raise ValueError("state must be a BackendConcurrencyState")
    completed = _query_ids(completed_query_ids, "completed_query_ids")
    queued = {item.query_id for item in state.compensation_queue}
    if not completed or not set(completed) <= queued:
        raise ValueError("completed_query_ids must name queued queries")
    done = set(completed)
    next_state = replace(
        state,
        compensation_queue=tuple(
            item for item in state.compensation_queue if item.query_id not in done
        ),
    )
    return ConcurrencyTransition(next_state, state.tier, "drain-compensation")
@dataclass(frozen=True)
class EvidenceAtom:
    entity_id: str
    entity_type: str
    field_name: str
    raw_value: object | None
    normalized_value: object | None
    unit: str | None
    valid_at: datetime | None
    observed_at: datetime
    source_url: str
    source_grade: SourceGrade
    derived: bool
    derivation: str | None
    confidence: float
    missing_reason: str | None

    def __post_init__(self) -> None:
        _require_nonempty_text(self.entity_id, "entity_id")
        _require_nonempty_text(self.entity_type, "entity_type")
        _require_nonempty_text(self.field_name, "field_name")
        if self.unit is not None:
            _require_nonempty_text(self.unit, "unit")
        if self.valid_at is not None and not isinstance(self.valid_at, datetime):
            raise ValueError("valid_at must be a datetime or None")
        if not isinstance(self.observed_at, datetime):
            raise ValueError("observed_at must be a datetime")
        _require_nonempty_text(self.source_url, "source_url")
        parsed_url = urlsplit(self.source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("source_url must be an absolute HTTP(S) URL")
        if self.source_grade not in {"A", "B", "C", "D", "E"}:
            raise ValueError("source_grade must be one of A, B, C, D, or E")
        if not isinstance(self.derived, bool):
            raise ValueError("derived must be a boolean")
        if self.derived:
            _require_nonempty_text(self.derivation, "derivation")
        elif self.derivation is not None:
            raise ValueError("derivation requires derived=True")
        _require_finite_nonnegative(self.confidence, "confidence")
        if self.confidence > 1:
            raise ValueError("confidence must not exceed 1")
        if self.missing_reason is not None:
            _require_nonempty_text(self.missing_reason, "missing_reason")


def _immutable_snapshot(
    value: object,
    active_containers: set[int] | None = None,
) -> object:
    """Freeze a value from the explicit evidence-value domain.

    Accepted scalars are exact built-in ``None``, ``bool``, ``int``, finite
    ``float``, and ``str`` values.  Accepted containers are exact built-in
    dictionaries, lists, tuples, sets, frozensets, and mapping proxies.  Both
    mapping keys and values are recursively validated and frozen.  Arbitrary
    objects and subclasses are rejected without invoking copy protocols.
    """

    value_type = type(value)
    if value is None or value_type in {bool, int, str}:
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError("evidence numeric values must be finite")
        return value

    is_mapping = value_type in {dict, MappingProxyType}
    is_sequence = value_type in {list, tuple}
    is_set = value_type in {set, frozenset}
    if not (is_mapping or is_sequence or is_set):
        raise ValueError(
            f"unsupported evidence value type: {value_type.__name__}"
        )

    if active_containers is None:
        active_containers = set()
    identity = id(value)
    if identity in active_containers:
        raise ValueError("cyclic evidence values are not supported")
    active_containers.add(identity)
    try:
        if is_mapping:
            frozen: dict[object, object] = {}
            for key, item in value.items():
                frozen_key = _immutable_snapshot(key, active_containers)
                try:
                    hash(frozen_key)
                except TypeError as error:
                    raise ValueError(
                        "evidence mapping keys must freeze to hashable values"
                    ) from error
                if frozen_key in frozen:
                    raise ValueError(
                        "evidence mapping keys collide after canonical freezing"
                    )
                frozen[frozen_key] = _immutable_snapshot(
                    item, active_containers
                )
            return MappingProxyType(frozen)
        if is_sequence:
            return tuple(
                _immutable_snapshot(item, active_containers) for item in value
            )
        return frozenset(
            _immutable_snapshot(item, active_containers) for item in value
        )
    finally:
        active_containers.remove(identity)


def aggregate_fields(
    atoms: Iterable[EvidenceAtom],
) -> Mapping[str, Mapping[str, tuple[EvidenceAtom, ...]]]:
    """Return a lossless, deeply immutable evidence snapshot."""

    grouped: dict[str, dict[str, list[EvidenceAtom]]] = {}
    for atom in atoms:
        if not isinstance(atom, EvidenceAtom):
            raise ValueError("atoms must contain only EvidenceAtom values")
        snapshot = replace(
            atom,
            raw_value=_immutable_snapshot(atom.raw_value),
            normalized_value=_immutable_snapshot(atom.normalized_value),
        )
        grouped.setdefault(snapshot.entity_id, {}).setdefault(
            snapshot.field_name, []
        ).append(snapshot)
    return MappingProxyType(
        {
            entity_id: MappingProxyType(
                {
                    field_name: tuple(field_atoms)
                    for field_name, field_atoms in fields.items()
                }
            )
            for entity_id, fields in grouped.items()
        }
    )


def _deterministic_json_value(value: object, name: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise ValueError(f"{name} mapping keys must be strings")
            normalized[key] = _deterministic_json_value(
                value[key], f"{name}.{key}"
            )
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _deterministic_json_value(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, (set, frozenset)):
        normalized_items = [
            _deterministic_json_value(item, name) for item in value
        ]
        try:
            return sorted(
                normalized_items,
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            )
        except TypeError as error:
            raise ValueError(f"{name} must be JSON serializable") from error
    raise ValueError(f"{name} must be JSON serializable")


def progress_payload(
    *,
    pure_search_seconds: float,
    requests: int,
    batches: int,
    raw_results: int,
    valid_urls: int,
    normalized_unique_urls: int,
    content_unique_pages: int,
    unique_objects: int,
    independent_domains: int,
    per_source_counts: Mapping[str, int],
    highest_concurrency: int,
    marginal_yield: float,
    current_gaps: object,
) -> dict[str, object]:
    """Build the complete deterministic, JSON-safe progress report."""

    _require_finite_nonnegative(pure_search_seconds, "pure_search_seconds")
    for name, value in (
        ("requests", requests),
        ("batches", batches),
        ("raw_results", raw_results),
        ("valid_urls", valid_urls),
        ("normalized_unique_urls", normalized_unique_urls),
        ("content_unique_pages", content_unique_pages),
        ("unique_objects", unique_objects),
        ("independent_domains", independent_domains),
        ("highest_concurrency", highest_concurrency),
    ):
        _require_count(value, name)
    if not (
        raw_results
        >= valid_urls
        >= normalized_unique_urls
        >= content_unique_pages
    ):
        raise ValueError(
            "counts must satisfy raw_results >= valid_urls >= "
            "normalized_unique_urls >= content_unique_pages"
        )
    if independent_domains > normalized_unique_urls:
        raise ValueError(
            "independent_domains must not exceed normalized_unique_urls"
        )
    if not isinstance(per_source_counts, Mapping):
        raise ValueError("per_source_counts must be a mapping")
    normalized_source_counts: dict[str, int] = {}
    for source, count in per_source_counts.items():
        _require_nonempty_text(source, "per_source_counts key")
        _require_count(count, f"per_source_counts[{source!r}]")
        canonical_source = _canonical_identity(source)
        normalized_source_counts[canonical_source] = (
            normalized_source_counts.get(canonical_source, 0) + count
        )
    normalized_source_counts = dict(sorted(normalized_source_counts.items()))
    if sum(normalized_source_counts.values()) != valid_urls:
        raise ValueError(
            "per_source_counts must partition all valid result-URL entries"
        )
    _require_finite_nonnegative(marginal_yield, "marginal_yield")

    return {
        "pure_search_seconds": pure_search_seconds,
        "requests": requests,
        "batches": batches,
        "raw_results": raw_results,
        "valid_urls": valid_urls,
        "normalized_unique_urls": normalized_unique_urls,
        "content_unique_pages": content_unique_pages,
        "unique_objects": unique_objects,
        "independent_domains": independent_domains,
        "per_source_counts": normalized_source_counts,
        "highest_concurrency": highest_concurrency,
        "marginal_yield": marginal_yield,
        "current_gaps": _deterministic_json_value(current_gaps, "current_gaps"),
    }
