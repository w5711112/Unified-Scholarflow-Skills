from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import time
from typing import Literal, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from scripts.backend_runner import AdapterFailure
from scripts.duckdb_runtime import (
    DuckDBExecutionResult,
    DuckDBResourceProfile,
    ResourceSnapshot,
    choose_resource_profile,
    default_cache_root,
    ensure_duckdb,
    probe_resources,
    run_duckdb,
)


_COLLECTION_ID_RE = re.compile(r"CC-MAIN-\d{4}-\d{2}\Z")
_DATA_HOST = "data.commoncrawl.org"
_DATA_PREFIX = f"https://{_DATA_HOST}/"
_MANIFEST_TEMPLATE = (
    _DATA_PREFIX + "crawl-data/{index_id}/cc-index-table.paths.gz"
)
_PARQUET_PREFIX_TEMPLATE = (
    "cc-index/table/cc-main/warc/crawl={index_id}/subset=warc/"
)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"
_MAX_FETCH_BYTES = 64 * 1024 * 1024
_DEFAULT_BUDGET_SECONDS = 600.0
FetchBytes = Callable[..., bytes]


@dataclass(frozen=True)
class UrlIndexRuntime:
    ensure_duckdb: Callable[..., Path] = ensure_duckdb
    probe_resources: Callable[[Path | str], ResourceSnapshot] = probe_resources
    choose_resource_profile: Callable[..., DuckDBResourceProfile] = (
        choose_resource_profile
    )
    run_duckdb: Callable[..., DuckDBExecutionResult] = run_duckdb


DEFAULT_RUNTIME = UrlIndexRuntime()


@dataclass(frozen=True)
class UrlIndexRequest:
    scope: Literal["domain", "subdomain", "prefix"]
    value: str
    index_id: str
    raw_result_limit: int
    timeout_seconds: float
    query_family: str

    def __post_init__(self) -> None:
        if self.scope not in {"domain", "subdomain", "prefix"}:
            raise ValueError("scope must be domain, subdomain, or prefix")
        _validate_index_id(self.index_id)
        _required_safe_text(self.value, "value")
        _required_safe_text(self.query_family, "query_family")
        if isinstance(self.raw_result_limit, bool) or not isinstance(
            self.raw_result_limit, int
        ):
            raise ValueError("raw_result_limit must be a positive integer")
        if self.raw_result_limit <= 0:
            raise ValueError("raw_result_limit must be a positive integer")
        if isinstance(self.timeout_seconds, bool) or not isinstance(
            self.timeout_seconds, (int, float)
        ):
            raise ValueError("timeout_seconds must be positive")
        if not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        _normalized_target(self.scope, self.value)


@dataclass(frozen=True)
class UrlIndexPlan:
    sql: str
    index_id: str
    parquet_file_count: int
    raw_result_limit: int


@dataclass(frozen=True)
class UrlIndexShardMapPlan:
    sql: str
    index_id: str
    parquet_file_count: int


@dataclass(frozen=True)
class ShardRange:
    file_name: str
    min_host: str
    max_host: str


def _required_safe_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if _CONTROL_RE.search(value):
        raise ValueError(f"{name} must not contain control characters")
    return value.strip()


def _validate_index_id(index_id: object) -> str:
    if not isinstance(index_id, str) or not _COLLECTION_ID_RE.fullmatch(index_id):
        raise ValueError("index_id must look like CC-MAIN-YYYY-NN")
    return index_id


def manifest_url(index_id: str) -> str:
    return _MANIFEST_TEMPLATE.format(index_id=_validate_index_id(index_id))


def _manifest_failure(detail: str) -> AdapterFailure:
    return AdapterFailure("common_crawl_manifest_invalid", False, detail)


def parse_manifest(payload: bytes, index_id: str) -> tuple[str, ...]:
    """Validate one Common Crawl URL Index manifest and return trusted HTTPS URLs."""

    selected_id = _validate_index_id(index_id)
    if not isinstance(payload, bytes):
        raise _manifest_failure("manifest payload must be bytes")
    try:
        text = gzip.decompress(payload).decode("utf-8")
    except (OSError, EOFError, UnicodeDecodeError) as exc:
        raise _manifest_failure(f"manifest could not be decoded: {exc}") from exc

    crawl_prefix = (
        "cc-index/table/cc-main/warc/"
        f"crawl={selected_id}/subset="
    )
    required_prefix = _PARQUET_PREFIX_TEMPLATE.format(index_id=selected_id)
    urls: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        relative = raw_line.strip()
        if not relative:
            continue
        if (
            _CONTROL_RE.search(relative)
            or ".." in relative.split("/")
            or "://" in relative
            or relative.startswith(("/", "\\"))
            or not relative.startswith(crawl_prefix)
            or not relative.endswith(".parquet")
        ):
            raise _manifest_failure("manifest contains an untrusted parquet path")
        if not relative.startswith(required_prefix):
            continue
        url = _DATA_PREFIX + relative
        if url not in seen:
            seen.add(url)
            urls.append(url)

    if not urls:
        raise _manifest_failure("manifest contains no parquet paths")
    return tuple(urls)


def _idna_host(host: str) -> str:
    candidate = host.rstrip(".").lower()
    if not candidate or _CONTROL_RE.search(candidate):
        raise ValueError("host must be non-empty and safe")
    labels = candidate.split(".")
    if len(labels) < 2 or any(not label for label in labels):
        raise ValueError("host must contain at least two non-empty labels")
    try:
        encoded = ".".join(label.encode("idna").decode("ascii") for label in labels)
    except UnicodeError as exc:
        raise ValueError("host is not a valid IDN hostname") from exc
    if len(encoded) > 253 or any(len(label) > 63 for label in encoded.split(".")):
        raise ValueError("host is too long")
    return encoded


def _domain_target(value: str) -> tuple[str, str]:
    if "://" in value:
        raise ValueError("domain scope requires a hostname, not a URL")
    parsed = urlsplit("//" + value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("domain contains an invalid port") from exc
    if (
        parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        raise ValueError("domain scope requires a bare hostname")
    host = _idna_host(parsed.hostname)
    return host, host


def _prefix_target(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("prefix scope requires an HTTP or HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("prefix URL must not contain user information")
    if parsed.hostname is None or parsed.fragment:
        raise ValueError("prefix URL requires a hostname and no fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("prefix URL contains an invalid port") from exc
    host = _idna_host(parsed.hostname)
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    authority = host if port is None or default_port else f"{host}:{port}"
    canonical = urlunsplit(
        SplitResult(
            parsed.scheme.lower(),
            authority,
            parsed.path or "/",
            parsed.query,
            "",
        )
    )
    return host, canonical


def _normalized_target(scope: str, value: str) -> tuple[str, str]:
    safe_value = _required_safe_text(value, "value")
    if scope in {"domain", "subdomain"}:
        return _domain_target(safe_value)
    if scope == "prefix":
        return _prefix_target(safe_value)
    raise ValueError("scope must be domain, subdomain, or prefix")


def _reverse_host(host: str) -> str:
    return ".".join(reversed(host.split(".")))


def _sql_literal(value: object) -> str:
    text = str(value)
    if _CONTROL_RE.search(text):
        raise ValueError("SQL values must not contain control characters")
    return "'" + text.replace("'", "''") + "'"


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _path_literal(path: Path | str, name: str) -> str:
    if not isinstance(path, (str, Path)):
        raise ValueError(f"{name} must be a filesystem path")
    resolved = Path(path).resolve(strict=False).as_posix()
    _required_safe_text(resolved, name)
    return _sql_literal(resolved)


def _validated_parquet_urls(
    parquet_urls: Sequence[str], index_id: str
) -> tuple[str, ...]:
    if isinstance(parquet_urls, (str, bytes)):
        raise ValueError("parquet_urls must be a sequence of URLs")
    required_path = "/" + _PARQUET_PREFIX_TEMPLATE.format(index_id=index_id)
    trusted: list[str] = []
    seen: set[str] = set()
    for url in parquet_urls:
        if not isinstance(url, str) or _CONTROL_RE.search(url):
            raise ValueError("parquet URL must be a safe string")
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("parquet URL contains an invalid port") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != _DATA_HOST
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.path.startswith(required_path)
            or not parsed.path.endswith(".parquet")
            or ".." in parsed.path.split("/")
        ):
            raise ValueError("parquet URL is outside the selected Common Crawl index")
        if url not in seen:
            seen.add(url)
            trusted.append(url)
    if not trusted:
        raise ValueError("parquet_urls must contain at least one URL")
    return tuple(trusted)


def build_query_plan(
    request: UrlIndexRequest,
    parquet_urls: Sequence[str],
    result_path: Path | str,
    *,
    threads: int,
    memory_limit_bytes: int,
    max_temp_directory_size_bytes: int,
    temp_directory: Path | str,
    extension_directory: Path | str,
) -> UrlIndexPlan:
    """Build a bounded DuckDB URL Index query without executing it."""

    if not isinstance(request, UrlIndexRequest):
        raise TypeError("request must be an UrlIndexRequest")
    selected_threads = _positive_integer(threads, "threads")
    selected_memory = _positive_integer(memory_limit_bytes, "memory_limit_bytes")
    selected_temp_size = _positive_integer(
        max_temp_directory_size_bytes, "max_temp_directory_size_bytes"
    )
    trusted_urls = _validated_parquet_urls(parquet_urls, request.index_id)
    host, normalized_value = _normalized_target(request.scope, request.value)
    reversed_host = _reverse_host(host)
    tld = host.rsplit(".", 1)[-1]

    if request.scope == "domain":
        scope_predicate = (
            f"url_host_name_reversed = {_sql_literal(reversed_host)}"
        )
    elif request.scope == "subdomain":
        scope_predicate = (
            "(url_host_name_reversed = "
            f"{_sql_literal(reversed_host)} OR "
            "starts_with(url_host_name_reversed, "
            f"{_sql_literal(reversed_host + '.')})"
        )
    else:
        scope_predicate = (
            f"url_host_name_reversed = {_sql_literal(reversed_host)} AND "
            f"starts_with(url, {_sql_literal(normalized_value)})"
        )

    parquet_list = ", ".join(_sql_literal(url) for url in trusted_urls)
    sql = "\n".join(
        (
            f"SET extension_directory = {_path_literal(extension_directory, 'extension_directory')};",
            "INSTALL httpfs;",
            "LOAD httpfs;",
            f"SET threads = {selected_threads};",
            f"SET memory_limit = {_sql_literal(str(selected_memory) + 'B')};",
            f"SET temp_directory = {_path_literal(temp_directory, 'temp_directory')};",
            "SET max_temp_directory_size = "
            f"{_sql_literal(str(selected_temp_size) + 'B')};",
            "COPY (",
            "  SELECT",
            "    url_surtkey, url, url_host_name, url_host_name_reversed, url_path,",
            "    fetch_time, fetch_status, content_mime_type, content_mime_detected,",
            "    content_digest, warc_filename, warc_record_offset,",
            "    warc_record_length, crawl, subset",
            f"  FROM read_parquet([{parquet_list}], hive_partitioning=true, union_by_name=true)",
            f"  WHERE crawl = {_sql_literal(request.index_id)}",
            "    AND subset = 'warc'",
            "    AND fetch_status = 200",
            f"    AND url_host_tld = {_sql_literal(tld)}",
            f"    AND {scope_predicate}",
            f"  LIMIT {request.raw_result_limit}",
            f") TO {_path_literal(result_path, 'result_path')} (FORMAT JSON, ARRAY false);",
            "",
        )
    )
    return UrlIndexPlan(
        sql=sql,
        index_id=request.index_id,
        parquet_file_count=len(trusted_urls),
        raw_result_limit=request.raw_result_limit,
    )


def build_shard_map_plan(
    index_id: str,
    parquet_urls: Sequence[str],
    result_path: Path | str,
    *,
    threads: int,
    memory_limit_bytes: int,
    max_temp_directory_size_bytes: int,
    temp_directory: Path | str,
    extension_directory: Path | str,
) -> UrlIndexShardMapPlan:
    """Build a footer-only query that maps every trusted file to its host range."""

    selected_id = _validate_index_id(index_id)
    selected_threads = _positive_integer(threads, "threads")
    selected_memory = _positive_integer(memory_limit_bytes, "memory_limit_bytes")
    selected_temp_size = _positive_integer(
        max_temp_directory_size_bytes, "max_temp_directory_size_bytes"
    )
    trusted_urls = _validated_parquet_urls(parquet_urls, selected_id)
    parquet_list = ", ".join(_sql_literal(url) for url in trusted_urls)
    sql = "\n".join(
        (
            f"SET extension_directory = {_path_literal(extension_directory, 'extension_directory')};",
            "INSTALL httpfs;",
            "LOAD httpfs;",
            f"SET threads = {selected_threads};",
            f"SET memory_limit = {_sql_literal(str(selected_memory) + 'B')};",
            f"SET temp_directory = {_path_literal(temp_directory, 'temp_directory')};",
            "SET max_temp_directory_size = "
            f"{_sql_literal(str(selected_temp_size) + 'B')};",
            "COPY (",
            "  SELECT file_name,",
            "    min(stats_min_value) AS min_host,",
            "    max(stats_max_value) AS max_host",
            f"  FROM parquet_metadata([{parquet_list}])",
            "  WHERE path_in_schema = 'url_host_name_reversed'",
            "  GROUP BY file_name",
            "  ORDER BY file_name",
            f") TO {_path_literal(result_path, 'result_path')} (FORMAT JSON, ARRAY false);",
            "",
        )
    )
    return UrlIndexShardMapPlan(sql, selected_id, len(trusted_urls))


def _shard_map_failure(detail: str) -> AdapterFailure:
    return AdapterFailure("common_crawl_shard_map_invalid", False, detail)


def parse_shard_map(
    payload: bytes,
    index_id: str,
    parquet_urls: Sequence[str],
) -> tuple[ShardRange, ...]:
    selected_id = _validate_index_id(index_id)
    trusted_urls = _validated_parquet_urls(parquet_urls, selected_id)
    if not isinstance(payload, bytes):
        raise _shard_map_failure("shard map payload must be bytes")
    rows: dict[str, ShardRange] = {}
    for raw_line in payload.splitlines():
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _shard_map_failure("shard map contains invalid JSONL") from exc
        if not isinstance(row, Mapping):
            raise _shard_map_failure("shard map row is not an object")
        file_name = row.get("file_name")
        min_host = row.get("min_host")
        max_host = row.get("max_host")
        if (
            not isinstance(file_name, str)
            or file_name not in trusted_urls
            or file_name in rows
            or not isinstance(min_host, str)
            or not min_host
            or _CONTROL_RE.search(min_host)
            or not isinstance(max_host, str)
            or not max_host
            or _CONTROL_RE.search(max_host)
            or min_host > max_host
        ):
            raise _shard_map_failure("shard map row is invalid or untrusted")
        rows[file_name] = ShardRange(file_name, min_host, max_host)
    if set(rows) != set(trusted_urls):
        raise _shard_map_failure("shard map does not cover every manifest parquet")
    return tuple(rows[url] for url in trusted_urls)


def select_candidate_parquet_urls(
    request: UrlIndexRequest,
    shard_map: Sequence[ShardRange],
) -> tuple[str, ...]:
    if not isinstance(request, UrlIndexRequest):
        raise TypeError("request must be an UrlIndexRequest")
    host, _ = _normalized_target(request.scope, request.value)
    reversed_host = _reverse_host(host)
    candidates: list[str] = []
    for shard in shard_map:
        if not isinstance(shard, ShardRange):
            raise TypeError("shard_map must contain ShardRange values")
        if request.scope == "subdomain":
            overlaps = (
                shard.max_host >= reversed_host
                and shard.min_host < reversed_host + "/"
            )
        else:
            overlaps = shard.min_host <= reversed_host <= shard.max_host
        if overlaps:
            candidates.append(shard.file_name)
    return tuple(candidates)


def fetch_bytes(
    url: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int = _MAX_FETCH_BYTES,
) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "searching-at-scale/1.0 (+metadata-only)",
            "Accept": "application/json, application/gzip, application/octet-stream",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(max_response_bytes + 1)
    except HTTPError as exc:
        exc.close()
        if exc.code in {429, 503}:
            raise AdapterFailure(
                "common_crawl_rate_limited", True, f"HTTP {exc.code}"
            ) from exc
        raise AdapterFailure(
            "common_crawl_http_error", exc.code >= 500, f"HTTP {exc.code}"
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise AdapterFailure("common_crawl_timeout", True, "request timed out") from exc
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise AdapterFailure(
                "common_crawl_timeout", True, "request timed out"
            ) from exc
        raise AdapterFailure(
            "common_crawl_network_error", True, type(exc.reason).__name__
        ) from exc
    if len(payload) > max_response_bytes:
        raise AdapterFailure(
            "common_crawl_response_too_large", False, "response exceeded byte limit"
        )
    return payload


def _fetch(fetcher: FetchBytes, url: str, timeout_seconds: float) -> bytes:
    try:
        payload = fetcher(url, timeout_seconds=timeout_seconds)
    except AdapterFailure:
        raise
    except (TimeoutError, socket.timeout) as exc:
        raise AdapterFailure("common_crawl_timeout", True, "request timed out") from exc
    except Exception as exc:
        raise AdapterFailure(
            "common_crawl_network_error", True, type(exc).__name__
        ) from exc
    if not isinstance(payload, bytes):
        raise AdapterFailure(
            "common_crawl_invalid_response", False, "fetcher returned non-bytes"
        )
    return payload


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AdapterFailure(
            "common_crawl_timeout", True, "the 10-minute task budget was exhausted"
        )
    return remaining


def _select_index_id(
    requested_id: object,
    fetcher: FetchBytes,
    deadline: float,
) -> str:
    if requested_id is not None:
        return _validate_index_id(requested_id)
    payload = _fetch(
        fetcher,
        _COLLECTIONS_URL,
        min(60.0, _remaining_seconds(deadline)),
    )
    try:
        collections = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdapterFailure(
            "common_crawl_invalid_collections", False, "invalid collection JSON"
        ) from exc
    if not isinstance(collections, list):
        raise AdapterFailure(
            "common_crawl_invalid_collections", False, "collection list is invalid"
        )
    for item in collections:
        if not isinstance(item, Mapping):
            continue
        candidate = item.get("id")
        if isinstance(candidate, str) and _COLLECTION_ID_RE.fullmatch(candidate):
            return candidate
    raise AdapterFailure(
        "common_crawl_invalid_collections", False, "no valid collection ID found"
    )


def _manifest_cache_path(cache_root: Path, index_id: str) -> Path:
    return (
        cache_root
        / "common-crawl"
        / "manifests"
        / f"{_validate_index_id(index_id)}.paths.gz"
    )


def _shard_map_cache_path(cache_root: Path, index_id: str) -> Path:
    return (
        cache_root
        / "common-crawl"
        / "shard-maps"
        / f"{_validate_index_id(index_id)}.ndjson"
    )


def _write_atomic_cache(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    partial_path = Path(partial_name)
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial_path, path)
    finally:
        try:
            partial_path.unlink()
        except FileNotFoundError:
            pass


def _cached_shard_map(
    cache_root: Path,
    index_id: str,
    parquet_urls: Sequence[str],
) -> tuple[ShardRange, ...] | None:
    path = _shard_map_cache_path(cache_root, index_id)
    if not path.is_file():
        return None
    try:
        return parse_shard_map(path.read_bytes(), index_id, parquet_urls)
    except (OSError, AdapterFailure):
        return None


def _load_manifest(
    index_id: str,
    *,
    fetcher: FetchBytes,
    cache_root: Path,
    deadline: float,
) -> tuple[str, ...]:
    cache_path = _manifest_cache_path(cache_root, index_id)
    if cache_path.is_file():
        try:
            return parse_manifest(cache_path.read_bytes(), index_id)
        except (OSError, AdapterFailure):
            pass

    payload = _fetch(
        fetcher,
        manifest_url(index_id),
        min(120.0, _remaining_seconds(deadline)),
    )
    parquet_urls = parse_manifest(payload, index_id)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{index_id}.", suffix=".partial", dir=cache_path.parent
    )
    partial_path = Path(partial_name)
    try:
        with os.fdopen(file_descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial_path, cache_path)
    finally:
        try:
            partial_path.unlink()
        except FileNotFoundError:
            pass
    return parquet_urls


def _positive_budget(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError("timeout_seconds must be positive and finite")
    return min(_DEFAULT_BUDGET_SECONDS, float(value))


def _raw_limit(payload: Mapping[str, object]) -> int:
    value = payload.get("raw_result_limit", payload.get("max_records", 5_000))
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("raw_result_limit must be a positive integer")
    return value


def _runtime_method(runtime: object, name: str) -> Callable[..., object]:
    method = getattr(runtime, name, None)
    if not callable(method):
        raise TypeError(f"runtime must provide callable {name}")
    return method


def _records_from_result(path: Path) -> tuple[tuple[Mapping[str, object], ...], bool]:
    if not path.exists():
        return (), False
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise AdapterFailure(
            "common_crawl_dependency", False, "could not read DuckDB result"
        ) from exc
    records: list[Mapping[str, object]] = []
    truncated = False
    lines = payload.splitlines(keepends=True)
    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped:
            continue
        has_line_ending = raw_line.endswith((b"\n", b"\r"))
        try:
            value = json.loads(stripped.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if index == len(lines) - 1 and not has_line_ending:
                truncated = True
                continue
            raise AdapterFailure(
                "common_crawl_schema_changed", False, "invalid DuckDB JSONL output"
            ) from exc
        if not isinstance(value, Mapping):
            raise AdapterFailure(
                "common_crawl_schema_changed", False, "DuckDB row is not an object"
            )
        records.append(value)
    return tuple(records), truncated


def _observed_at(fetch_time: object) -> str:
    if not isinstance(fetch_time, str) or not fetch_time.strip():
        return "1970-01-01T00:00:00Z"
    candidate = fetch_time.strip().replace(" ", "T", 1)
    if candidate.endswith("+00"):
        candidate += ":00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return "1970-01-01T00:00:00Z"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _url_event(
    record: Mapping[str, object], query_family: str, rank: int
) -> Mapping[str, object]:
    raw_url = record.get("url")
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise AdapterFailure(
            "common_crawl_schema_changed", False, "DuckDB row is missing URL"
        )
    return {
        "type": "url",
        "url": raw_url,
        "title": "",
        "snippet": "",
        "channels": ["common_crawl"],
        "source_class": "open_index",
        "query_family": query_family,
        "observed_at": _observed_at(record.get("fetch_time")),
        "metadata": {
            "source_role": "historical_index",
            "crawl": record.get("crawl", ""),
            "crawl_timestamp": record.get("fetch_time", ""),
            "status": record.get("fetch_status", ""),
            "mime": record.get(
                "content_mime_type", record.get("content_mime_detected", "")
            ),
            "digest": record.get("content_digest", ""),
            "warc_filename": record.get("warc_filename", ""),
            "warc_offset": record.get("warc_record_offset", ""),
            "warc_length": record.get("warc_record_length", ""),
            "rank": rank,
        },
    }


def _failure_from_stderr(stderr_path: Path, returncode: int | None) -> AdapterFailure:
    try:
        detail = stderr_path.read_text(encoding="utf-8", errors="replace")[-2_000:]
    except OSError:
        detail = ""
    lowered = detail.lower()
    if any(
        marker in lowered
        for marker in ("out of memory", "memory limit", "no space", "disk full")
    ):
        category, retryable = "common_crawl_resource_limit", True
    elif any(marker in lowered for marker in ("extension", "httpfs")):
        category, retryable = "common_crawl_dependency", False
    elif any(
        marker in lowered
        for marker in (
            "http",
            "network",
            "connection",
            "dns",
            "tls",
            "ssl",
            "timed out",
        )
    ):
        category, retryable = "common_crawl_network_error", True
    elif any(marker in lowered for marker in ("binder error", "column", "schema")):
        category, retryable = "common_crawl_schema_changed", False
    else:
        category, retryable = "common_crawl_dependency", False
    summary = f"DuckDB exited with code {returncode}"
    if detail.strip():
        summary += f": {detail.strip()}"
    return AdapterFailure(category, retryable, summary)


def iter_backend_events(
    payload: Mapping[str, object],
    *,
    fetcher: FetchBytes = fetch_bytes,
    runtime: object = DEFAULT_RUNTIME,
    cache_root: Path | str | None = None,
    cancel_event: object | None = None,
) -> Iterator[Mapping[str, object]]:
    """Query one Common Crawl URL Index crawl and yield bounded metadata events."""

    if not isinstance(payload, Mapping):
        raise ValueError("Common Crawl URL Index payload must be a mapping")
    scope = payload.get("scope")
    value = payload.get("value")
    query_family = payload.get("query_family", "common-crawl-history")
    budget = _positive_budget(
        payload.get("timeout_seconds", _DEFAULT_BUDGET_SECONDS)
    )
    deadline = time.monotonic() + budget
    index_id = _select_index_id(payload.get("index_id"), fetcher, deadline)
    request = UrlIndexRequest(
        scope=scope,
        value=value,
        index_id=index_id,
        raw_result_limit=_raw_limit(payload),
        timeout_seconds=budget,
        query_family=query_family,
    )
    selected_cache_root = (
        Path(cache_root).resolve(strict=False)
        if cache_root is not None
        else default_cache_root().resolve(strict=False)
    )
    parquet_urls = _load_manifest(
        index_id,
        fetcher=fetcher,
        cache_root=selected_cache_root,
        deadline=deadline,
    )

    batches_root = selected_cache_root / "common-crawl" / "batches"
    batches_root.mkdir(parents=True, exist_ok=True)
    batch_directory = Path(tempfile.mkdtemp(prefix="batch-", dir=batches_root))
    result_path = batch_directory / "result.ndjson"
    sql_path = batch_directory / "query.sql"
    stdout_path = batch_directory / "duckdb.stdout.log"
    stderr_path = batch_directory / "duckdb.stderr.log"
    shard_map_result_path = batch_directory / "shard-map.ndjson"
    shard_map_sql_path = batch_directory / "shard-map.sql"
    shard_map_stdout_path = batch_directory / "shard-map.stdout.log"
    shard_map_stderr_path = batch_directory / "shard-map.stderr.log"
    duckdb_temp = batch_directory / "duckdb-temp"
    extension_directory = selected_cache_root / "duckdb" / "extensions"
    duckdb_temp.mkdir(parents=True, exist_ok=True)
    extension_directory.mkdir(parents=True, exist_ok=True)

    try:
        ensure_method = _runtime_method(runtime, "ensure_duckdb")
        probe_method = _runtime_method(runtime, "probe_resources")
        choose_method = _runtime_method(runtime, "choose_resource_profile")
        run_method = _runtime_method(runtime, "run_duckdb")
        try:
            executable = ensure_method(
                cache_root=selected_cache_root,
                duckdb_path=payload.get("duckdb_path"),
            )
            snapshot = probe_method(batches_root)
            if not isinstance(snapshot, ResourceSnapshot):
                raise TypeError("runtime probe_resources returned an invalid snapshot")
            remaining = _remaining_seconds(deadline)
            profile = choose_method(
                snapshot,
                scope=request.scope,
                raw_result_limit=request.raw_result_limit,
                remaining_seconds=remaining,
            )
            if not isinstance(profile, DuckDBResourceProfile):
                raise TypeError("runtime returned an invalid resource profile")
            shard_map = _cached_shard_map(
                selected_cache_root, index_id, parquet_urls
            )
            shard_map_cache_hit = shard_map is not None
            metadata_elapsed = 0.0
            if shard_map is None:
                shard_plan = build_shard_map_plan(
                    index_id,
                    parquet_urls,
                    shard_map_result_path,
                    threads=profile.threads,
                    memory_limit_bytes=profile.memory_limit_bytes,
                    max_temp_directory_size_bytes=(
                        profile.max_temp_directory_size_bytes
                    ),
                    temp_directory=duckdb_temp,
                    extension_directory=extension_directory,
                )
                shard_map_sql_path.write_text(
                    shard_plan.sql, encoding="utf-8", newline="\n"
                )
                shard_timeout = min(300.0, _remaining_seconds(deadline))
                shard_execution = run_method(
                    executable,
                    shard_map_sql_path,
                    shard_map_stdout_path,
                    shard_map_stderr_path,
                    timeout_seconds=shard_timeout,
                    cancel_event=cancel_event,
                )
                if not isinstance(shard_execution, DuckDBExecutionResult):
                    raise TypeError("runtime returned invalid shard-map result")
                if shard_execution.timed_out:
                    raise AdapterFailure(
                        "common_crawl_timeout",
                        True,
                        "DuckDB shard-map query timed out",
                    )
                if shard_execution.cancelled:
                    raise AdapterFailure(
                        "common_crawl_cancelled",
                        True,
                        "DuckDB shard-map query was cancelled",
                    )
                if shard_execution.returncode != 0:
                    raise _failure_from_stderr(
                        shard_map_stderr_path, shard_execution.returncode
                    )
                try:
                    shard_payload = shard_map_result_path.read_bytes()
                except OSError as exc:
                    raise AdapterFailure(
                        "common_crawl_shard_map_invalid",
                        False,
                        "DuckDB did not produce a shard map",
                    ) from exc
                shard_map = parse_shard_map(
                    shard_payload, index_id, parquet_urls
                )
                _write_atomic_cache(
                    _shard_map_cache_path(selected_cache_root, index_id),
                    shard_payload,
                )
                metadata_elapsed = shard_execution.elapsed_seconds

            candidate_urls = select_candidate_parquet_urls(request, shard_map)
            actual_timeout = min(
                profile.timeout_seconds, _remaining_seconds(deadline)
            )
            if candidate_urls:
                plan = build_query_plan(
                    request,
                    candidate_urls,
                    result_path,
                    threads=profile.threads,
                    memory_limit_bytes=profile.memory_limit_bytes,
                    max_temp_directory_size_bytes=(
                        profile.max_temp_directory_size_bytes
                    ),
                    temp_directory=duckdb_temp,
                    extension_directory=extension_directory,
                )
                sql_path.write_text(plan.sql, encoding="utf-8", newline="\n")
                execution = run_method(
                    executable,
                    sql_path,
                    stdout_path,
                    stderr_path,
                    timeout_seconds=actual_timeout,
                    cancel_event=cancel_event,
                )
            else:
                execution = DuckDBExecutionResult(0, False, False, 0.0, None)
        except AdapterFailure:
            raise
        except (URLError, ConnectionError) as exc:
            raise AdapterFailure(
                "common_crawl_network_error", True, "DuckDB setup network failure"
            ) from exc
        except TimeoutError as exc:
            raise AdapterFailure(
                "common_crawl_timeout", True, "DuckDB setup timed out"
            ) from exc
        except (OSError, RuntimeError, TypeError) as exc:
            raise AdapterFailure(
                "common_crawl_dependency", False, type(exc).__name__
            ) from exc

        if not isinstance(execution, DuckDBExecutionResult):
            raise AdapterFailure(
                "common_crawl_dependency", False, "runtime returned invalid result"
            )
        records, truncated = _records_from_result(result_path)
        if execution.timed_out and not records:
            raise AdapterFailure(
                "common_crawl_timeout", True, "DuckDB timed out before a complete row"
            )
        if execution.cancelled and not records:
            raise AdapterFailure(
                "common_crawl_cancelled", True, "DuckDB was cancelled before a complete row"
            )
        if execution.returncode not in {0} and not (
            execution.timed_out or execution.cancelled
        ):
            raise _failure_from_stderr(stderr_path, execution.returncode)

        events = [
            _url_event(record, request.query_family, rank)
            for rank, record in enumerate(records)
        ]
        raw_count = len(events)
        if execution.timed_out:
            end_reason, incomplete_reason = "partial", "timeout"
        elif execution.cancelled:
            end_reason, incomplete_reason = "partial", "cancelled"
        elif raw_count >= request.raw_result_limit:
            end_reason, incomplete_reason = "partial", "result_limit"
        elif truncated:
            end_reason, incomplete_reason = "partial", "truncated_output"
        else:
            end_reason, incomplete_reason = "queue_exhausted", None

        summary: dict[str, object] = {
            "type": "summary",
            "end_reason": end_reason,
            "metric_stage": "canonical_url",
            "telemetry": {
                "raw_url_observations": raw_count,
                "successful_pages": 1 if execution.returncode == 0 else 0,
                "structured_records": 0,
            },
            "new_seeds": [],
            "round": {
                "query_family": request.query_family,
                "source_class": "open_index",
                "new_valid_urls": raw_count,
                "new_entities": 0,
                "new_fields": 0,
                "mostly_duplicates": False,
            },
            "scope_completion": {
                "boundary": (
                    f"{index_id}:{request.scope}:{request.value}:"
                    f"limit={request.raw_result_limit}"
                ),
                "crawl": index_id,
                "expected_pages": 1,
                "completed_pages": 1 if end_reason == "queue_exhausted" else 0,
                "failed_pages": 0 if execution.returncode == 0 else 1,
            },
            "deterministic_scope_complete": end_reason == "queue_exhausted",
            "duckdb_profile": {
                "threads": profile.threads,
                "memory_limit_bytes": profile.memory_limit_bytes,
                "max_temp_directory_size_bytes": (
                    profile.max_temp_directory_size_bytes
                ),
                "timeout_seconds": actual_timeout,
            },
            "resource_snapshot": {
                "logical_cpus": snapshot.logical_cpus,
                "total_memory_bytes": snapshot.total_memory_bytes,
                "available_memory_bytes": snapshot.available_memory_bytes,
                "free_disk_bytes": snapshot.free_disk_bytes,
            },
            "parquet_file_count": len(parquet_urls),
            "candidate_parquet_file_count": len(candidate_urls),
            "shard_map_cache_hit": shard_map_cache_hit,
            "elapsed_seconds": metadata_elapsed + execution.elapsed_seconds,
        }
        if incomplete_reason is not None:
            summary["incomplete_reason"] = incomplete_reason
    finally:
        shutil.rmtree(batch_directory, ignore_errors=True)

    yield from events
    yield summary


__all__ = [
    "DEFAULT_RUNTIME",
    "ShardRange",
    "UrlIndexPlan",
    "UrlIndexRequest",
    "UrlIndexRuntime",
    "UrlIndexShardMapPlan",
    "build_query_plan",
    "build_shard_map_plan",
    "fetch_bytes",
    "iter_backend_events",
    "manifest_url",
    "parse_manifest",
    "parse_shard_map",
    "select_candidate_parquet_urls",
]
