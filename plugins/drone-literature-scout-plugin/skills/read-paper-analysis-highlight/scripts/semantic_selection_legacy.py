from __future__ import annotations

import ipaddress
import re
from datetime import date
from typing import Any
from urllib.parse import urlsplit


class SemanticSelectionError(ValueError):
    """Raised when an annotation does not carry enough verifiable information."""


LOW_INFORMATION_EXACT = {
    "we propose",
    "our approach",
    "formal safety guarantees",
    "mass-normalized collective thrust",
    "quadratic program",
    "success rate remains",
    "moving obstacles",
    "forward invariance",
    "trained in isaac lab",
}

REQUIRED_COMMON = {
    "id",
    "page",
    "annotation_type",
    "kind",
    "color",
    "note_question",
    "claim",
    "reason",
    "information_roles",
    "evidence",
    "confidence",
}

ALLOWED_ROLES = {
    "problem",
    "motivation",
    "cause",
    "method",
    "mechanism",
    "design_rationale",
    "definition",
    "assumption",
    "condition",
    "metric",
    "comparison",
    "result",
    "limitation",
    "failure",
    "reuse",
    "evidence_gap",
    "reproducibility",
    "author_context",
}


SELECTION_MODES = {"semantic-span", "key-term", "key-metric", "author-name"}
AUTHOR_COMMENT_PREFIX = "\u5916\u90e8\u6838\u9a8c\uff0c\u4e0d\u662f\u8bba\u6587\u6b63\u6587\u4e8b\u5b9e\uff1a"

def _normalise(text: str) -> str:
    return " ".join(str(text).split()).strip().casefold()


def _word_like_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9μ×%]+|[\u4e00-\u9fff]", text))

def _non_empty_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_public_http_url(value: str) -> bool:
    if "\\" in value or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in value
    ):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError):
        return False
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.netloc
        or not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.netloc.endswith(":")
        or (port is not None and not 1 <= port <= 65535)
    ):
        return False

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        try:
            ascii_host = host.rstrip(".").encode("idna").decode("ascii").casefold()
        except UnicodeError:
            return False
        if (
            "." not in ascii_host
            or ascii_host == "localhost"
            or ascii_host.endswith((".localhost", ".local", ".internal"))
            or len(ascii_host) > 253
        ):
            return False
        return all(
            re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in ascii_host.split(".")
        )
    return address.is_global


def information_failures(item: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    missing = sorted(
        field for field in REQUIRED_COMMON
        if field not in item or item[field] in (None, "", [])
    )
    if missing:
        failures.append("missing required fields: " + ", ".join(missing))
        return failures

    roles = set(item.get("information_roles", []))
    unknown_roles = sorted(roles - ALLOWED_ROLES)
    if unknown_roles:
        failures.append("unknown information roles: " + ", ".join(unknown_roles))

    selection_mode = str(item.get("selection_mode") or "semantic-span")
    annotation_type = item.get("annotation_type")
    if selection_mode not in SELECTION_MODES:
        failures.append("selection_mode must be semantic-span, key-term, key-metric, or author-name")
    if annotation_type != "highlight" and selection_mode != "semantic-span":
        failures.append("non-semantic selection_mode requires annotation_type=highlight")

    if annotation_type == "highlight" and selection_mode == "semantic-span":
        for field in ("quote", "claim", "reason"):
            if _non_empty_text(item.get(field)) is None:
                failures.append(f"semantic-span requires non-empty {field}")


    if annotation_type == "highlight" and selection_mode != "semantic-span":
        quote = _non_empty_text(item.get("quote"))
        if quote is None:
            failures.append(f"{selection_mode} requires non-empty quote")
        quote = quote or ""

        if selection_mode == "key-term":
            if _word_like_count(quote) < 2:
                failures.append("key-term quote requires at least two word-like tokens")
            if _non_empty_text(item.get("context_summary")) is None:
                failures.append("key-term requires non-empty context_summary")
            if _non_empty_text(item.get("annotation_comment")) is None:
                failures.append("key-term requires non-empty annotation_comment")
        elif selection_mode == "key-metric":
            if not re.search(r"\d", quote):
                failures.append("key-metric quote must contain a number")
            if _non_empty_text(item.get("metric_context")) is None:
                failures.append("key-metric requires non-empty metric_context")
            if _non_empty_text(item.get("condition")) is None:
                failures.append("key-metric requires non-empty condition")
            if _non_empty_text(item.get("annotation_comment")) is None:
                failures.append("key-metric requires non-empty annotation_comment")
        elif selection_mode == "author-name":
            if item.get("kind") != "author-background":
                failures.append("author-name requires kind=author-background")
            if "author_context" not in roles:
                failures.append("author-name requires author_context role")
            if _non_empty_text(item.get("author_context")) is None:
                failures.append("author-name requires non-empty author_context")
            external_evidence = _non_empty_text(item.get("external_evidence"))
            if not external_evidence:
                failures.append("author-name requires non-empty external_evidence")
            elif not _is_public_http_url(external_evidence):
                failures.append("author-name external_evidence must be a public HTTP(S) URL")
            verified_at = _non_empty_text(item.get("verified_at"))
            if not verified_at:
                failures.append("author-name requires non-empty verified_at")
            else:
                try:
                    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified_at):
                        raise ValueError
                    date.fromisoformat(verified_at)
                except ValueError:
                    failures.append("author-name verified_at must be an ISO date")
            annotation_comment = _non_empty_text(item.get("annotation_comment"))
            if not annotation_comment:
                failures.append("author-name requires non-empty annotation_comment")
            elif not annotation_comment.startswith(AUTHOR_COMMENT_PREFIX):
                failures.append(
                    "author-name annotation_comment must start with "
                    f"'{AUTHOR_COMMENT_PREFIX}'"
                )

        if _word_like_count(str(item.get("claim", ""))) < 6:
            failures.append("claim does not explain what the evidence establishes")
        if _word_like_count(str(item.get("reason", ""))) < 6:
            failures.append("reason does not justify the selected span")
        return failures

    annotation_type = item.get("annotation_type")
    if annotation_type == "highlight":
        quote = str(item.get("quote", "")).strip()
        normalised = _normalise(quote)
        if not quote:
            failures.append("text highlight requires quote")
        if normalised in LOW_INFORMATION_EXACT:
            failures.append("quote is a low-information fragment")
        if re.fullmatch(r"[\d\s.,%μµ-]+", quote) and not re.search(
            r"\b(?:average|maximum|minimum|time|rate|latency|frequency|success|"
            r"computation|trigger|velocity|distance|trials?|images?|depth)\b",
            quote,
            flags=re.IGNORECASE,
        ):
            failures.append("number or noun fragment lacks metric context")
        if _word_like_count(quote) < 6:
            failures.append("quote is too short to carry a complete technical relation")
        if "method" in roles and not roles.intersection(
            {"mechanism", "design_rationale", "condition", "result", "definition"}
        ):
            failures.append("method highlight lacks mechanism, rationale, condition, result, or definition")
    elif annotation_type == "area":
        if not item.get("visual_object"):
            failures.append("area annotation requires visual_object")
        rect = item.get("rect")
        if not isinstance(rect, list) or len(rect) != 4:
            failures.append("area annotation requires a four-value rect")
        if not roles.intersection({"metric", "comparison", "result", "mechanism", "failure"}):
            failures.append("area annotation lacks a visual evidence role")
    else:
        failures.append("annotation_type must be highlight or area")

    if _word_like_count(str(item.get("claim", ""))) < 6:
        failures.append("claim does not explain what the evidence establishes")
    if _word_like_count(str(item.get("reason", ""))) < 6:
        failures.append("reason does not justify the selected span")
    return failures


def validate_semantic_annotation(item: dict[str, Any]) -> dict[str, Any]:
    validated = {**item, "selection_mode": item.get("selection_mode") or "semantic-span"}
    failures = information_failures(validated)
    if failures:
        raise SemanticSelectionError("; ".join(failures))
    return validated

