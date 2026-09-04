"""Stream backend events into the task SQLite ledger and emit one small result."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import sys
from threading import Lock
from time import perf_counter, sleep

if __package__ in {None, ""}:
    skill_root = str(Path(__file__).resolve().parents[1])
    if skill_root not in sys.path:
        sys.path.insert(0, skill_root)

from scripts.normalize_and_dedupe import (
    BatchSpec,
    SqliteUrlLedger,
    UrlObservation,
)
from scripts.marketplace_candidates import (
    candidate_from_url,
)
from scripts.edge_marketplace_query import (
    EdgeWorkerSession,
    EdgeWorkerFailure,
    iter_edge_marketplace_events,
)
from scripts.jd_pace import JdPaceController


Adapter = Callable[[Mapping[str, object]], Iterator[Mapping[str, object]]]
MAX_SPOOL_LINE_BYTES = 64 * 1024
WALL_CLEANUP_MARGIN_SECONDS = 2.0
_SENSITIVE_KEY = re.compile(
    r"(?:body|html|secret|token|cookie|authorization|credential|password|profile|storage)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE = re.compile(
    r"(?i)\b(secret|token|cookie|authorization|password)\s*[:=]\s*[^\s,;]+"
)
_PROJECTION_EVIDENCE_KEYS = frozenset(
    {"platform", "requested_page_number", "observed_page_number", "diagnostics"}
)
_PROJECTION_DIAGNOSTIC_KEYS = frozenset(
    {
        "document_ready_state",
        "data_sku_node_count",
        "candidate_anchor_count",
        "valid_item_count",
        "collection_elapsed_ms",
        "stable_rounds",
        "observed_page_number",
        "recovery_stage",
        "recovery_attempt",
        "source_path",
    }
)
_PROJECTION_STAGE_ATTEMPTS = {"initial": 0, "reproject": 1, "reload": 2}
_PROJECTION_SOURCE_PATHS = {"jd": "/Search", "taobao": "/search"}


def _validated_projection_evidence(value: Mapping[str, object]) -> dict[str, object]:
    if set(value) != _PROJECTION_EVIDENCE_KEYS:
        raise ValueError("projection evidence keys must match whitelist")
    platform = value.get("platform")
    requested = value.get("requested_page_number")
    observed = value.get("observed_page_number")
    diagnostics = value.get("diagnostics")
    if platform not in {"jd", "taobao"}:
        raise ValueError("projection evidence platform is invalid")
    if (
        isinstance(requested, bool)
        or not isinstance(requested, int)
        or not 1 <= requested <= 512
        or observed != requested
    ):
        raise ValueError("projection evidence page is invalid")
    if not isinstance(diagnostics, Mapping) or set(diagnostics) != _PROJECTION_DIAGNOSTIC_KEYS:
        raise ValueError("projection diagnostic keys must match whitelist")
    if (
        diagnostics.get("document_ready_state")
        not in {"loading", "interactive", "complete"}
        or diagnostics.get("source_path") != _PROJECTION_SOURCE_PATHS[platform]
    ):
        raise ValueError("projection diagnostic values are invalid")
    for name in (
        "data_sku_node_count",
        "candidate_anchor_count",
        "valid_item_count",
        "collection_elapsed_ms",
        "stable_rounds",
    ):
        count = diagnostics.get(name)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError(f"projection diagnostic {name} is invalid")
    if diagnostics.get("observed_page_number") != observed:
        raise ValueError("projection diagnostic observed page is invalid")
    stage = diagnostics.get("recovery_stage")
    attempt = diagnostics.get("recovery_attempt")
    if (
        isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or _PROJECTION_STAGE_ATTEMPTS.get(stage) != attempt
    ):
        raise ValueError("projection recovery stage and attempt are invalid")
    return deepcopy(dict(value))


@dataclass
class AdapterFailure(Exception):
    category: str
    retryable: bool
    detail: str = ""
    projection_evidence: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.category, str) or not self.category.strip():
            raise ValueError("adapter failure category must be non-empty")
        if not isinstance(self.retryable, bool):
            raise ValueError("adapter failure retryable must be a boolean")
        if not isinstance(self.detail, str):
            raise ValueError("adapter failure detail must be a string")
        if self.projection_evidence is not None:
            if not isinstance(self.projection_evidence, Mapping):
                raise ValueError("projection evidence must be a mapping or None")
            self.projection_evidence = _validated_projection_evidence(
                self.projection_evidence
            )

    def __str__(self) -> str:
        suffix = f": {self.detail}" if self.detail else ""
        return f"{self.category}{suffix}"


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterFailure("adapter_summary_invalid", False, f"invalid {name}")
    return value


def _validate_envelope(envelope: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(envelope, Mapping):
        raise ValueError("envelope must be a mapping")
    if envelope.get("type") != "task-envelope":
        raise ValueError("envelope type must be task-envelope")
    normalized = {
        "type": "task-envelope",
        "run_id": _required_text(envelope.get("run_id"), "run_id"),
        "scope_fingerprint": _required_text(
            envelope.get("scope_fingerprint"), "scope_fingerprint"
        ),
        "task_id": _required_text(envelope.get("task_id"), "task_id"),
        "lease_id": _required_text(envelope.get("lease_id"), "lease_id"),
        "time_session_id": _required_text(
            envelope.get("time_session_id"), "time_session_id"
        ),
        "adapter": _required_text(envelope.get("adapter"), "adapter"),
    }
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("envelope payload must be a mapping")
    try:
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise ValueError("envelope payload must be JSON serializable") from error
    normalized["payload"] = deepcopy(dict(payload))
    return normalized


def _reject_sensitive_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or _SENSITIVE_KEY.search(key):
                raise AdapterFailure(
                    "adapter_sensitive_field_rejected", False, "sensitive key"
                )
            _reject_sensitive_fields(item)
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_fields(item)
    elif isinstance(value, str) and len(value) > 8192:
        raise AdapterFailure(
            "adapter_large_field_rejected", False, "field exceeds 8192 characters"
        )


def _safe_detail(detail: object) -> str:
    value = detail if isinstance(detail, str) else type(detail).__name__
    value = _SENSITIVE_VALUE.sub(lambda match: f"{match.group(1)}=[redacted]", value)
    value = " ".join(value.split())
    return value[:512]


def _failure_digest(envelope: Mapping[str, object]) -> str:
    payload = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
    return sha256(payload.encode("utf-8")).hexdigest()


def _record_failure(
    ledger_path: Path | str,
    envelope: Mapping[str, object],
    failure: AdapterFailure,
) -> None:
    with SqliteUrlLedger(ledger_path) as ledger:
        ledger.record_failure(
            batch_id=str(envelope["lease_id"]),
            category=failure.category,
            parameter_digest=_failure_digest(envelope),
            compensation_route="retry_once" if failure.retryable else None,
            detail=_safe_detail(failure.detail),
        )


def _url_observation(event: Mapping[str, object]) -> UrlObservation:
    channels = event.get("channels")
    metadata = event.get("metadata", {})
    if not isinstance(channels, list):
        raise AdapterFailure("adapter_url_event_invalid", False, "channels must be a list")
    if not isinstance(metadata, Mapping):
        raise AdapterFailure("adapter_url_event_invalid", False, "metadata must be a mapping")
    try:
        url = _required_text(event.get("url"), "event url")
        title = event.get("title", "")
        query_family = _required_text(
            event.get("query_family"), "event query_family"
        )
        observed_at = _required_text(
            event.get("observed_at"), "event observed_at"
        )
        normalized_channels = tuple(channels)
        first_channel = _required_text(
            normalized_channels[0] if normalized_channels else None,
            "event discovery channel",
        )
        verified = candidate_from_url(
            url=url,
            title=title,
            discovery_channel=first_channel,
            query_family=query_family,
            observed_at=observed_at,
        )
        normalized_metadata = dict(metadata)
        declared_platform = normalized_metadata.get("platform")
        declared_product_id = normalized_metadata.get("product_id")
        if declared_platform is not None or declared_product_id is not None:
            if (
                verified is None
                or declared_platform != verified.platform
                or declared_product_id != verified.product_id
            ):
                raise AdapterFailure(
                    "adapter_marketplace_identity_mismatch",
                    False,
                    "declared identity does not match URL",
                )
        if verified is not None:
            normalized_metadata["platform"] = verified.platform
            normalized_metadata["product_id"] = verified.product_id
        return UrlObservation(
            url=url,
            title=title,
            snippet=event.get("snippet", ""),
            channels=normalized_channels,
            source_class=_required_text(
                event.get("source_class"), "event source_class"
            ),
            query_family=query_family,
            observed_at=observed_at,
            metadata=normalized_metadata,
        )
    except AdapterFailure:
        raise
    except (TypeError, ValueError) as error:
        raise AdapterFailure(
            "adapter_url_event_invalid", False, _safe_detail(error)
        ) from error


def _terminal_result(
    envelope: Mapping[str, object],
    summary: Mapping[str, object],
    *,
    raw_count: int,
    valid_count: int,
    unique_additions: int,
    unique_candidate_additions: int,
    total_unique_urls: int,
    total_unique_candidates: int,
) -> dict[str, object]:
    telemetry = summary.get("telemetry")
    round_value = summary.get("round")
    if not isinstance(telemetry, Mapping) or not isinstance(round_value, Mapping):
        raise AdapterFailure(
            "adapter_summary_invalid", False, "telemetry and round are required"
        )
    if _count(telemetry.get("raw_url_observations"), "raw_url_observations") != raw_count:
        raise AdapterFailure(
            "adapter_summary_count_mismatch", False, "raw URL count mismatch"
        )
    successful_pages = _count(
        telemetry.get("successful_pages", 0), "successful_pages"
    )
    structured_records = _count(
        telemetry.get("structured_records", 0), "structured_records"
    )
    reported_new_entities = _count(
        round_value.get("new_entities", 0), "new_entities"
    )
    new_fields = _count(round_value.get("new_fields", 0), "new_fields")
    end_reason = _required_text(summary.get("end_reason"), "end_reason")
    if end_reason not in {"queue_exhausted", "partial", "failed"}:
        raise AdapterFailure(
            "adapter_summary_invalid", False, "unsupported end_reason"
        )
    duplicate_count = valid_count - unique_additions
    metric_stage = _required_text(
        summary.get("metric_stage", "canonical_url"), "metric_stage"
    )
    new_entities = (
        unique_candidate_additions
        if metric_stage == "marketplace_candidate"
        else reported_new_entities
    )
    result = {
        "batch_id": envelope["lease_id"],
        "task_id": envelope["task_id"],
        "run_id": envelope["run_id"],
        "scope_fingerprint": envelope["scope_fingerprint"],
        "metric_stage": metric_stage,
        "time_session_id": envelope["time_session_id"],
        "ledger_committed": True,
        "ledger_counts": {
            "raw_url_observations": raw_count,
            "valid_urls": valid_count,
            "unique_additions": unique_additions,
            "total_unique_urls": total_unique_urls,
            "unique_candidate_additions": unique_candidate_additions,
            "total_unique_candidates": total_unique_candidates,
        },
        "active_intervals": deepcopy(summary.get("active_intervals", [])),
        "verified_objects": deepcopy(summary.get("verified_objects", [])),
        "invalidations": deepcopy(summary.get("invalidations", [])),
        "new_seeds": deepcopy(summary.get("new_seeds", [])),
        "round": {
            "query_family": _required_text(
                round_value.get("query_family"), "round query_family"
            ),
            "source_class": _required_text(
                round_value.get("source_class"), "round source_class"
            ),
            "new_valid_urls": unique_additions,
            "new_entities": new_entities,
            "new_fields": new_fields,
            "mostly_duplicates": valid_count > 0
            and duplicate_count > unique_additions,
        },
        "end_reason": end_reason,
        "telemetry": {
            "raw_url_observations": raw_count,
            "successful_pages": successful_pages,
            "structured_records": structured_records,
        },
    }
    if "unresponsive_engines" in telemetry:
        unresponsive = telemetry.get("unresponsive_engines")
        if not isinstance(unresponsive, list):
            raise AdapterFailure(
                "adapter_summary_invalid", False, "unresponsive_engines is invalid"
            )
        result["telemetry"]["unresponsive_engines"] = deepcopy(unresponsive)
    if "engine_health" in telemetry:
        engine_health = telemetry.get("engine_health")
        if not isinstance(engine_health, Mapping) or any(
            not isinstance(engine, str)
            or not engine.strip()
            or status
            not in {"available", "unresponsive", "rate_limited", "captcha"}
            for engine, status in engine_health.items()
        ):
            raise AdapterFailure(
                "adapter_summary_invalid", False, "engine_health is invalid"
            )
        result["telemetry"]["engine_health"] = {
            engine: engine_health[engine] for engine in sorted(engine_health)
        }
    if "cooldown_engines" in telemetry:
        cooldown = telemetry.get("cooldown_engines")
        if not isinstance(cooldown, list) or any(
            not isinstance(engine, str) or not engine.strip() for engine in cooldown
        ):
            raise AdapterFailure(
                "adapter_summary_invalid", False, "cooldown_engines is invalid"
            )
        result["telemetry"]["cooldown_engines"] = sorted(set(cooldown))
    if "scope_completion" in summary:
        completion = summary.get("scope_completion")
        if not isinstance(completion, Mapping):
            raise AdapterFailure(
                "adapter_summary_invalid", False, "scope_completion is invalid"
            )
        result["scope_completion"] = deepcopy(dict(completion))
        result["deterministic_scope_complete"] = bool(
            summary.get("deterministic_scope_complete", False)
        )
    if "cursor_evidence" in summary:
        cursor = summary.get("cursor_evidence")
        if not isinstance(cursor, Mapping) or set(cursor) != {
            "platform",
            "cursor_id",
            "page_number",
            "status",
            "observed_page_number",
            "pagination_state",
            "has_next_page",
            "sku_digest",
        }:
            raise AdapterFailure(
                "adapter_summary_invalid", False, "cursor_evidence is invalid"
            )
        result["cursor_evidence"] = {
            "platform": _required_text(cursor.get("platform"), "cursor platform"),
            "cursor_id": _required_text(cursor.get("cursor_id"), "cursor_id"),
            "page_number": _count(cursor.get("page_number"), "page_number"),
            "status": _required_text(cursor.get("status"), "cursor status"),
            "observed_page_number": _count(
                cursor.get("observed_page_number"), "observed_page_number"
            ),
            "pagination_state": _required_text(
                cursor.get("pagination_state"), "pagination_state"
            ),
            "has_next_page": cursor.get("has_next_page"),
            "sku_digest": _required_text(cursor.get("sku_digest"), "sku_digest"),
        }
        if not isinstance(cursor.get("has_next_page"), bool):
            raise AdapterFailure(
                "adapter_summary_invalid", False, "has_next_page is invalid"
            )
    _reject_sensitive_fields(result)
    try:
        json.dumps(result, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as error:
        raise AdapterFailure(
            "adapter_summary_invalid", False, "summary is not JSON serializable"
        ) from error
    return result


def run_adapter(
    envelope: Mapping[str, object],
    *,
    ledger_path: Path | str,
    adapter: Adapter,
) -> dict[str, object]:
    """Consume one adapter transaction and return its compact scheduler result."""
    normalized = _validate_envelope(envelope)
    if not callable(adapter):
        raise ValueError("adapter must be callable")
    batch_id = str(normalized["lease_id"])
    spec = BatchSpec(
        batch_id=batch_id,
        run_id=str(normalized["run_id"]),
        task_id=str(normalized["task_id"]),
        adapter=str(normalized["adapter"]),
        scope_fingerprint=str(normalized["scope_fingerprint"]),
    )
    try:
        _reject_sensitive_fields(normalized["payload"])
        with SqliteUrlLedger(ledger_path) as ledger:
            committed = ledger.batch_stats(batch_id)
            if committed is not None:
                stored = committed.terminal_summary.get("scheduler_result")
                if not isinstance(stored, Mapping):
                    raise AdapterFailure(
                        "committed_batch_missing_result", False, "cannot replay batch"
                    )
                return deepcopy(dict(stored))

            with ledger.batch(spec) as writer:
                raw_count = 0
                valid_count = 0
                unique_additions = 0
                unique_candidate_additions = 0
                summary: Mapping[str, object] | None = None
                try:
                    adapter_started = perf_counter()
                    events = adapter(normalized["payload"])
                    for event in events:
                        if not isinstance(event, Mapping):
                            raise AdapterFailure(
                                "adapter_event_invalid", False, "event must be a mapping"
                            )
                        event_type = event.get("type")
                        if summary is not None:
                            raise AdapterFailure(
                                "adapter_summary_not_terminal",
                                False,
                                "event followed terminal summary",
                            )
                        if event_type == "url":
                            raw_count += 1
                            outcome = writer.add(_url_observation(event))
                            valid_count += int(outcome.valid)
                            unique_additions += int(outcome.valid and not outcome.duplicate)
                            unique_candidate_additions += int(outcome.candidate_added)
                        elif event_type == "summary":
                            summary = dict(event)
                        else:
                            raise AdapterFailure(
                                "adapter_event_invalid", False, "unsupported event type"
                            )
                    adapter_ended = perf_counter()
                except AdapterFailure:
                    raise
                except Exception as error:
                    raise AdapterFailure(
                        "adapter_exception", True, _safe_detail(error)
                    ) from error
                if summary is None:
                    raise AdapterFailure(
                        "adapter_summary_required", False, "terminal summary missing"
                    )
                summary = dict(summary)
                summary.setdefault(
                    "active_intervals", [[adapter_started, adapter_ended]]
                )
                result = _terminal_result(
                    normalized,
                    summary,
                    raw_count=raw_count,
                    valid_count=valid_count,
                    unique_additions=unique_additions,
                    unique_candidate_additions=unique_candidate_additions,
                    total_unique_urls=ledger.stats().unique_urls,
                    total_unique_candidates=ledger.marketplace_candidate_count(),
                )
                writer.finish(
                    {
                        "end_reason": result["end_reason"],
                        "raw_url_observations": raw_count,
                        "valid_urls": valid_count,
                        "unique_additions": unique_additions,
                        "unique_candidate_additions": unique_candidate_additions,
                        "scheduler_result": result,
                    }
                )
            return result
    except AdapterFailure as failure:
        _record_failure(ledger_path, normalized, failure)
        raise


def _spool_path(spool_dir: Path, envelope: Mapping[str, object]) -> Path:
    identity = f"{envelope['task_id']}\0{envelope['lease_id']}"
    digest = sha256(identity.encode("utf-8")).hexdigest()
    return spool_dir / f"{digest}.ndjson"


def _write_adapter_spool(
    envelope: Mapping[str, object],
    *,
    adapter: Adapter,
    spool_path: Path,
) -> Path:
    summary_seen = False
    try:
        with spool_path.open("x", encoding="utf-8", newline="\n") as handle:
            try:
                events = adapter(envelope["payload"])
                for event in events:
                    if not isinstance(event, Mapping):
                        raise AdapterFailure(
                            "adapter_event_invalid", False, "event must be a mapping"
                        )
                    if summary_seen:
                        raise AdapterFailure(
                            "adapter_summary_not_terminal",
                            False,
                            "event followed terminal summary",
                        )
                    event_type = event.get("type")
                    if event_type not in {"url", "summary"}:
                        raise AdapterFailure(
                            "adapter_event_invalid", False, "unsupported event type"
                        )
                    if event_type == "summary":
                        summary_seen = True
                    try:
                        line = json.dumps(
                            dict(event), ensure_ascii=False, sort_keys=True
                        ).encode("utf-8")
                    except (TypeError, ValueError) as error:
                        raise AdapterFailure(
                            "adapter_event_invalid",
                            False,
                            "event is not JSON serializable",
                        ) from error
                    if len(line) > MAX_SPOOL_LINE_BYTES:
                        raise AdapterFailure(
                            "adapter_event_too_large",
                            False,
                            f"event exceeds {MAX_SPOOL_LINE_BYTES} bytes",
                        )
                    handle.write(line.decode("utf-8"))
                    handle.write("\n")
            except AdapterFailure:
                raise
            except Exception as error:
                raise AdapterFailure(
                    "adapter_exception", True, _safe_detail(error)
                ) from error
        if not summary_seen:
            raise AdapterFailure(
                "adapter_summary_required", False, "terminal summary missing"
            )
        return spool_path
    except BaseException:
        spool_path.unlink(missing_ok=True)
        raise


def _replay_spool(spool_path: Path) -> Iterator[Mapping[str, object]]:
    with spool_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            event = json.loads(line)
            if not isinstance(event, Mapping):
                raise AdapterFailure(
                    "adapter_event_invalid", False, "spooled event must be a mapping"
                )
            yield event


def _failure_adapter(failure: AdapterFailure) -> Adapter:
    def raise_failure(payload: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
        del payload
        raise failure
        yield

    return raise_failure


def run_adapter_group(
    envelopes: Sequence[Mapping[str, object]],
    *,
    ledger_path: Path | str,
    adapter: Adapter,
    max_workers: int,
    spool_dir: Path | str,
    telemetry: dict[str, object] | None = None,
    result_callback: Callable[[dict[str, object]], None] | None = None,
    activity_callback: Callable[[str, float, float, bool], None] | None = None,
    failure_callback: Callable[[str, AdapterFailure], None] | None = None,
    should_continue: Callable[[], bool] | None = None,
    commit_lock: object | None = None,
) -> tuple[dict[str, object], ...]:
    """Run a bounded adapter group and commit successful spools in input order."""
    if isinstance(max_workers, bool) or not isinstance(max_workers, int):
        raise ValueError("max_workers must be a positive integer")
    if max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    if not callable(adapter):
        raise ValueError("adapter must be callable")
    if telemetry is not None and not isinstance(telemetry, dict):
        raise ValueError("telemetry must be a mapping or None")
    if commit_lock is not None and (
        not callable(getattr(commit_lock, "__enter__", None))
        or not callable(getattr(commit_lock, "__exit__", None))
    ):
        raise ValueError("commit_lock must be a context manager")
    for callback, name in (
        (result_callback, "result_callback"),
        (activity_callback, "activity_callback"),
        (failure_callback, "failure_callback"),
        (should_continue, "should_continue"),
    ):
        if callback is not None and not callable(callback):
            raise ValueError(f"{name} must be callable or None")
    normalized = tuple(_validate_envelope(item) for item in envelopes)
    target = Path(spool_dir)
    target.mkdir(parents=True, exist_ok=True)
    owned_spools = tuple(_spool_path(target, item) for item in normalized)
    if len(set(owned_spools)) != len(owned_spools):
        raise ValueError("adapter group contains duplicate task leases")

    results: list[dict[str, object]] = []
    tracker_lock = Lock()
    active = 0
    peak = 0
    submitted = 0
    failures: list[dict[str, object]] = []
    attempt_intervals: dict[str, tuple[float, float]] = {}

    def tracked_adapter(
        task_id: str, payload: Mapping[str, object]
    ) -> Iterator[Mapping[str, object]]:
        nonlocal active, peak
        started = perf_counter()
        with tracker_lock:
            active += 1
            peak = max(peak, active)
        try:
            yield from adapter(payload)
        finally:
            finished = perf_counter()
            interval = (started, finished)
            consume_active_interval = getattr(
                adapter, "consume_active_interval", None
            )
            if callable(consume_active_interval):
                reported = consume_active_interval()
                if (
                    isinstance(reported, tuple)
                    and len(reported) == 2
                    and all(isinstance(value, (int, float)) for value in reported)
                    and float(reported[1]) >= float(reported[0])
                ):
                    interval = (float(reported[0]), float(reported[1]))
            with tracker_lock:
                active -= 1
                attempt_intervals[task_id] = interval

    try:
        for offset in range(0, len(normalized), max_workers):
            if should_continue is not None and not should_continue():
                break
            batch = normalized[offset : offset + max_workers]
            paths = owned_spools[offset : offset + max_workers]
            submitted += len(batch)
            futures: list[Future[Path]] = []
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for envelope, spool_path in zip(batch, paths, strict=True):
                    task_id = str(envelope["task_id"])
                    futures.append(
                        executor.submit(
                            _write_adapter_spool,
                            envelope,
                            adapter=lambda payload, current=task_id: tracked_adapter(
                                current, payload
                            ),
                            spool_path=spool_path,
                        )
                    )
                for envelope, spool_path, future in zip(
                    batch, paths, futures, strict=True
                ):
                    failure: AdapterFailure | None = None
                    try:
                        future.result()
                    except AdapterFailure as error:
                        failure = error
                    try:
                        if failure is not None:
                            with (
                                nullcontext()
                                if commit_lock is None
                                else commit_lock
                            ):
                                run_adapter(
                                    envelope,
                                    ledger_path=ledger_path,
                                    adapter=_failure_adapter(failure),
                                )
                        else:
                            with (
                                nullcontext()
                                if commit_lock is None
                                else commit_lock
                            ):
                                result = run_adapter(
                                    envelope,
                                    ledger_path=ledger_path,
                                    adapter=lambda payload, path=spool_path: _replay_spool(
                                        path
                                    ),
                                )
                            interval = attempt_intervals.get(str(envelope["task_id"]))
                            if interval is not None:
                                result["active_intervals"] = [[*interval]]
                            results.append(result)
                            if result_callback is not None:
                                result_callback(result)
                    except AdapterFailure as error:
                        if failure is None:
                            failure = error
                        continue
                    finally:
                        interval = attempt_intervals.get(str(envelope["task_id"]))
                        if activity_callback is not None and interval is not None:
                            activity_callback(
                                str(envelope["task_id"]),
                                interval[0],
                                interval[1],
                                failure is None,
                            )
                        if failure is not None:
                            if failure_callback is not None:
                                failure_callback(str(envelope["task_id"]), failure)
                            failures.append(
                                {
                                    "task_id": str(envelope["task_id"]),
                                    "category": failure.category,
                                    "retryable": failure.retryable,
                                }
                            )
                        spool_path.unlink(missing_ok=True)
        if telemetry is not None:
            telemetry["peak_inflight"] = peak
            telemetry["max_workers"] = max_workers
            telemetry["submitted_tasks"] = submitted
            telemetry["failures"] = failures
            telemetry["attempt_intervals"] = [
                [start, end]
                for start, end in sorted(attempt_intervals.values())
            ]
        return tuple(results)
    finally:
        for spool_path in owned_spools:
            spool_path.unlink(missing_ok=True)


def diagnostic_empty_adapter(
    payload: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    query_family = payload.get("query_family", "diagnostic")
    yield {
        "type": "summary",
        "end_reason": "queue_exhausted",
        "metric_stage": "canonical_url",
        "telemetry": {
            "raw_url_observations": 0,
            "successful_pages": 0,
            "structured_records": 0,
        },
        "new_seeds": [],
        "round": {
            "query_family": query_family,
            "source_class": "diagnostic",
            "new_valid_urls": 0,
            "new_entities": 0,
            "new_fields": 0,
            "mostly_duplicates": False,
        },
    }


def sitemap_adapter(
    payload: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    from scripts.discover_sitemaps import iter_backend_events

    yield from iter_backend_events(payload)


def common_crawl_adapter(
    payload: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    from scripts.common_crawl_query import iter_backend_events

    yield from iter_backend_events(payload)


def searxng_adapter(
    payload: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    from scripts.searxng_query import iter_searxng_events

    base_url = payload.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise AdapterFailure(
            "searxng_unavailable", False, "managed runtime base_url is required"
        )
    yield from iter_searxng_events(payload, base_url=base_url)


def browser_batch_adapter(
    payload: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    cursor = payload.get("cursor")
    if not isinstance(cursor, Mapping):
        raise AdapterFailure("browser_batch_invalid", False, "cursor must be a mapping")
    page_number = cursor.get("page_number")
    request_payload = {
        "platform": payload.get("platform"),
        "query": payload.get("query_family"),
        "query_family": payload.get("query_family"),
        "cursor": {
            "cursor_id": cursor.get("cursor_id"),
            "ordinal": 0,
            "page_number": page_number,
        },
        "user_data_dir": "",
        "deadline_seconds": 600.0,
        "max_items": 1000,
        "session_action": "start" if page_number == 1 else "next",
        "pagination_enabled": page_number != 1,
    }
    projection_evidence: dict[str, object] = {}
    try:
        yield from iter_edge_marketplace_events(
            request_payload,
            worker_runner=lambda normalized, **kwargs: payload,
            projection_evidence_sink=lambda evidence: projection_evidence.update(
                deepcopy(dict(evidence))
            ),
        )
    except EdgeWorkerFailure as error:
        raise AdapterFailure(
            error.category,
            retryable=error.retryable,
            detail=error.detail,
            projection_evidence=projection_evidence or None,
        ) from error


def edge_marketplace_adapter(
    payload: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    projection_evidence: dict[str, object] = {}
    try:
        yield from iter_edge_marketplace_events(
            payload,
            projection_evidence_sink=lambda evidence: projection_evidence.update(
                deepcopy(dict(evidence))
            ),
        )
    except EdgeWorkerFailure as error:
        raise AdapterFailure(
            error.category,
            retryable=error.retryable,
            detail=error.detail,
            projection_evidence=projection_evidence or None,
        ) from error


@contextmanager
def edge_marketplace_session_adapter(
    *,
    session_factory: Callable[[], object] = EdgeWorkerSession,
    pace_factory: Callable[[], object] | None = None,
    monotonic: Callable[[], float] = perf_counter,
    sleeper: Callable[[float], None] = sleep,
    wall_deadline: float | None = None,
) -> Iterator[Adapter]:
    """为同一调度批次复用一个临时 Node/CDP 会话，并按其健康度自适应用节奏。"""
    if wall_deadline is not None and (
        isinstance(wall_deadline, bool)
        or not isinstance(wall_deadline, (int, float))
        or not math.isfinite(float(wall_deadline))
        or float(wall_deadline) <= 0
    ):
        raise ValueError("wall_deadline must be positive and finite")
    try:
        session_context = session_factory()
        with session_context as session:
            run = getattr(session, "run", None)
            if not callable(run):
                raise TypeError("edge worker session must provide run(payload)")
            pace = (
                pace_factory()
                if pace_factory is not None
                else JdPaceController()
            )
            last_active_interval: tuple[float, float] | None = None

            def adapter(
                payload: Mapping[str, object],
            ) -> Iterator[Mapping[str, object]]:
                nonlocal pace, last_active_interval
                delay = pace.next_delay()
                if (
                    wall_deadline is not None
                    and monotonic() + delay + WALL_CLEANUP_MARGIN_SECONDS
                    >= float(wall_deadline)
                ):
                    raise AdapterFailure(
                        "wall_budget_exhausted",
                        retryable=False,
                        detail="pacing delay does not fit remaining wall budget",
                    )
                if delay > 0:
                    sleeper(delay)
                request_payload = payload
                if wall_deadline is not None:
                    remaining_wall = (
                        float(wall_deadline)
                        - monotonic()
                        - WALL_CLEANUP_MARGIN_SECONDS
                    )
                    if remaining_wall <= 0:
                        raise AdapterFailure(
                            "wall_budget_exhausted",
                            retryable=False,
                            detail="no wall budget remains for Edge request",
                        )
                    current_deadline = payload.get("deadline_seconds")
                    if isinstance(current_deadline, (int, float)) and not isinstance(
                        current_deadline, bool
                    ):
                        request_payload = dict(payload)
                        request_payload["deadline_seconds"] = min(
                            float(current_deadline), remaining_wall
                        )
                collected: list[Mapping[str, object]] = []
                projection_evidence: dict[str, object] = {}
                raw_count = 0
                started = monotonic()
                try:
                    for event in iter_edge_marketplace_events(
                        request_payload,
                        worker_runner=lambda normalized, **kwargs: run(normalized),
                        projection_evidence_sink=lambda evidence: projection_evidence.update(
                            deepcopy(dict(evidence))
                        ),
                    ):
                        collected.append(event)
                        if event.get("type") == "url":
                            raw_count += 1
                except EdgeWorkerFailure as error:
                    pace.on_warning(error.category)
                    raise AdapterFailure(
                        error.category,
                        retryable=error.retryable,
                        detail=error.detail,
                        projection_evidence=projection_evidence or None,
                    ) from error
                finally:
                    finished = monotonic()
                    last_active_interval = (started, finished)
                elapsed = finished - started
                if raw_count > 0:
                    pace.on_healthy()
                else:
                    pace.on_empty()
                if elapsed >= pace.params.slow_page_threshold_seconds:
                    pace.on_warning("", slow_seconds=elapsed)
                yield from collected

            def consume_active_interval() -> tuple[float, float] | None:
                nonlocal last_active_interval
                interval = last_active_interval
                last_active_interval = None
                return interval

            setattr(adapter, "consume_active_interval", consume_active_interval)

            yield adapter
    except AdapterFailure:
        raise
    except EdgeWorkerFailure as error:
        raise AdapterFailure(
            error.category,
            retryable=error.retryable,
            detail=error.detail,
        ) from error
    except OSError as error:
        raise AdapterFailure(
            "edge_worker_start_failed",
            retryable=False,
            detail=_safe_detail(error),
        ) from error


ADAPTER_REGISTRY: dict[str, Adapter] = {
    "diagnostic_empty": diagnostic_empty_adapter,
    "sitemap": sitemap_adapter,
    "common_crawl": common_crawl_adapter,
    "searxng": searxng_adapter,
    "browser_batch_ingest": browser_batch_adapter,
    "edge_marketplace": edge_marketplace_adapter,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one fixed-registry backend adapter")
    parser.add_argument("--envelope", required=True)
    parser.add_argument("--ledger", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        envelope = json.loads(Path(arguments.envelope).read_text(encoding="utf-8"))
        if not isinstance(envelope, Mapping):
            raise ValueError("envelope must be a JSON object")
        adapter_name = _required_text(envelope.get("adapter"), "adapter")
        adapter = ADAPTER_REGISTRY.get(adapter_name)
        if adapter is None:
            raise ValueError("adapter is not in the fixed registry")
        result = run_adapter(
            envelope,
            ledger_path=arguments.ledger,
            adapter=adapter,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (AdapterFailure, OSError, TypeError, ValueError) as error:
        print(_safe_detail(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
