from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import blake2b
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
from types import TracebackType
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from .marketplace_candidates import CARD_FIELD_KEYS, candidate_from_url
except ImportError:  # pragma: no cover - direct script execution
    from marketplace_candidates import CARD_FIELD_KEYS, candidate_from_url


TRACKING_KEYS = {"fbclid", "gclid", "spm", "yclid"}
ALLOWED_OBSERVATION_METADATA = frozenset(
    {
        "source_role",
        "mime",
        "status",
        "crawl_timestamp",
        "warc_filename",
        "warc_offset",
        "warc_length",
        "engines",
        "rank",
        "platform",
        "product_id",
        "card_fields",
    }
)
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _is_tracking(key: str) -> bool:
    lowered = key.lower()
    return lowered.startswith("utm_") or lowered in TRACKING_KEYS


def _has_malformed_percent_escape(value: str) -> bool:
    for index, character in enumerate(value):
        if character == "%" and (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            return True
    return False


def _canonical_host(hostname: str) -> str | None:
    """Validate a conservative, ASCII-only host representation."""
    if not hostname or not hostname.isascii():
        return None
    if any(character.isspace() or ord(character) < 32 for character in hostname):
        return None
    host = hostname.lower()
    if ":" in host:
        try:
            ipaddress.IPv6Address(host)
        except ValueError:
            return None
        return host
    if len(host) > 253 or any(
        not _HOST_LABEL.fullmatch(label) for label in host.split(".")
    ):
        return None
    return host


def _canonical_query(raw_query: str) -> str | None:
    if _has_malformed_percent_escape(raw_query):
        return None
    try:
        pairs = parse_qsl(
            raw_query,
            keep_blank_values=True,
            encoding="utf-8",
            errors="strict",
        )
    except UnicodeDecodeError:
        return None

    values_by_key: dict[str, list[str]] = {}
    for key, value in pairs:
        if not _is_tracking(key):
            values_by_key.setdefault(key, []).append(value)
    ordered_pairs = [
        (key, value)
        for key in sorted(values_by_key)
        for value in values_by_key[key]
    ]
    return urlencode(ordered_pairs)


def normalize_url(raw: str) -> str | None:
    """Return a conservative canonical HTTP(S) URL, or ``None`` if unsafe."""
    if not isinstance(raw, str) or any(ord(character) < 32 for character in raw):
        return None
    cleaned = raw.strip()
    if _has_malformed_percent_escape(cleaned):
        return None
    try:
        parts = urlsplit(cleaned)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or not parts.hostname:
            return None
        if "@" in parts.netloc or "\\" in parts.netloc or any(
            character.isspace() or ord(character) < 32 for character in parts.netloc
        ):
            return None
        host = _canonical_host(parts.hostname)
        if host is None:
            return None
        port = parts.port
    except ValueError:
        return None

    query = _canonical_query(parts.query)
    if query is None:
        return None
    default_port = (scheme == "http" and port in {None, 80}) or (
        scheme == "https" and port in {None, 443}
    )
    bracketed_host = f"[{host}]" if ":" in host else host
    netloc = bracketed_host if default_port else f"{bracketed_host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", query, ""))


def url_fingerprint(canonical: str) -> bytes:
    return blake2b(canonical.encode("utf-8"), digest_size=16).digest()


@dataclass(frozen=True)
class AddOutcome:
    valid: bool
    duplicate: bool
    canonical_url: str | None
    reason: str | None = None
    candidate_added: bool = False


@dataclass(frozen=True)
class UrlProvenance:
    canonical_url: str
    domain: str
    query_families: tuple[str, ...]
    source_classes: tuple[str, ...]
    access_limited: bool


@dataclass(frozen=True)
class LedgerStats:
    raw_results: int
    valid_urls: int
    unique_urls: int
    duplicate_results: int
    unique_domains: int
    access_limited_urls: int
    source_class_urls: tuple[tuple[str, int], ...]
    query_family_urls: tuple[tuple[str, int], ...]


@dataclass
class _Entry:
    canonical_url: str
    domain: str
    query_family: str
    source_class: str
    access_limited: bool = False
    additional_query_families: set[str] | None = None
    additional_source_classes: set[str] | None = None

    def merge_provenance(
        self, query_family: str, source_class: str, access_limited: bool
    ) -> tuple[bool, bool, bool]:
        query_added = query_family != self.query_family and (
            self.additional_query_families is None
            or query_family not in self.additional_query_families
        )
        source_added = source_class != self.source_class and (
            self.additional_source_classes is None
            or source_class not in self.additional_source_classes
        )
        if query_added:
            if self.additional_query_families is None:
                self.additional_query_families = {query_family}
            else:
                self.additional_query_families.add(query_family)
        if source_added:
            if self.additional_source_classes is None:
                self.additional_source_classes = {source_class}
            else:
                self.additional_source_classes.add(source_class)
        access_added = access_limited and not self.access_limited
        self.access_limited = self.access_limited or access_limited
        return source_added, query_added, access_added

    def provenance(self) -> UrlProvenance:
        query_families = {self.query_family}
        source_classes = {self.source_class}
        if self.additional_query_families is not None:
            query_families.update(self.additional_query_families)
        if self.additional_source_classes is not None:
            source_classes.update(self.additional_source_classes)
        return UrlProvenance(
            self.canonical_url,
            self.domain,
            tuple(sorted(query_families)),
            tuple(sorted(source_classes)),
            self.access_limited,
        )


class UrlLedger:
    """In-memory L0 identity/provenance ledger with collision-safe lookup."""

    def __init__(self) -> None:
        self._raw = 0
        self._valid = 0
        self._unique = 0
        self._duplicates = 0
        self._access_limited_urls = 0
        self._domain_counts: dict[str, int] = {}
        self._source_class_counts: dict[str, int] = {}
        self._query_family_counts: dict[str, int] = {}
        # Normal digests store one compact entry. A dict appears only after collision.
        self._entries_by_hash: dict[bytes, _Entry | dict[str, _Entry]] = {}

    def _record_provenance(
        self, entry: _Entry, query_family: str, source_class: str, access_limited: bool
    ) -> None:
        source_added, query_added, access_added = entry.merge_provenance(
            query_family, source_class, access_limited
        )
        if source_added:
            self._source_class_counts[source_class] = (
                self._source_class_counts.get(source_class, 0) + 1
            )
        if query_added:
            self._query_family_counts[query_family] = (
                self._query_family_counts.get(query_family, 0) + 1
            )
        if access_added:
            self._access_limited_urls += 1

    def _new_entry(
        self, canonical: str, query_family: str, source_class: str, access_limited: bool
    ) -> _Entry:
        domain = urlsplit(canonical).hostname
        assert domain is not None
        entry = _Entry(canonical, domain, query_family, source_class, access_limited)
        self._unique += 1
        self._domain_counts[domain] = self._domain_counts.get(domain, 0) + 1
        self._source_class_counts[source_class] = (
            self._source_class_counts.get(source_class, 0) + 1
        )
        self._query_family_counts[query_family] = (
            self._query_family_counts.get(query_family, 0) + 1
        )
        if access_limited:
            self._access_limited_urls += 1
        return entry

    def add(
        self,
        raw_url: str,
        *,
        title: str,
        query_family: str,
        source_class: str,
        access_limited: bool = False,
    ) -> AddOutcome:
        """Record identity and compact route metadata; title/snippets are discarded."""
        del title
        self._raw += 1
        canonical = normalize_url(raw_url)
        if canonical is None:
            return AddOutcome(False, False, None, "invalid-http-url")

        self._valid += 1
        digest = url_fingerprint(canonical)
        stored = self._entries_by_hash.get(digest)
        if stored is None:
            self._entries_by_hash[digest] = self._new_entry(
                canonical, query_family, source_class, access_limited
            )
            return AddOutcome(True, False, canonical)

        if isinstance(stored, _Entry):
            if stored.canonical_url == canonical:
                self._duplicates += 1
                self._record_provenance(
                    stored, query_family, source_class, access_limited
                )
                return AddOutcome(True, True, canonical)
            new_entry = self._new_entry(
                canonical, query_family, source_class, access_limited
            )
            self._entries_by_hash[digest] = {
                stored.canonical_url: stored,
                canonical: new_entry,
            }
            return AddOutcome(True, False, canonical)

        entry = stored.get(canonical)
        if entry is None:
            stored[canonical] = self._new_entry(
                canonical, query_family, source_class, access_limited
            )
            return AddOutcome(True, False, canonical)
        self._duplicates += 1
        self._record_provenance(entry, query_family, source_class, access_limited)
        return AddOutcome(True, True, canonical)

    def provenance_for(self, raw_url: str) -> UrlProvenance | None:
        """Return compact provenance for an accepted URL, if it was recorded."""
        canonical = normalize_url(raw_url)
        if canonical is None:
            return None
        stored = self._entries_by_hash.get(url_fingerprint(canonical))
        if isinstance(stored, _Entry):
            return stored.provenance() if stored.canonical_url == canonical else None
        if stored is None:
            return None
        entry = stored.get(canonical)
        return entry.provenance() if entry is not None else None

    def stats(self) -> LedgerStats:
        return LedgerStats(
            self._raw,
            self._valid,
            self._unique,
            self._duplicates,
            len(self._domain_counts),
            self._access_limited_urls,
            tuple(sorted(self._source_class_counts.items())),
            tuple(sorted(self._query_family_counts.items())),
        )


def _required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


_RECOVERY_STAGE_ATTEMPTS = {"initial": 0, "reproject": 1, "reload": 2}
_RECOVERY_CATEGORY_DISPOSITIONS = {
    "pagination_page_transient_empty": "retry_same_page",
    "pagination_page_stalled": "retry_same_page",
    "browser_page_structure_changed": "rotate_family",
    "pagination_session_missing": "rotate_family",
    "page_exhausted": "rotate_family",
    "authentication_required": "hard_block",
    "browser_authentication_required": "hard_block",
    "captcha_required": "hard_block",
    "browser_captcha_required": "hard_block",
    "rate_limited": "hard_block",
    "browser_rate_limited": "hard_block",
}


def _bounded_recovery_text(value: object, name: str, maximum: int) -> str:
    normalized = _required_text(value, name)
    if len(normalized) > maximum or any(ord(character) < 32 for character in normalized):
        raise ValueError(f"{name} is outside its safe text bound")
    return normalized


def _summary_count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _card_fields_json(value: Mapping[str, str]) -> str:
    normalized = {
        key: field_value.strip()
        for key, field_value in value.items()
        if key in CARD_FIELD_KEYS
        and isinstance(field_value, str)
        and field_value.strip()
    }
    return json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def _read_card_fields_json(value: object) -> dict[str, str]:
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, Mapping):
        return {}
    return {
        key: field_value.strip()
        for key, field_value in parsed.items()
        if key in CARD_FIELD_KEYS
        and isinstance(field_value, str)
        and field_value.strip()
    }


@dataclass(frozen=True)
class UrlObservation:
    url: str
    title: str
    snippet: str
    channels: tuple[str, ...]
    source_class: str
    query_family: str
    observed_at: str
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        _required_text(self.url, "url")
        if not isinstance(self.title, str) or not isinstance(self.snippet, str):
            raise ValueError("title and snippet must be strings")
        if not isinstance(self.channels, tuple) or not self.channels:
            raise ValueError("channels must be a non-empty tuple")
        if any(not isinstance(value, str) or not value.strip() for value in self.channels):
            raise ValueError("channels must contain non-empty strings")
        _required_text(self.source_class, "source_class")
        _required_text(self.query_family, "query_family")
        _required_text(self.observed_at, "observed_at")
        if not isinstance(self.metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        forbidden = set(self.metadata) - ALLOWED_OBSERVATION_METADATA
        if forbidden:
            raise ValueError(f"metadata-key-not-allowed: {sorted(forbidden)[0]}")
        try:
            json.dumps(dict(self.metadata), ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            raise ValueError("metadata must be JSON serializable") from error


@dataclass(frozen=True)
class BatchSpec:
    batch_id: str
    run_id: str
    task_id: str
    adapter: str
    scope_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "batch_id",
            "run_id",
            "task_id",
            "adapter",
            "scope_fingerprint",
        ):
            _required_text(getattr(self, name), name)


@dataclass(frozen=True)
class BatchLedgerStats:
    batch_id: str
    run_id: str
    task_id: str
    adapter: str
    scope_fingerprint: str
    end_reason: str
    raw_url_observations: int
    valid_urls: int
    unique_additions: int
    unique_candidate_additions: int
    terminal_summary: Mapping[str, object]


@dataclass(frozen=True)
class SqliteUrlProvenance:
    canonical_url: str
    domain: str
    discovery_channels: tuple[str, ...]
    query_families: tuple[str, ...]
    source_classes: tuple[str, ...]
    source_roles: tuple[str, ...]


@dataclass(frozen=True)
class SqliteMarketplaceCandidate:
    platform: str
    product_id: str
    title: str
    canonical_url: str
    first_observed_at: str
    first_batch_id: str
    card_fields: Mapping[str, str]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    query_id TEXT PRIMARY KEY,
    query_family TEXT NOT NULL,
    dimensions_json TEXT NOT NULL,
    status TEXT NOT NULL,
    unique_yield REAL,
    failure_category TEXT
);
CREATE TABLE IF NOT EXISTS batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    adapter TEXT NOT NULL,
    scope_fingerprint TEXT NOT NULL,
    status TEXT NOT NULL,
    end_reason TEXT NOT NULL,
    raw_url_observations INTEGER NOT NULL,
    valid_urls INTEGER NOT NULL,
    unique_additions INTEGER NOT NULL,
    unique_candidate_additions INTEGER NOT NULL DEFAULT 0,
    terminal_summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS urls (
    url_id INTEGER PRIMARY KEY,
    canonical_url TEXT NOT NULL UNIQUE,
    fingerprint BLOB NOT NULL,
    domain TEXT NOT NULL,
    first_raw_url TEXT NOT NULL,
    title TEXT NOT NULL,
    snippet TEXT NOT NULL,
    page_type TEXT,
    stage TEXT NOT NULL DEFAULT 'L0'
);
CREATE TABLE IF NOT EXISTS url_channels (
    url_id INTEGER NOT NULL REFERENCES urls(url_id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    source_class TEXT NOT NULL,
    query_family TEXT NOT NULL,
    first_batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    source_role TEXT,
    PRIMARY KEY (url_id, channel, source_class, query_family)
);
CREATE TABLE IF NOT EXISTS marketplace_candidates (
    platform TEXT NOT NULL,
    product_id TEXT NOT NULL,
    url_id INTEGER NOT NULL UNIQUE REFERENCES urls(url_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    first_batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    card_fields_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (platform, product_id)
);
CREATE TABLE IF NOT EXISTS marketplace_cursors (
    cursor_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    query_family TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('advanced', 'exhausted', 'blocked')),
    last_batch_id TEXT NOT NULL REFERENCES batches(batch_id),
    unique_candidate_additions INTEGER NOT NULL CHECK (unique_candidate_additions >= 0)
);
CREATE TABLE IF NOT EXISTS marketplace_recovery_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    query_family TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    recovery_stage TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    category TEXT NOT NULL,
    disposition TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS objects (
    object_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL,
    stable_key TEXT NOT NULL UNIQUE,
    verification_stage TEXT NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coverage_gaps (
    gap_id TEXT PRIMARY KEY,
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS failures (
    failure_id TEXT PRIMARY KEY,
    batch_id TEXT,
    category TEXT NOT NULL,
    parameter_digest TEXT NOT NULL,
    compensation_route TEXT,
    detail TEXT NOT NULL
);
"""


class _BatchWriter:
    def __init__(self, ledger: "SqliteUrlLedger", spec: BatchSpec) -> None:
        self._ledger = ledger
        self.spec = spec
        self._finished = False
        self._entered = False
        self._idempotent = False
        self._existing_summary: dict[str, object] | None = None
        self._raw = 0
        self._valid = 0
        self._unique = 0
        self._unique_candidates = 0

    def __enter__(self) -> "_BatchWriter":
        if self._entered:
            raise ValueError("batch-writer-cannot-be-reentered")
        if self._ledger._active_batch:
            raise ValueError("nested-batches-are-not-supported")
        connection = self._ledger._connection
        connection.execute("BEGIN IMMEDIATE")
        self._entered = True
        self._ledger._active_batch = True
        row = connection.execute(
            "SELECT * FROM batches WHERE batch_id = ?", (self.spec.batch_id,)
        ).fetchone()
        if row is not None:
            identity = (
                row["run_id"],
                row["task_id"],
                row["adapter"],
                row["scope_fingerprint"],
            )
            expected = (
                self.spec.run_id,
                self.spec.task_id,
                self.spec.adapter,
                self.spec.scope_fingerprint,
            )
            if row["status"] != "complete" or identity != expected:
                connection.rollback()
                self._ledger._active_batch = False
                raise ValueError("batch-id-conflict")
            self._idempotent = True
            self._existing_summary = json.loads(row["terminal_summary_json"])
            return self
        connection.execute(
            """
            INSERT INTO batches (
                batch_id, run_id, task_id, adapter, scope_fingerprint,
                status, end_reason, raw_url_observations, valid_urls,
                unique_additions, unique_candidate_additions,
                terminal_summary_json
            ) VALUES (?, ?, ?, ?, ?, 'open', '', 0, 0, 0, 0, '{}')
            """,
            (
                self.spec.batch_id,
                self.spec.run_id,
                self.spec.task_id,
                self.spec.adapter,
                self.spec.scope_fingerprint,
            ),
        )
        return self

    def add(self, observation: UrlObservation) -> AddOutcome:
        if not self._entered or self._finished:
            raise ValueError("batch-writer-is-not-open")
        if not isinstance(observation, UrlObservation):
            raise ValueError("observation must be a UrlObservation")
        self._raw += 1
        url_canonical = normalize_url(observation.url)
        if url_canonical is None:
            raise ValueError("invalid-http-url")
        self._valid += 1
        if self._idempotent:
            return AddOutcome(True, True, url_canonical)

        candidate = candidate_from_url(
            url=observation.url,
            title=observation.title,
            discovery_channel=sorted(observation.channels)[0],
            query_family=observation.query_family,
            observed_at=observation.observed_at,
            card_fields=observation.metadata.get("card_fields"),
        )
        canonical = (
            candidate.canonical_url if candidate is not None else url_canonical
        )

        domain = urlsplit(canonical).hostname
        assert domain is not None
        cursor = self._ledger._connection.execute(
            """
            INSERT OR IGNORE INTO urls (
                canonical_url, fingerprint, domain, first_raw_url, title, snippet
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                canonical,
                url_fingerprint(canonical),
                domain,
                observation.url,
                observation.title,
                observation.snippet,
            ),
        )
        added = cursor.rowcount == 1
        if added:
            self._unique += 1
        row = self._ledger._connection.execute(
            "SELECT url_id FROM urls WHERE canonical_url = ?", (canonical,)
        ).fetchone()
        assert row is not None
        source_role = observation.metadata.get("source_role")
        if source_role is not None and not isinstance(source_role, str):
            raise ValueError("source_role must be a string")
        for channel in sorted({value.strip() for value in observation.channels}):
            self._ledger._connection.execute(
                """
                INSERT OR IGNORE INTO url_channels (
                    url_id, channel, source_class, query_family,
                    first_batch_id, source_role
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["url_id"],
                    channel,
                    observation.source_class.strip(),
                    observation.query_family.strip(),
                    self.spec.batch_id,
                    source_role,
                ),
            )
        candidate_added = False
        declared_platform = observation.metadata.get("platform")
        declared_product_id = observation.metadata.get("product_id")
        if (
            candidate is not None
            and declared_platform == candidate.platform
            and declared_product_id == candidate.product_id
        ):
            cursor = self._ledger._connection.execute(
                """
                INSERT OR IGNORE INTO marketplace_candidates (
                    platform, product_id, url_id, title,
                    first_observed_at, first_batch_id, card_fields_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.platform,
                    candidate.product_id,
                    row["url_id"],
                    candidate.title,
                    candidate.observed_at,
                    self.spec.batch_id,
                    _card_fields_json(candidate.card_fields),
                ),
            )
            candidate_added = cursor.rowcount == 1
            if candidate_added:
                self._unique_candidates += 1
            elif candidate.card_fields:
                existing = self._ledger._connection.execute(
                    """
                    SELECT card_fields_json
                    FROM marketplace_candidates
                    WHERE platform = ? AND product_id = ?
                    """,
                    (candidate.platform, candidate.product_id),
                ).fetchone()
                if existing is not None:
                    merged = _read_card_fields_json(existing["card_fields_json"])
                    changed = False
                    for key, value in candidate.card_fields.items():
                        if key not in merged and value:
                            merged[key] = value
                            changed = True
                    if changed:
                        self._ledger._connection.execute(
                            """
                            UPDATE marketplace_candidates
                            SET card_fields_json = ?
                            WHERE platform = ? AND product_id = ?
                            """,
                            (
                                _card_fields_json(merged),
                                candidate.platform,
                                candidate.product_id,
                            ),
                        )
        return AddOutcome(
            True,
            not added,
            canonical,
            candidate_added=candidate_added,
        )

    def finish(self, terminal_summary: Mapping[str, object]) -> None:
        if not self._entered or self._finished:
            raise ValueError("finish-must-be-called-exactly-once")
        if not isinstance(terminal_summary, Mapping):
            raise ValueError("terminal summary must be a mapping")
        summary_value = dict(terminal_summary)
        end_reason = _required_text(summary_value.get("end_reason"), "end_reason")
        raw = _summary_count(
            summary_value.get("raw_url_observations"), "raw_url_observations"
        )
        valid = _summary_count(summary_value.get("valid_urls"), "valid_urls")
        unique = _summary_count(
            summary_value.get("unique_additions"), "unique_additions"
        )
        unique_candidates = _summary_count(
            summary_value.get("unique_candidate_additions", 0),
            "unique_candidate_additions",
        )
        summary_value["unique_candidate_additions"] = unique_candidates
        if raw != self._raw or valid != self._valid:
            raise ValueError("summary-count-mismatch")
        if self._idempotent:
            assert self._existing_summary is not None
            existing_counts = (
                self._existing_summary.get("raw_url_observations"),
                self._existing_summary.get("valid_urls"),
                self._existing_summary.get("unique_additions"),
                self._existing_summary.get("unique_candidate_additions", 0),
                self._existing_summary.get("end_reason"),
            )
            if existing_counts != (
                raw,
                valid,
                unique,
                unique_candidates,
                end_reason,
            ):
                raise ValueError("idempotent-summary-mismatch")
            self._finished = True
            return
        if unique != self._unique or unique_candidates != self._unique_candidates:
            raise ValueError("summary-count-mismatch")
        payload = json.dumps(summary_value, ensure_ascii=False, sort_keys=True)
        self._ledger._connection.execute(
            """
            UPDATE batches
            SET status = 'complete', end_reason = ?, raw_url_observations = ?,
                valid_urls = ?, unique_additions = ?, terminal_summary_json = ?
                , unique_candidate_additions = ?
            WHERE batch_id = ? AND status = 'open'
            """,
            (
                end_reason,
                raw,
                valid,
                unique,
                payload,
                unique_candidates,
                self.spec.batch_id,
            ),
        )
        self._finished = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc, traceback
        try:
            if exc_type is not None:
                self._ledger._connection.rollback()
                return False
            if not self._finished:
                self._ledger._connection.rollback()
                raise ValueError("terminal-summary-required")
            self._ledger._connection.commit()
            return False
        finally:
            self._ledger._active_batch = False


class SqliteUrlLedger:
    """Task-scoped streaming URL ledger with transactional batch commits."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = DELETE")
        self._connection.execute("PRAGMA synchronous = NORMAL")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.executescript(_SCHEMA)
        batch_columns = {
            row[1]
            for row in self._connection.execute("PRAGMA table_info(batches)")
        }
        if "unique_candidate_additions" not in batch_columns:
            self._connection.execute(
                """
                ALTER TABLE batches
                ADD COLUMN unique_candidate_additions INTEGER NOT NULL DEFAULT 0
                """
            )
        candidate_columns = {
            row[1]
            for row in self._connection.execute(
                "PRAGMA table_info(marketplace_candidates)"
            )
        }
        if "card_fields_json" not in candidate_columns:
            self._connection.execute(
                """
                ALTER TABLE marketplace_candidates
                ADD COLUMN card_fields_json TEXT NOT NULL DEFAULT '{}'
                """
            )
        self._active_batch = False
        self._closed = False

    def __enter__(self) -> "SqliteUrlLedger":
        if self._closed:
            raise ValueError("ledger-is-closed")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        if self._active_batch:
            self._connection.rollback()
            self._active_batch = False
        self._connection.close()
        self._closed = True

    def batch(self, spec: BatchSpec) -> _BatchWriter:
        if self._closed:
            raise ValueError("ledger-is-closed")
        if not isinstance(spec, BatchSpec):
            raise ValueError("spec must be a BatchSpec")
        return _BatchWriter(self, spec)

    def has_batch(self, batch_id: str) -> bool:
        normalized = _required_text(batch_id, "batch_id")
        row = self._connection.execute(
            "SELECT 1 FROM batches WHERE batch_id = ? AND status = 'complete'",
            (normalized,),
        ).fetchone()
        return row is not None

    def batch_stats(self, batch_id: str) -> BatchLedgerStats | None:
        normalized = _required_text(batch_id, "batch_id")
        row = self._connection.execute(
            "SELECT * FROM batches WHERE batch_id = ? AND status = 'complete'",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        return BatchLedgerStats(
            batch_id=row["batch_id"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            adapter=row["adapter"],
            scope_fingerprint=row["scope_fingerprint"],
            end_reason=row["end_reason"],
            raw_url_observations=row["raw_url_observations"],
            valid_urls=row["valid_urls"],
            unique_additions=row["unique_additions"],
            unique_candidate_additions=row["unique_candidate_additions"],
            terminal_summary=json.loads(row["terminal_summary_json"]),
        )

    def committed_batches(self) -> tuple[BatchLedgerStats, ...]:
        rows = self._connection.execute(
            """
            SELECT batch_id FROM batches
            WHERE status = 'complete' ORDER BY rowid
            """
        ).fetchall()
        return tuple(
            stats
            for row in rows
            if (stats := self.batch_stats(row["batch_id"])) is not None
        )

    def record_failure(
        self,
        *,
        batch_id: str | None,
        category: str,
        parameter_digest: str,
        compensation_route: str | None,
        detail: str,
    ) -> None:
        normalized_category = _required_text(category, "category")
        normalized_digest = _required_text(parameter_digest, "parameter_digest")
        if batch_id is not None:
            _required_text(batch_id, "batch_id")
        if compensation_route is not None:
            _required_text(compensation_route, "compensation_route")
        if not isinstance(detail, str):
            raise ValueError("detail must be a string")
        identity = "\0".join(
            (
                batch_id or "",
                normalized_category,
                normalized_digest,
                compensation_route or "",
            )
        )
        failure_id = blake2b(identity.encode("utf-8"), digest_size=16).hexdigest()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO failures (
                    failure_id, batch_id, category, parameter_digest,
                    compensation_route, detail
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    failure_id,
                    batch_id,
                    normalized_category,
                    normalized_digest,
                    compensation_route,
                    detail,
                ),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def failure_categories(self) -> tuple[str, ...]:
        return tuple(
            row["category"]
            for row in self._connection.execute(
                "SELECT DISTINCT category FROM failures ORDER BY category"
            )
        )

    def provenance_for(self, raw_url: str) -> SqliteUrlProvenance | None:
        canonical = normalize_url(raw_url)
        if canonical is None:
            return None
        url = self._connection.execute(
            "SELECT url_id, canonical_url, domain FROM urls WHERE canonical_url = ?",
            (canonical,),
        ).fetchone()
        if url is None:
            return None
        routes = self._connection.execute(
            """
            SELECT channel, source_class, query_family, source_role
            FROM url_channels WHERE url_id = ?
            """,
            (url["url_id"],),
        ).fetchall()
        return SqliteUrlProvenance(
            canonical_url=url["canonical_url"],
            domain=url["domain"],
            discovery_channels=tuple(sorted({row["channel"] for row in routes})),
            query_families=tuple(sorted({row["query_family"] for row in routes})),
            source_classes=tuple(sorted({row["source_class"] for row in routes})),
            source_roles=tuple(
                sorted({row["source_role"] for row in routes if row["source_role"]})
            ),
        )

    def marketplace_candidate_count(self) -> int:
        return int(
            self._connection.execute(
                "SELECT COUNT(*) FROM marketplace_candidates"
            ).fetchone()[0]
        )

    def marketplace_candidate(
        self, platform: str, product_id: str
    ) -> SqliteMarketplaceCandidate | None:
        normalized_platform = _required_text(platform, "platform").lower()
        normalized_product_id = _required_text(product_id, "product_id")
        if normalized_platform not in {"jd", "taobao"}:
            raise ValueError("unsupported-marketplace-platform")
        if not normalized_product_id.isdigit():
            raise ValueError("product_id must be numeric")
        row = self._connection.execute(
            """
            SELECT candidate.platform, candidate.product_id, candidate.title,
                   candidate.first_observed_at, candidate.first_batch_id,
                   candidate.card_fields_json,
                   urls.canonical_url
            FROM marketplace_candidates AS candidate
            JOIN urls ON urls.url_id = candidate.url_id
            WHERE candidate.platform = ? AND candidate.product_id = ?
            """,
            (normalized_platform, normalized_product_id),
        ).fetchone()
        if row is None:
            return None
        return SqliteMarketplaceCandidate(
            platform=row["platform"],
            product_id=row["product_id"],
            title=row["title"],
            canonical_url=row["canonical_url"],
            first_observed_at=row["first_observed_at"],
            first_batch_id=row["first_batch_id"],
            card_fields=_read_card_fields_json(row["card_fields_json"]),
        )

    def marketplace_card_field_coverage(self) -> dict[str, int]:
        coverage = {field: 0 for field in CARD_FIELD_KEYS}
        with_any = 0
        for row in self._connection.execute(
            "SELECT card_fields_json FROM marketplace_candidates"
        ):
            fields = _read_card_fields_json(row["card_fields_json"])
            if fields:
                with_any += 1
            for field in fields:
                coverage[field] += 1
        coverage["candidates_with_any_card_field"] = with_any
        return coverage

    def marketplace_candidate_counts_by_channel(self) -> tuple[tuple[str, int], ...]:
        return tuple(
            (row["channel"], row["candidate_count"])
            for row in self._connection.execute(
                """
                SELECT routes.channel,
                       COUNT(DISTINCT candidates.platform || ':' ||
                                      candidates.product_id) AS candidate_count
                FROM marketplace_candidates AS candidates
                JOIN url_channels AS routes ON routes.url_id = candidates.url_id
                GROUP BY routes.channel
                ORDER BY routes.channel
                """
            )
        )

    def record_marketplace_cursor(
        self,
        *,
        cursor_id: str,
        source: str,
        query_family: str,
        status: str,
        last_batch_id: str,
        unique_candidate_additions: int,
    ) -> None:
        """Upsert compact cursor evidence after its batch has committed."""
        normalized_cursor = _required_text(cursor_id, "cursor_id")
        normalized_source = _required_text(source, "source")
        normalized_family = _required_text(query_family, "query_family")
        normalized_status = _required_text(status, "status").lower()
        normalized_batch = _required_text(last_batch_id, "last_batch_id")
        if normalized_status not in {"advanced", "exhausted", "blocked"}:
            raise ValueError("unsupported-marketplace-cursor-status")
        if (
            isinstance(unique_candidate_additions, bool)
            or not isinstance(unique_candidate_additions, int)
            or unique_candidate_additions < 0
        ):
            raise ValueError(
                "unique_candidate_additions must be a non-negative integer"
            )
        batch = self._connection.execute(
            "SELECT status FROM batches WHERE batch_id = ?", (normalized_batch,)
        ).fetchone()
        if batch is None or batch["status"] != "complete":
            raise ValueError("marketplace-cursor-requires-complete-batch")
        self._connection.execute(
            """
            INSERT INTO marketplace_cursors (
                cursor_id, source, query_family, status, last_batch_id,
                unique_candidate_additions
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cursor_id) DO UPDATE SET
                source = excluded.source,
                query_family = excluded.query_family,
                status = excluded.status,
                last_batch_id = excluded.last_batch_id,
                unique_candidate_additions = excluded.unique_candidate_additions
            """,
            (
                normalized_cursor,
                normalized_source,
                normalized_family,
                normalized_status,
                normalized_batch,
                unique_candidate_additions,
            ),
        )

    def record_marketplace_recovery(
        self,
        *,
        run_id: str,
        platform: str,
        query_family: str,
        page_number: int,
        recovery_stage: str,
        attempt: int,
        category: str,
        disposition: str,
    ) -> None:
        """Commit one compact recovery decision independently of URL batches."""
        normalized_run = _bounded_recovery_text(run_id, "run_id", 256)
        normalized_platform = _bounded_recovery_text(platform, "platform", 16).casefold()
        normalized_family = _bounded_recovery_text(
            query_family, "query_family", 512
        )
        normalized_stage = _bounded_recovery_text(
            recovery_stage, "recovery_stage", 16
        ).casefold()
        normalized_category = _bounded_recovery_text(category, "category", 64)
        normalized_disposition = _bounded_recovery_text(
            disposition, "disposition", 32
        )
        if normalized_platform not in {"jd", "taobao"}:
            raise ValueError("unsupported-marketplace-platform")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= 512
        ):
            raise ValueError("page_number must be from 1 to 512")
        if (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or _RECOVERY_STAGE_ATTEMPTS.get(normalized_stage) != attempt
        ):
            raise ValueError("attempt must match recovery_stage")
        expected_disposition = _RECOVERY_CATEGORY_DISPOSITIONS.get(
            normalized_category
        )
        if expected_disposition is None:
            raise ValueError("unsupported-marketplace-recovery-category")
        if normalized_disposition != expected_disposition:
            raise ValueError("recovery disposition does not match category")
        if self._active_batch:
            raise ValueError("recovery-event-cannot-share-url-batch")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                INSERT INTO marketplace_recovery_events (
                    run_id, platform, query_family, page_number,
                    recovery_stage, attempt, category, disposition
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_run,
                    normalized_platform,
                    normalized_family,
                    page_number,
                    normalized_stage,
                    attempt,
                    normalized_category,
                    normalized_disposition,
                ),
            )
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise

    def recovery_events(self, *, run_id: str | None = None) -> tuple[dict[str, object], ...]:
        """Return detached fixed-key recovery evidence in insertion order."""
        parameters: tuple[object, ...] = ()
        where = ""
        if run_id is not None:
            where = "WHERE run_id = ?"
            parameters = (_bounded_recovery_text(run_id, "run_id", 256),)
        rows = self._connection.execute(
            f"""
            SELECT event_id, run_id, platform, query_family, page_number,
                   recovery_stage, attempt, category, disposition
            FROM marketplace_recovery_events
            {where}
            ORDER BY event_id
            """,
            parameters,
        ).fetchall()
        return tuple(
            {
                "event_id": int(row["event_id"]),
                "run_id": row["run_id"],
                "platform": row["platform"],
                "query_family": row["query_family"],
                "page_number": int(row["page_number"]),
                "recovery_stage": row["recovery_stage"],
                "attempt": int(row["attempt"]),
                "category": row["category"],
                "disposition": row["disposition"],
            }
            for row in rows
        )

    def marketplace_query_family_counts(
        self, *, run_id: str
    ) -> dict[str, dict[str, int]]:
        normalized_run = _bounded_recovery_text(run_id, "run_id", 256)
        rows = self._connection.execute(
            """
            SELECT cursors.query_family,
                   SUM(CASE WHEN cursors.status IN ('advanced', 'exhausted') THEN 1 ELSE 0 END)
                       AS successful_pages,
                   SUM(CASE WHEN cursors.status IN ('advanced', 'exhausted')
                            THEN cursors.unique_candidate_additions ELSE 0 END) AS new_skus
            FROM marketplace_cursors AS cursors
            JOIN batches ON batches.batch_id = cursors.last_batch_id
            WHERE batches.status = 'complete' AND batches.run_id = ?
            GROUP BY cursors.query_family
            ORDER BY cursors.query_family
            """,
            (normalized_run,),
        ).fetchall()
        return {
            row["query_family"]: {
                "successful_pages": int(row["successful_pages"] or 0),
                "new_skus": int(row["new_skus"] or 0),
            }
            for row in rows
        }

    def marketplace_recovery_summary(self, *, run_id: str) -> dict[str, object]:
        recoveries: dict[str, int] = {}
        abandoned: dict[str, dict[str, int]] = {}
        hard_blocks: dict[str, dict[str, int]] = {}
        for row in self.recovery_events(run_id=run_id):
            family = str(row["query_family"])
            category = str(row["category"])
            disposition = row["disposition"]
            if disposition == "retry_same_page":
                recoveries[family] = recoveries.get(family, 0) + 1
            elif disposition == "rotate_family":
                categories = abandoned.setdefault(family, {})
                categories[category] = categories.get(category, 0) + 1
            elif disposition == "hard_block":
                categories = hard_blocks.setdefault(family, {})
                categories[category] = categories.get(category, 0) + 1
        return {
            "recoveries": recoveries,
            "abandoned_families": abandoned,
            "hard_blocks": hard_blocks,
        }

    def marketplace_scope_summary(self) -> dict[str, object]:
        """Return bounded aggregate evidence without titles, URLs, or product IDs."""
        source_rows = self._connection.execute(
            """
            SELECT source,
                   COUNT(*) AS attempted,
                   SUM(CASE WHEN status = 'exhausted' THEN 1 ELSE 0 END) AS exhausted,
                   SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked,
                   SUM(CASE WHEN status = 'advanced' THEN 1 ELSE 0 END) AS open
            FROM marketplace_cursors
            GROUP BY source
            ORDER BY source
            """
        ).fetchall()
        additions = self._connection.execute(
            """
            SELECT unique_candidate_additions
            FROM batches
            WHERE status = 'complete'
            ORDER BY rowid DESC
            LIMIT 3
            """
        ).fetchall()
        return {
            "sources": {
                row["source"]: {
                    "attempted": int(row["attempted"]),
                    "exhausted": int(row["exhausted"]),
                    "blocked": int(row["blocked"]),
                    "open": int(row["open"]),
                }
                for row in source_rows
            },
            "last_three_candidate_additions": tuple(
                int(row["unique_candidate_additions"]) for row in additions
            ),
        }

    def stats(self) -> LedgerStats:
        counts = self._connection.execute(
            """
            SELECT COALESCE(SUM(raw_url_observations), 0) AS raw,
                   COALESCE(SUM(valid_urls), 0) AS valid,
                   COALESCE(SUM(unique_additions), 0) AS additions
            FROM batches WHERE status = 'complete'
            """
        ).fetchone()
        unique_urls = self._connection.execute(
            "SELECT COUNT(*) FROM urls"
        ).fetchone()[0]
        unique_domains = self._connection.execute(
            "SELECT COUNT(DISTINCT domain) FROM urls"
        ).fetchone()[0]
        access_limited = self._connection.execute(
            """
            SELECT COUNT(DISTINCT url_id) FROM url_channels
            WHERE source_role = 'access_limited'
            """
        ).fetchone()[0]
        source_counts = tuple(
            (row["source_class"], row["count"])
            for row in self._connection.execute(
                """
                SELECT source_class, COUNT(DISTINCT url_id) AS count
                FROM url_channels GROUP BY source_class ORDER BY source_class
                """
            )
        )
        query_counts = tuple(
            (row["query_family"], row["count"])
            for row in self._connection.execute(
                """
                SELECT query_family, COUNT(DISTINCT url_id) AS count
                FROM url_channels GROUP BY query_family ORDER BY query_family
                """
            )
        )
        return LedgerStats(
            raw_results=counts["raw"],
            valid_urls=counts["valid"],
            unique_urls=unique_urls,
            duplicate_results=counts["valid"] - counts["additions"],
            unique_domains=unique_domains,
            access_limited_urls=access_limited,
            source_class_urls=source_counts,
            query_family_urls=query_counts,
        )
