"""Validate author-research evidence records against the local contract."""

from __future__ import annotations

from datetime import date, datetime
from ipaddress import ip_address
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit


ALLOWED_STATUSES = {
    "verified",
    "not_publicly_verified",
    "not_applicable",
    "inference",
}
AUTHOR_FIELDS = (
    "education",
    "current_position",
    "qs_ranking",
    "scholar",
    "memberships",
    "standing_assessment",
)
TOP_LEVEL_FIELDS = ("paper_id", "verified_at", "designated_authors", "authors")


def _is_nonblank_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_iso_date_or_datetime(value: object) -> bool:
    if not _is_nonblank_string(value) or value != value.strip():
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        pass
    if "T" not in value:
        return False
    normalized_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized_value)
        return True
    except ValueError:
        return False


def _is_valid_hostname(hostname: str) -> bool:
    try:
        return ip_address(hostname).is_global
    except ValueError:
        pass
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    if ascii_hostname == "localhost" or ascii_hostname.endswith(".localhost"):
        return False
    for label in ascii_hostname.split("."):
        if not 1 <= len(label) <= 63:
            return False
        if not label[0].isalnum() or not label[-1].isalnum():
            return False
        if any(not (character.isalnum() or character == "-") for character in label):
            return False
    return True


def _is_http_url(value: object) -> bool:
    if (
        not _is_nonblank_string(value)
        or value != value.strip()
        or "\\" in value
        or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        return False
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False
    authority = parsed.netloc.rsplit("@", 1)[-1]
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not authority.endswith(":")
        and hostname is not None
        and _is_valid_hostname(hostname)
    )


def _author_roles(entries: object, label: str, errors: list[str]) -> dict[str, set[str]]:
    if not isinstance(entries, list):
        errors.append(f"{label} must be an array")
        return {}

    result: dict[str, set[str]] = {}
    for index, entry in enumerate(entries):
        path = f"{label}[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{path} must be an object")
            continue
        name = entry.get("name")
        roles = entry.get("roles")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{path}.name must be non-empty")
            continue
        if not isinstance(roles, list) or not roles or any(
            not isinstance(role, str) or not role.strip() for role in roles
        ):
            errors.append(f"{path}.roles must be a non-empty string array")
            continue
        normalized_name = name.strip()
        if name != normalized_name:
            errors.append(f"{path}.name must not have leading or trailing whitespace")
        if normalized_name in result:
            errors.append(f"{label} contains duplicate author name {normalized_name!r}")
        result.setdefault(normalized_name, set()).update(roles)
    return result


def _validate_evidence(item: object, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(f"{path} must be an evidence object")
        return
    status = item.get("status")
    if status not in ALLOWED_STATUSES:
        errors.append(f"{path}.status must be one of {sorted(ALLOWED_STATUSES)}")
        return
    if status == "verified":
        if not _is_nonblank_string(item.get("value")):
            errors.append(f"{path}.value must be a non-blank string when status is verified")
        sources = item.get("sources")
        if not isinstance(sources, list) or not any(_is_http_url(source) for source in sources):
            errors.append(f"{path}.sources must include an HTTP(S) URL when status is verified")
    if status == "not_publicly_verified":
        searched_sources = item.get("searched_sources")
        if not isinstance(searched_sources, list) or not searched_sources or any(
            not isinstance(source, str) or not source.strip() for source in searched_sources
        ):
            errors.append(f"{path}.searched_sources must be non-empty when status is not_publicly_verified")
        value = item.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0:
            errors.append(f"{path} must not use 0 for an unknown value")


def validate_document(document: object) -> list[str]:
    """Return contract violations; an empty list means the document is valid."""
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["top-level JSON value must be an object"]

    for field in TOP_LEVEL_FIELDS:
        if field not in document:
            errors.append(f"top-level field {field!r} is required")
    if errors:
        return errors

    if not _is_iso_date_or_datetime(document["verified_at"]):
        errors.append("verified_at must be a valid ISO date or date-time string")

    designated = _author_roles(document["designated_authors"], "designated_authors", errors)
    authors = _author_roles(document["authors"], "authors", errors)
    if set(designated) != set(authors):
        errors.append("designated_authors and authors must have identical names")
    for name in set(designated) & set(authors):
        if designated[name] != authors[name]:
            errors.append(f"author {name!r} has mismatched roles between designated_authors and authors")

    if not isinstance(document["authors"], list):
        return errors
    for index, author in enumerate(document["authors"]):
        path = f"authors[{index}]"
        if not isinstance(author, dict):
            continue
        for field in AUTHOR_FIELDS:
            if field not in author:
                errors.append(f"{path}.{field} is required")
        for field in AUTHOR_FIELDS[:-1]:
            if field in author:
                _validate_evidence(author[field], f"{path}.{field}", errors)

        scholar = author.get("scholar")
        if (
            isinstance(scholar, dict)
            and scholar.get("status") == "verified"
            and not _is_iso_date_or_datetime(scholar.get("as_of"))
        ):
            errors.append(f"{path}.scholar.as_of must be a valid ISO date or date-time string")
        qs_ranking = author.get("qs_ranking")
        if (
            isinstance(qs_ranking, dict)
            and qs_ranking.get("status") == "verified"
            and not _is_nonblank_string(qs_ranking.get("edition"))
        ):
            errors.append(f"{path}.qs_ranking.edition must be a non-blank string when status is verified")

        standing = author.get("standing_assessment")
        standing_path = f"{path}.standing_assessment"
        if not isinstance(standing, dict):
            if "standing_assessment" in author:
                errors.append(f"{standing_path} must be an evidence object")
        elif standing.get("status") != "inference":
            errors.append(f"{standing_path}.status must be inference")
        elif not _is_nonblank_string(standing.get("basis")):
            errors.append(f"{standing_path}.basis must be a non-blank string when status is inference")

    return errors


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: validate_author_research.py PATH_TO_JSON", file=sys.stderr)
        return 2
    try:
        document = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        print(f"unable to read JSON evidence record: {error}", file=sys.stderr)
        return 2

    errors = validate_document(document)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
