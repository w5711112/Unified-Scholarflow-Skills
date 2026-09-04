"""Validate author-research evidence records against the V3 contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import validate_author_research_legacy as _legacy


V3_SCHEMA_VERSION = 3
V3_EVIDENCE_FIELDS = (
    "education",
    "current_position",
    "qs_ranking",
    "scholar",
    "memberships",
    "research_areas",
    "lab",
    "projects",
    "honors",
    "representative_outputs",
    "bibliometrics",
)
V3_AUTHOR_FIELDS = V3_EVIDENCE_FIELDS + (
    "standing_assessment",
    "metric_source",
    "url_checks",
)
METRIC_SOURCES = {
    "Google Scholar",
    "OpenAlex",
    "Semantic Scholar",
    "AD Scientific Index",
    "not_verified",
}
BIBLIOMETRIC_SOURCES = {
    "OpenAlex",
    "Semantic Scholar",
    "AD Scientific Index",
}


def _url_check_map(
    author: dict[str, Any],
    path: str,
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    checks = author.get("url_checks")
    if not isinstance(checks, list) or not checks:
        errors.append(f"{path}.url_checks must be a non-empty array")
        return {}

    result: dict[str, dict[str, Any]] = {}
    for index, check in enumerate(checks):
        check_path = f"{path}.url_checks[{index}]"
        if not isinstance(check, dict):
            errors.append(f"{check_path} must be an object")
            continue
        required = {
            "requested_url",
            "final_url",
            "status_code",
            "checked_at",
            "accessible",
        }
        missing = sorted(required.difference(check))
        if missing:
            errors.append(f"{check_path} missing fields: {missing}")
            continue
        requested = check["requested_url"]
        final = check["final_url"]
        if not _legacy._is_http_url(requested):
            errors.append(f"{check_path}.requested_url must be public HTTP(S)")
        if not _legacy._is_http_url(final):
            errors.append(f"{check_path}.final_url must be public HTTP(S)")
        if not _legacy._is_iso_date_or_datetime(check["checked_at"]):
            errors.append(f"{check_path}.checked_at must be an ISO date")
        if not isinstance(check["accessible"], bool):
            errors.append(f"{check_path}.accessible must be boolean")
        status = check["status_code"]
        if (
            status is not None
            and (
                isinstance(status, bool)
                or not isinstance(status, int)
                or not 100 <= status <= 599
            )
        ):
            errors.append(
                f"{check_path}.status_code must be an HTTP status or null"
            )
        if isinstance(requested, str):
            if requested in result:
                errors.append(
                    f"{path}.url_checks contains duplicate requested_url "
                    f"{requested!r}"
                )
            result[requested] = check
        if isinstance(final, str):
            result.setdefault(final, check)
    return result


def _verified_sources(evidence: object) -> list[str]:
    if not isinstance(evidence, dict) or evidence.get("status") != "verified":
        return []
    sources = evidence.get("sources")
    if not isinstance(sources, list):
        return []
    return [source for source in sources if isinstance(source, str)]


def _validate_v3_author(
    author: object,
    path: str,
    errors: list[str],
) -> None:
    if not isinstance(author, dict):
        return
    for field in V3_AUTHOR_FIELDS:
        if field not in author:
            errors.append(f"{path}.{field} is required by V3")

    for field in V3_EVIDENCE_FIELDS:
        if field in author:
            _legacy._validate_evidence(
                author[field],
                f"{path}.{field}",
                errors,
            )

    metric_source = author.get("metric_source")
    if metric_source not in METRIC_SOURCES:
        errors.append(
            f"{path}.metric_source must be one of {sorted(METRIC_SOURCES)}"
        )
    scholar = author.get("scholar")
    if (
        isinstance(scholar, dict)
        and scholar.get("status") == "verified"
        and metric_source != "Google Scholar"
    ):
        errors.append(
            f"{path}.metric_source must be Google Scholar when scholar is verified"
        )
    bibliometrics = author.get("bibliometrics")
    if (
        isinstance(bibliometrics, dict)
        and bibliometrics.get("status") == "verified"
        and metric_source not in BIBLIOMETRIC_SOURCES
    ):
        errors.append(
            f"{path}.metric_source must identify the verified bibliometrics platform"
        )

    checks = _url_check_map(author, path, errors)
    for field in V3_EVIDENCE_FIELDS:
        for source in _verified_sources(author.get(field)):
            check = checks.get(source)
            if check is None:
                errors.append(
                    f"{path}.{field} verified source lacks a url_checks record: "
                    f"{source}"
                )
            elif check.get("accessible") is not True:
                errors.append(
                    f"{path}.{field} verified source is not accessible: {source}"
                )


def validate_document(document: object) -> list[str]:
    """Return contract violations; an empty list means the document is valid."""

    errors = _legacy.validate_document(document)
    if not isinstance(document, dict):
        return errors
    raw_version = document.get("author_research_schema_version", 2)
    if isinstance(raw_version, bool):
        errors.append(
            "author_research_schema_version must be an integer"
        )
        return errors
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        errors.append(
            "author_research_schema_version must be an integer"
        )
        return errors
    if version < V3_SCHEMA_VERSION:
        return errors
    if version != V3_SCHEMA_VERSION:
        errors.append(
            f"unsupported author_research_schema_version: {version}"
        )
        return errors

    authors = document.get("authors")
    if not isinstance(authors, list):
        return errors
    for index, author in enumerate(authors):
        _validate_v3_author(author, f"authors[{index}]", errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print(
            "usage: validate_author_research.py PATH_TO_JSON",
            file=sys.stderr,
        )
        return 2
    try:
        document = json.loads(
            Path(arguments[0]).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(
            f"unable to read JSON evidence record: {error}",
            file=sys.stderr,
        )
        return 2

    errors = validate_document(document)
    print(
        json.dumps(
            {"valid": not errors, "errors": errors},
            ensure_ascii=False,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
