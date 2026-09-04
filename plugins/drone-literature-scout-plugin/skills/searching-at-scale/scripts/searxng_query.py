"""Loopback-only SearXNG JSON search adapter."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from scripts.backend_runner import AdapterFailure


DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_SNIPPET_CHARS = 2000
ENGINE_HEALTH_CATEGORIES = frozenset(
    {"available", "unresponsive", "rate_limited", "captcha"}
)


@dataclass(frozen=True)
class SearxngEngineProbe:
    available: tuple[str, ...]
    unresponsive: tuple[str, ...]
    rate_limited: tuple[str, ...]
    captcha: tuple[str, ...]

    @property
    def cooldown_engines(self) -> tuple[str, ...]:
        return tuple(
            sorted({*self.unresponsive, *self.rate_limited, *self.captcha})
        )

    @property
    def next_engines(self) -> tuple[str, ...]:
        return self.available

    @property
    def runtime_available(self) -> bool:
        return bool(self.available)


def _base_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("base_url must be a loopback HTTP URL with an explicit port")
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError("base_url has an invalid port") from error
    if (
        parts.scheme != "http"
        or parts.hostname not in {"127.0.0.1", "localhost"}
        or port is None
        or not 1 <= port <= 65535
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise ValueError("base_url must be a loopback HTTP URL with an explicit port")
    return f"http://{parts.hostname}:{port}"


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _fetch_json(open_url, request: Request, timeout: float) -> Mapping[str, object]:
    try:
        with open_url(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        error.close()
        if error.code == 429:
            raise AdapterFailure("searxng_rate_limited", True, "HTTP 429") from error
        raise AdapterFailure(
            "searxng_http_error", error.code >= 500, f"HTTP {error.code}"
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise AdapterFailure("searxng_timeout", True, "request timed out") from error
    except URLError as error:
        raise AdapterFailure(
            "searxng_network_error", True, type(error.reason).__name__
        ) from error
    if not isinstance(payload, bytes) or len(payload) > MAX_RESPONSE_BYTES:
        raise AdapterFailure(
            "searxng_response_too_large", False, "JSON response exceeded byte limit"
        )
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdapterFailure("searxng_invalid_json", False, "invalid JSON") from error
    if not isinstance(value, Mapping):
        raise AdapterFailure("searxng_invalid_json", False, "response is not an object")
    return value


def _failure_health(reason: str) -> str:
    normalized = reason.casefold()
    if "captcha" in normalized:
        return "captcha"
    if "429" in normalized or "rate limit" in normalized:
        return "rate_limited"
    return "unresponsive"


def _engine_health(
    engines: list[str] | tuple[str, ...], unresponsive: object
) -> dict[str, str]:
    if not isinstance(unresponsive, list):
        raise AdapterFailure(
            "searxng_invalid_json", False, "unresponsive_engines must be an array"
        )
    health = {engine: "available" for engine in engines}
    for entry in unresponsive:
        if (
            not isinstance(entry, (list, tuple))
            or len(entry) < 2
            or not isinstance(entry[0], str)
            or not entry[0].strip()
            or not isinstance(entry[1], str)
        ):
            raise AdapterFailure(
                "searxng_invalid_json", False, "invalid unresponsive engine entry"
            )
        health[entry[0].strip()] = _failure_health(entry[1])
    return dict(sorted(health.items()))


def probe_searxng_engines(
    *,
    base_url: str,
    engines: tuple[str, ...] | list[str],
    open_url=urlopen,
    timeout_seconds: float = 3.0,
) -> SearxngEngineProbe:
    """Probe each requested engine once and return a four-way health partition."""
    base = _base_url(base_url)
    if not isinstance(engines, (tuple, list)) or not engines:
        raise ValueError("engines must be a non-empty sequence")
    if any(not isinstance(engine, str) or not engine.strip() for engine in engines):
        raise ValueError("engines must contain non-empty strings")
    normalized = tuple(dict.fromkeys(engine.strip() for engine in engines))
    if len(normalized) != len(engines):
        raise ValueError("engines must be unique")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or timeout_seconds <= 0
    ):
        raise ValueError("timeout_seconds must be finite and positive")
    categories: dict[str, list[str]] = {
        "available": [],
        "unresponsive": [],
        "rate_limited": [],
        "captcha": [],
    }
    for engine in normalized:
        request = Request(
            f"{base}/search?{urlencode((('q', 'site:example.com'), ('format', 'json'), ('engines', engine)))}",
            headers={
                "Accept": "application/json",
                "User-Agent": "searching-at-scale/1.0 (engine-preflight)",
            },
        )
        try:
            response = _fetch_json(open_url, request, float(timeout_seconds))
        except AdapterFailure as error:
            if error.category == "searxng_rate_limited":
                category = "rate_limited"
            else:
                category = "unresponsive"
        else:
            health = _engine_health(
                (engine,), response.get("unresponsive_engines", [])
            )
            category = health.get(engine, "available")
        categories[category].append(engine)
    return SearxngEngineProbe(
        available=tuple(sorted(categories["available"])),
        unresponsive=tuple(sorted(categories["unresponsive"])),
        rate_limited=tuple(sorted(categories["rate_limited"])),
        captcha=tuple(sorted(categories["captcha"])),
    )


def iter_searxng_events(
    payload: Mapping[str, object],
    *,
    base_url: str,
    open_url=urlopen,
) -> Iterator[dict[str, object]]:
    """Query a managed loopback instance without fetching result bodies."""
    if not isinstance(payload, Mapping):
        raise ValueError("SearXNG payload must be a mapping")
    base = _base_url(base_url)
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    query_family = str(payload.get("query_family", "searxng-search")).strip()
    if not query_family:
        raise ValueError("query_family must be non-empty")
    language = str(payload.get("language", "all")).strip()
    if not language:
        raise ValueError("language must be non-empty")
    pageno = _positive_int(payload.get("pageno", 1), "pageno")
    time_range = payload.get("time_range")
    if time_range is not None and time_range not in {"day", "week", "month", "year"}:
        raise ValueError("time_range must be day, week, month, or year")
    raw_engines = payload.get("engines", [])
    if not isinstance(raw_engines, list) or any(
        not isinstance(engine, str) or not engine.strip() for engine in raw_engines
    ):
        raise ValueError("engines must be an array of non-empty strings")
    engines = sorted({engine.strip() for engine in raw_engines})
    timeout = payload.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("timeout_seconds must be finite and positive")
    parameters: list[tuple[str, object]] = [
        ("q", query.strip()),
        ("format", "json"),
        ("language", language),
        ("pageno", pageno),
    ]
    if time_range is not None:
        parameters.append(("time_range", time_range))
    if engines:
        parameters.append(("engines", ",".join(engines)))
    request = Request(
        f"{base}/search?{urlencode(parameters)}",
        headers={
            "Accept": "application/json",
            "User-Agent": "searching-at-scale/1.0 (local-runtime)",
        },
    )
    response = _fetch_json(open_url, request, float(timeout))
    results = response.get("results", [])
    if not isinstance(results, list):
        raise AdapterFailure("searxng_invalid_json", False, "results must be an array")
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    raw_count = 0
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            raise AdapterFailure("searxng_invalid_json", False, "result is not an object")
        url = result.get("url")
        if not isinstance(url, str) or not url.strip():
            raise AdapterFailure("searxng_invalid_json", False, "result URL missing")
        result_engines: set[str] = set()
        engine = result.get("engine")
        if isinstance(engine, str) and engine.strip():
            result_engines.add(engine.strip())
        multiple = result.get("engines", [])
        if isinstance(multiple, list):
            result_engines.update(
                value.strip()
                for value in multiple
                if isinstance(value, str) and value.strip()
            )
        if not result_engines:
            result_engines.add("unknown")
        ordered_engines = sorted(result_engines)
        title = result.get("title", "")
        snippet = result.get("content", "")
        if not isinstance(title, str) or not isinstance(snippet, str):
            raise AdapterFailure(
                "searxng_invalid_json", False, "title and content must be strings"
            )
        positions = result.get("positions", [])
        rank = min(
            (value for value in positions if isinstance(value, int) and value > 0),
            default=index + 1,
        ) if isinstance(positions, list) else index + 1
        raw_count += 1
        yield {
            "type": "url",
            "url": url,
            "title": title,
            "snippet": snippet[:MAX_SNIPPET_CHARS],
            "channels": [f"searxng:{value}" for value in ordered_engines],
            "source_class": "search_engine",
            "query_family": query_family,
            "observed_at": observed_at,
            "metadata": {"engines": ordered_engines, "rank": rank},
        }
    unresponsive = response.get("unresponsive_engines", [])
    health = _engine_health(tuple(engines), unresponsive)
    cooldown = sorted(
        engine for engine, category in health.items() if category != "available"
    )
    yield {
        "type": "summary",
        "end_reason": "queue_exhausted",
        "metric_stage": "canonical_url",
        "telemetry": {
            "raw_url_observations": raw_count,
            "successful_pages": 1,
            "structured_records": 0,
            "unresponsive_engines": unresponsive,
            "engine_health": health,
            "cooldown_engines": cooldown,
        },
        "new_seeds": [],
        "round": {
            "query_family": query_family,
            "source_class": "search_engine",
            "new_valid_urls": raw_count,
            "new_entities": 0,
            "new_fields": 0,
            "mostly_duplicates": False,
        },
    }
