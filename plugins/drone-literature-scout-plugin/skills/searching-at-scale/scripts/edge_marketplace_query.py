"""Transient Edge CDP worker adapter for public marketplace projections."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import threading
from typing import Any
from urllib.parse import urlsplit

from scripts.domestic_marketplace_query import (
    EDGE_PAYLOAD_KEYS,
    SAT_EDGE_PIPE_PATH_ENV,
    edge_pipe_path,
)
from scripts.marketplace_candidates import (
    BrowserBatchError,
    iter_browser_batch_events,
)


# Node 客户端 fitBatch 上限为 200KB（edge_extension_client.mjs），Python 端必须至少
# 容纳同样大小，否则 fetch 跨页累计带回的多页卡片（240+ 卡）会被判 edge_worker_output_invalid。
MAX_WORKER_OUTPUT_BYTES = 200 * 1024
_CURSOR_KEYS = frozenset({"cursor_id", "ordinal", "page_number"})
_ERROR_KEYS = frozenset({"category", "retryable"})
_PLATFORMS = frozenset({"jd", "taobao"})
_BATCH_KEYS = frozenset(
    {
        "projection_schema_version",
        "capabilities",
        "platform",
        "page_state",
        "source_url",
        "query_family",
        "cursor",
        "observed_page_number",
        "pagination_state",
        "has_next_page",
        "sku_digest",
        "diagnostics",
        "items",
    }
)
_RESULT_CURSOR_KEYS = frozenset({"cursor_id", "page_number", "status"})
_DIAGNOSTIC_KEYS = frozenset(
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
_PROJECTION_CAPABILITIES = [
    "stable_card_fields_v2",
    "verified_pagination_v1",
    "resilient_pagination_v1",
]
_DOCUMENT_READY_STATES = frozenset({"loading", "interactive", "complete"})
_RECOVERY_STAGES = frozenset({"initial", "reproject", "reload"})
_SOURCE_HOSTS = {"jd": "search.jd.com", "taobao": "s.taobao.com"}


@dataclass
class EdgeWorkerFailure(Exception):
    category: str
    retryable: bool
    detail: str

    def __str__(self) -> str:
        return f"{self.category}: {self.detail}"


def _failure(category: str, detail: str, *, retryable: bool = False) -> EdgeWorkerFailure:
    return EdgeWorkerFailure(category, retryable, detail)


def _required_text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _failure("edge_worker_input_invalid", f"{name} must be a string")
    normalized = value.strip()
    if (not allow_empty and not normalized) or any(ord(char) < 32 for char in normalized):
        raise _failure("edge_worker_input_invalid", f"{name} is invalid")
    return normalized


def _positive_int(value: object, name: str, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > maximum
    ):
        raise _failure(
            "edge_worker_input_invalid",
            f"{name} must be a bounded positive integer",
        )
    return value


def _validate_payload(payload: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(payload, Mapping) or set(payload) != EDGE_PAYLOAD_KEYS:
        raise _failure("edge_worker_input_invalid", "payload keys must match whitelist")
    platform = _required_text(payload.get("platform"), "platform")
    if platform not in _PLATFORMS:
        raise _failure("edge_worker_input_invalid", "unsupported marketplace")
    query = _required_text(payload.get("query"), "query")
    query_family = _required_text(payload.get("query_family"), "query_family")
    cursor = payload.get("cursor")
    if not isinstance(cursor, Mapping) or set(cursor) != _CURSOR_KEYS:
        raise _failure("edge_worker_input_invalid", "cursor keys must match whitelist")
    cursor_id = _required_text(cursor.get("cursor_id"), "cursor_id")
    ordinal = cursor.get("ordinal")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise _failure("edge_worker_input_invalid", "cursor ordinal must be non-negative")
    page_number = _positive_int(cursor.get("page_number"), "page_number", 512)
    user_data_dir = _required_text(
        payload.get("user_data_dir"), "user_data_dir", allow_empty=True
    )
    deadline = payload.get("deadline_seconds")
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not 0 < float(deadline) <= 600
    ):
        raise _failure(
            "edge_worker_input_invalid", "deadline_seconds must be in (0, 600]"
        )
    max_items = _positive_int(payload.get("max_items"), "max_items", 1000)
    session_action = _required_text(payload.get("session_action"), "session_action")
    if session_action not in {"start", "next", "recover"}:
        raise _failure("edge_worker_input_invalid", "session_action is unsupported")
    pagination_enabled = payload.get("pagination_enabled")
    if not isinstance(pagination_enabled, bool):
        raise _failure(
            "edge_worker_input_invalid", "pagination_enabled must be a boolean"
        )
    if session_action == "start" and page_number != 1:
        raise _failure(
            "edge_worker_input_invalid", "start action must target page_number 1"
        )
    if session_action == "next" and not pagination_enabled:
        raise _failure(
            "edge_worker_input_invalid",
            "pagination actions require explicit pagination enablement",
        )
    if session_action == "next" and page_number <= 1:
        raise _failure(
            "edge_worker_input_invalid", "next action must target a later page"
        )
    return {
        "platform": platform,
        "query": query,
        "query_family": query_family,
        "cursor": {
            "cursor_id": cursor_id,
            "ordinal": ordinal,
            "page_number": page_number,
        },
        "user_data_dir": user_data_dir,
        "deadline_seconds": float(deadline),
        "max_items": max_items,
        "session_action": session_action,
        "pagination_enabled": pagination_enabled,
    }


def _terminate_owned(process: Any) -> None:
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def _read_bounded_stdout(stream: Any, holder: dict[str, object]) -> None:
    try:
        holder["text"] = stream.read(MAX_WORKER_OUTPUT_BYTES + 1)
    except Exception as error:  # pragma: no cover - operating-system pipe failure
        holder["error"] = type(error).__name__


def _parse_worker_output(text: object, returncode: int) -> Mapping[str, object]:
    if not isinstance(text, str):
        raise _failure("edge_worker_output_invalid", "worker output is not text")
    if len(text.encode("utf-8")) > MAX_WORKER_OUTPUT_BYTES:
        raise _failure("edge_worker_output_invalid", "worker output exceeded limit")
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].strip():
        raise _failure("edge_worker_output_invalid", "worker must emit one JSON line")
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise _failure("edge_worker_output_invalid", "worker output is invalid JSON") from error
    if not isinstance(value, Mapping):
        raise _failure("edge_worker_output_invalid", "worker output must be an object")
    if set(value) == {"error"}:
        error = value.get("error")
        if not isinstance(error, Mapping) or set(error) != _ERROR_KEYS:
            raise _failure("edge_worker_output_invalid", "worker error is invalid")
        category = _required_text(error.get("category"), "error category")
        if category == "rate_limited":
            category = "browser_rate_limited"
        retryable = error.get("retryable")
        if not isinstance(retryable, bool):
            raise _failure("edge_worker_output_invalid", "worker retryability is invalid")
        raise _failure(category, "Edge worker reported a compact failure", retryable=retryable)
    if returncode != 0:
        raise _failure(
            "edge_worker_exit_failure",
            f"Edge worker exited with code {returncode}",
            retryable=True,
        )
    return dict(value)


def _validate_projection_batch(
    batch: Mapping[str, object],
    expected: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(batch, Mapping) or set(batch) != _BATCH_KEYS:
        raise _failure(
            "edge_worker_output_invalid", "projection keys must match whitelist"
        )
    if (
        batch.get("projection_schema_version") != 4
        or batch.get("capabilities") != _PROJECTION_CAPABILITIES
    ):
        raise _failure("edge_worker_output_invalid", "projection schema is invalid")
    diagnostics = batch.get("diagnostics")
    if not isinstance(diagnostics, Mapping) or set(diagnostics) != _DIAGNOSTIC_KEYS:
        raise _failure(
            "edge_worker_output_invalid", "diagnostic keys must match whitelist"
        )
    if (
        diagnostics.get("document_ready_state") not in _DOCUMENT_READY_STATES
        or diagnostics.get("recovery_stage") not in _RECOVERY_STAGES
        or diagnostics.get("source_path") != "/Search"
    ):
        raise _failure("edge_worker_output_invalid", "diagnostic values are invalid")
    for name in (
        "data_sku_node_count",
        "candidate_anchor_count",
        "valid_item_count",
        "collection_elapsed_ms",
        "stable_rounds",
    ):
        value = diagnostics.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _failure(
                "edge_worker_output_invalid", f"diagnostic {name} is invalid"
            )
    recovery_attempt = diagnostics.get("recovery_attempt")
    if (
        isinstance(recovery_attempt, bool)
        or not isinstance(recovery_attempt, int)
        or not 0 <= recovery_attempt <= 2
    ):
        raise _failure(
            "edge_worker_output_invalid", "diagnostic recovery_attempt is invalid"
        )
    observed_page_number = diagnostics.get("observed_page_number")
    if (
        isinstance(observed_page_number, bool)
        or not isinstance(observed_page_number, int)
        or not 1 <= observed_page_number <= 512
        or observed_page_number != batch.get("observed_page_number")
    ):
        raise _failure(
            "edge_worker_output_invalid", "diagnostic observed_page_number is invalid"
        )
    cursor = batch.get("cursor")
    expected_cursor = expected.get("cursor")
    if (
        not isinstance(cursor, Mapping)
        or set(cursor) != _RESULT_CURSOR_KEYS
        or not isinstance(expected_cursor, Mapping)
        or batch.get("platform") != expected.get("platform")
        or batch.get("query_family") != expected.get("query_family")
        or cursor.get("cursor_id") != expected_cursor.get("cursor_id")
        or cursor.get("page_number") != expected_cursor.get("page_number")
        or observed_page_number != expected_cursor.get("page_number")
    ):
        raise _failure("edge_worker_output_invalid", "projection cursor is invalid")
    items = batch.get("items")
    if (
        not isinstance(items, list)
        or diagnostics.get("valid_item_count") != len(items)
        or diagnostics.get("candidate_anchor_count", -1) < len(items)
    ):
        raise _failure("edge_worker_output_invalid", "diagnostic counts are invalid")
    try:
        source = urlsplit(str(batch.get("source_url", "")))
        source_port = source.port
    except ValueError as error:
        raise _failure("edge_worker_output_invalid", "projection source is invalid") from error
    expected_path = "/Search" if batch.get("platform") == "jd" else "/search"
    if (
        source.scheme != "https"
        or source.hostname != _SOURCE_HOSTS.get(str(batch.get("platform")))
        or source_port not in {None, 443}
        or source.username is not None
        or source.password is not None
        or source.path != expected_path
        or source.query
        or source.fragment
    ):
        raise _failure("edge_worker_output_invalid", "projection source is invalid")
    return dict(batch)


def _legacy_candidate_batch(batch: Mapping[str, object]) -> dict[str, object]:
    compatible = dict(batch)
    compatible.pop("diagnostics", None)
    compatible["projection_schema_version"] = 3
    compatible["capabilities"] = [
        "stable_card_fields_v2",
        "verified_pagination_v1",
    ]
    return compatible


def _projection_evidence(batch: Mapping[str, object]) -> dict[str, object]:
    diagnostics = batch["diagnostics"]
    cursor = batch["cursor"]
    return {
        "platform": batch["platform"],
        "requested_page_number": cursor["page_number"],
        "observed_page_number": batch["observed_page_number"],
        "diagnostics": {
            key: diagnostics[key]
            for key in _DIAGNOSTIC_KEYS
        },
    }


def run_edge_worker(
    payload: Mapping[str, object],
    *,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    node_binary: str = "node",
    script_path: Path | str | None = None,
) -> Mapping[str, object]:
    """Run one owned Node worker and return its single bounded projection."""
    normalized = _validate_payload(payload)
    worker = (
        Path(script_path)
        if script_path is not None
        else Path(__file__).with_name("edge_extension_client.mjs")
    )
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    process = popen_factory(
        [node_binary, str(worker)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="strict",
        shell=False,
        close_fds=True,
        creationflags=creationflags,
    )
    if process.stdin is None or process.stdout is None:
        raise _failure("edge_worker_start_failed", "worker pipes are unavailable")
    holder: dict[str, object] = {}
    reader = threading.Thread(
        target=_read_bounded_stdout,
        args=(process.stdout, holder),
        name="edge-worker-stdout",
        daemon=True,
    )
    try:
        process.stdin.write(json.dumps(normalized, ensure_ascii=False, separators=(",", ":")))
        process.stdin.close()
        reader.start()
        try:
            returncode = process.wait(timeout=float(normalized["deadline_seconds"]))
        except subprocess.TimeoutExpired as error:
            _terminate_owned(process)
            raise _failure(
                "edge_worker_timeout", "owned Edge worker exceeded its deadline"
            ) from error
        reader.join(timeout=2.0)
        if reader.is_alive() or "error" in holder:
            _terminate_owned(process)
            raise _failure("edge_worker_output_invalid", "worker output could not be read")
        batch = _parse_worker_output(holder.get("text"), int(returncode))
        return _validate_projection_batch(batch, normalized)
    finally:
        if not getattr(process.stdin, "closed", True):
            process.stdin.close()
        process.stdout.close()


def _pipe_override_args() -> list[str]:
    """CLI args selecting a per-profile broker pipe, or [] for the default."""
    override = os.environ.get(SAT_EDGE_PIPE_PATH_ENV) or ""
    if not override:
        return []
    return ["--pipe-path", override]


def probe_edge_background_bridge(
    timeout_seconds: float = 60.0,
    *,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    node_binary: str = "node",
    script_path: Path | str | None = None,
) -> Mapping[str, object]:
    """Probe the broker pipe from the same Node execution context as real work."""
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < float(timeout_seconds) <= 600
    ):
        raise _failure(
            "edge_worker_input_invalid", "preflight timeout must be in (0, 600]"
        )
    worker = (
        Path(script_path)
        if script_path is not None
        else Path(__file__).with_name("edge_extension_client.mjs")
    )
    timeout_ms = str(max(1, round(float(timeout_seconds) * 1000)))
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    process = popen_factory(
        [node_binary, str(worker), "--probe-pipe", "--timeout-ms", timeout_ms]
        + _pipe_override_args(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="strict",
        shell=False,
        close_fds=True,
        creationflags=creationflags,
    )
    if process.stdout is None:
        raise _failure("edge_worker_start_failed", "preflight stdout is unavailable")
    holder: dict[str, object] = {}
    reader = threading.Thread(
        target=_read_bounded_stdout,
        args=(process.stdout, holder),
        name="edge-preflight-stdout",
        daemon=True,
    )
    try:
        reader.start()
        try:
            returncode = process.wait(timeout=float(timeout_seconds) + 2.0)
        except subprocess.TimeoutExpired as error:
            _terminate_owned(process)
            raise _failure(
                "edge_background_bridge_unavailable",
                "background bridge preflight timed out",
                retryable=True,
            ) from error
        reader.join(timeout=2.0)
        if reader.is_alive() or "error" in holder:
            _terminate_owned(process)
            raise _failure(
                "edge_worker_output_invalid", "preflight output could not be read"
            )
        result = _parse_worker_output(holder.get("text"), int(returncode))
        if set(result) != {"ok", "pipe"} or result.get("ok") is not True:
            raise _failure("edge_worker_output_invalid", "preflight result is invalid")
        return result
    finally:
        process.stdout.close()


class EdgeWorkerSession:
    """Own one Node worker and exchange bounded JSON lines synchronously."""

    def __init__(
        self,
        *,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        node_binary: str = "node",
        script_path: Path | str | None = None,
    ) -> None:
        worker = (
            Path(script_path)
            if script_path is not None
            else Path(__file__).with_name("edge_extension_client.mjs")
        )
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._process = popen_factory(
            [node_binary, str(worker)] + _pipe_override_args(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="strict",
            shell=False,
            close_fds=True,
            creationflags=creationflags,
        )
        if self._process.stdin is None or self._process.stdout is None:
            raise _failure("edge_worker_start_failed", "worker pipes are unavailable")
        self._closed = False

    def __enter__(self) -> "EdgeWorkerSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del exc_type, exc, traceback
        self.close()
        return False

    def run(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if self._closed:
            raise _failure("edge_worker_closed", "worker session is closed")
        normalized = _validate_payload(payload)
        encoded = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        self._process.stdin.write(encoded + "\n")
        flush = getattr(self._process.stdin, "flush", None)
        if callable(flush):
            flush()
        holder: dict[str, object] = {}

        def read_line() -> None:
            try:
                holder["text"] = self._process.stdout.readline(
                    MAX_WORKER_OUTPUT_BYTES + 1
                )
            except Exception as error:  # pragma: no cover - pipe failure
                holder["error"] = type(error).__name__

        reader = threading.Thread(
            target=read_line,
            name="edge-worker-session-stdout",
            daemon=True,
        )
        reader.start()
        reader.join(timeout=float(normalized["deadline_seconds"]))
        if reader.is_alive():
            _terminate_owned(self._process)
            self._closed = True
            raise _failure(
                "edge_worker_timeout", "owned Edge worker exceeded its deadline"
            )
        if "error" in holder:
            raise _failure("edge_worker_output_invalid", "worker output could not be read")
        batch = _parse_worker_output(holder.get("text"), 0)
        return _validate_projection_batch(batch, normalized)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if not getattr(self._process.stdin, "closed", True):
            self._process.stdin.close()
        try:
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            _terminate_owned(self._process)
        self._process.stdout.close()


def iter_edge_marketplace_events(
    payload: Mapping[str, object],
    *,
    worker_runner: Callable[..., Mapping[str, object]] = run_edge_worker,
    projection_evidence_sink: Callable[[Mapping[str, object]], object] | None = None,
    **worker_kwargs: object,
) -> Iterator[Mapping[str, object]]:
    """Yield existing browser projection events from one transient Edge worker."""
    normalized = _validate_payload(payload)
    batch = _validate_projection_batch(
        worker_runner(normalized, **worker_kwargs),
        normalized,
    )
    if projection_evidence_sink is not None:
        if not callable(projection_evidence_sink):
            raise _failure(
                "edge_worker_input_invalid",
                "projection_evidence_sink must be callable",
            )
        try:
            projection_evidence_sink(_projection_evidence(batch))
        except Exception as error:
            raise _failure(
                "projection_evidence_sink_failed",
                "projection evidence sink failed",
            ) from error
    try:
        yield from iter_browser_batch_events(_legacy_candidate_batch(batch))
    except BrowserBatchError as error:
        raise _failure(error.category, error.detail, retryable=error.retryable) from error


__all__ = [
    "EdgeWorkerSession",
    "EdgeWorkerFailure",
    "iter_edge_marketplace_events",
    "probe_edge_background_bridge",
    "run_edge_worker",
]
