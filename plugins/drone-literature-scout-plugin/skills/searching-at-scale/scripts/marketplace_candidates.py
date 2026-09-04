from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MarketplacePlatform = Literal["jd", "taobao"]

_JD_PC_PATH = re.compile(r"/(\d+)\.html")
_JD_MOBILE_PATH = re.compile(r"/product/(\d+)\.html")
_TAOBAO_PRODUCT_HOSTS = frozenset(
    {
        "item.taobao.com",
        "detail.tmall.com",
        "detail.tmall.hk",
    }
)
BROWSER_BATCH_KEYS = frozenset(
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
        "items",
    }
)
ITEM_KEYS = frozenset({"product_id", "title", "url"})
CARD_FIELD_KEYS = frozenset(
    {"price", "shop", "commit", "good_rate", "promo", "stock", "image"}
)
_CURSOR_KEYS = frozenset({"cursor_id", "page_number", "status"})
_CURSOR_STATUSES = frozenset({"advanced", "exhausted", "stalled"})
_PAGINATION_STATES = frozenset(
    {"pagination_unverified", "page_verified", "page_exhausted", "page_stalled"}
)
_BLOCKED_PAGE_STATES = {
    "authentication_required": "browser_authentication_required",
    "captcha_required": "browser_captcha_required",
    "page_structure_changed": "browser_page_structure_changed",
    "rate_limited": "browser_rate_limited",
}


@dataclass
class BrowserBatchError(ValueError):
    category: str
    retryable: bool
    detail: str

    def __str__(self) -> str:
        return f"{self.category}: {self.detail}"


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


@dataclass(frozen=True)
class MarketplaceCandidate:
    platform: MarketplacePlatform
    product_id: str
    title: str
    canonical_url: str
    discovery_channel: str
    query_family: str
    observed_at: str
    card_fields: Mapping[str, str] = field(default_factory=dict)


def _safe_url_parts(url: object):
    if not isinstance(url, str) or not url.strip():
        return None
    if any(ord(character) < 32 for character in url):
        return None
    try:
        parts = urlsplit(url.strip())
        hostname = parts.hostname.lower() if parts.hostname else ""
        port = parts.port
    except (AttributeError, ValueError):
        return None
    if (
        parts.scheme.lower() not in {"http", "https"}
        or not hostname
        or "@" in parts.netloc
        or "\\" in parts.netloc
        or (port is not None and port not in {80, 443})
    ):
        return None
    return parts, hostname


def _jd_identity(hostname: str, path: str) -> tuple[MarketplacePlatform, str, str] | None:
    pattern = None
    if hostname == "item.jd.com":
        pattern = _JD_PC_PATH
    elif hostname == "item.m.jd.com":
        pattern = _JD_MOBILE_PATH
    if pattern is None:
        return None
    match = pattern.fullmatch(path)
    if match is None:
        return None
    product_id = match.group(1)
    return "jd", product_id, f"https://item.jd.com/{product_id}.html"


def _taobao_identity(
    hostname: str, path: str, query: str
) -> tuple[MarketplacePlatform, str, str] | None:
    if hostname not in _TAOBAO_PRODUCT_HOSTS or path != "/item.htm":
        return None
    try:
        values = [
            value
            for key, value in parse_qsl(
                query,
                keep_blank_values=True,
                encoding="utf-8",
                errors="strict",
            )
            if key == "id"
        ]
    except UnicodeDecodeError:
        return None
    if len(values) != 1 or not values[0].isdigit():
        return None
    product_id = values[0]
    canonical = urlunsplit(
        ("https", hostname, "/item.htm", urlencode({"id": product_id}), "")
    )
    return "taobao", product_id, canonical


def candidate_from_url(
    *,
    url: str,
    title: str,
    discovery_channel: str,
    query_family: str,
    observed_at: str,
    card_fields: Mapping[str, object] | None = None,
) -> MarketplaceCandidate | None:
    """Return a verified marketplace identity or ``None`` for a plain URL."""
    channel = _required_text(discovery_channel, "discovery_channel")
    family = _required_text(query_family, "query_family")
    timestamp = _required_text(observed_at, "observed_at")
    if not isinstance(title, str):
        raise ValueError("title must be a string")
    normalized_title = title.strip()
    if not normalized_title:
        return None
    safe_parts = _safe_url_parts(url)
    if safe_parts is None:
        return None
    parts, hostname = safe_parts
    identity = _jd_identity(hostname, parts.path)
    if identity is None:
        identity = _taobao_identity(hostname, parts.path, parts.query)
    if identity is None:
        return None
    platform, product_id, canonical_url = identity
    normalized_card_fields: dict[str, str] = {}
    if isinstance(card_fields, Mapping):
        for key, value in card_fields.items():
            if key in CARD_FIELD_KEYS and isinstance(value, str) and value.strip():
                normalized_card_fields[key] = value.strip()
    return MarketplaceCandidate(
        platform=platform,
        product_id=product_id,
        title=normalized_title,
        canonical_url=canonical_url,
        discovery_channel=channel,
        query_family=family,
        observed_at=timestamp,
        card_fields=normalized_card_fields,
    )


def _browser_invalid(detail: str) -> BrowserBatchError:
    return BrowserBatchError("browser_batch_invalid", False, detail)


def _exact_keys(
    value: Mapping[str, object], allowed: frozenset[str], name: str
) -> None:
    keys = set(value)
    if keys != allowed:
        unknown = sorted(keys - allowed)
        missing = sorted(allowed - keys)
        detail = f"{name} keys must match whitelist"
        if unknown:
            detail += f"; unknown={unknown[0]}"
        if missing:
            detail += f"; missing={missing[0]}"
        raise _browser_invalid(detail)


def _keys_within_allowed(
    value: Mapping[str, object],
    required: frozenset[str],
    optional: frozenset[str],
    name: str,
) -> None:
    keys = set(value)
    allowed = required | optional
    unknown = sorted(keys - allowed)
    missing = sorted(required - keys)
    if unknown or missing:
        detail = f"{name} keys are outside the allowed whitelist"
        if unknown:
            detail += f"; unknown={unknown[0]}"
        if missing:
            detail += f"; missing={missing[0]}"
        raise _browser_invalid(detail)


def _browser_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _browser_invalid(f"{name} must be a non-empty string")
    return value.strip()


def _validated_browser_batch(
    payload: Mapping[str, object],
) -> tuple[str, str, dict[str, object], tuple[MarketplaceCandidate, ...]]:
    if not isinstance(payload, Mapping):
        raise _browser_invalid("payload must be a mapping")
    _exact_keys(payload, BROWSER_BATCH_KEYS, "payload")
    if payload.get("projection_schema_version") != 3:
        raise BrowserBatchError(
            "edge_extension_reload_required", False, "projection schema is stale"
        )
    capabilities = payload.get("capabilities")
    if capabilities != ["stable_card_fields_v2", "verified_pagination_v1"]:
        raise BrowserBatchError(
            "edge_extension_reload_required", False, "projection capability is stale"
        )
    platform = _browser_text(payload.get("platform"), "platform").lower()
    if platform not in {"jd", "taobao"}:
        raise _browser_invalid("unsupported platform")
    page_state = _browser_text(payload.get("page_state"), "page_state")
    if page_state in _BLOCKED_PAGE_STATES:
        raise BrowserBatchError(_BLOCKED_PAGE_STATES[page_state], False, page_state)
    if page_state != "ready":
        raise _browser_invalid("unsupported page_state")
    source_url = _browser_text(payload.get("source_url"), "source_url")
    if _safe_url_parts(source_url) is None:
        raise _browser_invalid("source_url must be a safe HTTP URL")
    query_family = _browser_text(payload.get("query_family"), "query_family")

    cursor = payload.get("cursor")
    if not isinstance(cursor, Mapping):
        raise _browser_invalid("cursor must be a mapping")
    _exact_keys(cursor, _CURSOR_KEYS, "cursor")
    cursor_id = _browser_text(cursor.get("cursor_id"), "cursor_id")
    page_number = cursor.get("page_number")
    if (
        isinstance(page_number, bool)
        or not isinstance(page_number, int)
        or page_number < 1
    ):
        raise _browser_invalid("page_number must be a positive integer")
    cursor_status = _browser_text(cursor.get("status"), "cursor status")
    if cursor_status not in _CURSOR_STATUSES:
        raise _browser_invalid("unsupported cursor status")
    observed_page_number = payload.get("observed_page_number")
    if (
        isinstance(observed_page_number, bool)
        or not isinstance(observed_page_number, int)
        or observed_page_number < 1
        or observed_page_number != page_number
    ):
        raise _browser_invalid(
            "observed_page_number must equal the requested page_number"
        )
    pagination_state = _browser_text(
        payload.get("pagination_state"), "pagination_state"
    )
    if pagination_state not in _PAGINATION_STATES:
        raise _browser_invalid("unsupported pagination_state")
    has_next_page = payload.get("has_next_page")
    if not isinstance(has_next_page, bool):
        raise _browser_invalid("has_next_page must be a boolean")
    sku_digest = _browser_text(payload.get("sku_digest"), "sku_digest")
    if len(sku_digest) > 4096:
        raise _browser_invalid("sku_digest exceeds its bound")
    cursor_evidence = {
        "platform": platform,
        "cursor_id": cursor_id,
        "page_number": page_number,
        "status": cursor_status,
        "observed_page_number": observed_page_number,
        "pagination_state": pagination_state,
        "has_next_page": has_next_page,
        "sku_digest": sku_digest,
    }

    items = payload.get("items")
    if not isinstance(items, list):
        raise _browser_invalid("items must be a list")
    if len(items) > 1000:
        raise _browser_invalid("items exceeds 1000 public projections")
    channel = f"edge:{platform}"
    observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    candidates: list[MarketplaceCandidate] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise _browser_invalid("item must be a mapping")
        _exact_keys(item, ITEM_KEYS | CARD_FIELD_KEYS, "item")
        for field_name in CARD_FIELD_KEYS:
            field_value = item.get(field_name)
            if field_value is not None and (
                not isinstance(field_value, str) or not field_value.strip()
            ):
                raise _browser_invalid(
                    f"{field_name} must be non-empty text or null"
                )
        product_id = _browser_text(item.get("product_id"), "product_id")
        if not product_id.isdigit():
            raise _browser_invalid("product_id must be numeric")
        title = _browser_text(item.get("title"), "title")
        url = _browser_text(item.get("url"), "url")
        candidate = candidate_from_url(
            url=url,
            title=title,
            discovery_channel=channel,
            query_family=query_family,
            observed_at=observed_at,
            card_fields=item,
        )
        if (
            candidate is None
            or candidate.platform != platform
            or candidate.product_id != product_id
        ):
            raise _browser_invalid("item identity does not match its URL")
        candidates.append(candidate)
    return platform, query_family, cursor_evidence, tuple(candidates)


def iter_browser_batch_events(
    payload: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    """Validate a public Edge projection and emit URL events plus one summary."""
    platform, query_family, cursor_evidence, candidates = _validated_browser_batch(
        payload
    )
    for candidate in candidates:
        yield {
            "type": "url",
            "url": candidate.canonical_url,
            "title": candidate.title,
            "snippet": "",
            "channels": [f"edge:{platform}"],
            "source_class": "marketplace_list",
            "query_family": query_family,
            "observed_at": candidate.observed_at,
            "metadata": {
                "source_role": "marketplace_store",
                "platform": candidate.platform,
                "product_id": candidate.product_id,
                "card_fields": dict(candidate.card_fields),
            },
        }
    cursor_status = str(cursor_evidence["status"])
    yield {
        "type": "summary",
        "end_reason": "queue_exhausted" if cursor_status == "exhausted" else "partial",
        "metric_stage": "marketplace_candidate",
        "cursor_evidence": cursor_evidence,
        "telemetry": {
            "raw_url_observations": len(candidates),
            "successful_pages": 1,
            "structured_records": len(candidates),
        },
        "new_seeds": [],
        "round": {
            "query_family": query_family,
            "source_class": "marketplace_list",
            "new_valid_urls": len(candidates),
            "new_entities": len(candidates),
            "new_fields": 0,
            "mostly_duplicates": False,
        },
    }
