"""Polite, metadata-only Common Crawl CDXJ adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import re
import socket
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from scripts.backend_runner import AdapterFailure


COLLECTIONS_URL = "https://index.commoncrawl.org/collinfo.json"
OFFICIAL_INDEX_HOST = "index.commoncrawl.org"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
FetchBytes = Callable[..., bytes]
BulkAdapter = Callable[[Mapping[str, object]], Iterator[Mapping[str, object]]]


@dataclass(frozen=True)
class CommonCrawlRequest:
    scope: Literal["exact", "domain", "subdomain", "prefix"]
    value: str
    index_id: str | None = None
    start_page: int = 0
    workers: int = 1
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_pages: int = 100
    max_records: int = 100

    def __post_init__(self) -> None:
        if self.scope not in {"exact", "domain", "subdomain", "prefix"}:
            raise ValueError("scope must be exact, domain, subdomain, or prefix")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("value must be a non-empty string")
        if any(ord(character) < 32 for character in self.value):
            raise ValueError("value contains control characters")
        if self.index_id is not None and (
            not isinstance(self.index_id, str)
            or not re.fullmatch(r"CC-MAIN-\d{4}-\d{2}", self.index_id)
        ):
            raise ValueError("index_id must be a CC-MAIN collection ID")
        if (
            isinstance(self.start_page, bool)
            or not isinstance(self.start_page, int)
            or self.start_page < 0
        ):
            raise ValueError("start_page must be a non-negative integer")
        if (
            isinstance(self.workers, bool)
            or not isinstance(self.workers, int)
            or self.workers < 1
            or self.workers > 2
        ):
            raise ValueError("workers must be 1 or 2")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if (
            isinstance(self.max_pages, bool)
            or not isinstance(self.max_pages, int)
            or self.max_pages < 1
        ):
            raise ValueError("max_pages must be a positive integer")
        if (
            isinstance(self.max_records, bool)
            or not isinstance(self.max_records, int)
            or self.max_records < 1
        ):
            raise ValueError("max_records must be a positive integer")


def _official_endpoint(endpoint: object) -> str:
    if not isinstance(endpoint, str):
        raise AdapterFailure(
            "common_crawl_untrusted_endpoint", False, "CDX endpoint is not text"
        )
    parts = urlsplit(endpoint)
    if (
        parts.scheme != "https"
        or parts.hostname != OFFICIAL_INDEX_HOST
        or parts.username is not None
        or parts.password is not None
        or parts.port not in {None, 443}
        or not parts.path.endswith("-index")
        or parts.query
        or parts.fragment
    ):
        raise AdapterFailure(
            "common_crawl_untrusted_endpoint", False, "CDX endpoint is not official"
        )
    return endpoint


def _scope_query(request: CommonCrawlRequest) -> tuple[str, str]:
    value = request.value.strip()
    if request.scope == "exact":
        return value, "exact"
    if request.scope == "domain":
        return value, "domain"
    if request.scope == "subdomain":
        return (value if value.startswith("*.") else f"*.{value}"), "domain"
    return value, "prefix"


def build_query_url(
    endpoint: str,
    request: CommonCrawlRequest,
    *,
    show_num_pages: bool = False,
    page: int | None = None,
) -> str:
    base = _official_endpoint(endpoint)
    query_value, match_type = _scope_query(request)
    parameters: list[tuple[str, object]] = [("url", query_value)]
    if match_type != "exact":
        parameters.append(("matchType", match_type))
    parameters.extend(
        (
            ("output", "json"),
            ("filter", "status:200"),
        )
    )
    if match_type == "exact":
        parameters.append(("limit", request.max_records))
    if show_num_pages:
        parameters.append(("showNumPages", "true"))
    if page is not None:
        if isinstance(page, bool) or not isinstance(page, int) or page < 0:
            raise ValueError("page must be a non-negative integer")
        parameters.append(("page", page))
    return f"{base}?{urlencode(parameters)}"


def fetch_bytes(
    url: str,
    *,
    timeout_seconds: float,
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "searching-at-scale/1.0 (+metadata-only; polite-client)",
            "Accept": "application/json, application/x-ndjson, text/plain",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read(max_response_bytes + 1)
    except HTTPError as error:
        error.close()
        if error.code in {429, 503}:
            raise AdapterFailure(
                "common_crawl_rate_limited", True, f"HTTP {error.code}"
            ) from error
        raise AdapterFailure(
            "common_crawl_http_error", error.code >= 500, f"HTTP {error.code}"
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise AdapterFailure("common_crawl_timeout", True, "request timed out") from error
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise AdapterFailure(
                "common_crawl_timeout", True, "request timed out"
            ) from error
        raise AdapterFailure(
            "common_crawl_network_error", True, type(error.reason).__name__
        ) from error
    if len(payload) > max_response_bytes:
        raise AdapterFailure(
            "common_crawl_response_too_large", False, "response exceeded byte limit"
        )
    return payload


def _fetch(fetcher: FetchBytes, url: str, timeout_seconds: float) -> bytes:
    try:
        value = fetcher(url, timeout_seconds=timeout_seconds)
    except AdapterFailure:
        raise
    except (TimeoutError, socket.timeout) as error:
        raise AdapterFailure("common_crawl_timeout", True, "request timed out") from error
    except Exception as error:
        raise AdapterFailure(
            "common_crawl_network_error", True, type(error).__name__
        ) from error
    if not isinstance(value, bytes):
        raise AdapterFailure(
            "common_crawl_invalid_response", False, "fetcher returned non-bytes"
        )
    return value


def _json_value(payload: bytes, category: str) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterFailure(category, False, "invalid JSON") from error


def _select_collection(
    payload: bytes, requested_id: str | None
) -> tuple[str, str]:
    collections = _json_value(payload, "common_crawl_invalid_collections")
    if not isinstance(collections, list) or not collections:
        raise AdapterFailure(
            "common_crawl_invalid_collections", False, "collection list is empty"
        )
    selected = None
    for item in collections:
        if not isinstance(item, Mapping):
            continue
        if requested_id is None or item.get("id") == requested_id:
            selected = item
            break
    if selected is None:
        raise AdapterFailure(
            "common_crawl_index_not_found", False, "requested collection missing"
        )
    index_id = selected.get("id")
    if not isinstance(index_id, str):
        raise AdapterFailure(
            "common_crawl_invalid_collections", False, "collection ID missing"
        )
    return index_id, _official_endpoint(selected.get("cdx-api"))


def _page_count(payload: bytes) -> int:
    value = _json_value(payload, "common_crawl_invalid_page_count")
    if not isinstance(value, Mapping):
        raise AdapterFailure(
            "common_crawl_invalid_page_count", False, "page count is not an object"
        )
    pages = value.get("pages")
    if isinstance(pages, bool) or not isinstance(pages, int) or pages < 0:
        raise AdapterFailure(
            "common_crawl_invalid_page_count", False, "pages is invalid"
        )
    return pages


def _records(payload: bytes) -> tuple[Mapping[str, object], ...]:
    if not payload.strip():
        raise AdapterFailure("common_crawl_page_missing", True, "empty index page")
    records: list[Mapping[str, object]] = []
    for line in payload.splitlines():
        if not line.strip():
            continue
        value = _json_value(line, "common_crawl_invalid_jsonl")
        if not isinstance(value, Mapping):
            raise AdapterFailure(
                "common_crawl_invalid_jsonl", False, "record is not an object"
            )
        records.append(value)
    if not records:
        raise AdapterFailure("common_crawl_page_missing", True, "index page has no records")
    return tuple(records)


def _observed_at(timestamp: object) -> str:
    if isinstance(timestamp, str) and re.fullmatch(r"\d{14}", timestamp):
        value = datetime.strptime(timestamp, "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc
        )
        return value.isoformat().replace("+00:00", "Z")
    return "1970-01-01T00:00:00Z"


def _request_from_payload(payload: Mapping[str, object]) -> CommonCrawlRequest:
    return CommonCrawlRequest(
        scope=payload.get("scope"),
        value=payload.get("value"),
        index_id=payload.get("index_id"),
        start_page=payload.get("start_page", 0),
        workers=payload.get("workers", 1),
        timeout_seconds=payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        max_pages=payload.get("max_pages", 100),
        max_records=payload.get("max_records", 100),
    )


def iter_backend_events(
    payload: Mapping[str, object],
    *,
    fetcher: FetchBytes = fetch_bytes,
    bulk_adapter: BulkAdapter | None = None,
) -> Iterator[Mapping[str, object]]:
    """Yield historical URL metadata and one deterministic terminal summary."""
    if not isinstance(payload, Mapping):
        raise ValueError("Common Crawl payload must be a mapping")
    request = _request_from_payload(payload)
    query_family = str(payload.get("query_family", "common-crawl-history")).strip()
    if not query_family:
        raise ValueError("query_family must be non-empty")
    if request.scope != "exact":
        if bulk_adapter is None:
            from scripts.common_crawl_url_index import (
                iter_backend_events as bulk_adapter,
            )

        yield from bulk_adapter(payload)
        return
    collection_payload = _fetch(
        fetcher, COLLECTIONS_URL, float(request.timeout_seconds)
    )
    index_id, endpoint = _select_collection(collection_payload, request.index_id)
    records = _records(
        _fetch(
            fetcher,
            build_query_url(endpoint, request),
            float(request.timeout_seconds),
        )
    )
    raw_count = 0
    for rank, record in enumerate(records):
        raw_url = record.get("url")
        if not isinstance(raw_url, str) or not raw_url.strip():
            raise AdapterFailure(
                "common_crawl_invalid_jsonl", False, "record URL missing"
            )
        raw_count += 1
        yield {
            "type": "url",
            "url": raw_url,
            "title": "",
            "snippet": "",
            "channels": ["common_crawl"],
            "source_class": "open_index",
            "query_family": query_family,
            "observed_at": _observed_at(record.get("timestamp")),
            "metadata": {
                "source_role": "historical_index",
                "crawl_timestamp": str(record.get("timestamp", "")),
                "status": str(record.get("status", "")),
                "mime": str(record.get("mime", "")),
                "warc_filename": str(record.get("filename", "")),
                "warc_offset": str(record.get("offset", "")),
                "warc_length": str(record.get("length", "")),
                "rank": rank,
            },
        }
    full_completion = raw_count < request.max_records
    completion = {
        "boundary": f"{index_id}:exact:{request.value}:limit={request.max_records}",
        "expected_pages": 1,
        "completed_pages": 1,
        "failed_pages": 0,
    }
    yield {
        "type": "summary",
        "end_reason": "queue_exhausted" if full_completion else "partial",
        "metric_stage": "canonical_url",
        "telemetry": {
            "raw_url_observations": raw_count,
            "successful_pages": 1,
            "structured_records": 0,
        },
        "new_seeds": [],
        "round": {
            "query_family": query_family,
            "source_class": "open_index",
            "new_valid_urls": raw_count,
            "new_entities": 0,
            "new_fields": 0,
            "mostly_duplicates": False,
        },
        "scope_completion": completion,
        "deterministic_scope_complete": full_completion,
    }
