"""Deterministic CSV/Markdown corpus parsing, deduplication, and audit helpers."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit


CSV_FIELDS = (
    "title",
    "venue_time",
    "source",
    "abstract",
    "url",
    "citation",
    "lab_group",
    "doi",
    "abstract_source_url",
    "fulltext_status",
    "fulltext_url",
    "method_evidence",
    "compute_evidence",
    "experiment_evidence",
    "verification_date",
)

EVIDENCE_FIELDS = ("method_evidence", "compute_evidence", "experiment_evidence")
PLACEHOLDER_PATTERN = re.compile(r"\?{2,}")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_record_integrity(record: dict[str, str]) -> list[str]:
    """Return hard errors that indicate a damaged or shifted corpus row."""

    errors: list[str] = []
    for field in EVIDENCE_FIELDS:
        value = (record.get(field) or "").strip()
        if "\ufffd" in value or PLACEHOLDER_PATTERN.search(value):
            errors.append(f"{field}: placeholder or replacement-character evidence")
    experiment = (record.get("experiment_evidence") or "").strip()
    verification_date = (record.get("verification_date") or "").strip()
    if DATE_PATTERN.fullmatch(experiment) and not verification_date:
        errors.append("experiment_evidence: date appears shifted; use verification_date")
    if verification_date and not DATE_PATTERN.fullmatch(verification_date):
        errors.append("verification_date: expected YYYY-MM-DD")
    return errors


def validate_csv_file(path: Path) -> list[str]:
    """Validate UTF-8 CSV encoding, exact schema, row width, and field integrity."""

    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if header != list(CSV_FIELDS):
                errors.append("header: expected exact 15-column schema and field order")
            for line_number, values in enumerate(reader, start=2):
                if len(values) != len(CSV_FIELDS):
                    errors.append(f"row {line_number}: expected 15 columns, got {len(values)}")
                    continue
                record = dict(zip(CSV_FIELDS, values))
                errors.extend(f"row {line_number}: {item}" for item in validate_record_integrity(record))
    except UnicodeDecodeError as exc:
        errors.append(f"file: not valid UTF-8 ({exc})")
    except OSError as exc:
        errors.append(f"file: cannot read ({exc})")
    return errors


EXCLUDED_SOURCES = {
    "arxiv",
    "mdpi",
    "ieee access",
    "frontiers",
    "tai",
    "tcst",
}

OFFICIAL_URL_HOSTS = {
    "doi.org",
    "ieeexplore.ieee.org",
    "science.org",
    "nature.com",
    "www.nature.com",
    "openaccess.thecvf.com",
    "cvpr.thecvf.com",
    "proceedings.mlr.press",
    "roboticsproceedings.org",
    "roboticsconference.org",
    "proceedings.neurips.cc",
    "neurips.cc",
    "openreview.net",
    "rssconf.org",
    # Institutional repositories used only for directly reviewed full text.
    "par.nsf.gov",
    "hub.hku.hk",
    "aerial-core.eu",
    "nicsefc.ee.tsinghua.edu.cn",
    "orca.cardiff.ac.uk",
}


def normalize_title(value: str | None) -> str:
    value = (value or "").casefold()
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(value: str | None) -> str:
    value = (value or "").strip().casefold()
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme and parts.netloc:
        parts = parts._replace(query="", fragment="", path=parts.path.rstrip("/"))
        return urlunsplit(parts)
    return value.rstrip("/")


def is_official_record_url(value: str | None) -> bool:
    """Return whether a URL is a publisher, DOI, or official proceedings record."""

    normalized = normalize_url(value)
    if not normalized:
        return False
    parts = urlsplit(normalized)
    host = parts.hostname or ""
    if host == "arxiv.org" or host.endswith(".arxiv.org"):
        return False
    if host in OFFICIAL_URL_HOSTS:
        return True
    return any(host.endswith(f".{allowed}") for allowed in OFFICIAL_URL_HOSTS if allowed not in {"doi.org"})


def is_reviewed_fulltext_url(value: str | None) -> bool:
    """Allow official/open full-text hosts for evidence, including arXiv copies."""

    normalized = normalize_url(value)
    if not normalized:
        return False
    parts = urlsplit(normalized)
    host = parts.hostname or ""
    return is_official_record_url(normalized) or host == "arxiv.org" or host.endswith(".arxiv.org")


def has_complete_original_abstract(record: dict[str, str]) -> bool:
    """Require a sourced, non-summary abstract before a record enters the corpus."""

    abstract = re.sub(r"\s+", " ", (record.get("abstract") or "").strip())
    source_url = (record.get("abstract_source_url") or "").strip()
    disallowed = ("assistant summary", "brief summary", "summary only", "待补充", "not available")
    return (
        len(abstract) >= 280
        and is_official_record_url(source_url)
        and not any(marker in abstract.casefold() for marker in disallowed)
    )


def can_support_quantitative_claim(record: dict[str, str]) -> bool:
    """Return whether a paper has reviewed full-text evidence for numeric claims."""

    status = (record.get("fulltext_status") or "").strip().casefold()
    return (
        status in {"reviewed_open_access", "reviewed_official"}
        and is_reviewed_fulltext_url(record.get("fulltext_url"))
        and bool((record.get("compute_evidence") or "").strip() or (record.get("experiment_evidence") or "").strip())
    )


def extract_identifier(value: str | None) -> str | None:
    value = (value or "").strip().casefold()
    doi = re.search(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", value)
    if doi:
        return f"doi:{doi.group(0).rstrip('.,;') }"
    arxiv = re.search(
        r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)\s*(\d{4}\.\d{4,5}(?:v\d+)?)",
        value,
    )
    if arxiv:
        return f"arxiv:{arxiv.group(1)}"
    return None


def parse_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [
            {field: (row.get(field) or "").strip() for field in CSV_FIELDS}
            for row in reader
            if any((value or "").strip() for value in row.values())
        ]


def _infer_source(meta: str) -> str:
    known = (
        "Science Robotics",
        "Nature Machine Intelligence",
        "NeurIPS",
        "Nature",
        "Science",
        "TPAMI",
        "TNNLS",
        "TMech",
        "TASE",
        "TITS",
        "IJRR",
        "ICRA",
        "IROS",
        "CoRL",
        "CVPR",
        "ICCV",
        "ICML",
        "ICLR",
        "AAAI",
        "RSS",
        "RAL",
        "TRO",
        "arXiv",
    )
    lowered = meta.casefold()
    for source in known:
        if source.casefold() in lowered:
            return "NMI" if source == "Nature Machine Intelligence" else source
    return ""


def _infer_year(meta: str) -> str:
    match = re.search(r"20\d{2}(?:-\d{2})?", meta)
    return match.group(0) if match else ""


def _infer_citation(value: str) -> str:
    match = re.search(r"\b\d+\b", value or "")
    return match.group(0) if match else "0"


def parse_markdown_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pattern = re.compile(
        r"^\|\s*\[(.*?)\]\((.*?)\)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$"
    )
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        title, link, meta, abstract, official_url, citation = match.groups()
        rows.append(
            {
                "title": title.strip(),
                "venue_time": _infer_year(meta),
                "source": _infer_source(meta),
                "abstract": abstract.strip(),
                "url": (official_url or link or "").strip(),
                "citation": _infer_citation(citation),
                "lab_group": "否",
                "raw_meta": meta.strip(),
            }
        )
    return rows


def _keys(record: dict[str, str]) -> set[str]:
    keys = set()
    title = normalize_title(record.get("title"))
    url = normalize_url(record.get("url"))
    identifier = extract_identifier(record.get("url")) or extract_identifier(record.get("title"))
    if title:
        keys.add(f"title:{title}")
    if url:
        keys.add(f"url:{url}")
    if identifier:
        keys.add(identifier)
    return keys


def _citation_number(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _merge_fields(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    merged = {field: (old.get(field) or "").strip() for field in CSV_FIELDS}
    for field in CSV_FIELDS:
        candidate = (new.get(field) or "").strip()
        if field == "citation":
            if _citation_number(candidate) > _citation_number(merged[field]):
                merged[field] = candidate
        elif field == "url" and is_official_record_url(candidate) and not is_official_record_url(merged[field]):
            merged[field] = candidate
        elif not merged[field] or (field == "source" and merged[field] not in EXCLUDED_SOURCES and candidate):
            if candidate:
                merged[field] = candidate
    if merged["lab_group"] in {"", "否"} and new.get("lab_group") not in {None, "", "否"}:
        merged["lab_group"] = new["lab_group"]
    return merged


def deduplicate_records(
    records: Iterable[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Collapse repeated title/URL/identifier records, preferring richer official records."""

    clean: list[dict[str, str]] = []
    decisions: list[dict[str, str]] = []
    key_to_index: dict[str, int] = {}
    for raw in records:
        row = {field: (raw.get(field) or "").strip() for field in CSV_FIELDS}
        normalized_source = row["source"].casefold()
        if normalized_source == "nature machine intelligence":
            row["source"] = "NMI"
        keys = _keys(row)
        matches = {key_to_index[key] for key in keys if key in key_to_index}
        if not matches:
            index = len(clean)
            clean.append(row)
            for key in keys:
                key_to_index[key] = index
            decisions.append({"decision": "unique", "title": row["title"]})
            continue

        index = min(matches)
        clean[index] = _merge_fields(clean[index], row)
        for key in _keys(clean[index]):
            key_to_index[key] = index
        decisions.append({"decision": "duplicate", "title": row["title"]})
    return clean, decisions


def merge_records(
    existing: list[dict[str, str]], incoming: Iterable[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    merged = [{field: (row.get(field) or "").strip() for field in CSV_FIELDS} for row in existing]
    decisions: list[dict[str, str]] = []
    key_to_index: dict[str, int] = {}
    for index, row in enumerate(merged):
        for key in _keys(row):
            key_to_index[key] = index

    for raw in incoming:
        row = {field: (raw.get(field) or "").strip() for field in CSV_FIELDS}
        matches = {key_to_index[key] for key in _keys(row) if key in key_to_index}
        if matches:
            index = min(matches)
            merged[index] = _merge_fields(merged[index], row)
            for key in _keys(merged[index]):
                key_to_index[key] = index
            decisions.append({"decision": "duplicate", "title": row["title"]})
            continue
        index = len(merged)
        merged.append(row)
        for key in _keys(row):
            key_to_index[key] = index
        decisions.append({"decision": "accepted_candidate", "title": row["title"]})
    return merged, decisions


def audit_record(record: dict[str, str], whitelist: set[str]) -> dict[str, str]:
    source = (record.get("source") or "").strip()
    lowered = source.casefold()
    url = (record.get("url") or "").strip()
    title = (record.get("title") or "").strip()
    if not title or not url:
        return {"status": "reject", "reason": "missing title or official URL"}
    if lowered in EXCLUDED_SOURCES or "arxiv.org" in url.casefold():
        return {"status": "reject", "reason": "excluded or arXiv-only source"}
    if source not in whitelist:
        return {"status": "needs_verification", "reason": "venue is not a recognized abbreviation"}
    return {"status": "accepted", "reason": "passes source-level audit"}
